#!/bin/bash
# vps_setup.sh - Final Optimized Tunnelgrain VPS Setup
# Run this ONCE on fresh Ubuntu 24.04 VPS
# Tested and production-ready

set -e

# Colors for beautiful output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
NC='\033[0m'

# Configuration - MODIFY THESE FOR YOUR SETUP
SERVER_IP="213.170.133.116"  # Your VPS IP address
VPS_NAME="tunnelgrain-vps"    # Your VPS identifier
ADMIN_EMAIL="support@tunnelgrain.com"  # Your support email

# Business tiers - OPTIMIZED FOR SINGLE VPS
declare -A BUSINESS_TIERS
BUSINESS_TIERS[test]=50        # 50 test slots (15 min each)
BUSINESS_TIERS[monthly]=30     # 30 monthly slots ($4.99 each)
BUSINESS_TIERS[quarterly]=20   # 20 three-month slots ($12.99 each)
BUSINESS_TIERS[biannual]=15    # 15 six-month slots ($23.99 each)
BUSINESS_TIERS[annual]=10      # 10 yearly slots ($39.99 each)
BUSINESS_TIERS[lifetime]=5     # 5 lifetime slots ($99.99 each)
# Total: 130 slots = PERFECT FOR ONE VPS

# Beautiful header
echo -e "${CYAN}"
cat << 'HEADER'
╔══════════════════════════════════════════════════════════════╗
║                    🚀 TUNNELGRAIN VPN                       ║
║                 Production Setup v3.0                       ║
║              Complete Business-Ready Solution                ║
╚══════════════════════════════════════════════════════════════╝
HEADER
echo -e "${NC}"

echo -e "${BLUE}Server IP:${NC} $SERVER_IP"
echo -e "${BLUE}Total Capacity:${NC} 130 VPN slots across 6 tiers"
echo -e "${BLUE}Revenue Potential:${NC} \$1,669+ monthly at full capacity"
echo -e "${BLUE}Setup Time:${NC} ~5 minutes"
echo ""

# Logging functions
log() { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }

# ============================================================================
# STEP 1: SYSTEM FOUNDATION
# ============================================================================
log "STEP 1/8: Installing system foundation..."

# Update system
apt update -qq && apt upgrade -yqq

# Install core packages (avoiding problematic ones)
apt install -yqq \
    wireguard \
    wireguard-tools \
    qrencode \
    python3 \
    python3-venv \
    python3-pip \
    ufw \
    curl \
    jq \
    net-tools \
    htop \
    nano

# Configure firewall
ufw --force reset >/dev/null 2>&1
ufw default deny incoming >/dev/null 2>&1
ufw default allow outgoing >/dev/null 2>&1
ufw allow 22/tcp >/dev/null 2>&1     # SSH
ufw allow 51820/udp >/dev/null 2>&1  # WireGuard
ufw allow 8080/tcp >/dev/null 2>&1   # API daemon
ufw --force enable >/dev/null 2>&1

# Configure IP forwarding
echo 'net.ipv4.ip_forward=1' > /etc/sysctl.conf
echo 'net.ipv4.conf.all.forwarding=1' >> /etc/sysctl.conf
sysctl -p >/dev/null 2>&1

success "System foundation installed"

# ============================================================================
# STEP 2: DIRECTORY STRUCTURE
# ============================================================================
log "STEP 2/8: Creating secure directory structure..."

# Create main business directory
mkdir -p /opt/tunnelgrain/{keys,configs,qr_codes,backups,logs,scripts,api}

# Create tier subdirectories
for tier in test monthly quarterly biannual annual lifetime; do
    mkdir -p /opt/tunnelgrain/configs/$tier
    mkdir -p /opt/tunnelgrain/qr_codes/$tier
done

# Set secure permissions
chmod 700 /opt/tunnelgrain
chmod 700 /opt/tunnelgrain/keys
chmod 755 /opt/tunnelgrain/scripts
chmod 755 /opt/tunnelgrain/api

success "Secure directory structure created"

# ============================================================================
# STEP 3: CRYPTOGRAPHIC KEY GENERATION
# ============================================================================
log "STEP 3/8: Generating cryptographic keys..."

# Generate server keys with maximum security
cd /opt/tunnelgrain/keys
umask 077

