#!/bin/bash
# Reset VPS Expiration Daemon Data - Run this on your VPS

echo "🗑️ RESETTING VPS EXPIRATION DAEMON"
echo "================================="

cd /opt/tunnelgrain

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Stop the daemon
echo -e "${YELLOW}1. Stopping expiration daemon...${NC}"
systemctl stop tunnelgrain-expiration

# Backup current data
echo -e "${YELLOW}2. Backing up current data...${NC}"
mkdir -p backups/reset_$(date +%Y%m%d_%H%M%S)
cp active_timers.json peer_mapping.json backups/reset_$(date +%Y%m%d_%H%M%S)/ 2>/dev/null || true

# Reset JSON files
echo -e "${YELLOW}3. Resetting daemon data...${NC}"
cat > active_timers.json << 'EOF'
{}
EOF

cat > peer_mapping.json << 'EOF'
{}
EOF

# Clear log files
echo -e "${YELLOW}4. Clearing logs...${NC}"
> logs/expiration.log 2>/dev/null || true

# Restart daemon
echo -e "${YELLOW}5. Starting fresh daemon...${NC}"
systemctl start tunnelgrain-expiration

sleep 3

# Check status
if systemctl is-active tunnelgrain-expiration >/dev/null; then
    echo -e "${GREEN}✅ Expiration daemon restarted${NC}"
else
    echo -e "${RED}❌ Daemon failed to start${NC}"
    journalctl -u tunnelgrain-expiration -n 20 --no-pager
    exit 1
fi

# Test API
echo -e "${YELLOW}6. Testing API...${NC}"
sleep 2

if curl -s http://localhost:8081/api/status | jq . >/dev/null 2>&1; then
    echo -e "${GREEN}✅ API responding${NC}"
    
    echo -e "\n${YELLOW}Fresh API Status:${NC}"
    curl -s http://localhost:8081/api/status | jq .
else
    echo -e "${RED}❌ API not responding${NC}"
fi

echo -e "\n${GREEN}✅ VPS DAEMON RESET COMPLETE!${NC}"
echo "The expiration daemon now has:"
echo "- 0 active timers"
echo "- 0 expired timers" 
echo "- 0 total timers"
echo "- Fresh peer mapping"