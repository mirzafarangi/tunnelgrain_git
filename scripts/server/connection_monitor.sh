#!/bin/bash
# connection_monitor.sh - Monitor VPN connections with client/test separation

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
NC='\033[0m'

# API Configuration
API_BASE="https://tunnelgrain-git.onrender.com"

echo -e "${BLUE}═══════════════════════════════════════════${NC}"
echo -e "${BLUE}    🔍 TUNNELGRAIN CONNECTION MONITOR       ${NC}"
echo -e "${BLUE}═══════════════════════════════════════════${NC}"
echo "Generated: $(date)"
echo ""

# Function to get IP range for client type
get_ip_info() {
    local allowed_ip="$1"
    local ip_num=$(echo "$allowed_ip" | cut -d'.' -f4 | cut -d'/' -f1)
    
    if [ $ip_num -ge 2 ] && [ $ip_num -le 11 ]; then
        local client_num=$((ip_num - 1))
        echo "client_$(printf "%02d" $client_num) (MONTHLY)"
    elif [ $ip_num -ge 21 ] && [ $ip_num -le 30 ]; then
        local test_num=$((ip_num - 20))
        echo "test_$(printf "%02d" $test_num) (TEST)"
    else
        echo "unknown ($allowed_ip)"
    fi
}

# Function to format time duration
format_duration() {
    local input="$1"
    
    # Handle different time formats
    if [[ $input =~ ([0-9]+)\ seconds?\ ago ]]; then
        echo "${BASH_REMATCH[1]}s ago"
    elif [[ $input =~ ([0-9]+)\ minutes?,\ ([0-9]+)\ seconds?\ ago ]]; then
        echo "${BASH_REMATCH[1]}m ${BASH_REMATCH[2]}s ago"
    elif [[ $input =~ ([0-9]+)\ hours?,\ ([0-9]+)\ minutes?\ ago ]]; then
        echo "${BASH_REMATCH[1]}h ${BASH_REMATCH[2]}m ago"
    else
        echo "$input"
    fi
}

# Get current WireGuard status
echo -e "${GREEN}🔗 CURRENT VPN CONNECTIONS${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Parse WireGuard output
wg_output=$(wg show wg0 2>/dev/null)
if [ $? -ne 0 ]; then
    echo -e "${RED}❌ WireGuard interface not found${NC}"
    exit 1
fi

# Count total connections
total_peers=$(echo "$wg_output" | grep "peer:" | wc -l)
monthly_count=0
test_count=0
monthly_connections=""
test_connections=""

if [ $total_peers -eq 0 ]; then
    echo -e "${YELLOW}📱 No active connections${NC}"