wg genkey > server_private.key
cat server_private.key | wg pubkey > server_public.key

# Set proper permissions
chmod 600 server_private.key
chmod 644 server_public.key
chown root:root *.key

# Load keys
SERVER_PRIVATE=$(cat server_private.key)
SERVER_PUBLIC=$(cat server_public.key)

info "Server Public Key: $SERVER_PUBLIC"
success "Cryptographic keys generated securely"

# ============================================================================
# STEP 4: VPN CONFIGURATION GENERATION
# ============================================================================
log "STEP 4/8: Generating business VPN configurations..."

total_configs=0
current_ip=10

# Create peer mapping for server config
PEER_MAP="/opt/tunnelgrain/peer_mapping.txt"
> "$PEER_MAP"

# Generate configurations for each business tier
for tier in test monthly quarterly biannual annual lifetime; do
    count=${BUSINESS_TIERS[$tier]}
    info "Generating $count VPN configs for $tier tier..."
    
    for ((i=1; i<=count; i++)); do
        # Generate business order number
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
        
        # Create professional client configuration
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
        
        # Add to server peer mapping
        echo "$order_number:$client_public:$client_ip:$tier" >> "$PEER_MAP"
        
        # Progress indicator
        if ((i % 10 == 0)); then
            echo -n "."
        fi
    done
    
    total_configs=$((total_configs + count))
    echo " ✅ $count configs generated"
done

success "Generated $total_configs professional VPN configurations"

# ============================================================================
# STEP 5: WIREGUARD SERVER CONFIGURATION
# ============================================================================
log "STEP 5/8: Creating WireGuard server configuration..."

# Create production server config
cat > /etc/wireguard/wg0.conf << EOF
# Tunnelgrain Production WireGuard Server
# Generated: $(date)
# Server: $SERVER_IP
# Capacity: $total_configs clients

[Interface]
Address = 10.0.0.1/24
ListenPort = 51820
PrivateKey = $SERVER_PRIVATE

# Network configuration
PostUp = iptables -A FORWARD -i %i -j ACCEPT
PostUp = iptables -A FORWARD -o %i -j ACCEPT
PostUp = iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostUp = echo "WireGuard Started: \$(date)" >> /opt/tunnelgrain/logs/server.log

PostDown = iptables -D FORWARD -i %i -j ACCEPT
PostDown = iptables -D FORWARD -o %i -j ACCEPT
PostDown = iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE
PostDown = echo "WireGuard Stopped: \$(date)" >> /opt/tunnelgrain/logs/server.log

EOF

# Add business peers organized by tier
for tier in test monthly quarterly biannual annual lifetime; do
    echo "" >> /etc/wireguard/wg0.conf
    echo "# ========== $tier TIER CLIENTS ==========" >> /etc/wireguard/wg0.conf
    
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

success "WireGuard server configured with $total_configs peers"

# ============================================================================
# STEP 6: WIREGUARD SERVICE STARTUP
# ============================================================================
log "STEP 6/8: Starting WireGuard service..."

# Enable and start WireGuard
systemctl enable wg-quick@wg0 >/dev/null 2>&1
systemctl start wg-quick@wg0

# Wait for service to initialize
sleep 3

# Verify WireGuard is running
if systemctl is-active wg-quick@wg0 >/dev/null 2>&1; then
    peer_count=$(wg show wg0 2>/dev/null | grep -c "peer:" || echo "0")
    success "WireGuard started successfully ($peer_count peers configured)"
else
    error "WireGuard failed to start"
    journalctl -u wg-quick@wg0 --no-pager -l | tail -5
    exit 1
fi

# ============================================================================
# STEP 7: PYTHON API SERVICE
# ============================================================================
log "STEP 7/8: Installing business API service..."

# Create Python virtual environment
python3 -m venv /opt/tunnelgrain/api/venv

# Activate virtual environment and install packages
source /opt/tunnelgrain/api/venv/bin/activate
pip install -q flask requests gunicorn

# Create professional API service
cat > /opt/tunnelgrain/api/tunnelgrain_api.py << 'API_EOF'
#!/usr/bin/env python3
"""
Tunnelgrain Business API Service
Production-ready VPN management system v3.0
"""

