#!/bin/bash
# complete_system_recovery.sh - Clean restart with ORDER-BASED naming

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🔄 TUNNELGRAIN ORDER-BASED SYSTEM RECOVERY${NC}"
echo "This script will clean and rebuild your entire VPN system with order-based naming"
echo ""

# Server configuration
SERVER_PRIVATE_KEY="WHiWHa/bR9i8uIaQ9Hcln+angcl9cVfQBxjBZ0wptFc="
SERVER_PUBLIC_KEY="gWJ+k9yV83ByDSXRIB6w+WKBDHqSGyCIT+e5aFaWY2Q="
SERVER_ENDPOINT="213.170.133.116:51820"

# Directories
CONFIG_DIR="/root/configs"
BACKUP_DIR="/root/backup_$(date +%Y%m%d_%H%M%S)"
QR_DIR="/root/qr_codes"

# ORDER NUMBER FUNCTIONS
generate_monthly_order() {
    local index=$1
    echo "42$(printf "%06X" $((0x100000 + index)))"
}

generate_test_order() {
    local index=$1
    echo "72$(printf "%06X" $((0x100000 + index)))"
}

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

echo -e "${YELLOW}📋 Step 4: Generate ORDER-BASED Configs${NC}"

# MONTHLY CLIENTS (ORDER-BASED NAMING)
echo "🚀 Generating monthly client configs with ORDER NUMBERS..."
for i in $(seq 1 10); do
    ORDER_NUMBER=$(generate_monthly_order $i)
    SLOT_ID="client_$(printf "%02d" $i)"
    CLIENT_IP="10.0.0.$((i + 1))"
    
    # ✅ FIX: Config file named with ORDER NUMBER (not slot_id)
    config_file="$CONFIG_DIR/monthly/${ORDER_NUMBER}.conf"
    qr_file="$QR_DIR/${ORDER_NUMBER}.png"
    
    # Generate new keys for this client
    client_private=$(wg genkey)
    client_public=$(echo "$client_private" | wg pubkey)
    
    # Create client config with ORDER NUMBER as filename
    cat > "$config_file" << EOF
[Interface]
PrivateKey = $client_private
Address = $CLIENT_IP/24
DNS = 1.1.1.1

[Peer]
PublicKey = $SERVER_PUBLIC_KEY
Endpoint = $SERVER_ENDPOINT
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
EOF
    
    # Generate QR code with ORDER NUMBER as filename
    qrencode -t png -o "$qr_file" < "$config_file"
    chmod 600 "$config_file"
    chmod 644 "$qr_file"
    
    # Store mapping for server config
    echo "$SLOT_ID:$ORDER_NUMBER:$client_public:$CLIENT_IP" >> /tmp/monthly_mapping.txt
    
    echo "  ✅ Generated $ORDER_NUMBER (slot: $SLOT_ID, IP: $CLIENT_IP)"
done

# TEST CLIENTS (ORDER-BASED NAMING)
echo "🧪 Generating test client configs with ORDER NUMBERS..."
for i in $(seq 1 10); do
    ORDER_NUMBER=$(generate_test_order $i)
    SLOT_ID="test_$(printf "%02d" $i)"
    CLIENT_IP="10.0.0.$((i + 20))"
    
    # ✅ FIX: Config file named with ORDER NUMBER (not slot_id)
    config_file="$CONFIG_DIR/test/${ORDER_NUMBER}.conf"
    qr_file="$QR_DIR/${ORDER_NUMBER}.png"
    
    # Generate new keys for this client
    client_private=$(wg genkey)
    client_public=$(echo "$client_private" | wg pubkey)
    
    # Create client config with ORDER NUMBER as filename
    cat > "$config_file" << EOF
[Interface]
PrivateKey = $client_private
Address = $CLIENT_IP/24
DNS = 1.1.1.1

[Peer]
PublicKey = $SERVER_PUBLIC_KEY
Endpoint = $SERVER_ENDPOINT
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
EOF
    
    # Generate QR code with ORDER NUMBER as filename
    qrencode -t png -o "$qr_file" < "$config_file"
    chmod 600 "$config_file"
    chmod 644 "$qr_file"
    
    # Store mapping for server config
    echo "$SLOT_ID:$ORDER_NUMBER:$client_public:$CLIENT_IP" >> /tmp/test_mapping.txt
    
    echo "  ✅ Generated $ORDER_NUMBER (slot: $SLOT_ID, IP: $CLIENT_IP)"
done

echo -e "${YELLOW}📋 Step 5: Build Clean Server Config${NC}"

# Build server configuration with ORDER NUMBERS in comments
server_config="[Interface]
Address = 10.0.0.1/24
ListenPort = 51820
PrivateKey = $SERVER_PRIVATE_KEY
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

# ===== MONTHLY CLIENTS (Order Numbers: 42XXXXXX) =====
# IP Range: 10.0.0.2 - 10.0.0.11

"

# Add monthly clients to server config
while IFS=: read -r slot_id order_number client_public client_ip; do
    server_config+="[Peer]
