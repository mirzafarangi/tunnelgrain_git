#!/bin/bash
# clean_setup.sh - Clean up mess and setup everything properly

echo "🧹 TUNNELGRAIN CLEAN SETUP"
echo "========================="

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Function to clean up old files
cleanup_old_files() {
    echo -e "\n${YELLOW}1. Cleaning Up Old Files...${NC}"
    echo "---------------------------"
    
    cd /opt/tunnelgrain
    
    # Backup important data first
    mkdir -p backups/cleanup_$(date +%Y%m%d_%H%M%S)
    cp active_timers.json peer_mapping.json backups/cleanup_$(date +%Y%m%d_%H%M%S)/ 2>/dev/null || true
    
    # Remove all the messy fix scripts
    rm -f diagnose_*.sh 2>/dev/null
    rm -f fix_*.sh 2>/dev/null
    rm -f immediate_*.sh 2>/dev/null
    rm -f test_*.sh 2>/dev/null
    rm -f expiration_daemon*.py.backup* 2>/dev/null
    rm -f expiration_daemon_*.py 2>/dev/null
    
    # Remove old log files over 100MB
    find logs/ -type f -size +100M -delete 2>/dev/null || true
    
    echo -e "${GREEN}✅ Cleaned up old files${NC}"
    
    # Show what's left
    echo -e "\nRemaining files in /opt/tunnelgrain:"
    ls -la | grep -v "^d"
}

# Function to setup clean daemon
setup_clean_daemon() {
    echo -e "\n${YELLOW}2. Setting Up Clean Expiration Daemon...${NC}"
    echo "-----------------------------------------"
    
    # Stop current daemon
    systemctl stop tunnelgrain-expiration 2>/dev/null || true
    
    # Make sure we have the clean daemon (user should have created it)
    if [ ! -f /opt/tunnelgrain/expiration_daemon.py ]; then
        echo -e "${RED}❌ expiration_daemon.py not found!${NC}"
        echo "Please create it first with the provided code"
        return 1
    fi
    
    # Set permissions
    chmod +x /opt/tunnelgrain/expiration_daemon.py
    
    # Create/update systemd service
    cat > /etc/systemd/system/tunnelgrain-expiration.service << 'EOF'
[Unit]
Description=Tunnelgrain VPN Expiration Daemon
After=network.target wg-quick@wg0.service
Wants=wg-quick@wg0.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/tunnelgrain
Environment=PATH=/opt/tunnelgrain/venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/opt/tunnelgrain/venv/bin/python /opt/tunnelgrain/expiration_daemon.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
    
    # Reload systemd
    systemctl daemon-reload
    
    # Enable and start service
    systemctl enable tunnelgrain-expiration
    systemctl start tunnelgrain-expiration
    
    sleep 3
    
    if systemctl is-active tunnelgrain-expiration >/dev/null; then
        echo -e "${GREEN}✅ Expiration daemon running${NC}"
    else
        echo -e "${RED}❌ Expiration daemon failed to start${NC}"
        journalctl -u tunnelgrain-expiration -n 20 --no-pager
    fi
}

# Function to verify file structure
verify_structure() {
    echo -e "\n${YELLOW}3. Verifying File Structure...${NC}"
    echo "------------------------------"
    
    # Check required directories
    dirs=(
        "/opt/tunnelgrain/configs/test"
        "/opt/tunnelgrain/configs/monthly"
        "/opt/tunnelgrain/configs/quarterly"
        "/opt/tunnelgrain/configs/biannual"
        "/opt/tunnelgrain/configs/annual"
        "/opt/tunnelgrain/configs/lifetime"
        "/opt/tunnelgrain/qr_codes/test"
        "/opt/tunnelgrain/qr_codes/monthly"
        "/opt/tunnelgrain/qr_codes/quarterly"
        "/opt/tunnelgrain/qr_codes/biannual"
        "/opt/tunnelgrain/qr_codes/annual"
        "/opt/tunnelgrain/qr_codes/lifetime"
        "/opt/tunnelgrain/logs"
        "/opt/tunnelgrain/backups"
    )
    
    for dir in "${dirs[@]}"; do
        if [ -d "$dir" ]; then
            count=$(ls "$dir" 2>/dev/null | wc -l)
            echo -e "${GREEN}✅${NC} $dir ($count files)"
        else
            echo -e "${RED}❌${NC} $dir (missing)"
            mkdir -p "$dir"
        fi
    done
}

