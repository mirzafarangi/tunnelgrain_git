#!/bin/bash

# VPN Configuration Generator
# Generates 10 monthly + 10 test VPN configs with QR codes

set -e

# Server configuration
SERVER_PRIVATE_KEY="0Ac9E5xwq75N34QhRUytVzDuGAZopnczeWv7ldJVrHw="
SERVER_PUBLIC_KEY="kYrikmdCzYOhM4R+A6LVnh6f0y3XPAfuPLNEaoExN30="
SERVER_ENDPOINT="213.170.133.116:51820"
SERVER_SUBNET="10.0.0.0/24"

# Directories
MONTHLY_DIR="./data/monthly"
TEST_DIR="./data/test"
QR_DIR="./static/qr_codes"

echo "🔧 Setting up directories..."
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
    qrencode -t PNG -o "${QR_DIR}/${client_name}.png" < "${output_dir}/${client_name}.conf"
    
    # Return public key for server config
    echo "$public_key"
}

echo "🚀 Generating Monthly VPN configs (client_01 to client_10)..."
monthly_peers=""
for i in $(seq -f "%02g" 1 10); do
    client_name="client_$i"
    # Fix octal issue by using decimal base
    ip_suffix=$((10#$i + 1))
    client_ip="10.0.0.$ip_suffix"  # 10.0.0.2 to 10.0.0.11
    
    echo "  → Generating $client_name ($client_ip)"
    public_key=$(generate_client_config "$client_name" "$client_ip" "$MONTHLY_DIR")
    
    # Add to server peers
    monthly_peers+="
[Peer]
# Monthly Client $i
PublicKey = $public_key
AllowedIPs = $client_ip/32
"
done

echo "🧪 Generating Test VPN configs (test_01 to test_10)..."
test_peers=""
for i in $(seq -f "%02g" 1 10); do
    client_name="test_$i"
    # Fix octal issue by using decimal base
    ip_suffix=$((10#$i + 20))
    client_ip="10.0.0.$ip_suffix"  # 10.0.0.21 to 10.0.0.30
    
    echo "  → Generating $client_name ($client_ip)"
    public_key=$(generate_client_config "$client_name" "$client_ip" "$TEST_DIR")
    
    # Add to server peers
    test_peers+="
[Peer]
# Test Client $i
PublicKey = $public_key
AllowedIPs = $client_ip/32
"
done

echo "📋 Updating server configuration..."
# Generate new server config with all peers
cat > ./wg0_server_update.conf <<EOF
[Interface]
Address = 10.0.0.1/24
ListenPort = 51820
PrivateKey = $SERVER_PRIVATE_KEY
PostUp = ufw route allow in on wg0 out on eth0
PostDown = ufw route delete allow in on wg0 out on eth0
$monthly_peers
$test_peers
EOF

echo "✅ Generation complete!"
echo ""
echo "📁 Generated files:"
echo "   Monthly configs: $MONTHLY_DIR/ (10 files)"
echo "   Test configs: $TEST_DIR/ (10 files)" 
echo "   QR codes: $QR_DIR/ (20 files)"
echo "   Server config: ./wg0_server_update.conf"
echo ""
echo "🔧 Next steps:"
echo "1. Copy wg0_server_update.conf to /etc/wireguard/wg0.conf on your server"
echo "2. Restart WireGuard: sudo systemctl restart wg-quick@wg0"
echo "3. Run the Flask app to serve these configs"
echo ""
echo "🎯 Ready for Flask integration!"