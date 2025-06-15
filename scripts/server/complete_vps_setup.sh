#!/bin/bash
# Complete VPS Setup - Use this instead of your current one
# This includes everything: WireGuard + API + Expiration Daemon

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

echo -e "${CYAN}🚀 TUNNELGRAIN COMPLETE SETUP v4.0${NC}"
echo "===================================="

# STEP 1: System Foundation
log "Installing system foundation..."
apt update -qq && apt upgrade -yqq
apt install -yqq wireguard wireguard-tools qrencode python3 python3-venv python3-pip ufw curl jq net-tools htop nano

# Configure firewall
ufw --force reset >/dev/null 2>&1
ufw default deny incoming >/dev/null 2>&1
ufw default allow outgoing >/dev/null 2>&1
ufw allow 22/tcp >/dev/null 2>&1
ufw allow 51820/udp >/dev/null 2>&1
ufw allow 8081/tcp >/dev/null 2>&1   # Changed to 8081 for expiration daemon
ufw --force enable >/dev/null 2>&1

# IP forwarding
echo 'net.ipv4.ip_forward=1' > /etc/sysctl.conf
echo 'net.ipv4.conf.all.forwarding=1' >> /etc/sysctl.conf
sysctl -p >/dev/null 2>&1

# STEP 2: Directory Structure
log "Creating directory structure..."
mkdir -p /opt/tunnelgrain/{keys,configs,qr_codes,backups,logs,scripts,api}

for tier in test monthly quarterly biannual annual lifetime; do
    mkdir -p /opt/tunnelgrain/configs/$tier
    mkdir -p /opt/tunnelgrain/qr_codes/$tier
done

chmod 700 /opt/tunnelgrain/keys
chmod 755 /opt/tunnelgrain/{scripts,api}

# STEP 3: Generate Keys
log "Generating cryptographic keys..."
cd /opt/tunnelgrain/keys
umask 077

wg genkey > server_private.key
cat server_private.key | wg pubkey > server_public.key
chmod 600 server_private.key
chmod 644 server_public.key

SERVER_PRIVATE=$(cat server_private.key)
SERVER_PUBLIC=$(cat server_public.key)

success "Server Public Key: $SERVER_PUBLIC"

# STEP 4: Generate Configs
log "Generating VPN configurations..."
total_configs=0
current_ip=10

PEER_MAP="/opt/tunnelgrain/peer_mapping.txt"
> "$PEER_MAP"

for tier in test monthly quarterly biannual annual lifetime; do
    count=${BUSINESS_TIERS[$tier]}
    log "Generating $count configs for $tier..."
    
    for ((i=1; i<=count; i++)); do
        if [[ "$tier" == "test" ]]; then
            order_number="72$(printf "%06X" $((0x100000 + total_configs + i)))"
        else
            order_number="42$(printf "%06X" $((0x100000 + total_configs + i)))"
        fi
        
        client_ip="10.0.0.$current_ip"
        current_ip=$((current_ip + 1))
        
        umask 077
        client_private=$(wg genkey)
        client_public=$(echo "$client_private" | wg pubkey)
        
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
        
        qrencode -t PNG -s 8 -m 2 -o "/opt/tunnelgrain/qr_codes/$tier/${order_number}.png" \
                 < "/opt/tunnelgrain/configs/$tier/${order_number}.conf"
        chmod 644 "/opt/tunnelgrain/qr_codes/$tier/${order_number}.png"
        
        echo "$order_number:$client_public:$client_ip:$tier" >> "$PEER_MAP"
    done
    
    total_configs=$((total_configs + count))
    echo " ✅ $count configs generated"
done

success "Generated $total_configs configurations"

# STEP 5: WireGuard Server Config
log "Creating WireGuard server configuration..."

cat > /etc/wireguard/wg0.conf << EOF
# Tunnelgrain Production WireGuard Server
[Interface]
Address = 10.0.0.1/24
ListenPort = 51820
PrivateKey = $SERVER_PRIVATE

PostUp = iptables -A FORWARD -i %i -j ACCEPT
PostUp = iptables -A FORWARD -o %i -j ACCEPT
PostUp = iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE

PostDown = iptables -D FORWARD -i %i -j ACCEPT
PostDown = iptables -D FORWARD -o %i -j ACCEPT
PostDown = iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

EOF

# Add peers organized by tier
for tier in test monthly quarterly biannual annual lifetime; do
    echo "" >> /etc/wireguard/wg0.conf
    echo "# ========== $tier TIER ==========" >> /etc/wireguard/wg0.conf
    
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

# STEP 6: Start WireGuard
log "Starting WireGuard..."
systemctl enable wg-quick@wg0 >/dev/null 2>&1
systemctl start wg-quick@wg0
sleep 3

