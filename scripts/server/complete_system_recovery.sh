#!/bin/bash
# complete_system_recovery.sh - Clean restart of Tunnelgrain VPN system

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🔄 TUNNELGRAIN SYSTEM RECOVERY${NC}"
echo "This script will clean and rebuild your entire VPN system"
echo ""

# Server configuration
SERVER_PRIVATE_KEY="0Ac9E5xwq75N34QhRUytVzDuGAZopnczeWv7ldJVrHw="
SERVER_PUBLIC_KEY="kYrikmdCzYOhM4R+A6LVnh6f0y3XPAfuPLNEaoExN30="
SERVER_ENDPOINT="213.170.133.116:51820"

# Directories
CONFIG_DIR="/root/configs"
BACKUP_DIR="/root/backup_$(date +%Y%m%d_%H%M%S)"
QR_DIR="/root/qr_codes"

echo -e "${YELLOW}📋 Step 1: Backup Current System${NC}"
mkdir -p "$BACKUP_DIR"
if [ -f "/etc/wireguard/wg0.conf" ]; then
    cp /etc/wireguard/wg0.conf "$BACKUP_DIR/"
    echo "✅ Backed up current WireGuard config"
fi
if [ -d "$CONFIG_DIR" ]; then
    cp -r "$CONFIG_DIR" "$BACKUP_DIR/"
    echo "✅ Backed up existing configs"
fi

echo -e "${YELLOW}📋 Step 2: Stop and Clean WireGuard${NC}"
systemctl stop wg-quick@wg0 2>/dev/null || echo "WireGuard wasn't running"
rm -f /etc/wireguard/wg0.conf
echo "✅ Cleaned WireGuard configuration"

echo -e "${YELLOW}📋 Step 3: Create Fresh Directory Structure${NC}"
rm -rf "$CONFIG_DIR" "$QR_DIR"
mkdir -p "$CONFIG_DIR/monthly" "$CONFIG_DIR/test" "$QR_DIR"
echo "✅ Created clean directory structure"

echo -e "${YELLOW}📋 Step 4: Generate ALL Configs Fresh${NC}"

# Monthly clients (these stay permanent)
echo "🚀 Generating monthly client configs..."
for i in $(seq -f "%02g" 1 10); do
    client_name="client_$i"
    client_ip="10.0.0.$((10#$i + 1))"
    config_file="$CONFIG_DIR/monthly/${client_name}.conf"
    qr_file="$QR_DIR/${client_name}.png"
    
    # Generate new keys for this client
    client_private=$(wg genkey)
    client_public=$(echo "$client_private" | wg pubkey)
    
    # Create client config
    cat > "$config_file" << EOF
[Interface]
PrivateKey = $client_private
Address = $client_ip/24
DNS = 1.1.1.1

[Peer]
PublicKey = $SERVER_PUBLIC_KEY
Endpoint = $SERVER_ENDPOINT
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
EOF
    
    # Generate QR code
    qrencode -t png -o "$qr_file" < "$config_file"
    chmod 600 "$config_file"
    chmod 644 "$qr_file"
    
    echo "  ✅ Generated $client_name ($client_ip) - $client_public"
done

# Test clients (these will be regenerated daily)
echo "🧪 Generating test client configs..."
for i in $(seq -f "%02g" 1 10); do
    client_name="test_$i"
    client_ip="10.0.0.$((10#$i + 20))"
    config_file="$CONFIG_DIR/test/${client_name}.conf"
    qr_file="$QR_DIR/${client_name}.png"
    
    # Generate new keys for this client
    client_private=$(wg genkey)
    client_public=$(echo "$client_private" | wg pubkey)
    
    # Create client config
    cat > "$config_file" << EOF
[Interface]
PrivateKey = $client_private
Address = $client_ip/24
DNS = 1.1.1.1

[Peer]
PublicKey = $SERVER_PUBLIC_KEY
Endpoint = $SERVER_ENDPOINT
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
EOF
    
    # Generate QR code
    qrencode -t png -o "$qr_file" < "$config_file"
    chmod 600 "$config_file"
    chmod 644 "$qr_file"
    
    echo "  ✅ Generated $client_name ($client_ip) - $client_public"
done

echo -e "${YELLOW}📋 Step 5: Build Clean Server Config${NC}"

