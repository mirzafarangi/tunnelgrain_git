#!/bin/bash
# sync_wireguard_peers.sh - Fixed Automated peer management

set -e

# Configuration
WG_INTERFACE="wg0"
FLASK_API_URL="https://tunnelgrain-git.onrender.com"
SCRIPT_DIR="/root/wireguard-sync"
LOG_FILE="/var/log/wireguard-sync.log"
CONFIG_DIR="/root/configs"

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Get active slots from Flask API
get_active_slots() {
    local response=$(curl -s -f "${FLASK_API_URL}/api/active-slots" 2>/dev/null || echo "")
    if [ -z "$response" ]; then
        log "ERROR: Failed to get active slots from API"
        echo '{"monthly":[],"test":[]}'
        return 1
    fi
    echo "$response"
}

# Remove peer from WireGuard
remove_peer() {
    local public_key="$1"
    log "Removing peer: $public_key"
    wg set "$WG_INTERFACE" peer "$public_key" remove 2>/dev/null || log "Failed to remove peer $public_key"
}

# Add peer to WireGuard
add_peer() {
    local public_key="$1"
    local allowed_ip="$2"
    log "Adding peer: $public_key ($allowed_ip)"
    wg set "$WG_INTERFACE" peer "$public_key" allowed-ips "$allowed_ip" 2>/dev/null || log "Failed to add peer $public_key"
}

# Get currently connected peers
get_current_peers() {
    wg show "$WG_INTERFACE" peers 2>/dev/null || echo ""
}

# Extract public key from config file
get_public_key_from_config() {
    local config_file="$1"
    if [ -f "$config_file" ]; then
        local private_key=$(grep "PrivateKey" "$config_file" | awk '{print $3}' | tr -d '\r')
        if [ -n "$private_key" ]; then
            echo "$private_key" | wg pubkey 2>/dev/null || echo ""
        fi
    fi
}

# Main sync function
sync_peers() {
    log "Starting WireGuard peer synchronization"
    
    # Get active slots from Flask
    local active_slots_json=$(get_active_slots)
    
    # Parse JSON and build expected peers list
    local expected_peers=""
    
    # Check if jq is available
    if ! command -v jq &> /dev/null; then
        log "WARNING: jq not found. Installing jq..."
        apt-get update && apt-get install -y jq 2>/dev/null || {
            log "ERROR: Failed to install jq. Cannot parse API response."
            return 1
        }
    fi
    
    # Process monthly slots
    local monthly_slots=$(echo "$active_slots_json" | jq -r '.monthly[]?' 2>/dev/null || echo "")
    for slot_id in $monthly_slots; do
        local config_file="$CONFIG_DIR/monthly/${slot_id}.conf"
        local public_key=$(get_public_key_from_config "$config_file")
        local slot_num=$(echo "$slot_id" | sed 's/client_0*//')
        local allowed_ip="10.0.0.$((slot_num + 1))/32"
        
        if [ -n "$public_key" ]; then
            expected_peers="$expected_peers$public_key:$allowed_ip "
            log "Should be active: $slot_id -> $public_key ($allowed_ip)"
        else
            log "WARNING: Could not get public key for $slot_id"
        fi
    done
    
    # Process test slots
    local test_slots=$(echo "$active_slots_json" | jq -r '.test[]?' 2>/dev/null || echo "")
    for slot_id in $test_slots; do
        local config_file="$CONFIG_DIR/test/${slot_id}.conf"
        local public_key=$(get_public_key_from_config "$config_file")
        local slot_num=$(echo "$slot_id" | sed 's/test_0*//')
        local allowed_ip="10.0.0.$((slot_num + 20))/32"
        
        if [ -n "$public_key" ]; then
            expected_peers="$expected_peers$public_key:$allowed_ip "
            log "Should be active: $slot_id -> $public_key ($allowed_ip)"
        else
            log "WARNING: Could not get public key for $slot_id"
        fi
    done
    
    # Get currently connected peers
    local current_peers=$(get_current_peers)
    local current_count=$(echo "$current_peers" | wc -w)
    
    log "Current peers: $current_count"
    log "Expected peers: $(echo $expected_peers | wc -w)"
    
    # Remove peers that shouldn't be active
    for peer in $current_peers; do
        local should_keep=false
        for expected_pair in $expected_peers; do
            local expected_key=$(echo "$expected_pair" | cut -d: -f1)
            if [ "$peer" = "$expected_key" ]; then
                should_keep=true
                break
            fi
        done
        
        if [ "$should_keep" = false ]; then
            remove_peer "$peer"
        fi
    done
    
    # Add peers that should be active but aren't
    for expected_pair in $expected_peers; do
        local expected_key=$(echo "$expected_pair" | cut -d: -f1)
        local expected_ip=$(echo "$expected_pair" | cut -d: -f2)
        local peer_exists=false
        
        for current_peer in $current_peers; do
            if [ "$current_peer" = "$expected_key" ]; then
                peer_exists=true
                break
            fi
        done
        
        if [ "$peer_exists" = false ]; then
            add_peer "$expected_key" "$expected_ip"
        fi
    done
    
    # Save current WireGuard config
    wg-quick save "$WG_INTERFACE" 2>/dev/null || log "WARNING: Failed to save config"
    
    local final_count=$(get_current_peers | wc -w)
    log "Synchronization complete. Active peers: $final_count"
}

# Install as cron job
install_cron() {
    local cron_entry="*/5 * * * * /root/wireguard-sync/sync_wireguard_peers.sh sync >> /var/log/wireguard-sync.log 2>&1"
    
    # Remove old entries
    (crontab -l 2>/dev/null | grep -v "sync_wireguard_peers.sh") | crontab -
    
    # Add new entry
    (crontab -l 2>/dev/null; echo "$cron_entry") | crontab -
    
    log "Cron job installed - will sync every 5 minutes"
}

# Test API connectivity
test_api() {
    log "Testing API connectivity..."
    local response=$(curl -s -w "%{http_code}" "${FLASK_API_URL}/api/active-slots" -o /tmp/api_test.json)
    
    if [ "$response" = "200" ]; then
        log "API test successful"
        cat /tmp/api_test.json
    else
        log "API test failed with code: $response"
        return 1
    fi
}

# Main execution
case "${1:-sync}" in
    "sync")
        sync_peers
        ;;
    "install")
        mkdir -p "$SCRIPT_DIR"
        mkdir -p "$CONFIG_DIR"
        cp "$0" "$SCRIPT_DIR/"
        chmod +x "$SCRIPT_DIR/sync_wireguard_peers.sh"
        install_cron
        log "Automation installed successfully"
        ;;
    "test")
        test_api
        ;;
    "status")
        log "Current WireGuard status:"
        wg show "$WG_INTERFACE"
        echo ""
        log "Current peers: $(get_current_peers | wc -w)"
        ;;
    *)
        echo "Usage: $0 {sync|install|test|status}"
        echo "  sync    - Synchronize peers with Flask API"
        echo "  install - Install automation and cron job"
        echo "  test    - Test API connectivity"
        echo "  status  - Show current WireGuard status"
        exit 1
        ;;
esac