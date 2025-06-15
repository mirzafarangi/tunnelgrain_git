#!/bin/bash
# fix_vpn_internet.sh - Fix VPN internet connectivity issues

echo "🔧 FIXING VPN INTERNET CONNECTIVITY"
echo "==================================="

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Function to check current status
check_status() {
    echo -e "\n${YELLOW}1. Checking Current Status...${NC}"
    echo "----------------------------"
    
    # Check IP forwarding
    echo -n "IP Forwarding: "
    if [ "$(cat /proc/sys/net/ipv4/ip_forward)" = "1" ]; then
        echo -e "${GREEN}✅ Enabled${NC}"
    else
        echo -e "${RED}❌ Disabled${NC}"
    fi
    
    # Check WireGuard interface
    echo -n "WireGuard Interface: "
    if ip link show wg0 &>/dev/null; then
        echo -e "${GREEN}✅ Exists${NC}"
    else
        echo -e "${RED}❌ Missing${NC}"
    fi
    
    # Check iptables rules
    echo -n "NAT Rules: "
    if iptables -t nat -L POSTROUTING -n | grep -q "MASQUERADE"; then
        echo -e "${GREEN}✅ Present${NC}"
    else
        echo -e "${RED}❌ Missing${NC}"
    fi
}

# Function to fix IP forwarding
fix_ip_forwarding() {
    echo -e "\n${YELLOW}2. Fixing IP Forwarding...${NC}"
    echo "-------------------------"
    
    # Enable IP forwarding immediately
    echo 1 > /proc/sys/net/ipv4/ip_forward
    
    # Make it permanent
    if ! grep -q "net.ipv4.ip_forward=1" /etc/sysctl.conf; then
        echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
    fi
    
    # Also add to sysctl.d for good measure
    echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-wireguard.conf
    
    # Apply sysctl settings
    sysctl -p /etc/sysctl.conf >/dev/null 2>&1
    sysctl -p /etc/sysctl.d/99-wireguard.conf >/dev/null 2>&1
    
    echo -e "${GREEN}✅ IP forwarding enabled${NC}"
}

# Function to fix iptables rules
fix_iptables() {
    echo -e "\n${YELLOW}3. Fixing iptables Rules...${NC}"
    echo "---------------------------"
    
    # Get the main network interface (usually eth0 or ens3)
    MAIN_IFACE=$(ip route | grep default | awk '{print $5}' | head -n1)
    
    if [ -z "$MAIN_IFACE" ]; then
        echo -e "${RED}❌ Could not detect main network interface${NC}"
        echo "Using eth0 as default"
        MAIN_IFACE="eth0"
    else
        echo "Detected main interface: $MAIN_IFACE"
    fi
    
    # Clear existing WireGuard-related rules to avoid duplicates
    iptables -D FORWARD -i wg0 -j ACCEPT 2>/dev/null
    iptables -D FORWARD -o wg0 -j ACCEPT 2>/dev/null
    iptables -t nat -D POSTROUTING -o $MAIN_IFACE -j MASQUERADE 2>/dev/null
    
    # Add necessary iptables rules
    iptables -A FORWARD -i wg0 -j ACCEPT
    iptables -A FORWARD -o wg0 -j ACCEPT
    iptables -t nat -A POSTROUTING -o $MAIN_IFACE -j MASQUERADE
    
    # Save iptables rules
    if command -v netfilter-persistent &>/dev/null; then
        netfilter-persistent save
    elif command -v iptables-save &>/dev/null; then
        iptables-save > /etc/iptables/rules.v4
    fi
    
    echo -e "${GREEN}✅ iptables rules configured${NC}"
}

