#!/bin/bash
# manage_test_slots.sh - Automated test slot lifecycle management

set -e

# Configuration
SERVER_PRIVATE_KEY="0Ac9E5xwq75N34QhRUytVzDuGAZopnczeWv7ldJVrHw="
SERVER_PUBLIC_KEY="kYrikmdCzYOhM4R+A6LVnh6f0y3XPAfuPLNEaoExN30="
SERVER_ENDPOINT="213.170.133.116:51820"

# Directories
TEST_DIR="/root/configs/test"
QR_DIR="/root/qr_codes"
ARCHIVE_DIR="/root/archives/test_slots"
LOG_FILE="/var/log/test-slot-management.log"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Create directories
create_directories() {
    mkdir -p "$TEST_DIR" "$QR_DIR" "$ARCHIVE_DIR"
}

# Generate a single test config
generate_test_config() {
    local slot_num="$1"
    local slot_id="test_$(printf "%02d" $slot_num)"
    local client_ip="10.0.0.$((slot_num + 20))"
    local config_file="$TEST_DIR/${slot_id}.conf"
    local qr_file="$QR_DIR/${slot_id}.png"
    
    # Generate client keys
    local client_private=$(wg genkey)
    local client_public=$(echo "$client_private" | wg pubkey)
    
    # Create config content
    local config_content="[Interface]
PrivateKey = $client_private
Address = $client_ip/24
DNS = 1.1.1.1

[Peer]
PublicKey = $SERVER_PUBLIC_KEY
Endpoint = $SERVER_ENDPOINT
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25"
    
    # Write config file
    echo "$config_content" > "$config_file"
    chmod 600 "$config_file"
    
    # Generate QR code
    qrencode -t png -o "$qr_file" "$config_content"
    chmod 644 "$qr_file"
    
    log "Generated: $slot_id -> $client_public ($client_ip)"
    echo "$slot_id:$client_public:$client_ip"
}

# Generate all test slots
generate_all_test_slots() {
    log "Starting test slot generation..."
    
    local server_peers=""
    
    for i in $(seq 1 10); do
        local result=$(generate_test_config $i)
        local slot_id=$(echo "$result" | cut -d: -f1)
        local public_key=$(echo "$result" | cut -d: -f2)
        local ip=$(echo "$result" | cut -d: -f3)
        
        # Add to server config
        server_peers+="
[Peer]
# Test Slot $i - Auto-generated $(date)
PublicKey = $public_key
AllowedIPs = $ip/32
"
    done
    
    # Update server config
    update_server_config "$server_peers"
    
    log "✅ Generated 10 new test slots successfully"
    echo -e "${GREEN}✅ All test slots generated and ready!${NC}"
}

