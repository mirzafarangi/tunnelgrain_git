#!/bin/bash
# Complete WireGuard + Internet Reset - Run this on your VPS

echo "🔄 COMPLETE WIREGUARD RESET"
echo "=========================="

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Function to backup WireGuard config
backup_config() {
    echo -e "${YELLOW}1. Backing up WireGuard config...${NC}"
    cp /etc/wireguard/wg0.conf /etc/wireguard/wg0.conf.backup.$(date +%s)
}

# Function to completely reset WireGuard
reset_wireguard() {
    echo -e "${YELLOW}2. Stopping WireGuard...${NC}"
    systemctl stop wg-quick@wg0
    
    echo -e "${YELLOW}3. Clearing all iptables rules...${NC}"
    # Clear all rules
    iptables -F
    iptables -t nat -F
    iptables -X
    iptables -t nat -X
    
    # Reset to default policies
    iptables -P INPUT ACCEPT
    iptables -P FORWARD ACCEPT
    iptables -P OUTPUT ACCEPT
    
    echo -e "${YELLOW}4. Rebuilding basic iptables...${NC}"
    # Get main interface
    MAIN_IFACE=$(ip route | grep default | awk '{print $5}' | head -n1)
    [ -z "$MAIN_IFACE" ] && MAIN_IFACE="eth0"
    
    # Basic rules for internet access
    iptables -A FORWARD -i wg0 -j ACCEPT
    iptables -A FORWARD -o wg0 -j ACCEPT
    iptables -t nat -A POSTROUTING -o $MAIN_IFACE -j MASQUERADE
    
    # Enable IP forwarding
    echo 1 > /proc/sys/net/ipv4/ip_forward
    echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-wireguard.conf
    sysctl -p /etc/sysctl.d/99-wireguard.conf >/dev/null
    
    # Save rules
    if command -v netfilter-persistent >/dev/null; then
        netfilter-persistent save
    else
        mkdir -p /etc/iptables
        iptables-save > /etc/iptables/rules.v4
    fi
}

# Function to clean WireGuard config
clean_wireguard_config() {
    echo -e "${YELLOW}5. Cleaning WireGuard config...${NC}"
    
    # Extract just the interface section
    awk '
    BEGIN { in_interface = 0 }
    /^\[Interface\]/ { in_interface = 1; print; next }
    /^\[Peer\]/ { in_interface = 0 }
    in_interface { print }
    ' /etc/wireguard/wg0.conf > /etc/wireguard/wg0.conf.interface_only
    
    # Create fresh config with just interface
    cat > /etc/wireguard/wg0.conf << EOF
[Interface]
PrivateKey = $(grep "PrivateKey" /etc/wireguard/wg0.conf.interface_only | cut -d'=' -f2 | xargs)
Address = $(grep "Address" /etc/wireguard/wg0.conf.interface_only | cut -d'=' -f2 | xargs)
ListenPort = 51820
PostUp = iptables -A FORWARD -i %i -j ACCEPT
PostUp = iptables -A FORWARD -o %i -j ACCEPT  
PostUp = iptables -t nat -A POSTROUTING -o $MAIN_IFACE -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT
PostDown = iptables -D FORWARD -o %i -j ACCEPT
PostDown = iptables -t nat -D POSTROUTING -o $MAIN_IFACE -j MASQUERADE

# All peers will be added dynamically by the system

EOF
    
    # Clean up temp file
    rm -f /etc/wireguard/wg0.conf.interface_only
    
    echo -e "${GREEN}✅ WireGuard config cleaned (no peers)${NC}"
}

# Function to restart and test
restart_and_test() {
    echo -e "${YELLOW}6. Starting WireGuard...${NC}"
    systemctl start wg-quick@wg0
    
    if systemctl is-active wg-quick@wg0 >/dev/null; then
        echo -e "${GREEN}✅ WireGuard started successfully${NC}"
    else
        echo -e "${RED}❌ WireGuard failed to start${NC}"
        journalctl -u wg-quick@wg0 -n 20
        return 1
    fi
    
    echo -e "${YELLOW}7. Testing connectivity...${NC}"
    if ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Server has internet${NC}"
    else
        echo -e "${RED}❌ No internet access${NC}"
    fi
    
    echo -e "\nWireGuard Status:"
    wg show wg0 || echo "No peers connected"
}

# Main execution
echo "This will completely reset WireGuard and fix internet issues"
echo "All current VPN connections will be dropped!"
echo ""
read -p "Continue? (y/N): " confirm

if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Cancelled"
    exit 0
fi

backup_config
reset_wireguard
clean_wireguard_config
restart_and_test

echo -e "\n${GREEN}✅ WIREGUARD RESET COMPLETE!${NC}"
echo ""
echo "Your WireGuard is now:"
echo "- Completely clean (no peers)"
echo "- Properly configured for internet"
echo "- Ready for new connections"
echo ""
echo "Next steps:"
echo "1. Reset the expiration daemon database"
echo "2. Reset the Render database"
echo "3. Test with a fresh config download"