# Function to fix WireGuard config
fix_wireguard_config() {
    echo -e "\n${YELLOW}4. Fixing WireGuard Configuration...${NC}"
    echo "------------------------------------"
    
    # Backup current config
    cp /etc/wireguard/wg0.conf /etc/wireguard/wg0.conf.backup.$(date +%s)
    
    # Get main network interface
    MAIN_IFACE=$(ip route | grep default | awk '{print $5}' | head -n1)
    [ -z "$MAIN_IFACE" ] && MAIN_IFACE="eth0"
    
    # Check if PostUp/PostDown rules exist
    if ! grep -q "PostUp" /etc/wireguard/wg0.conf; then
        echo -e "${YELLOW}Adding PostUp/PostDown rules...${NC}"
        
        # Create temp file with updated config
        awk '
        /^\[Interface\]/ {
            print
            in_interface = 1
            next
        }
        /^Address/ && in_interface {
            print
            print "PostUp = iptables -A FORWARD -i %i -j ACCEPT"
            print "PostUp = iptables -A FORWARD -o %i -j ACCEPT"
            print "PostUp = iptables -t nat -A POSTROUTING -o '$MAIN_IFACE' -j MASQUERADE"
            print "PostDown = iptables -D FORWARD -i %i -j ACCEPT"
            print "PostDown = iptables -D FORWARD -o %i -j ACCEPT"
            print "PostDown = iptables -t nat -D POSTROUTING -o '$MAIN_IFACE' -j MASQUERADE"
            in_interface = 0
            next
        }
        { print }
        ' /etc/wireguard/wg0.conf > /etc/wireguard/wg0.conf.tmp
        
        mv /etc/wireguard/wg0.conf.tmp /etc/wireguard/wg0.conf
    fi
    
    echo -e "${GREEN}✅ WireGuard config updated${NC}"
}

# Function to restart WireGuard
restart_wireguard() {
    echo -e "\n${YELLOW}5. Restarting WireGuard...${NC}"
    echo "--------------------------"
    
    # Stop WireGuard
    systemctl stop wg-quick@wg0
    
    # Wait a moment
    sleep 2
    
    # Start WireGuard
    systemctl start wg-quick@wg0
    
    if systemctl is-active wg-quick@wg0 >/dev/null; then
        peer_count=$(wg show wg0 | grep -c "peer:" || echo "0")
        echo -e "${GREEN}✅ WireGuard started successfully (${peer_count} peers)${NC}"
    else
        echo -e "${RED}❌ WireGuard failed to start${NC}"
        echo "Check logs: journalctl -u wg-quick@wg0 -n 50"
        return 1
    fi
}

# Function to test connectivity
test_connectivity() {
    echo -e "\n${YELLOW}6. Testing Connectivity...${NC}"
    echo "--------------------------"
    
    # Test from server
    echo -n "Server internet access: "
    if ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Working${NC}"
    else
        echo -e "${RED}❌ Failed${NC}"
    fi
    
    # Show active peers
    peer_count=$(wg show wg0 | grep -c "peer:" || echo "0")
    echo "Active VPN connections: $peer_count"
    
    # Show iptables nat rules
    echo -e "\nCurrent NAT rules:"
    iptables -t nat -L POSTROUTING -n | grep MASQUERADE || echo "No MASQUERADE rules found"
}

# Main execution
echo "This will fix VPN internet connectivity issues"
echo ""

# Initial status check
check_status

# Apply fixes
fix_ip_forwarding
fix_iptables
fix_wireguard_config
restart_wireguard

# Final check
echo -e "\n${YELLOW}=== FINAL STATUS ===${NC}"
check_status
test_connectivity

echo -e "\n${GREEN}✅ VPN INTERNET FIX COMPLETE!${NC}"
echo ""
echo "Your VPN clients should now have internet access."
echo ""
echo "If clients still have no internet:"
echo "1. Have them disconnect and reconnect"
echo "2. Check firewall: ufw status"
echo "3. Check logs: journalctl -u wg-quick@wg0 -f"
echo ""
echo "To verify a specific client has internet:"
echo "- Check if they appear in: wg show wg0"
echo "- Check their data transfer stats are increasing"