else
    echo -e "${CYAN}📊 Total Active: $total_peers connections${NC}"
    echo ""
    
    # Parse each peer
    current_peer=""
    current_endpoint=""
    current_allowed=""
    current_handshake=""
    current_transfer=""
    
    while IFS= read -r line; do
        if [[ $line == peer:* ]]; then
            # Process previous peer if exists
            if [ -n "$current_peer" ]; then
                client_info=$(get_ip_info "$current_allowed")
                if [[ $client_info == *"MONTHLY"* ]]; then
                    monthly_count=$((monthly_count + 1))
                    monthly_connections="${monthly_connections}${current_peer}|${current_endpoint}|${current_allowed}|${current_handshake}|${current_transfer}|${client_info}\n"
                elif [[ $client_info == *"TEST"* ]]; then
                    test_count=$((test_count + 1))
                    test_connections="${test_connections}${current_peer}|${current_endpoint}|${current_allowed}|${current_handshake}|${current_transfer}|${client_info}\n"
                fi
            fi
            
            # Start new peer
            current_peer=$(echo "$line" | awk '{print $2}')
            current_endpoint=""
            current_allowed=""
            current_handshake=""
            current_transfer=""
        elif [[ $line == *"endpoint"* ]]; then
            current_endpoint=$(echo "$line" | cut -d':' -f2- | xargs)
        elif [[ $line == *"allowed ips"* ]]; then
            current_allowed=$(echo "$line" | cut -d':' -f2- | xargs)
        elif [[ $line == *"latest handshake"* ]]; then
            current_handshake=$(echo "$line" | cut -d':' -f2- | xargs)
        elif [[ $line == *"transfer"* ]]; then
            current_transfer=$(echo "$line" | cut -d':' -f2- | xargs)
        fi
    done <<< "$wg_output"
    
    # Process last peer
    if [ -n "$current_peer" ]; then
        client_info=$(get_ip_info "$current_allowed")
        if [[ $client_info == *"MONTHLY"* ]]; then
            monthly_count=$((monthly_count + 1))
            monthly_connections="${monthly_connections}${current_peer}|${current_endpoint}|${current_allowed}|${current_handshake}|${current_transfer}|${client_info}\n"
        elif [[ $client_info == *"TEST"* ]]; then
            test_count=$((test_count + 1))
            test_connections="${test_connections}${current_peer}|${current_endpoint}|${current_allowed}|${current_handshake}|${current_transfer}|${client_info}\n"
        fi
    fi
    
    # Display Monthly Connections
    echo -e "${GREEN}💰 MONTHLY CLIENTS: $monthly_count connected${NC}"
    if [ $monthly_count -gt 0 ]; then
        echo -e "$monthly_connections" | while IFS='|' read -r peer endpoint allowed handshake transfer info; do
            if [ -n "$peer" ]; then
                echo -e "   ${YELLOW}🔑${NC} ${peer:0:20}..."
                echo -e "   ${CYAN}📍${NC} Endpoint: $endpoint"
                echo -e "   ${CYAN}🌐${NC} Client: $info"
                echo -e "   ${CYAN}⏰${NC} Last seen: $(format_duration "$handshake")"
                echo -e "   ${CYAN}📊${NC} Traffic: $transfer"
                echo ""
            fi
        done
    fi
    
    # Display Test Connections
    echo -e "${PURPLE}🧪 TEST CLIENTS: $test_count connected${NC}"
    if [ $test_count -gt 0 ]; then
        echo -e "$test_connections" | while IFS='|' read -r peer endpoint allowed handshake transfer info; do
            if [ -n "$peer" ]; then
                echo -e "   ${YELLOW}🔑${NC} ${peer:0:20}..."
                echo -e "   ${CYAN}📍${NC} Endpoint: $endpoint"
                echo -e "   ${CYAN}🌐${NC} Client: $info"
                echo -e "   ${CYAN}⏰${NC} Last seen: $(format_duration "$handshake")"
                echo -e "   ${CYAN}📊${NC} Traffic: $transfer"
                echo ""
            fi
        done
    fi
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Get Flask API status
echo -e "${GREEN}💼 BUSINESS METRICS${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

api_data=$(curl -s "${API_BASE}/api/slot-status" 2>/dev/null)
if [ $? -eq 0 ]; then
    monthly_available=$(echo "$api_data" | jq -r '.monthly_available' 2>/dev/null || echo "?")
    test_available=$(echo "$api_data" | jq -r '.test_available' 2>/dev/null || echo "?")
    
    # Calculate revenue metrics
    monthly_sold=$((10 - monthly_available))
    revenue=$((monthly_sold * 499))  # in cents
    revenue_dollars=$((revenue / 100))
    
    echo -e "${CYAN}📈 Revenue Status:${NC}"
    echo "   Monthly slots sold: $monthly_sold/10"
    echo "   Current revenue: \$${revenue_dollars}.$(printf "%02d" $((revenue % 100)))"
    echo "   Potential revenue: \$49.90 (if all sold)"
    echo ""
    echo -e "${CYAN}📊 Slot Availability:${NC}"
    echo "   Monthly available: $monthly_available/10"
    echo "   Test available: $test_available/10"
    echo ""
    echo -e "${CYAN}🔌 Connection vs Sold:${NC}"
    echo "   Monthly sold: $monthly_sold | Connected: $monthly_count"
    echo "   Test available: $test_available | Connected: $test_count"
else
    echo -e "${RED}❌ Cannot connect to Flask API${NC}"
fi

echo ""

# Server performance
echo -e "${GREEN}🖥️  SERVER STATUS${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# WireGuard service status
wg_status=$(systemctl is-active wg-quick@wg0)
if [ "$wg_status" = "active" ]; then
    echo -e "WireGuard Service: ${GREEN}●${NC} Active"
else
    echo -e "WireGuard Service: ${RED}●${NC} $wg_status"
fi

# System load
load_avg=$(uptime | awk -F'load average:' '{print $2}' | xargs)
echo "Server load: $load_avg"

# Memory usage
mem_info=$(free -h | grep Mem)
mem_used=$(echo "$mem_info" | awk '{print $3}')
mem_total=$(echo "$mem_info" | awk '{print $2}')
echo "Memory usage: $mem_used / $mem_total"

echo ""
echo -e "${BLUE}═══════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ Monitoring complete!${NC}"
echo ""
echo -e "${YELLOW}💡 Quick commands:${NC}"
echo "   wg show                    # Raw WireGuard status"
echo "   ./connection_monitor.sh    # Run this monitor"
echo "   systemctl status wg-quick@wg0  # Service status"