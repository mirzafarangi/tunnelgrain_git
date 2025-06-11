#!/bin/bash
# monitor_vpn.sh - Quick VPN monitoring and reporting

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# API endpoints
API_BASE="https://tunnelgrain-git.onrender.com"
ADMIN_KEY="tunnelgrain_admin_secret_2024_xyz"

# Quick status overview
quick_status() {
    echo -e "${BLUE}=== TUNNELGRAIN VPN STATUS ===${NC}"
    echo "Generated at: $(date)"
    echo ""
    
    # Get current WireGuard peers
    local wg_peers=$(wg show wg0 peers 2>/dev/null | wc -l)
    echo -e "${GREEN}Currently Connected:${NC} $wg_peers users"
    
    # Get Flask API data
    local api_data=$(curl -s "${API_BASE}/api/active-slots" 2>/dev/null)
    if [ $? -eq 0 ]; then
        local monthly_active=$(echo "$api_data" | jq -r '.monthly | length' 2>/dev/null || echo "0")
        local test_active=$(echo "$api_data" | jq -r '.test | length' 2>/dev/null || echo "0")
        
        echo -e "${YELLOW}Monthly Accounts:${NC} $monthly_active active"
        echo -e "${YELLOW}Test Accounts:${NC} $test_active active"
    else
        echo -e "${RED}❌ API Connection Failed${NC}"
    fi
    
    echo ""
    echo -e "${BLUE}--- Quick Commands ---${NC}"
    echo "Full report:     ./monitor_vpn.sh report"
    echo "Active users:    ./monitor_vpn.sh active"
    echo "Expired users:   ./monitor_vpn.sh expired"
    echo "Force cleanup:   ./monitor_vpn.sh cleanup"
}

# Detailed report
full_report() {
    echo -e "${BLUE}=== DETAILED VPN REPORT ===${NC}"
    echo "Generated at: $(date)"
    echo ""
    
    # WireGuard status
    echo -e "${GREEN}=== CURRENTLY CONNECTED USERS ===${NC}"
    wg show wg0 2>/dev/null | while IFS= read -r line; do
        if [[ $line == peer:* ]]; then
            local peer_key=$(echo "$line" | cut -d' ' -f2)
            echo "🔗 Connected: ${peer_key:0:20}..."
        elif [[ $line == *"latest handshake"* ]]; then
            echo "   Last seen: $(echo "$line" | cut -d':' -f2-)"
        elif [[ $line == *"transfer"* ]]; then
            echo "   Traffic: $(echo "$line" | cut -d':' -f2-)"
            echo ""
        fi
    done
    
    # Get slot data from API
    local slot_data=$(curl -s "${API_BASE}/api/slot-status" 2>/dev/null)
    if [ $? -eq 0 ]; then
        local monthly_avail=$(echo "$slot_data" | jq -r '.monthly_available' 2>/dev/null || echo "?")
        local test_avail=$(echo "$slot_data" | jq -r '.test_available' 2>/dev/null || echo "?")
        
        echo -e "${YELLOW}=== SLOT AVAILABILITY ===${NC}"
        echo "Monthly slots: $monthly_avail/10 available"
        echo "Test slots: $test_avail/10 available"
        echo ""
    fi
    
    # Show active accounts with details
    echo -e "${GREEN}=== ACTIVE ACCOUNTS ===${NC}"
    active_users
    
    echo ""
    echo -e "${RED}=== EXPIRED/CLEANED ACCOUNTS ===${NC}"
    expired_users
}

# Show active users
active_users() {
    local api_data=$(curl -s "${API_BASE}/api/active-slots" 2>/dev/null)
    if [ $? -ne 0 ]; then
        echo "❌ Cannot connect to API"
        return 1
    fi
    
    # Monthly accounts
    echo "📅 MONTHLY ACCOUNTS:"
    echo "$api_data" | jq -r '.monthly[]?' 2>/dev/null | while read -r slot; do
        if [ -n "$slot" ]; then
            echo "  ✅ $slot (30-day access)"
        fi
    done
    
    # Test accounts  
    echo ""
    echo "🧪 TEST ACCOUNTS:"
    echo "$api_data" | jq -r '.test[]?' 2>/dev/null | while read -r slot; do
        if [ -n "$slot" ]; then
            echo "  ⏱️  $slot (15-minute trial)"
        fi
    done
}

# Show expired users from logs
expired_users() {
    local log_file="/var/log/wireguard-sync.log"
    if [ -f "$log_file" ]; then
        echo "Recent expired slots (last 24h):"
        grep -E "(Auto-released|Removing peer)" "$log_file" | tail -20 | while IFS= read -r line; do
            if [[ $line == *"Auto-released"* ]]; then
                local slot=$(echo "$line" | grep -oE "(monthly|test):[a-z_0-9]+" | cut -d: -f2)
                local time=$(echo "$line" | grep -oE "\[[0-9-]+ [0-9:]+\]")
                echo "  🗑️  $slot expired at $time"
            fi
        done
    else
        echo "No log file found"
    fi
}

# Force cleanup
force_cleanup() {
    echo -e "${YELLOW}Forcing cleanup of expired slots...${NC}"
    
    local response=$(curl -s -X POST "${API_BASE}/api/force-cleanup" \
        -H "X-Admin-Key: $ADMIN_KEY" \
        -H "Content-Type: application/json" 2>/dev/null)
    
    if [ $? -eq 0 ]; then
        local cleaned=$(echo "$response" | jq -r '.cleaned_slots | length' 2>/dev/null || echo "0")
        echo -e "${GREEN}✅ Cleanup complete. Cleaned $cleaned slots.${NC}"
    else
        echo -e "${RED}❌ Cleanup failed${NC}"
    fi
}

# Show usage
show_usage() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  status    - Quick status overview (default)"
    echo "  report    - Detailed full report"
    echo "  active    - Show only active users"
    echo "  expired   - Show only expired users"
    echo "  cleanup   - Force cleanup expired slots"
    echo ""
    echo "Examples:"
    echo "  $0              # Quick status"
    echo "  $0 report       # Full detailed report"
    echo "  $0 active       # See who's currently using VPN"
}

# Main execution
case "${1:-status}" in
    "status")
        quick_status
        ;;
    "report")
        full_report
        ;;
    "active")
        echo -e "${GREEN}=== ACTIVE VPN USERS ===${NC}"
        active_users
        ;;
    "expired")
        echo -e "${RED}=== EXPIRED VPN USERS ===${NC}"
        expired_users
        ;;
    "cleanup")
        force_cleanup
        ;;
    "help"|"-h"|"--help")
        show_usage
        ;;
    *)
        echo "Unknown command: $1"
        show_usage
        exit 1
        ;;
esac