if systemctl is-active wg-quick@wg0 >/dev/null 2>&1; then
    peer_count=$(wg show wg0 2>/dev/null | grep -c "peer:" || echo "0")
    success "WireGuard started ($peer_count peers)"
else
    echo "❌ WireGuard failed to start"
    exit 1
fi

# STEP 7: Python Environment
log "Setting up Python environment..."
python3 -m venv /opt/tunnelgrain/api/venv
source /opt/tunnelgrain/api/venv/bin/activate
pip install -q flask requests

# STEP 8: Expiration Daemon
log "Creating expiration daemon..."

cat > /opt/tunnelgrain/expiration_daemon.py << 'DAEMON_EOF'
#!/usr/bin/env python3
"""
Tunnelgrain Expiration Daemon v4.0 FINAL
Complete clean implementation
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
            except:
                self.active_timers = {}
        
        if os.path.exists(PEER_MAP_FILE):
            try:
                with open(PEER_MAP_FILE, 'r') as f:
                    self.peer_mapping = json.load(f)
                logger.info(f"Loaded {len(self.peer_mapping)} peer mappings")
            except:
                self.peer_mapping = {}
    
    def save_data(self):
        """Save data"""
        try:
            with self.lock:
                with open(TIMER_FILE, 'w') as f:
                    json.dump(self.active_timers, f, indent=2, default=str)
                with open(PEER_MAP_FILE, 'w') as f:
                    json.dump(self.peer_mapping, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving: {e}")
    
    def build_peer_mapping(self):
        """Build peer mapping from WireGuard config"""
        try:
            if not os.path.exists('/etc/wireguard/wg0.conf'):
                return
            
            with open('/etc/wireguard/wg0.conf', 'r') as f:
                content = f.read()
            
            lines = content.split('\n')
            current_order = None
            
            for line in lines:
                if line.strip().startswith('#'):
                    match = re.search(r'(42[A-F0-9]{6}|72[A-F0-9]{6})', line)
                    if match:
                        current_order = match.group(1)
                elif current_order and line.strip().startswith('PublicKey'):
                    parts = line.split('=', 1)
                    if len(parts) == 2:
                        public_key = parts[1].strip()
                        tier = 'test' if current_order.startswith('72') else 'monthly'
                        
                        self.peer_mapping[current_order] = {
                            'public_key': public_key,
                            'tier': tier
                        }
                        current_order = None
            
            self.save_data()
            logger.info(f"Built peer mapping with {len(self.peer_mapping)} entries")
            
        except Exception as e:
            logger.error(f"Error building peer mapping: {e}")
    
    def get_public_key(self, order_number):
        """Get public key for order"""
        if order_number in self.peer_mapping:
            return self.peer_mapping[order_number].get('public_key')
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
                    'status': 'active'
                }
            
            self.save_data()
            
            public_key = self.get_public_key(order_number)
            if not public_key:
                logger.warning(f"No public key found for {order_number} - will try later")
            
            logger.info(f"⏰ Timer added: {order_number} ({tier}) expires in {duration_minutes} minutes")
            return True
            
        except Exception as e:
            logger.error(f"Error adding timer: {e}")
            return False
    
    def remove_peer_from_wireguard(self, public_key):
        """Remove peer from WireGuard"""
        try:
            if not public_key:
                return False
            
            result = subprocess.run(
                ['wg', 'set', 'wg0', 'peer', public_key, 'remove'],
                capture_output=True, text=True, timeout=10
            )
            
            if result.returncode == 0:
                logger.info(f"🔥 Peer removed from WireGuard: {public_key[:20]}...")
                return True
            else:
                logger.error(f"Failed to remove peer: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error removing peer: {e}")
            return False
    
    def check_expiring_timers(self):
        """Check and expire timers"""
        now = datetime.now()
        expired_orders = []
        
        with self.lock:
            for order_number, timer_data in list(self.active_timers.items()):
                try:
                    expires_at = datetime.fromisoformat(timer_data['expires_at'])
                    
                    if expires_at <= now:
                        public_key = self.get_public_key(order_number)
                        
                        if public_key:
                            if self.remove_peer_from_wireguard(public_key):
                                logger.info(f"⏰ Timer expired for {order_number}")
                                expired_orders.append(order_number)
                            else:
                                logger.error(f"Failed to expire {order_number}")
                        else:
                            logger.error(f"No public key found for {order_number}")
                            expired_orders.append(order_number)  # Remove anyway
                
                except Exception as e:
                    logger.error(f"Error processing timer {order_number}: {e}")
            
            # Remove expired timers
            for order_number in expired_orders:
                self.active_timers.pop(order_number, None)
        
        if expired_orders:
            self.save_data()
        
        return len(expired_orders)
    
    def expiration_loop(self):
        """Main expiration loop"""
        logger.info("Starting expiration checker")
        
        while self.running:
            try:
                expired_count = self.check_expiring_timers()
                if expired_count > 0:
                    logger.info(f"Expired {expired_count} timers")
                
                time.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                logger.error(f"Error in expiration loop: {e}")
                time.sleep(30)

# Global manager
manager = ExpirationManager()

@app.route('/api/status', methods=['GET'])
def get_status():
    """Get daemon status"""
    try:
        with manager.lock:
            active_count = len(manager.active_timers)
            expired_count = 0
            
            # Get WireGuard peer count
            try:
                result = subprocess.run(['wg', 'show', 'wg0'], 
                                      capture_output=True, text=True, timeout=5)
                wireguard_peers = len([line for line in result.stdout.split('\n') 
                                     if line.strip().startswith('peer:')])
            except:
                wireguard_peers = 0
        
        return jsonify({
            'daemon': 'running',
            'version': '4.0',
            'timestamp': datetime.now().isoformat(),
            'active_timers': active_count,
            'expired_timers': expired_count,
            'total_timers': active_count + expired_count,
            'wireguard_peers': wireguard_peers
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
                    'status': 'active' if time_remaining > 0 else 'expired'
                })
        
        return jsonify({
            'count': len(timers),
            'timers': timers
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info("Shutting down...")
    manager.running = False
    sys.exit(0)

if __name__ == '__main__':
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Start expiration checker thread
    expiration_thread = threading.Thread(target=manager.expiration_loop, daemon=True)
    expiration_thread.start()
    
    logger.info("🚀 Tunnelgrain Expiration Daemon v4.0 starting")
    app.run(host='0.0.0.0', port=8081, debug=False)
DAEMON_EOF

chmod +x /opt/tunnelgrain/expiration_daemon.py

# STEP 9: Create systemd service for expiration daemon
log "Creating expiration daemon service..."

cat > /etc/systemd/system/tunnelgrain-expiration.service << EOF
[Unit]
Description=Tunnelgrain VPN Expiration Daemon
After=network.target wg-quick@wg0.service

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

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable tunnelgrain-expiration >/dev/null 2>&1
systemctl start tunnelgrain-expiration

# Wait for service
sleep 5

if systemctl is-active tunnelgrain-expiration >/dev/null 2>&1; then
    success "Expiration daemon started"
else
    echo "❌ Expiration daemon failed to start"
    journalctl -u tunnelgrain-expiration --no-pager -l | tail -10
fi

# STEP 10: Management Scripts
log "Creating management scripts..."

cat > /opt/tunnelgrain/scripts/status.sh << 'STATUS_EOF'
#!/bin/bash
echo "🚀 TUNNELGRAIN STATUS"
echo "===================="
echo "Time: $(date)"
echo ""

echo "🔧 Services:"
echo "  WireGuard: $(systemctl is-active wg-quick@wg0 && echo "✅ Running" || echo "❌ Failed")"
echo "  Expiration: $(systemctl is-active tunnelgrain-expiration && echo "✅ Running" || echo "❌ Failed")"
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

echo "🌐 API Status:"
curl -s http://localhost:8081/api/status 2>/dev/null | jq -r '
  "  Active Timers: " + (.active_timers | tostring),
  "  WireGuard Peers: " + (.wireguard_peers | tostring),
  "  Daemon: " + .daemon
' 2>/dev/null || echo "  ❌ API not responding"
STATUS_EOF

chmod +x /opt/tunnelgrain/scripts/status.sh

# Deactivate Python environment
deactivate

# FINAL VERIFICATION
log "Running final verification..."
sleep 3

config_count=$(find /opt/tunnelgrain/configs -name "*.conf" | wc -l)
qr_count=$(find /opt/tunnelgrain/qr_codes -name "*.png" | wc -l)

echo ""
echo -e "${CYAN}🎉 SETUP COMPLETED! 🎉${NC}"
echo "====================="
echo "  🖥️  Server IP: $SERVER_IP"
echo "  🔧 WireGuard: $(systemctl is-active wg-quick@wg0)"
echo "  ⏰ Expiration: $(systemctl is-active tunnelgrain-expiration)"
echo "  📄 Configs: $config_count"
echo "  📱 QR Codes: $qr_count"
echo ""
echo -e "${YELLOW}🧪 Test Commands:${NC}"
echo "  curl http://$SERVER_IP:8081/api/status"
echo "  /opt/tunnelgrain/scripts/status.sh"
echo ""
echo -e "${YELLOW}📤 Download configs to your local machine:${NC}"
echo "  scp -r root@$SERVER_IP:/opt/tunnelgrain/configs/* ./data/vps_1/ip_$SERVER_IP/"
echo "  scp -r root@$SERVER_IP:/opt/tunnelgrain/qr_codes/* ./static/qr_codes/vps_1/ip_$SERVER_IP/"
echo ""
success "🎯 Ready for business! Test with: curl http://$SERVER_IP:8081/api/status"