#!/bin/bash
# cleanup_project.sh - Clean your local Tunnelgrain project

set -e

echo "🧹 CLEANING TUNNELGRAIN PROJECT"
echo "This will organize your project and remove outdated files"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${YELLOW}📋 Step 1: Backup Current Project${NC}"
BACKUP_DIR="./backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp -r . "$BACKUP_DIR/" 2>/dev/null || true
echo "✅ Project backed up to: $BACKUP_DIR"

echo -e "${YELLOW}📋 Step 2: Remove Outdated Scripts${NC}"
# Remove old/duplicate scripts that are now handled by the server
rm -f generate_vpn_configs.sh      # Replaced by complete_system_recovery.sh
rm -f manage_test_slots.sh          # Now runs on server automatically
rm -f sync_wireguard_peers.sh       # Server-side automation
rm -f monitor_vpn.sh                # Server monitoring only
rm -f fix_wg_config.sh              # One-time fix, no longer needed
echo "✅ Removed outdated server scripts"

echo -e "${YELLOW}📋 Step 3: Keep Only Essential Files${NC}"
# Create final project structure
mkdir -p scripts/server
mkdir -p scripts/local

# Move the recovery script to server scripts folder
mv complete_system_recovery.sh scripts/server/ 2>/dev/null || true

echo -e "${YELLOW}📋 Step 4: Download Fresh Configs from Server${NC}"
echo "Run these commands to get your fresh configs:"
echo ""
echo -e "${BLUE}# Download monthly and test configs${NC}"
echo "scp -r root@213.170.133.116:/root/configs ./data"
echo ""
echo -e "${BLUE}# Download QR codes${NC}"
echo "scp -r root@213.170.133.116:/root/qr_codes ./static"
echo ""
echo -e "${GREEN}✅ Project cleanup complete!${NC}"
echo ""
echo -e "${BLUE}📋 Your clean project structure:${NC}"
echo "├── app.py                    # Main Flask application"
echo "├── requirements.txt          # Python dependencies"
echo "├── slots.json               # Slot tracking database"
echo "├── data/                    # VPN config files (download from server)"
echo "│   ├── monthly/             # 10 permanent monthly configs"
echo "│   └── test/                # 10 rotating test configs"
echo "├── static/                  # Static files"
echo "│   └── qr_codes/            # QR code images (download from server)"
echo "├── templates/               # HTML templates"
echo "├── scripts/                 # Organized scripts"
echo "│   ├── server/              # Server-side scripts"
echo "│   └── local/               # Local development scripts"
echo "└── backup_*/                # Automatic backups"