# Archive old test configs
archive_old_configs() {
    local archive_date=$(date '+%Y%m%d_%H%M%S')
    local archive_path="$ARCHIVE_DIR/archive_$archive_date"
    
    mkdir -p "$archive_path"
    
    if [ -d "$TEST_DIR" ] && [ "$(ls -A $TEST_DIR 2>/dev/null)" ]; then
        log "Archiving old test configs to $archive_path"
        cp -r "$TEST_DIR"/* "$archive_path/" 2>/dev/null || true
        cp -r "$QR_DIR"/test_*.png "$archive_path/" 2>/dev/null || true
        
        # Clean old configs
        rm -f "$TEST_DIR"/test_*.conf
        rm -f "$QR_DIR"/test_*.png
        
        log "✅ Archived old configs to $archive_path"
    else
        log "No old configs to archive"
    fi
}

# Update server configuration
update_server_config() {
    local test_peers="$1"
    local config_file="/etc/wireguard/wg0.conf"
    local backup_file="/etc/wireguard/wg0.conf.backup.$(date +%Y%m%d_%H%M%S)"
    
    log "Updating server WireGuard configuration..."
    
    # Backup current config
    if [ -f "$config_file" ]; then
        cp "$config_file" "$backup_file"
        log "Backed up current config to $backup_file"
    fi
    
    # Build new server config
    local server_config="[Interface]
Address = 10.0.0.1/24
ListenPort = 51820
PrivateKey = $SERVER_PRIVATE_KEY
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

# Monthly clients (preserved)
$(grep -A 3 "Monthly Client" "$config_file" 2>/dev/null | grep -E "(# Monthly Client|PublicKey|AllowedIPs)" || echo "# No monthly clients found")

# Test clients (auto-generated)
$test_peers"
    
    # Write new config
    echo "$server_config" > "$config_file"
    chmod 600 "$config_file"
    
    # Restart WireGuard
    systemctl reload wg-quick@wg0 2>/dev/null || {
        log "Restarting WireGuard service..."
        systemctl restart wg-quick@wg0
    }
    
    log "✅ Server configuration updated and reloaded"
}

# Clean old archives (keep last 7 days)
cleanup_old_archives() {
    log "Cleaning archives older than 7 days..."
    find "$ARCHIVE_DIR" -name "archive_*" -type d -mtime +7 -exec rm -rf {} \; 2>/dev/null || true
    log "✅ Old archives cleaned"
}

# Upload new configs to Flask app
upload_to_flask() {
    log "Uploading new test configs to Flask app server..."
    
    # This would typically use scp or rsync to upload to your Flask server
    # For Render.com, you'll need to rebuild/redeploy with new configs
    
    # Example for VPS hosting Flask:
    # scp -r "$TEST_DIR"/* user@flask-server:/app/data/test/
    # scp -r "$QR_DIR"/test_*.png user@flask-server:/app/static/qr_codes/
    
    log "⚠️  MANUAL STEP: Upload $TEST_DIR and $QR_DIR/test_*.png to your Flask app"
    echo -e "${YELLOW}📤 Manual upload required:${NC}"
    echo "   Test configs: $TEST_DIR/*.conf"
    echo "   QR codes: $QR_DIR/test_*.png"
    echo "   Upload these to your Flask app and redeploy"
}

# Daily maintenance routine
daily_maintenance() {
    log "🔄 Starting daily test slot maintenance..."
    
    # Archive old configs
    archive_old_configs
    
    # Generate new test slots
    generate_all_test_slots
    
    # Clean old archives
    cleanup_old_archives
    
    # Upload notification
    upload_to_flask
    
    log "✅ Daily maintenance completed successfully"
    
    echo -e "${GREEN}🎉 Daily maintenance complete!${NC}"
    echo "New test slots generated and ready for upload to Flask app"
}

# Show status
show_status() {
    echo -e "${BLUE}=== TEST SLOT STATUS ===${NC}"
    echo "Current time: $(date)"
    echo ""
    
    # Count current configs
    local config_count=$(ls "$TEST_DIR"/test_*.conf 2>/dev/null | wc -l)
    local qr_count=$(ls "$QR_DIR"/test_*.png 2>/dev/null | wc -l)
    
    echo "Test configs: $config_count/10"
    echo "QR codes: $qr_count/10"
    echo ""
    
    # Check archives
    local archive_count=$(ls -d "$ARCHIVE_DIR"/archive_* 2>/dev/null | wc -l)
    echo "Archives: $archive_count"
    echo ""
    
    # Last generation
    if [ -f "$LOG_FILE" ]; then
        local last_gen=$(grep "Generated.*test_" "$LOG_FILE" | tail -1 | cut -d']' -f1 | tr -d '[')
        echo "Last generation: $last_gen"
    fi
}

# Install daily cron job
install_daily_cron() {
    local script_path="$(readlink -f "$0")"
    local cron_entry="0 2 * * * $script_path daily >> $LOG_FILE 2>&1"
    
    # Remove old entries
    (crontab -l 2>/dev/null | grep -v "manage_test_slots.sh") | crontab -
    
    # Add new entry
    (crontab -l 2>/dev/null; echo "$cron_entry") | crontab -
    
    log "✅ Daily cron job installed - runs at 2 AM every day"
    echo -e "${GREEN}✅ Automated daily generation enabled!${NC}"
}

# Show usage
show_usage() {
    echo "Test Slot Management System"
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  generate  - Generate new test slots immediately"
    echo "  daily     - Run daily maintenance (archive old + generate new)"
    echo "  status    - Show current status"
    echo "  install   - Install daily automation (2 AM cron job)"
    echo "  archive   - Archive current configs only"
    echo "  cleanup   - Clean old archives only"
    echo ""
    echo "Examples:"
    echo "  $0 generate    # Generate 10 new test slots now"
    echo "  $0 daily       # Full daily maintenance routine"
    echo "  $0 install     # Enable automatic daily generation"
}

# Main execution
case "${1:-status}" in
    "generate")
        create_directories
        generate_all_test_slots
        ;;
    "daily")
        create_directories
        daily_maintenance
        ;;
    "status")
        show_status
        ;;
    "install")
        install_daily_cron
        ;;
    "archive")
        create_directories
        archive_old_configs
        ;;
    "cleanup")
        cleanup_old_archives
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