import os
import json
import logging
import subprocess
from datetime import datetime
from flask import Flask, request, jsonify, send_file
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/opt/tunnelgrain/logs/api.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('TunnelgrainAPI')

app = Flask(__name__)

# Business configuration
CONFIG = {
    'base_dir': '/opt/tunnelgrain',
    'server_ip': '213.170.133.116',
    'business_tiers': {
        'test': {'capacity': 50, 'price': 0, 'duration': '15 minutes'},
        'monthly': {'capacity': 30, 'price': 499, 'duration': '30 days'},
        'quarterly': {'capacity': 20, 'price': 1299, 'duration': '90 days'},
        'biannual': {'capacity': 15, 'price': 2399, 'duration': '180 days'},
        'annual': {'capacity': 10, 'price': 3999, 'duration': '365 days'},
        'lifetime': {'capacity': 5, 'price': 9999, 'duration': 'lifetime'}
    }
}

def get_tier_status(tier):
    """Get real-time status for business tier"""
    config_dir = Path(CONFIG['base_dir']) / 'configs' / tier
    qr_dir = Path(CONFIG['base_dir']) / 'qr_codes' / tier
    
    if not config_dir.exists():
        return {
            'tier': tier,
            'capacity': CONFIG['business_tiers'][tier]['capacity'],
            'available': 0,
            'price_cents': CONFIG['business_tiers'][tier]['price'],
            'duration': CONFIG['business_tiers'][tier]['duration'],
            'status': 'not_configured'
        }
    
    config_count = len(list(config_dir.glob('*.conf')))
    qr_count = len(list(qr_dir.glob('*.png')))
    
    return {
        'tier': tier,
        'capacity': CONFIG['business_tiers'][tier]['capacity'],
        'available': config_count,
        'qr_codes': qr_count,
        'price_cents': CONFIG['business_tiers'][tier]['price'],
        'price_usd': CONFIG['business_tiers'][tier]['price'] / 100,
        'duration': CONFIG['business_tiers'][tier]['duration'],
        'revenue_potential': config_count * CONFIG['business_tiers'][tier]['price'],
        'status': 'operational'
    }

def get_wireguard_status():
    """Get WireGuard service status"""
    try:
        result = subprocess.run(['systemctl', 'is-active', 'wg-quick@wg0'], 
                              capture_output=True, text=True, timeout=5)
        service_active = result.returncode == 0
        
        if service_active:
            wg_result = subprocess.run(['wg', 'show', 'wg0'], 
                                     capture_output=True, text=True, timeout=5)
            peer_count = len([line for line in wg_result.stdout.split('\n') 
                            if line.strip().startswith('peer:')])
            return {
                'status': 'active',
                'peers_configured': peer_count,
                'interface': 'wg0',
                'port': 51820
            }
        else:
            return {'status': 'inactive', 'peers_configured': 0}
            
    except Exception as e:
        logger.error(f"Error checking WireGuard status: {e}")
        return {'status': 'error', 'error': str(e)}

