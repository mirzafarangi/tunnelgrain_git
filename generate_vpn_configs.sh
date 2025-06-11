#!/bin/bash

# Fix WireGuard Server Configuration for Tunnelgrain
# This script reads existing client configs and updates server config

set -e

echo "🔧 Fixing Tunnelgrain WireGuard Server Configuration..."

# Server configuration
SERVER_PRIVATE_KEY="0Ac9E5xwq75N34QhRUytVzDuGAZopnczeWv7ldJVrHw="
SERVER_PUBLIC_KEY="kYrikmdCzYOhM4R+A6LVnh6f0y3XPAfuPLNEaoExN30="

# Directories
MONTHLY_DIR="./data/monthly"
TEST_DIR="./data/test"

# Function to extract public key from client config
extract_public_key_from_config() {
    local config_file="$1"
    local client_ip="$2"
    
    if [ -f "$config_file" ]; then
        # Extract the private key from the config
        local private_key=$(grep "PrivateKey" "$config_file" | cut -d' ' -f3)
        # Generate public key from private key
        local public_key=$(echo "$private_key" | wg pubkey)
        echo "$public_key"
    else
        echo "ERROR: Config file $config_file not found"
        return 1
    fi
}

echo "📋 Building server configuration with existing client keys..."

# Start building the server config
server_config="[Interface]
Address = 10.0.0.1/24
ListenPort = 51820
PrivateKey = $SERVER_PRIVATE_KEY
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

"

# Add monthly clients
echo "🚀 Processing monthly client configs..."
for i in $(seq -f "%02g" 1 10); do
    client_name="client_$i"
    config_file="$MONTHLY_DIR/${client_name}.conf"
    ip_suffix=$((10#$i + 1))
    client_ip="10.0.0.$ip_suffix"
    
    if [ -f "$config_file" ]; then
        echo "  → Processing $client_name ($client_ip)"
        public_key=$(extract_public_key_from_config "$config_file" "$client_ip")
        
        server_config+="[Peer]
# Monthly Client $i - Tunnelgrain
PublicKey = $public_key
AllowedIPs = $client_ip/32

"
    else
        echo "  ⚠ Warning: $config_file not found"
    fi
done

# Add test clients
echo "🧪 Processing test client configs..."
for i in $(seq -f "%02g" 1 10); do
    client_name="test_$i"
    config_file="$TEST_DIR/${client_name}.conf"
    ip_suffix=$((10#$i + 20))
    client_ip="10.0.0.$ip_suffix"
    
    if [ -f "$config_file" ]; then
        echo "  → Processing $client_name ($client_ip)"
        public_key=$(extract_public_key_from_config "$config_file" "$client_ip")
        
        server_config+="[Peer]
# Test Client $i - Tunnelgrain
PublicKey = $public_key
AllowedIPs = $client_ip/32

"
    else
        echo "  ⚠ Warning: $config_file not found"
    fi
done

# Write the complete server config
echo "$server_config" > wg0_complete.conf

echo ""
echo "✅ Server configuration updated!"
echo "📄 New config saved as: wg0_complete.conf"
echo ""
echo "🔧 To apply the new configuration:"
echo "1. Stop WireGuard:"
echo "   sudo systemctl stop wg-quick@wg0"
echo ""
echo "2. Backup current config:"
echo "   sudo cp /etc/wireguard/wg0.conf /etc/wireguard/wg0.conf.backup"
echo ""
echo "3. Install new config:"
echo "   sudo cp wg0_complete.conf /etc/wireguard/wg0.conf"
echo "   sudo chmod 600 /etc/wireguard/wg0.conf"
echo ""
echo "4. Start WireGuard:"
echo "   sudo systemctl start wg-quick@wg0"
echo ""
echo "5. Check status:"
echo "   sudo wg show"
echo ""

# Show preview of config
echo "📋 Preview of generated config:"
echo "================================"
head -20 wg0_complete.conf
echo "..."
echo "(showing first 20 lines - full config saved to wg0_complete.conf)"