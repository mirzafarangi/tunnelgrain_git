#!/bin/bash

# Tunnelgrain VPN Configuration Generator
# Generates 10 monthly + 10 test VPN configs with QR codes

set -e

# Server configuration (Your actual server keys)
SERVER_PRIVATE_KEY="0Ac9E5xwq75N34QhRUytVzDuGAZopnczeWv7ldJVrHw="
SERVER_PUBLIC_KEY="kYrikmdCzYOhM4R+A6LVnh6f0y3XPAfuPLNEaoExN30="
SERVER_ENDPOINT="213.170.133.116:51820"
SERVER_SUBNET="10.0.0.0/24"

# Directories
MONTHLY_DIR="./data/monthly"
TEST_DIR="./data/test"
QR_DIR="./static/qr_codes"

echo "🔧 Setting up Tunnelgrain VPN configuration..."
echo "📍 Server: $SERVER_ENDPOINT"
echo "🏠 Subnet: $SERVER_SUBNET"
echo ""

# Create directories
mkdir -p "$MONTHLY_DIR" "$TEST_DIR" "$QR_DIR"

# Function to generate client config
generate_client_config() {
    local client_name="$1"
    local client_ip="$2"
    local output_dir="$3"
    local dns="${4:-1.1.1.1}"
    
    # Generate client keys
    local private_key=$(wg genkey)
    local public_key=$(echo "$private_key" | wg pubkey)
    
    # Create client config file
    cat > "${output_dir}/${client_name}.conf" <<EOF
[Interface]
PrivateKey = $private_key
Address = $client_ip/24
DNS = $dns

[Peer]
PublicKey = $SERVER_PUBLIC_KEY
Endpoint = $SERVER_ENDPOINT
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
EOF

    # Generate QR code
    if command -v qrencode &> /dev/null; then
        qrencode -t PNG -o "${QR_DIR}/${client_name}.png" < "${output_dir}/${client_name}.conf"
        echo "    ✓ Generated QR code: ${client_name}.png"
    else
        echo "    ⚠ Warning: qrencode not found, skipping QR code generation"
    fi
    
    # Return public key for server config
    echo "$public_key"
}

echo "🚀 Generating Monthly VPN configs (client_01 to client_10)..."
monthly_peers=""
for i in $(seq -f "%02g" 1 10); do
    client_name="client_$i"
    # Assign IPs 10.0.0.2 to 10.0.0.11
    ip_suffix=$((10#$i + 1))
    client_ip="10.0.0.$ip_suffix"
    
    echo "  → $client_name ($client_ip)"
    public_key=$(generate_client_config "$client_name" "$client_ip" "$MONTHLY_DIR")
    
    # Add to server peers
    monthly_peers+="
[Peer]
# Monthly Client $i - Tunnelgrain
PublicKey = $public_key
AllowedIPs = $client_ip/32
"
done

echo ""
echo "🧪 Generating Test VPN configs (test_01 to test_10)..."
test_peers=""
for i in $(seq -f "%02g" 1 10); do
    client_name="test_$i"
    # Assign IPs 10.0.0.21 to 10.0.0.30
    ip_suffix=$((10#$i + 20))
    client_ip="10.0.0.$ip_suffix"
    
    echo "  → $client_name ($client_ip)"
    public_key=$(generate_client_config "$client_name" "$client_ip" "$TEST_DIR")
    
    # Add to server peers
    test_peers+="
[Peer]
# Test Client $i - Tunnelgrain  
PublicKey = $public_key
AllowedIPs = $client_ip/32
"
done

echo ""
echo "📋 Updating server configuration..."

# Generate complete server config with all peers
cat > ./wg0_server_complete.conf <<EOF
[Interface]
Address = 10.0.0.1/24
ListenPort = 51820
PrivateKey = $SERVER_PRIVATE_KEY
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE
$monthly_peers
$test_peers
EOF

echo "✅ Generation complete!"
echo ""
echo "📁 Generated files:"
echo "   📂 Monthly configs: $MONTHLY_DIR/ (10 files)"
echo "   📂 Test configs: $TEST_DIR/ (10 files)" 
echo "   📂 QR codes: $QR_DIR/ (20 files)"
echo "   📄 Server config: ./wg0_server_complete.conf"
echo ""
echo "🔧 Next steps to deploy on server:"
echo "1. Copy wg0_server_complete.conf to /etc/wireguard/wg0.conf:"
echo "   sudo cp wg0_server_complete.conf /etc/wireguard/wg0.conf"
echo ""
echo "2. Set proper permissions:"
echo "   sudo chmod 600 /etc/wireguard/wg0.conf"
echo ""
echo "3. Start WireGuard service:"
echo "   sudo systemctl enable wg-quick@wg0"
echo "   sudo systemctl start wg-quick@wg0"
echo ""
echo "4. Check status:"
echo "   sudo systemctl status wg-quick@wg0"
echo "   sudo wg show"
echo ""
echo "🎯 Ready for Tunnelgrain Flask app!"

# Create a summary file
cat > ./setup_summary.txt <<EOF
Tunnelgrain VPN Setup Summary
============================
Generated: $(date)
Server: $SERVER_ENDPOINT
Network: $SERVER_SUBNET

Monthly VPN IPs: 10.0.0.2 - 10.0.0.11
Test VPN IPs: 10.0.0.21 - 10.0.0.30

Files created:
- 10 monthly config files in $MONTHLY_DIR/
- 10 test config files in $TEST_DIR/
- 20 QR code files in $QR_DIR/
- Complete server config: wg0_server_complete.conf

Next: Deploy server config and start WireGuard service
EOF

echo ""
echo "📄 Setup summary saved to: setup_summary.txt"