# Function to test everything
test_system() {
    echo -e "\n${YELLOW}4. Testing System...${NC}"
    echo "-------------------"
    
    # Test WireGuard
    echo -n "WireGuard Service: "
    if systemctl is-active wg-quick@wg0 >/dev/null; then
        peer_count=$(wg show wg0 | grep -c "peer:" || echo "0")
        echo -e "${GREEN}✅ Running (${peer_count} peers)${NC}"
    else
        echo -e "${RED}❌ Not running${NC}"
    fi
    
    # Test Expiration Daemon
    echo -n "Expiration Daemon: "
    if systemctl is-active tunnelgrain-expiration >/dev/null; then
        echo -e "${GREEN}✅ Running${NC}"
    else
        echo -e "${RED}❌ Not running${NC}"
    fi
    
    # Test API
    echo -n "API Health Check: "
    if curl -s http://localhost:8081/api/health | grep -q "healthy"; then
        echo -e "${GREEN}✅ Responding${NC}"
    else
        echo -e "${RED}❌ Not responding${NC}"
    fi
    
    # Test Internet connectivity
    echo -n "Internet Access: "
    if ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Working${NC}"
    else
        echo -e "${RED}❌ No internet${NC}"
    fi
    
    # Show API status
    echo -e "\nAPI Status:"
    curl -s http://localhost:8081/api/status | jq . 2>/dev/null || echo "API not responding"
}

# Function to create helper scripts
create_helpers() {
    echo -e "\n${YELLOW}5. Creating Helper Scripts...${NC}"
    echo "-----------------------------"
    
    # Create status script
    cat > /opt/tunnelgrain/status.sh << 'EOF'
#!/bin/bash
echo "TUNNELGRAIN STATUS"
echo "=================="
echo ""
echo "Services:"
systemctl is-active wg-quick@wg0 >/dev/null && echo "✅ WireGuard: Running" || echo "❌ WireGuard: Stopped"
systemctl is-active tunnelgrain-expiration >/dev/null && echo "✅ Expiration: Running" || echo "❌ Expiration: Stopped"
echo ""
echo "Statistics:"
echo "WireGuard Peers: $(wg show wg0 2>/dev/null | grep -c 'peer:' || echo '0')"
echo ""
echo "API Status:"
curl -s http://localhost:8081/api/status | jq . 2>/dev/null || echo "API not responding"
EOF
    chmod +x /opt/tunnelgrain/status.sh
    
    # Create logs script
    cat > /opt/tunnelgrain/logs.sh << 'EOF'
#!/bin/bash
echo "1. Expiration Daemon Logs"
echo "2. WireGuard Logs"
echo "3. Both (Live)"
read -p "Choose (1-3): " choice
case $choice in
    1) journalctl -u tunnelgrain-expiration -f ;;
    2) journalctl -u wg-quick@wg0 -f ;;
    3) journalctl -u tunnelgrain-expiration -u wg-quick@wg0 -f ;;
esac
EOF
    chmod +x /opt/tunnelgrain/logs.sh
    
    echo -e "${GREEN}✅ Helper scripts created${NC}"
    echo "  - ./status.sh - Check system status"
    echo "  - ./logs.sh - View logs"
}

# Main menu
echo -e "${BLUE}This will clean up your Tunnelgrain setup${NC}"
echo "It will:"
echo "- Remove old/duplicate scripts"
echo "- Setup clean expiration daemon"
echo "- Fix internet connectivity"
echo "- Create helper scripts"
echo ""
read -p "Continue? (y/N): " confirm

if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Cancelled"
    exit 0
fi

# Execute steps
cleanup_old_files
setup_clean_daemon
verify_structure

# Fix internet connectivity
echo -e "\n${YELLOW}Running Internet Fix...${NC}"
if [ -f /opt/tunnelgrain/fix_vpn_internet.sh ]; then
    bash /opt/tunnelgrain/fix_vpn_internet.sh
else
    echo -e "${YELLOW}fix_vpn_internet.sh not found - run it separately${NC}"
fi

# Final testing
test_system
create_helpers

# Show final structure
echo -e "\n${BLUE}=== CLEAN FILE STRUCTURE ===${NC}"
echo "/opt/tunnelgrain/"
echo "├── expiration_daemon.py     # Main daemon"
echo "├── fix_vpn_internet.sh      # Fix internet issues"
echo "├── clean_setup.sh           # This cleanup script"
echo "├── status.sh                # Check status"
echo "├── logs.sh                  # View logs"
echo "├── active_timers.json       # Timer data"
echo "├── peer_mapping.json        # Peer mappings"
echo "├── configs/                 # VPN configs"
echo "├── qr_codes/                # QR codes"
echo "├── logs/                    # Log files"
echo "├── backups/                 # Backups"
echo "└── venv/                    # Python environment"

echo -e "\n${GREEN}✅ CLEAN SETUP COMPLETE!${NC}"
echo ""
echo "Quick commands:"
echo "- Check status: ./status.sh"
echo "- View logs: ./logs.sh"
echo "- Fix internet: ./fix_vpn_internet.sh"
echo ""
echo "Your VPN service should now be working properly!"