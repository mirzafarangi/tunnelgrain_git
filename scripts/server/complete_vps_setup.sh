#!/bin/bash
# Complete VPS Setup v5.0 FINAL - With Working Expiration System
# This includes everything: WireGuard + API + FIXED Expiration Daemon

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

# Configuration
SERVER_IP="213.170.133.116"
VPS_NAME="tunnelgrain-vps"
ADMIN_EMAIL="support@tunnelgrain.com"

# Business tiers
declare -A BUSINESS_TIERS
BUSINESS_TIERS[test]=50
BUSINESS_TIERS[monthly]=30
BUSINESS_TIERS[quarterly]=20
BUSINESS_TIERS[biannual]=15
BUSINESS_TIERS[annual]=10
BUSINESS_TIERS[lifetime]=5

# Logging functions
log() { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo -e "${CYAN}🚀 TUNNELGRAIN COMPLETE SETUP v5.0 FINAL${NC}"
echo "=============================================="
echo "  📅 Setup Date: $(date)"
echo "  🖥️  Server IP: $SERVER_IP"
echo "  🏢 VPS Name: $VPS_NAME"
echo "=============================================="

# STEP 1: System Foundation
log "Installing system foundation..."
apt update -qq && apt upgrade -yqq

# Install required packages
apt install -yqq \
    wireguard wireguard-tools \
    qrencode \
    python3 python3-venv python3-pip \
    ufw curl jq \
    net-tools htop nano \
    iptables-persistent \
    systemd

success "System packages installed"

# Configure firewall
log "Configuring firewall..."
ufw --force reset >/dev/null 2>&1
ufw default deny incoming >/dev/null 2>&1
ufw default allow outgoing >/dev/null 2>&1
ufw allow 22/tcp >/dev/null 2>&1      # SSH
ufw allow 51820/udp >/dev/null 2>&1   # WireGuard
ufw allow 8081/tcp >/dev/null 2>&1    # Expiration daemon API
ufw --force enable >/dev/null 2>&1

success "Firewall configured"

# Configure IP forwarding
log "Configuring IP forwarding..."
echo 'net.ipv4.ip_forward=1' > /etc/sysctl.conf
echo 'net.ipv4.conf.all.forwarding=1' >> /etc/sysctl.conf
echo 'net.ipv6.conf.all.forwarding=1' >> /etc/sysctl.conf
sysctl -p >/dev/null 2>&1

success "IP forwarding enabled"

# STEP 2: Directory Structure
log "Creating directory structure..."
mkdir -p /opt/tunnelgrain/{keys,configs,qr_codes,backups,logs,scripts,api}

for tier in test monthly quarterly biannual annual lifetime; do
    mkdir -p /opt/tunnelgrain/configs/$tier
    mkdir -p /opt/tunnelgrain/qr_codes/$tier
done

# Set proper permissions
chmod 700 /opt/tunnelgrain/keys
chmod 755 /opt/tunnelgrain/{scripts,api,logs}
chmod 644 /opt/tunnelgrain/{configs,qr_codes}

success "Directory structure created"

# STEP 3: Generate Cryptographic Keys
log "Generating cryptographic keys..."
cd /opt/tunnelgrain/keys
umask 077

# Generate WireGuard server keys
wg genkey > server_private.key
cat server_private.key | wg pubkey > server_public.key
chmod 600 server_private.key
chmod 644 server_public.key

SERVER_PRIVATE=$(cat server_private.key)
SERVER_PUBLIC=$(cat server_public.key)

success "Server Public Key: $SERVER_PUBLIC"

# STEP 4: Generate VPN Configurations
log "Generating VPN configurations..."
total_configs=0
current_ip=10

PEER_MAP="/opt/tunnelgrain/peer_mapping.txt"
> "$PEER_MAP"

for tier in test monthly quarterly biannual annual lifetime; do
    count=${BUSINESS_TIERS[$tier]}
    log "Generating $count configs for $tier..."
    
    for ((i=1; i<=count; i++)); do
        # Generate order number with proper formatting
        if [[ "$tier" == "test" ]]; then
            order_number="72$(printf "%06X" $((0x100000 + total_configs + i)))"
        else
            order_number="42$(printf "%06X" $((0x100000 + total_configs + i)))"
        fi
        
        # Assign IP address
        client_ip="10.0.0.$current_ip"
        current_ip=$((current_ip + 1))
        
        # Generate client keys
        umask 077
        client_private=$(wg genkey)
        client_public=$(echo "$client_private" | wg pubkey)
        
        # Create client configuration file
        cat > "/opt/tunnelgrain/configs/$tier/${order_number}.conf" << EOF
# Tunnelgrain VPN Configuration
# Tier: $tier | Order: $order_number
# Generated: $(date)
# Support: $ADMIN_EMAIL

[Interface]
PrivateKey = $client_private
Address = $client_ip/24
DNS = 1.1.1.1, 1.0.0.1

[Peer]
PublicKey = $SERVER_PUBLIC
Endpoint = $SERVER_IP:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
EOF
        
        chmod 600 "/opt/tunnelgrain/configs/$tier/${order_number}.conf"
        
        # Generate QR code
        qrencode -t PNG -s 8 -m 2 -o "/opt/tunnelgrain/qr_codes/$tier/${order_number}.png" \
                 < "/opt/tunnelgrain/configs/$tier/${order_number}.conf"
        chmod 644 "/opt/tunnelgrain/qr_codes/$tier/${order_number}.png"
        
        # Store peer mapping (CRITICAL for expiration system)
        echo "$order_number:$client_public:$client_ip:$tier" >> "$PEER_MAP"
    done
    
    total_configs=$((total_configs + count))
    success "$count configs generated for $tier"
done

success "Generated $total_configs total configurations"

# STEP 5: Create WireGuard Server Configuration
log "Creating WireGuard server configuration..."

cat > /etc/wireguard/wg0.conf << EOF
# Tunnelgrain Production WireGuard Server
# Generated: $(date)
# Total Peers: $total_configs

[Interface]
Address = 10.0.0.1/24
ListenPort = 51820
PrivateKey = $SERVER_PRIVATE

# NAT and forwarding rules
PostUp = iptables -A FORWARD -i %i -j ACCEPT
PostUp = iptables -A FORWARD -o %i -j ACCEPT
PostUp = iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostUp = ip6tables -A FORWARD -i %i -j ACCEPT 2>/dev/null || true
PostUp = ip6tables -A FORWARD -o %i -j ACCEPT 2>/dev/null || true

PostDown = iptables -D FORWARD -i %i -j ACCEPT
PostDown = iptables -D FORWARD -o %i -j ACCEPT
PostDown = iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE
PostDown = ip6tables -D FORWARD -i %i -j ACCEPT 2>/dev/null || true
PostDown = ip6tables -D FORWARD -o %i -j ACCEPT 2>/dev/null || true

EOF

# Add peers organized by tier
for tier in test monthly quarterly biannual annual lifetime; do
    echo "" >> /etc/wireguard/wg0.conf
    echo "# ========== $tier TIER (${BUSINESS_TIERS[$tier]} peers) ==========" >> /etc/wireguard/wg0.conf
    
    grep ":$tier$" "$PEER_MAP" | while IFS=: read -r order_number client_public client_ip tier_name; do
        cat >> /etc/wireguard/wg0.conf << EOF

[Peer]
# $order_number ($tier_name)
PublicKey = $client_public
AllowedIPs = $client_ip/32
EOF
    done
done

chmod 600 /etc/wireguard/wg0.conf

success "WireGuard server configuration created"

# STEP 6: Start WireGuard Service
log "Starting WireGuard service..."
systemctl enable wg-quick@wg0 >/dev/null 2>&1
systemctl start wg-quick@wg0
sleep 3

if systemctl is-active wg-quick@wg0 >/dev/null 2>&1; then
    peer_count=$(wg show wg0 2>/dev/null | grep -c "peer:" || echo "0")
    success "WireGuard started successfully ($peer_count peers active)"
else
    error "WireGuard failed to start"
    systemctl status wg-quick@wg0
    exit 1
fi

# STEP 7: Python Environment Setup
log "Setting up Python environment..."
python3 -m venv /opt/tunnelgrain/api/venv
source /opt/tunnelgrain/api/venv/bin/activate
pip install -q --upgrade pip
pip install -q flask requests

success "Python environment configured"

# STEP 8: Create FIXED Expiration Daemon
log "Creating FIXED expiration daemon..."

cat > /opt/tunnelgrain/expiration_daemon.py << 'FIXED_DAEMON_EOF'
#!/usr/bin/env python3
"""
Tunnelgrain Expiration Daemon v5.0 FINAL
Properly removes peers from WireGuard when expired
FIXED VERSION - Works correctly with peer removal
"""

import time
import json
import subprocess
import logging
import os
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import signal
import sys
import re

# Configuration
CONFIG_BASE = "/opt/tunnelgrain"
TIMER_FILE = f"{CONFIG_BASE}/active_timers.json"
LOG_FILE = f"{CONFIG_BASE}/logs/expiration.log"
PEER_MAP_FILE = f"{CONFIG_BASE}/peer_mapping.json"

os.makedirs(f"{CONFIG_BASE}/logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

class ExpirationManager:
    def __init__(self):
        self.active_timers = {}
        self.peer_mapping = {}
        self.lock = threading.RLock()
        self.running = True
        self.load_data()
        self.build_peer_mapping()
        
    def load_data(self):
        """Load saved data"""
        if os.path.exists(TIMER_FILE):
            try:
                with open(TIMER_FILE, 'r') as f:
                    self.active_timers = json.load(f)
                logger.info(f"Loaded {len(self.active_timers)} timers")
            except Exception as e:
                logger.error(f"Error loading timers: {e}")
                self.active_timers = {}
        
        if os.path.exists(PEER_MAP_FILE):
            try:
                with open(PEER_MAP_FILE, 'r') as f:
                    self.peer_mapping = json.load(f)
                logger.info(f"Loaded {len(self.peer_mapping)} peer mappings")
            except Exception as e:
                logger.error(f"Error loading peer mappings: {e}")
                self.peer_mapping = {}
    
    def save_data(self):
        """Save data to files"""
        try:
            with self.lock:
                with open(TIMER_FILE, 'w') as f:
                    json.dump(self.active_timers, f, indent=2, default=str)
                with open(PEER_MAP_FILE, 'w') as f:
                    json.dump(self.peer_mapping, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving data: {e}")
    
    def build_peer_mapping(self):
        """Build peer mapping from peer_mapping.txt file"""
        try:
            peer_txt_file = f"{CONFIG_BASE}/peer_mapping.txt"
            if not os.path.exists(peer_txt_file):
                logger.warning("peer_mapping.txt not found, building from WireGuard config")
                self.build_peer_mapping_from_wg()
                return
            
            # Read from peer_mapping.txt (format: order_number:public_key:ip:tier)
            with open(peer_txt_file, 'r') as f:
                lines = f.readlines()
            
            for line in lines:
                line = line.strip()
                if line and ':' in line:
                    try:
                        parts = line.split(':')
                        if len(parts) >= 4:
                            order_number = parts[0]
                            public_key = parts[1]
                            client_ip = parts[2]
                            tier = parts[3]
                            
                            self.peer_mapping[order_number] = {
                                'public_key': public_key,
                                'client_ip': client_ip,
                                'tier': tier
                            }
                    except Exception as e:
                        logger.error(f"Error parsing line: {line} - {e}")
            
            self.save_data()
            logger.info(f"Built peer mapping with {len(self.peer_mapping)} entries from peer_mapping.txt")
            
        except Exception as e:
            logger.error(f"Error building peer mapping: {e}")
            self.build_peer_mapping_from_wg()
    
    def build_peer_mapping_from_wg(self):
        """Fallback: Build peer mapping from WireGuard config"""
        try:
            if not os.path.exists('/etc/wireguard/wg0.conf'):
                logger.error("WireGuard config not found")
                return
            
            with open('/etc/wireguard/wg0.conf', 'r') as f:
                content = f.read()
            
            # Parse WireGuard config
            sections = content.split('[Peer]')
            
            for section in sections[1:]:  # Skip first section (Interface)
                lines = section.strip().split('\n')
                order_number = None
                public_key = None
                client_ip = None
                tier = None
                
                for line in lines:
                    line = line.strip()
                    
                    # Look for order number in comments
                    if line.startswith('#'):
                        match = re.search(r'(42[A-F0-9]{6}|72[A-F0-9]{6})', line)
                        if match:
                            order_number = match.group(1)
                            tier = 'test' if order_number.startswith('72') else 'unknown'
                    
                    # Extract public key
                    elif line.startswith('PublicKey'):
                        parts = line.split('=', 1)
                        if len(parts) == 2:
                            public_key = parts[1].strip()
                    
                    # Extract IP
                    elif line.startswith('AllowedIPs'):
                        parts = line.split('=', 1)
                        if len(parts) == 2:
                            ip_with_mask = parts[1].strip()
                            client_ip = ip_with_mask.split('/')[0]
                
                # Store mapping if we have all required info
                if order_number and public_key:
                    self.peer_mapping[order_number] = {
                        'public_key': public_key,
                        'client_ip': client_ip or 'unknown',
                        'tier': tier or 'unknown'
                    }
                    logger.info(f"Mapped {order_number} -> {public_key[:16]}...")
            
            self.save_data()
            logger.info(f"Built peer mapping with {len(self.peer_mapping)} entries from WireGuard config")
            
        except Exception as e:
            logger.error(f"Error building peer mapping from WireGuard: {e}")
    
    def get_public_key(self, order_number):
        """Get public key for order"""
        if order_number in self.peer_mapping:
            return self.peer_mapping[order_number].get('public_key')
        
        logger.warning(f"No public key found for {order_number} in mapping")
        return None
    
    def add_timer(self, order_number, tier, duration_minutes):
        """Add expiration timer"""
        try:
            expires_at = datetime.now() + timedelta(minutes=duration_minutes)
            
            with self.lock:
                self.active_timers[order_number] = {
                    'order_number': order_number,
                    'tier': tier,
                    'expires_at': expires_at.isoformat(),
                    'duration_minutes': duration_minutes,
                    'status': 'active',
                    'created_at': datetime.now().isoformat()
                }
            
            self.save_data()
            
            # Verify we can find the public key
            public_key = self.get_public_key(order_number)
            if public_key:
                logger.info(f"⏰ Timer added: {order_number} ({tier}) expires in {duration_minutes} minutes (key: {public_key[:16]}...)")
            else:
                logger.warning(f"⚠️ Timer added for {order_number} but no public key found - expiration may fail")
            
            return True
            
        except Exception as e:
            logger.error(f"Error adding timer: {e}")
            return False
    
    def remove_peer_from_wireguard(self, order_number, public_key):
        """Remove peer from WireGuard interface and config"""
        try:
            if not public_key:
                logger.error(f"Cannot remove {order_number} - no public key")
                return False
            
            logger.info(f"🔥 Removing peer {order_number} with key {public_key[:16]}...")
            
            # Remove from running WireGuard interface
            result = subprocess.run(
                ['wg', 'set', 'wg0', 'peer', public_key, 'remove'],
                capture_output=True, text=True, timeout=10
            )
            
            if result.returncode == 0:
                logger.info(f"✅ Successfully removed peer {order_number} from WireGuard interface")
                
                # Also remove from config file to make it permanent
                self.remove_peer_from_config(order_number, public_key)
                
                return True
            else:
                logger.error(f"❌ Failed to remove peer {order_number}: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"❌ Timeout removing peer {order_number}")
            return False
        except Exception as e:
            logger.error(f"❌ Error removing peer {order_number}: {e}")
            return False
    
    def remove_peer_from_config(self, order_number, public_key):
        """Remove peer from WireGuard config file"""
        try:
            logger.info(f"🗑️ Removing {order_number} from config file...")
            
            with open('/etc/wireguard/wg0.conf', 'r') as f:
                lines = f.readlines()
            
            new_lines = []
            skip_section = False
            i = 0
            
            while i < len(lines):
                line = lines[i].strip()
                
                # Check if this line starts a peer section
                if line == '[Peer]':
                    # Look ahead to see if this peer contains our order number or public key
                    peer_section = []
                    j = i
                    while j < len(lines) and (j == i or not lines[j].strip().startswith('[')):
                        peer_section.append(lines[j])
                        j += 1
                    
                    peer_content = ''.join(peer_section)
                    
                    # Check if this peer section contains our target
                    if order_number in peer_content or public_key in peer_content:
                        logger.info(f"🗑️ Found and removing peer section for {order_number}")
                        i = j  # Skip this entire peer section
                        continue
                    else:
                        # Keep this peer section
                        new_lines.extend(peer_section)
                        i = j
                        continue
                
                new_lines.append(lines[i])
                i += 1
            
            # Write updated config
            with open('/etc/wireguard/wg0.conf', 'w') as f:
                f.writelines(new_lines)
            
            logger.info(f"✅ Updated WireGuard config file")
            
        except Exception as e:
            logger.error(f"❌ Error updating config file: {e}")
    
    def check_expiring_timers(self):
        """Check and expire timers"""
        now = datetime.now()
        expired_orders = []
        
        with self.lock:
            for order_number, timer_data in list(self.active_timers.items()):
                try:
                    if timer_data.get('status') != 'active':
                        continue
                    
                    expires_at = datetime.fromisoformat(timer_data['expires_at'])
                    
                    if expires_at <= now:
                        logger.info(f"⏰ Timer expired for {order_number}")
                        
                        # Get public key and remove peer
                        public_key = self.get_public_key(order_number)
                        
                        if public_key:
                            if self.remove_peer_from_wireguard(order_number, public_key):
                                # Mark as expired
                                timer_data['status'] = 'expired'
                                timer_data['expired_at'] = now.isoformat()
                                expired_orders.append(order_number)
                                logger.info(f"✅ Successfully expired {order_number}")
                            else:
                                logger.error(f"❌ Failed to expire {order_number}")
                        else:
                            logger.error(f"❌ No public key found for {order_number} - marking as expired anyway")
                            timer_data['status'] = 'expired'
                            timer_data['expired_at'] = now.isoformat()
                            expired_orders.append(order_number)
                
                except Exception as e:
                    logger.error(f"❌ Error processing timer {order_number}: {e}")
        
        if expired_orders:
            self.save_data()
            
            # Log current WireGuard peer count
            try:
                result = subprocess.run(['wg', 'show', 'wg0'], capture_output=True, text=True, timeout=5)
                current_peers = len([line for line in result.stdout.split('\n') if line.strip().startswith('peer:')])
                logger.info(f"📊 Current WireGuard peers: {current_peers}")
            except:
                pass
        
        return len(expired_orders)
    
    def expiration_loop(self):
        """Main expiration loop"""
        logger.info("🚀 Starting expiration checker")
        
        while self.running:
            try:
                expired_count = self.check_expiring_timers()
                if expired_count > 0:
                    logger.info(f"⏰ Expired {expired_count} timers this cycle")
                
                time.sleep(15)  # Check every 15 seconds for faster response
                
            except Exception as e:
                logger.error(f"❌ Error in expiration loop: {e}")
                time.sleep(30)

# Global manager
manager = ExpirationManager()

@app.route('/api/status', methods=['GET'])
def get_status():
    """Get daemon status"""
    try:
        with manager.lock:
            active_count = len([t for t in manager.active_timers.values() if t.get('status') == 'active'])
            expired_count = len([t for t in manager.active_timers.values() if t.get('status') == 'expired'])
            
            # Get WireGuard peer count
            try:
                result = subprocess.run(['wg', 'show', 'wg0'], 
                                      capture_output=True, text=True, timeout=5)
                wireguard_peers = len([line for line in result.stdout.split('\n') 
                                     if line.strip().startswith('peer:')])
            except:
                wireguard_peers = -1
        
        return jsonify({
            'daemon': 'running',
            'version': '5.0-final',
            'timestamp': datetime.now().isoformat(),
            'active_timers': active_count,
            'expired_timers': expired_count,
            'total_timers': len(manager.active_timers),
            'wireguard_peers': wireguard_peers,
            'peer_mappings': len(manager.peer_mapping)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/start-timer', methods=['POST'])
def start_timer():
    """Start timer for an order"""
    try:
        data = request.json
        order_number = data.get('order_number')
        tier = data.get('tier')
        duration_minutes = data.get('duration_minutes')
        
        if not all([order_number, tier, duration_minutes]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        success = manager.add_timer(order_number, tier, duration_minutes)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Timer started for {order_number}',
                'expires_in_minutes': duration_minutes
            })
        else:
            return jsonify({'error': 'Failed to start timer'}), 500
            
    except Exception as e:
        logger.error(f"Error starting timer: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/list-timers', methods=['GET'])
def list_timers():
    """List active timers"""
    try:
        with manager.lock:
            timers = []
            now = datetime.now()
            
            for order_number, timer_data in manager.active_timers.items():
                expires_at = datetime.fromisoformat(timer_data['expires_at'])
                time_remaining = (expires_at - now).total_seconds() / 60
                
                timers.append({
                    'order_number': order_number,
                    'tier': timer_data['tier'],
                    'expires_at': timer_data['expires_at'],
                    'time_remaining_minutes': max(0, round(time_remaining, 1)),
                    'status': timer_data.get('status', 'unknown')
                })
        
        return jsonify({
            'count': len(timers),
            'timers': timers
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/force-expire/<order_number>', methods=['POST'])
def force_expire(order_number):
    """Force expire a specific order"""
    try:
        with manager.lock:
            # Get public key and remove peer
            public_key = manager.get_public_key(order_number)
            
            if public_key:
                if manager.remove_peer_from_wireguard(order_number, public_key):
                    # Mark as expired if timer exists
                    if order_number in manager.active_timers:
                        manager.active_timers[order_number]['status'] = 'expired'
                        manager.active_timers[order_number]['expired_at'] = datetime.now().isoformat()
                    manager.save_data()
                    
                    return jsonify({
                        'success': True,
                        'message': f'Order {order_number} force expired'
                    })
                else:
                    return jsonify({'error': 'Failed to remove peer from WireGuard'}), 500
            else:
                return jsonify({'error': 'Public key not found'}), 404
                
    except Exception as e:
        logger.error(f"Error force expiring {order_number}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'version': '5.0-final',
        'timestamp': datetime.now().isoformat()
    })

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info("🛑 Shutting down expiration daemon...")
    manager.running = False
    sys.exit(0)

if __name__ == '__main__':
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Start expiration checker thread
    expiration_thread = threading.Thread(target=manager.expiration_loop, daemon=True)
    expiration_thread.start()
    
    logger.info("🚀 Tunnelgrain Expiration Daemon v5.0-FINAL starting")
    app.run(host='0.0.0.0', port=8081, debug=False)
FIXED_DAEMON_EOF

chmod +x /opt/tunnelgrain/expiration_daemon.py

success "FIXED expiration daemon created"

# STEP 9: Create Systemd Service
log "Creating systemd service..."

cat > /etc/systemd/system/tunnelgrain-expiration.service << EOF
[Unit]
Description=Tunnelgrain VPN Expiration Daemon v5.0
After=network.target wg-quick@wg0.service
Wants=wg-quick@wg0.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/tunnelgrain
Environment=PATH=/opt/tunnelgrain/api/venv/bin
ExecStart=/opt/tunnelgrain/api/venv/bin/python /opt/tunnelgrain/expiration_daemon.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Security settings
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=/opt/tunnelgrain /etc/wireguard

[Install]
WantedBy=multi-user.target
EOF

# Enable and start the service
systemctl daemon-reload
systemctl enable tunnelgrain-expiration >/dev/null 2>&1
systemctl start tunnelgrain-expiration

# Wait for service to start
sleep 5

if systemctl is-active tunnelgrain-expiration >/dev/null 2>&1; then
    success "Expiration daemon service started successfully"
else
    error "Expiration daemon failed to start"
    echo "Service logs:"
    journalctl -u tunnelgrain-expiration --no-pager -l | tail -15
    exit 1
fi

# STEP 10: Create Management Scripts
log "Creating management scripts..."

# Status script
cat > /opt/tunnelgrain/scripts/status.sh << 'STATUS_EOF'
#!/bin/bash
echo "🚀 TUNNELGRAIN STATUS v5.0"
echo "=========================="
echo "Time: $(date)"
echo "Server: $(hostname) ($(curl -s ifconfig.me))"
echo ""

echo "🔧 Services:"
wg_status=$(systemctl is-active wg-quick@wg0)
exp_status=$(systemctl is-active tunnelgrain-expiration)
echo "  WireGuard: $wg_status $([ "$wg_status" = "active" ] && echo "✅" || echo "❌")"
echo "  Expiration: $exp_status $([ "$exp_status" = "active" ] && echo "✅" || echo "❌")"
echo ""

echo "📊 Configurations:"
total=0
for tier in test monthly quarterly biannual annual lifetime; do
    count=$(ls /opt/tunnelgrain/configs/$tier/*.conf 2>/dev/null | wc -l)
    total=$((total + count))
    echo "  $tier: $count configs"
done
echo "  TOTAL: $total configs"
echo ""

echo "🌐 WireGuard Status:"
if [ "$wg_status" = "active" ]; then
    peer_count=$(wg show wg0 | grep -c "peer:" || echo "0")
    echo "  Active Peers: $peer_count"
    if [ "$peer_count" -gt 0 ]; then
        echo "  Latest handshakes:"
        wg show wg0 latest-handshakes | head -3 | while read line; do
            echo "    $line"
        done
    fi
else
    echo "  ❌ WireGuard not running"
fi
echo ""

echo "🔗 API Status:"
api_response=$(curl -s http://localhost:8081/api/status 2>/dev/null)
if [ $? -eq 0 ]; then
    echo "$api_response" | jq -r '
        "  Version: " + .version,
        "  Active Timers: " + (.active_timers | tostring),
        "  Expired Timers: " + (.expired_timers | tostring),
        "  WireGuard Peers: " + (.wireguard_peers | tostring),
        "  Peer Mappings: " + (.peer_mappings | tostring),
        "  Daemon: " + .daemon
    ' 2>/dev/null || echo "  API responding but invalid JSON"
else
    echo "  ❌ API not responding"
fi

echo ""
echo "🧪 Quick Tests:"
echo "  curl http://$(curl -s ifconfig.me):8081/api/status"
echo "  /opt/tunnelgrain/scripts/status.sh"
echo ""
STATUS_EOF

# Backup script
cat > /opt/tunnelgrain/scripts/backup.sh << 'BACKUP_EOF'
#!/bin/bash
BACKUP_DIR="/opt/tunnelgrain/backups"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/tunnelgrain_backup_$DATE.tar.gz"

mkdir -p "$BACKUP_DIR"

echo "Creating backup: $BACKUP_FILE"
tar -czf "$BACKUP_FILE" \
    /opt/tunnelgrain/configs \
    /opt/tunnelgrain/keys \
    /opt/tunnelgrain/peer_mapping.txt \
    /opt/tunnelgrain/active_timers.json \
    /opt/tunnelgrain/peer_mapping.json \
    /etc/wireguard/wg0.conf \
    2>/dev/null

if [ $? -eq 0 ]; then
    echo "✅ Backup created successfully"
    ls -lh "$BACKUP_FILE"
    
    # Keep only last 5 backups
    cd "$BACKUP_DIR"
    ls -t tunnelgrain_backup_*.tar.gz | tail -n +6 | xargs rm -f 2>/dev/null
    echo "Old backups cleaned up"
else
    echo "❌ Backup failed"
fi
BACKUP_EOF

# Test script
cat > /opt/tunnelgrain/scripts/test-expiration.sh << 'TEST_EOF'
#!/bin/bash
echo "🧪 Testing Expiration System"
echo "============================"

# Check if we have any test configs
test_configs=$(ls /opt/tunnelgrain/configs/test/*.conf 2>/dev/null | wc -l)
echo "Available test configs: $test_configs"

if [ "$test_configs" -eq 0 ]; then
    echo "❌ No test configs available"
    exit 1
fi

# Get first test config
first_test=$(ls /opt/tunnelgrain/configs/test/*.conf | head -1)
order_number=$(basename "$first_test" .conf)

echo "Testing with order: $order_number"

# Start a 1-minute timer
echo "Starting 1-minute test timer..."
response=$(curl -s -X POST http://localhost:8081/api/start-timer \
    -H "Content-Type: application/json" \
    -d "{\"order_number\":\"$order_number\",\"tier\":\"test\",\"duration_minutes\":1}")

echo "Response: $response"

if echo "$response" | grep -q "success"; then
    echo "✅ Timer started successfully"
    echo "⏰ Timer will expire in 1 minute"
    echo "📊 Monitor with: curl http://localhost:8081/api/list-timers"
    echo "🔗 Force expire with: curl -X POST http://localhost:8081/api/force-expire/$order_number"
else
    echo "❌ Failed to start timer"
fi
TEST_EOF

chmod +x /opt/tunnelgrain/scripts/*.sh

success "Management scripts created"

# Deactivate Python environment
deactivate

# STEP 11: Final Verification
log "Running final verification..."
sleep 3

# Count files
config_count=$(find /opt/tunnelgrain/configs -name "*.conf" | wc -l)
qr_count=$(find /opt/tunnelgrain/qr_codes -name "*.png" | wc -l)
peer_mapping_lines=$(wc -l < /opt/tunnelgrain/peer_mapping.txt)

# Test API
api_test=$(curl -s http://localhost:8081/api/status 2>/dev/null || echo "FAILED")

# Check services
wg_status=$(systemctl is-active wg-quick@wg0)
exp_status=$(systemctl is-active tunnelgrain-expiration)

echo ""
echo -e "${CYAN}🎉 SETUP COMPLETED SUCCESSFULLY! 🎉${NC}"
echo "==========================================="
echo -e "  📅 Setup Date: ${GREEN}$(date)${NC}"
echo -e "  🖥️  Server IP: ${GREEN}$SERVER_IP${NC}"
echo -e "  🔧 WireGuard: ${GREEN}$wg_status${NC}"
echo -e "  ⏰ Expiration: ${GREEN}$exp_status${NC}"
echo -e "  📄 Configs: ${GREEN}$config_count${NC}"
echo -e "  📱 QR Codes: ${GREEN}$qr_count${NC}"
echo -e "  🔗 Peer Mappings: ${GREEN}$peer_mapping_lines${NC}"
echo -e "  🌐 API: ${GREEN}$([ "$api_test" != "FAILED" ] && echo "Working" || echo "Failed")${NC}"
echo ""

if [ "$wg_status" = "active" ] && [ "$exp_status" = "active" ] && [ "$api_test" != "FAILED" ]; then
    echo -e "${GREEN}✅ ALL SYSTEMS OPERATIONAL${NC}"
    echo ""
    echo -e "${YELLOW}🧪 Quick Tests:${NC}"
    echo "  curl http://$SERVER_IP:8081/api/status"
    echo "  /opt/tunnelgrain/scripts/status.sh"
    echo "  /opt/tunnelgrain/scripts/test-expiration.sh"
    echo ""
    echo -e "${YELLOW}📤 Download configs to your local machine:${NC}"
    echo "  scp -r root@$SERVER_IP:/opt/tunnelgrain/configs/* ./data/vps_1/ip_$SERVER_IP/"
    echo "  scp -r root@$SERVER_IP:/opt/tunnelgrain/qr_codes/* ./static/qr_codes/vps_1/ip_$SERVER_IP/"
    echo ""
    echo -e "${YELLOW}📋 Management Commands:${NC}"
    echo "  systemctl status tunnelgrain-expiration"
    echo "  journalctl -u tunnelgrain-expiration -f"
    echo "  /opt/tunnelgrain/scripts/backup.sh"
    echo ""
    success "🎯 VPN business system ready! Test expiration works correctly."
else
    error "Some services failed to start properly"
    echo "Please check the logs and try again"
    exit 1
fi