# Function to extract public key from config
get_public_key() {
    local config_file="$1"
    local private_key=$(grep "PrivateKey" "$config_file" | awk '{print $3}')
    echo "$private_key" | wg pubkey
}

# Build server configuration
server_config="[Interface]
Address = 10.0.0.1/24
ListenPort = 51820
PrivateKey = $SERVER_PRIVATE_KEY
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

# ===== MONTHLY CLIENTS (client_01 to client_10) =====
# IP Range: 10.0.0.2 - 10.0.0.11

"

# Add monthly clients to server config
for i in $(seq -f "%02g" 1 10); do
    client_name="client_$i"
    config_file="$CONFIG_DIR/monthly/${client_name}.conf"
    client_ip="10.0.0.$((10#$i + 1))"
    client_public=$(get_public_key "$config_file")
    
    server_config+="[Peer]
# Monthly Client $i - Tunnelgrain
PublicKey = $client_public
AllowedIPs = $client_ip/32

"
done

server_config+="# ===== TEST CLIENTS (test_01 to test_10) =====
# IP Range: 10.0.0.21 - 10.0.0.30

"

# Add test clients to server config
for i in $(seq -f "%02g" 1 10); do
    client_name="test_$i"
    config_file="$CONFIG_DIR/test/${client_name}.conf"
    client_ip="10.0.0.$((10#$i + 20))"
    client_public=$(get_public_key "$config_file")
    
    server_config+="[Peer]
# Test Client $i - Tunnelgrain
PublicKey = $client_public
AllowedIPs = $client_ip/32

"
done

# Write server config
echo "$server_config" > /etc/wireguard/wg0.conf
chmod 600 /etc/wireguard/wg0.conf
echo "✅ Created clean server configuration"

echo -e "${YELLOW}📋 Step 6: Start WireGuard Service${NC}"
systemctl enable wg-quick@wg0
systemctl start wg-quick@wg0
echo "✅ WireGuard service started"

echo -e "${YELLOW}📋 Step 7: Create Automation Scripts${NC}"

# Create test slot regeneration script
cat > /root/regenerate_test_slots.sh << 'REGEN_EOF'
#!/bin/bash
# regenerate_test_slots.sh - Daily test slot regeneration

set -e

SERVER_PRIVATE_KEY="0Ac9E5xwq75N34QhRUytVzDuGAZopnczeWv7ldJVrHw="
SERVER_PUBLIC_KEY="kYrikmdCzYOhM4R+A6LVnh6f0y3XPAfuPLNEaoExN30="
SERVER_ENDPOINT="213.170.133.116:51820"
CONFIG_DIR="/root/configs"
QR_DIR="/root/qr_codes"
LOG_FILE="/var/log/test-slot-regeneration.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "🔄 Starting daily test slot regeneration..."