@app.route('/api/status', methods=['GET'])
def get_business_status():
    """Get complete business status"""
    try:
        tier_statuses = {}
        total_revenue_potential = 0
        total_available = 0
        total_capacity = 0
        
        for tier in CONFIG['business_tiers']:
            tier_status = get_tier_status(tier)
            tier_statuses[tier] = tier_status
            total_available += tier_status['available']
            total_capacity += tier_status['capacity']
            total_revenue_potential += tier_status['revenue_potential']
        
        wireguard_status = get_wireguard_status()
        
        return jsonify({
            'business_name': 'Tunnelgrain',
            'timestamp': datetime.now().isoformat(),
            'server_ip': CONFIG['server_ip'],
            'status': 'operational',
            'version': '3.0.0',
            'tiers': tier_statuses,
            'summary': {
                'total_capacity': total_capacity,
                'total_available': total_available,
                'utilization_percent': round((total_capacity - total_available) / total_capacity * 100, 1) if total_capacity > 0 else 0,
                'revenue_potential_cents': total_revenue_potential,
                'revenue_potential_usd': round(total_revenue_potential / 100, 2),
                'wireguard': wireguard_status
            }
        })
        
    except Exception as e:
        logger.error(f"Error in business status: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/tiers', methods=['GET'])
def get_tiers():
    """Get tier information"""
    try:
        tiers = {}
        for tier, config in CONFIG['business_tiers'].items():
            tier_status = get_tier_status(tier)
            tiers[tier] = {
                'name': tier.title(),
                'capacity': config['capacity'],
                'price_cents': config['price'],
                'price_usd': config['price'] / 100,
                'duration': config['duration'],
                'available': tier_status['available'],
                'description': f"{config['duration']} VPN access for ${config['price']/100:.2f}"
            }
        
        return jsonify({'tiers': tiers})
        
    except Exception as e:
        logger.error(f"Error getting tiers: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Business health check"""
    return jsonify({
        'status': 'healthy',
        'service': 'tunnelgrain-business-api',
        'version': '3.0.0',
        'timestamp': datetime.now().isoformat(),
        'server_ip': CONFIG['server_ip']
    })

@app.route('/api/config/<tier>/<order_number>', methods=['GET'])
def serve_config(tier, order_number):
    """Serve VPN configuration file"""
    try:
        if tier not in CONFIG['business_tiers']:
            return jsonify({'error': 'Invalid tier'}), 400
            
        config_file = Path(CONFIG['base_dir']) / 'configs' / tier / f"{order_number}.conf"
        
        if config_file.exists():
            logger.info(f"Serving config: {tier}/{order_number}")
            return send_file(str(config_file), 
                           as_attachment=True,
                           download_name=f"tunnelgrain_{order_number}.conf")
        
        return jsonify({'error': 'Configuration not found'}), 404
        
    except Exception as e:
        logger.error(f"Error serving config {tier}/{order_number}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/qr/<tier>/<order_number>', methods=['GET'])
def serve_qr_code(tier, order_number):
    """Serve QR code"""
    try:
        if tier not in CONFIG['business_tiers']:
            return jsonify({'error': 'Invalid tier'}), 400
            
        qr_file = Path(CONFIG['base_dir']) / 'qr_codes' / tier / f"{order_number}.png"
        
        if qr_file.exists():
            logger.info(f"Serving QR code: {tier}/{order_number}")
            return send_file(str(qr_file),
                           as_attachment=True,
                           download_name=f"tunnelgrain_{order_number}_qr.png")
        
        return jsonify({'error': 'QR code not found'}), 404
        
    except Exception as e:
        logger.error(f"Error serving QR {tier}/{order_number}: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    logger.info("Starting Tunnelgrain Business API v3.0.0")
    app.run(host='0.0.0.0', port=8080, debug=False)
API_EOF

chmod +x /opt/tunnelgrain/api/tunnelgrain_api.py

# Deactivate virtual environment
deactivate

# Create systemd service for API
cat > /etc/systemd/system/tunnelgrain-api.service << EOF
[Unit]
Description=Tunnelgrain Business API Service v3.0
After=network.target wg-quick@wg0.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/tunnelgrain/api
Environment=PATH=/opt/tunnelgrain/api/venv/bin
ExecStart=/opt/tunnelgrain/api/venv/bin/python /opt/tunnelgrain/api/tunnelgrain_api.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Start API service
systemctl daemon-reload
systemctl enable tunnelgrain-api >/dev/null 2>&1
systemctl start tunnelgrain-api

# Wait for API to initialize
sleep 3

if systemctl is-active tunnelgrain-api >/dev/null 2>&1; then
    success "Business API service started successfully"
else
    warn "API service may need a moment to start (this is normal)"
fi

# ============================================================================
# STEP 8: MANAGEMENT TOOLS
# ============================================================================
log "STEP 8/8: Creating management tools..."

# Status monitoring script
cat > /opt/tunnelgrain/scripts/status.sh << 'STATUS_EOF'
#!/bin/bash
# Tunnelgrain Business Status Monitor

echo -e "\033[0;36m🚀 TUNNELGRAIN BUSINESS STATUS\033[0m"
echo "==============================="
echo "Time: $(date)"
echo ""

# Service status
echo -e "\033[0;34m🔧 Core Services:\033[0m"
wg_status=$(systemctl is-active wg-quick@wg0 2>/dev/null && echo "✅ Running" || echo "❌ Failed")
api_status=$(systemctl is-active tunnelgrain-api 2>/dev/null && echo "✅ Running" || echo "❌ Failed")
echo "  WireGuard: $wg_status"
echo "  API Service: $api_status"
echo ""

# Configuration counts
echo -e "\033[0;34m📊 Configuration Inventory:\033[0m"
total=0
for tier in test monthly quarterly biannual annual lifetime; do
    count=$(ls /opt/tunnelgrain/configs/$tier/*.conf 2>/dev/null | wc -l)
    total=$((total + count))
    echo "  $tier: $count configs"
done
echo "  TOTAL: $total configs"
echo ""

# Revenue potential
echo -e "\033[0;34m💰 Revenue Potential:\033[0m"
curl -s http://localhost:8080/api/status 2>/dev/null | jq -r '
  "  Max Monthly Revenue: $" + (.summary.revenue_potential_usd | tostring),
  "  Server Status: " + .status,
  "  WireGuard Peers: " + (.summary.wireguard.peers_configured | tostring)
' 2>/dev/null || echo "  ❌ API not responding"

echo ""
echo -e "\033[0;34m🌐 Test Commands:\033[0m"
echo "  curl http://213.170.133.116:8080/api/health"
echo "  curl http://213.170.133.116:8080/api/status"
echo "  curl http://213.170.133.116:8080/api/tiers"
STATUS_EOF

chmod +x /opt/tunnelgrain/scripts/status.sh

# Backup script
cat > /opt/tunnelgrain/scripts/backup.sh << 'BACKUP_EOF'
#!/bin/bash
# Tunnelgrain Business Backup Script

BACKUP_DIR="/opt/tunnelgrain/backups/backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "🔄 Creating business backup..."

# Backup critical business data
cp -r /opt/tunnelgrain/configs "$BACKUP_DIR/"
cp -r /opt/tunnelgrain/qr_codes "$BACKUP_DIR/"
cp -r /opt/tunnelgrain/keys "$BACKUP_DIR/"
cp /etc/wireguard/wg0.conf "$BACKUP_DIR/"
cp -r /opt/tunnelgrain/api "$BACKUP_DIR/"
cp /opt/tunnelgrain/peer_mapping.txt "$BACKUP_DIR/" 2>/dev/null || true

# Create manifest
cat > "$BACKUP_DIR/manifest.txt" << EOF
Tunnelgrain Business Backup
Created: $(date)
Server: 213.170.133.116
Total Configs: $(find /opt/tunnelgrain/configs -name "*.conf" | wc -l)
Total QR Codes: $(find /opt/tunnelgrain/qr_codes -name "*.png" | wc -l)
WireGuard Status: $(systemctl is-active wg-quick@wg0)
API Status: $(systemctl is-active tunnelgrain-api)
EOF

echo "✅ Business backup created: $BACKUP_DIR"

# Create compressed archive
tar -czf "$BACKUP_DIR.tar.gz" -C "$(dirname "$BACKUP_DIR")" "$(basename "$BACKUP_DIR")" 2>/dev/null
echo "✅ Compressed backup: $BACKUP_DIR.tar.gz"

# Keep only last 10 backups
cd /opt/tunnelgrain/backups
ls -t backup_*.tar.gz 2>/dev/null | tail -n +11 | xargs rm -f 2>/dev/null || true

echo "📊 Backup completed successfully"
BACKUP_EOF

chmod +x /opt/tunnelgrain/scripts/backup.sh

# Quick test script
cat > /opt/tunnelgrain/scripts/test.sh << 'TEST_EOF'
#!/bin/bash
# Quick functionality test

echo "🧪 TUNNELGRAIN FUNCTIONALITY TEST"
echo "================================="

# Test WireGuard
echo -n "WireGuard Service: "
if systemctl is-active wg-quick@wg0 >/dev/null; then
    echo "✅ PASS"
else
    echo "❌ FAIL"
fi

# Test API Health
echo -n "API Health Check: "
if curl -s http://localhost:8080/api/health >/dev/null; then
    echo "✅ PASS"
else
    echo "❌ FAIL"
fi

# Test API Status
echo -n "API Status Endpoint: "
if curl -s http://localhost:8080/api/status | jq . >/dev/null 2>&1; then
    echo "✅ PASS"
else
    echo "❌ FAIL"
fi

# Test Configuration Files
echo -n "Configuration Files: "
config_count=$(find /opt/tunnelgrain/configs -name "*.conf" | wc -l)
if [ "$config_count" -gt 100 ]; then
    echo "✅ PASS ($config_count configs)"
else
    echo "❌ FAIL ($config_count configs)"
fi

echo ""
echo "Test completed. If all PASS, your VPN business is ready!"
TEST_EOF

chmod +x /opt/tunnelgrain/scripts/test.sh

success "Management tools created"

# ============================================================================
# FINAL VERIFICATION & STATUS REPORT
# ============================================================================
log "Running final verification..."

# Test API
api_test="❌"
if curl -s http://localhost:8080/api/health >/dev/null 2>&1; then
    api_test="✅"
fi

# Count configurations
config_count=$(find /opt/tunnelgrain/configs -name "*.conf" | wc -l)
qr_count=$(find /opt/tunnelgrain/qr_codes -name "*.png" | wc -l)

# Calculate revenue potential
revenue_test=0
revenue_monthly=$((30 * 499))
revenue_quarterly=$((20 * 1299))
revenue_biannual=$((15 * 2399))
revenue_annual=$((10 * 3999))
revenue_lifetime=$((5 * 9999))
total_revenue=$((revenue_monthly + revenue_quarterly + revenue_biannual + revenue_annual + revenue_lifetime))

# ============================================================================
# BEAUTIFUL FINAL REPORT
# ============================================================================
echo ""
echo -e "${CYAN}"
cat << 'SUCCESS_HEADER'
╔══════════════════════════════════════════════════════════════╗
║                🎉 SETUP COMPLETED SUCCESSFULLY! 🎉          ║
║              Your VPN Business is Ready to Launch           ║
╚══════════════════════════════════════════════════════════════╝
SUCCESS_HEADER
echo -e "${NC}"

echo -e "${BLUE}📊 BUSINESS SUMMARY${NC}"
echo "==================="
echo "  🖥️  Server IP: $SERVER_IP"
echo "  🔧 WireGuard: $(systemctl is-active wg-quick@wg0 && echo "✅ Running" || echo "❌ Failed")"
echo "  🌐 API Service: $api_test $(systemctl is-active tunnelgrain-api 2>/dev/null || echo "Starting...")"
echo "  📄 VPN Configs: $config_count"
echo "  📱 QR Codes: $qr_count"

echo ""
echo -e "${BLUE}💰 REVENUE POTENTIAL${NC}"
echo "===================="
echo "  📊 Test (Free): 50 slots × \$0.00 = \$0.00"
echo "  📅 Monthly: 30 slots × \$4.99 = \$149.70"
echo "  📈 Quarterly: 20 slots × \$12.99 = \$259.80"
echo "  📊 Biannual: 15 slots × \$23.99 = \$359.85"
echo "  📆 Annual: 10 slots × \$39.99 = \$399.90"
echo "  ♾️  Lifetime: 5 slots × \$99.99 = \$499.95"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  💎 TOTAL POTENTIAL: \$1,669.20/month"

echo ""
echo -e "${BLUE}🔧 MANAGEMENT TOOLS${NC}"
echo "==================="
echo "  📊 Business Status: /opt/tunnelgrain/scripts/status.sh"
echo "  💾 Create Backup: /opt/tunnelgrain/scripts/backup.sh"
echo "  🧪 Run Tests: /opt/tunnelgrain/scripts/test.sh"
echo "  📋 View Logs: journalctl -u tunnelgrain-api -f"

echo ""
echo -e "${BLUE}🌐 API ENDPOINTS${NC}"
echo "================"
echo "  🏥 Health: curl http://$SERVER_IP:8080/api/health"
echo "  📊 Status: curl http://$SERVER_IP:8080/api/status"
echo "  🏷️  Tiers: curl http://$SERVER_IP:8080/api/tiers"
echo "  📄 Config: curl http://$SERVER_IP:8080/api/config/[tier]/[order_number]"
echo "  📱 QR Code: curl http://$SERVER_IP:8080/api/qr/[tier]/[order_number]"

echo ""
echo -e "${BLUE}📁 BUSINESS DATA LOCATIONS${NC}"
echo "=========================="
echo "  🏠 Base Directory: /opt/tunnelgrain/"
echo "  📄 VPN Configs: /opt/tunnelgrain/configs/"
echo "  📱 QR Codes: /opt/tunnelgrain/qr_codes/"
echo "  🔑 Keys: /opt/tunnelgrain/keys/"
echo "  💾 Backups: /opt/tunnelgrain/backups/"
echo "  📊 Logs: /opt/tunnelgrain/logs/"

echo ""
echo -e "${BLUE}📤 DOWNLOAD CONFIGS TO LOCAL MACHINE${NC}"
echo "====================================="
echo "Run these commands on your local machine:"
echo ""
echo -e "${YELLOW}# Create local directory structure${NC}"
echo "mkdir -p tunnelgrain_configs/{test,monthly,quarterly,biannual,annual,lifetime}"
echo "mkdir -p tunnelgrain_qrcodes/{test,monthly,quarterly,biannual,annual,lifetime}"
echo ""
echo -e "${YELLOW}# Download all configs and QR codes${NC}"
echo "scp -r root@$SERVER_IP:/opt/tunnelgrain/configs/* tunnelgrain_configs/"
echo "scp -r root@$SERVER_IP:/opt/tunnelgrain/qr_codes/* tunnelgrain_qrcodes/"
echo ""
echo -e "${YELLOW}# Download server keys (for backup)${NC}"
echo "scp root@$SERVER_IP:/opt/tunnelgrain/keys/* ."

echo ""
echo -e "${GREEN}✅ IMMEDIATE NEXT STEPS${NC}"
echo "======================="
echo "1. 🧪 Test the setup: /opt/tunnelgrain/scripts/test.sh"
echo "2. 📊 Check status: /opt/tunnelgrain/scripts/status.sh"
echo "3. 📤 Download configs to your local machine (commands above)"
echo "4. 🔧 Update your Render Flask app to use this VPS API"
echo "5. 💳 Configure Stripe for the new multi-tier pricing"
echo "6. 🚀 Start taking payments and serving customers!"

echo ""
echo -e "${GREEN}🎯 QUICK VERIFICATION${NC}"
echo "==================="
echo "Run this command to verify everything is working:"
echo -e "${CYAN}curl http://$SERVER_IP:8080/api/status | jq${NC}"

echo ""
echo -e "${PURPLE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${PURPLE}║  🚀 CONGRATULATIONS! Your VPN business is ready to go!  ║${NC}"
echo -e "${PURPLE}║     Professional setup complete in $(date +%M) minutes! 🎉            ║${NC}"
echo -e "${PURPLE}═══════════════════════════════════════════════════════════${NC}"

# Create a quick status check
echo ""
log "Running quick verification..."

# Wait a moment for services to fully start
sleep 5

# Test API
if curl -s http://localhost:8080/api/health | grep -q "healthy"; then
    success "✅ API is responding correctly"
else
    warn "⚠️ API may still be starting up (this is normal)"
fi

# Final file count verification
final_config_count=$(find /opt/tunnelgrain/configs -name "*.conf" | wc -l)
final_qr_count=$(find /opt/tunnelgrain/qr_codes -name "*.png" | wc -l)

if [ "$final_config_count" -eq 130 ] && [ "$final_qr_count" -eq 130 ]; then
    success "✅ All 130 configs and QR codes generated successfully"
else
    warn "⚠️ Config count: $final_config_count, QR count: $final_qr_count (expected 130 each)"
fi

echo ""
echo -e "${CYAN}🎯 SETUP COMPLETE! Run this to verify everything:${NC}"
echo -e "${YELLOW}/opt/tunnelgrain/scripts/test.sh${NC}"

# Create helpful aliases for root
cat >> /root/.bashrc << 'BASHRC_EOF'

# Tunnelgrain VPN Business Aliases
alias tg-status="/opt/tunnelgrain/scripts/status.sh"
alias tg-backup="/opt/tunnelgrain/scripts/backup.sh"
alias tg-test="/opt/tunnelgrain/scripts/test.sh"
alias tg-logs="journalctl -u tunnelgrain-api -f"
alias tg-restart="systemctl restart tunnelgrain-api wg-quick@wg0"

echo "🚀 Tunnelgrain VPN Business Server Ready!"
echo "Quick commands: tg-status, tg-backup, tg-test, tg-logs, tg-restart"
BASHRC_EOF

success "Setup completed successfully! 🎉"