# Monthly Client: $slot_id - Order: $order_number
PublicKey = $client_public
AllowedIPs = $client_ip/32

"
done < /tmp/monthly_mapping.txt

server_config+="# ===== TEST CLIENTS (Order Numbers: 72XXXXXX) =====
# IP Range: 10.0.0.21 - 10.0.0.30

"

# Add test clients to server config
while IFS=: read -r slot_id order_number client_public client_ip; do
    server_config+="[Peer]
# Test Client: $slot_id - Order: $order_number
PublicKey = $client_public
AllowedIPs = $client_ip/32

"
done < /tmp/test_mapping.txt

# Write server config
echo "$server_config" > /etc/wireguard/wg0.conf
chmod 600 /etc/wireguard/wg0.conf
echo "✅ Created clean server configuration with order-based comments"

echo -e "${YELLOW}📋 Step 6: Start WireGuard Service${NC}"
systemctl enable wg-quick@wg0
systemctl start wg-quick@wg0
echo "✅ WireGuard service started"

echo -e "${YELLOW}📋 Step 7: Create ORDER-BASED Automation Scripts${NC}"

# Create UPDATED test slot regeneration script with ORDER NUMBERS
cat > /root/regenerate_test_slots.sh << 'REGEN_EOF'
#!/bin/bash
# regenerate_test_slots.sh - Daily test slot regeneration with ORDER NUMBERS

set -e

SERVER_PRIVATE_KEY="0Ac9E5xwq75N34QhRUytVzDuGAZopnczeWv7ldJVrHw="
SERVER_PUBLIC_KEY="kYrikmdCzYOhM4R+A6LVnh6f0y3XPAfuPLNEaoExN30="
SERVER_ENDPOINT="213.170.133.116:51820"
CONFIG_DIR="/root/configs"
QR_DIR="/root/qr_codes"
LOG_FILE="/var/log/test-slot-regeneration.log"

# ORDER NUMBER FUNCTIONS
generate_test_order() {
    local index=$1
    echo "72$(printf "%06X" $((0x100000 + index)))"
}

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "🔄 Starting daily test slot regeneration with ORDER NUMBERS..."