# Archive old test configs
ARCHIVE_DIR="/root/archives/test_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$ARCHIVE_DIR"
if [ -d "$CONFIG_DIR/test" ]; then
    cp -r "$CONFIG_DIR/test"/* "$ARCHIVE_DIR/" 2>/dev/null || true
    cp "$QR_DIR"/test_*.png "$ARCHIVE_DIR/" 2>/dev/null || true
    log "✅ Archived old test configs to $ARCHIVE_DIR"
fi

# Generate new test configs
for i in $(seq -f "%02g" 1 10); do
    client_name="test_$i"
    client_ip="10.0.0.$((10#$i + 20))"
    config_file="$CONFIG_DIR/test/${client_name}.conf"
    qr_file="$QR_DIR/${client_name}.png"
    
    # Generate new keys
    client_private=$(wg genkey)
    client_public=$(echo "$client_private" | wg pubkey)
    
    # Create config
    cat > "$config_file" << EOF
[Interface]
PrivateKey = $client_private
Address = $client_ip/24
DNS = 1.1.1.1

[Peer]
PublicKey = $SERVER_PUBLIC_KEY
Endpoint = $SERVER_ENDPOINT
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
EOF
    
    # Generate QR code
    qrencode -t png -o "$qr_file" < "$config_file"
    chmod 600 "$config_file"
    chmod 644 "$qr_file"
    
    log "  ✅ Regenerated $client_name - $client_public"
done

# Update server config with new test client keys
get_public_key() {
    local config_file="$1"
    local private_key=$(grep "PrivateKey" "$config_file" | awk '{print $3}')
    echo "$private_key" | wg pubkey
}

# Rebuild server config
server_config="[Interface]
Address = 10.0.0.1/24
ListenPort = 51820
PrivateKey = $SERVER_PRIVATE_KEY
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

# ===== MONTHLY CLIENTS (client_01 to client_10) =====
# IP Range: 10.0.0.2 - 10.0.0.11

"

# Add monthly clients (these never change)
for i in $(seq -f "%02g" 1 10); do
    client_name="client_$i"
    config_file="$CONFIG_DIR/monthly/${client_name}.conf"
    client_ip="10.0.0.$((10#$i + 1))"
    client_public=$(get_public_key "$config_file")
    
    server_config+="[Peer]
# Monthly Client $i - Tunnelgrain
PublicKey = $client_public
AllowedIPs = $client_ip/32

"
done

server_config+="# ===== TEST CLIENTS (test_01 to test_10) =====
# IP Range: 10.0.0.21 - 10.0.0.30

"

# Add new test clients
for i in $(seq -f "%02g" 1 10); do
    client_name="test_$i"
    config_file="$CONFIG_DIR/test/${client_name}.conf"
    client_ip="10.0.0.$((10#$i + 20))"
    client_public=$(get_public_key "$config_file")
    
    server_config+="[Peer]
# Test Client $i - Tunnelgrain (Generated $(date))
PublicKey = $client_public
AllowedIPs = $client_ip/32

"
done

# Update server config
echo "$server_config" > /etc/wireguard/wg0.conf
chmod 600 /etc/wireguard/wg0.conf

# Restart WireGuard
systemctl restart wg-quick@wg0

log "✅ Test slot regeneration completed successfully"
log "📤 MANUAL STEP: Upload new test configs to Flask app"

# Clean old archives (keep last 30 days)
find /root/archives -name "test_*" -type d -mtime +30 -exec rm -rf {} \; 2>/dev/null || true
REGEN_EOF

chmod +x /root/regenerate_test_slots.sh
echo "✅ Created test slot regeneration script"

# Install daily cron job
(crontab -l 2>/dev/null | grep -v "regenerate_test_slots.sh"; echo "0 2 * * * /root/regenerate_test_slots.sh >> /var/log/test-slot-regeneration.log 2>&1") | crontab -
echo "✅ Installed daily cron job (2 AM)"

echo -e "${YELLOW}📋 Step 8: Create Quick Management Scripts${NC}"

# Create status check script
cat > /root/check_status.sh << 'STATUS_EOF'
#!/bin/bash
echo "=== TUNNELGRAIN VPN STATUS ==="
echo "Time: $(date)"
echo ""
echo "WireGuard Status:"
systemctl status wg-quick@wg0 --no-pager
echo ""
echo "Active Connections:"
wg show
echo ""
echo "Config Files:"
echo "Monthly: $(ls /root/configs/monthly/*.conf 2>/dev/null | wc -l)/10"
echo "Test: $(ls /root/configs/test/*.conf 2>/dev/null | wc -l)/10"
echo "QR Codes: $(ls /root/qr_codes/*.png 2>/dev/null | wc -l)/20"
STATUS_EOF

chmod +x /root/check_status.sh
echo "✅ Created status check script"

echo -e "${GREEN}🎉 SYSTEM RECOVERY COMPLETE!${NC}"
echo ""
echo -e "${BLUE}📋 Next Steps:${NC}"
echo "1. Run: /root/check_status.sh (verify everything works)"
echo "2. Test connection with one config file"
echo "3. Download configs to your local machine for Flask app:"
echo "   scp -r root@213.170.133.116:/root/configs ./data"
echo "   scp -r root@213.170.133.116:/root/qr_codes ./static"
echo "4. Update your Flask app with new config files"
echo ""
echo -e "${YELLOW}⚡ Automation Installed:${NC}"
echo "• Daily test slot regeneration at 2 AM"
echo "• Run manually: /root/regenerate_test_slots.sh"
echo "• Check logs: tail -f /var/log/test-slot-regeneration.log"
echo ""
echo -e "${GREEN}✅ Your VPN service is now clean and automated!${NC}"