# Archive old test configs
ARCHIVE_DIR="/root/archives/test_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$ARCHIVE_DIR"
if [ -d "$CONFIG_DIR/test" ]; then
    cp -r "$CONFIG_DIR/test"/* "$ARCHIVE_DIR/" 2>/dev/null || true
    cp "$QR_DIR"/72*.png "$ARCHIVE_DIR/" 2>/dev/null || true
    log "✅ Archived old test configs to $ARCHIVE_DIR"
fi

# Remove old test configs (ORDER-BASED cleanup)
rm -f "$CONFIG_DIR/test"/72*.conf
rm -f "$QR_DIR"/72*.png

# Generate new test configs with ORDER NUMBERS
for i in $(seq 1 10); do
    ORDER_NUMBER=$(generate_test_order $i)
    SLOT_ID="test_$(printf "%02d" $i)"
    CLIENT_IP="10.0.0.$((i + 20))"
    
    # ✅ FIX: Config file named with ORDER NUMBER
    config_file="$CONFIG_DIR/test/${ORDER_NUMBER}.conf"
    qr_file="$QR_DIR/${ORDER_NUMBER}.png"
    
    # Generate new keys
    client_private=$(wg genkey)
    client_public=$(echo "$client_private" | wg pubkey)
    
    # Create config with ORDER NUMBER as filename
    cat > "$config_file" << EOF
[Interface]
PrivateKey = $client_private
Address = $CLIENT_IP/24
DNS = 1.1.1.1

[Peer]
PublicKey = $SERVER_PUBLIC_KEY
Endpoint = $SERVER_ENDPOINT
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
EOF
    
    # Generate QR code with ORDER NUMBER as filename
    qrencode -t png -o "$qr_file" < "$config_file"
    chmod 600 "$config_file"
    chmod 644 "$qr_file"
    
    # Store mapping
    echo "$SLOT_ID:$ORDER_NUMBER:$client_public:$CLIENT_IP" >> /tmp/new_test_mapping.txt
    
    log "  ✅ Regenerated $ORDER_NUMBER (slot: $SLOT_ID)"
done

# Update server config with new test client keys (keeping monthly unchanged)
get_public_key() {
    local config_file="$1"
    local private_key=$(grep "PrivateKey" "$config_file" | awk '{print $3}')
    echo "$private_key" | wg pubkey
}

# Rebuild server config (preserve monthly, update test)
server_config="[Interface]
Address = 10.0.0.1/24
ListenPort = 51820
PrivateKey = $SERVER_PRIVATE_KEY
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

# ===== MONTHLY CLIENTS (Order Numbers: 42XXXXXX) =====
# IP Range: 10.0.0.2 - 10.0.0.11

"

# Add monthly clients (these never change) - ORDER-BASED FILES
for i in $(seq 1 10); do
    monthly_order="42$(printf "%06X" $((0x100000 + i)))"
    slot_id="client_$(printf "%02d" $i)"
    config_file="$CONFIG_DIR/monthly/${monthly_order}.conf"  # ✅ FIX: Use ORDER NUMBER
    client_ip="10.0.0.$((i + 1))"
    client_public=$(get_public_key "$config_file")
    
    server_config+="[Peer]
# Monthly Client: $slot_id - Order: $monthly_order
PublicKey = $client_public
AllowedIPs = $client_ip/32

"
done

server_config+="# ===== TEST CLIENTS (Order Numbers: 72XXXXXX) =====
# IP Range: 10.0.0.21 - 10.0.0.30
# Regenerated: $(date)

"

# Add new test clients
while IFS=: read -r slot_id order_number client_public client_ip; do
    server_config+="[Peer]
# Test Client: $slot_id - Order: $order_number (Generated $(date))
PublicKey = $client_public
AllowedIPs = $client_ip/32

"
done < /tmp/new_test_mapping.txt

# Update server config
echo "$server_config" > /etc/wireguard/wg0.conf
chmod 600 /etc/wireguard/wg0.conf

# Restart WireGuard
systemctl restart wg-quick@wg0

log "✅ Test slot regeneration completed successfully with ORDER NUMBERS"
log "📤 MANUAL STEP: Upload new test configs to Flask app"

# Clean old archives (keep last 30 days)
find /root/archives -name "test_*" -type d -mtime +30 -exec rm -rf {} \; 2>/dev/null || true

# Cleanup temp files
rm -f /tmp/new_test_mapping.txt
REGEN_EOF

chmod +x /root/regenerate_test_slots.sh
echo "✅ Created ORDER-BASED test slot regeneration script"

# Install daily cron job
(crontab -l 2>/dev/null | grep -v "regenerate_test_slots.sh"; echo "0 2 * * * /root/regenerate_test_slots.sh >> /var/log/test-slot-regeneration.log 2>&1") | crontab -
echo "✅ Installed daily cron job (2 AM) with ORDER-BASED regeneration"

echo -e "${YELLOW}📋 Step 8: Create Quick Management Scripts${NC}"

# Create status check script
cat > /root/check_status.sh << 'STATUS_EOF'
#!/bin/bash
echo "=== TUNNELGRAIN VPN STATUS (ORDER-BASED) ==="
echo "Time: $(date)"
echo ""
echo "WireGuard Status:"
systemctl status wg-quick@wg0 --no-pager
echo ""
echo "Active Connections:"
wg show
echo ""
echo "Config Files (ORDER-BASED):"
echo "Monthly (42XXXXXX): $(ls /root/configs/monthly/42*.conf 2>/dev/null | wc -l)/10"
echo "Test (72XXXXXX): $(ls /root/configs/test/72*.conf 2>/dev/null | wc -l)/10"
echo "QR Codes: $(ls /root/qr_codes/*.png 2>/dev/null | wc -l)/20"
echo ""
echo "File Examples:"
echo "Monthly: $(ls /root/configs/monthly/ | head -3 | xargs)"
echo "Test: $(ls /root/configs/test/ | head -3 | xargs)"
echo "QR Examples: $(ls /root/qr_codes/ | head -3 | xargs)"
STATUS_EOF

chmod +x /root/check_status.sh
echo "✅ Created ORDER-BASED status check script"

# Cleanup temp files
rm -f /tmp/monthly_mapping.txt /tmp/test_mapping.txt

echo -e "${GREEN}🎉 ORDER-BASED SYSTEM RECOVERY COMPLETE!${NC}"
echo ""
echo -e "${BLUE}📋 File Structure Created:${NC}"
echo "Monthly configs: 42100001.conf to 4210000A.conf"
echo "Test configs: 72100001.conf to 7210000A.conf"
echo "QR codes: Same naming as configs but .png"
echo ""
echo -e "${BLUE}📋 Verification Commands:${NC}"
echo "ls -la /root/configs/monthly/    # Should show 42*.conf files"
echo "ls -la /root/configs/test/       # Should show 72*.conf files"
echo "ls -la /root/qr_codes/           # Should show 42*.png and 72*.png files"
echo ""
echo -e "${BLUE}📋 Next Steps:${NC}"
echo "1. Run: /root/check_status.sh (verify everything works)"
echo "2. Test connection with one config file"
echo "3. Download ORDER-BASED configs to your local machine:"
echo "   scp -r root@213.170.133.116:/root/configs ./data"
echo "   scp -r root@213.170.133.116:/root/qr_codes ./static"
echo "4. Deploy your updated Flask app with OrderBasedSlotManager"
echo ""
echo -e "${YELLOW}⚡ Automation Updated:${NC}"
echo "• Daily ORDER-BASED test slot regeneration at 2 AM"
echo "• Run manually: /root/regenerate_test_slots.sh"
echo "• Check logs: tail -f /var/log/test-slot-regeneration.log"
echo ""
echo -e "${GREEN}✅ Your VPN service is now ORDER-BASED and automated!${NC}"