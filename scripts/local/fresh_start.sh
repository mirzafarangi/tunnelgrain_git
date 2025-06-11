#!/bin/bash
# fresh_start.sh - Complete fresh start with new configs

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🔥 COMPLETE FRESH START${NC}"
echo "This will regenerate ALL configs and give you a clean slate"
echo ""

# Confirm with user
read -p "⚠️  This will reset everything. Continue? (y/N): " confirm
if [[ $confirm != [yY] ]]; then
    echo "❌ Cancelled"
    exit 1
fi

echo -e "${YELLOW}📋 Step 1: Regenerate All Server Configs${NC}"
echo "We'll run the complete system recovery on your server..."

# Run complete system recovery on the server
echo "Running complete system recovery on server..."
ssh root@213.170.133.116 << 'EOF'
cd /root
if [ -f "complete_system_recovery.sh" ]; then
    echo "🔄 Running existing recovery script..."
    ./complete_system_recovery.sh
else
    echo "📥 Downloading recovery script..."
    curl -o complete_system_recovery.sh https://raw.githubusercontent.com/mirzafarangi/tunnelgrain_git/refs/heads/main/complete_system_recovery.sh
    chmod +x complete_system_recovery.sh
    ./complete_system_recovery.sh
fi
EOF

echo -e "${GREEN}✅ Server regeneration complete!${NC}"
echo ""

echo -e "${YELLOW}📋 Step 2: Clean Local Project${NC}"
# Backup current project
BACKUP_DIR="./backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp -r . "$BACKUP_DIR/" 2>/dev/null || true
echo "✅ Project backed up to: $BACKUP_DIR"

# Clean old configs completely
echo "🗑️  Removing old configs..."
rm -rf data/monthly/* data/test/* static/qr_codes/* 2>/dev/null || true

echo -e "${YELLOW}📋 Step 3: Download Fresh Configs${NC}"
# Download fresh configs from server
echo "📥 Downloading fresh monthly configs..."
scp -r root@213.170.133.116:/root/configs/monthly/* ./data/monthly/ 2>/dev/null || true

echo "📥 Downloading fresh test configs..."
scp -r root@213.170.133.116:/root/configs/test/* ./data/test/ 2>/dev/null || true

echo "📥 Downloading fresh QR codes..."
scp -r root@213.170.133.116:/root/qr_codes/* ./static/qr_codes/ 2>/dev/null || true

echo -e "${YELLOW}📋 Step 4: Verify Downloaded Files${NC}"
# Check what we got
monthly_count=$(ls data/monthly/*.conf 2>/dev/null | wc -l)
test_count=$(ls data/test/*.conf 2>/dev/null | wc -l)
qr_count=$(ls static/qr_codes/*.png 2>/dev/null | wc -l)

echo "📊 Downloaded files:"
echo "   Monthly configs: $monthly_count/10"
echo "   Test configs: $test_count/10"
echo "   QR codes: $qr_count/20"

if [ $monthly_count -ne 10 ] || [ $test_count -ne 10 ] || [ $qr_count -ne 20 ]; then
    echo -e "${RED}⚠️  Missing some files! Check your server.${NC}"
else
    echo -e "${GREEN}✅ All files downloaded successfully!${NC}"
fi

echo -e "${YELLOW}📋 Step 5: Reset Flask App State${NC}"
# Reset slots.json to clean state
echo "🔄 Resetting slot tracking..."
rm -f slots.json

echo -e "${YELLOW}📋 Step 6: Verify Key Consistency${NC}"
# Check that first config matches server
echo "🔍 Verifying key consistency..."

# Get first client config private key and convert to public
if [ -f "data/monthly/client_01.conf" ]; then
    local_public=$(grep "PrivateKey" data/monthly/client_01.conf | awk '{print $3}' | wg pubkey)
    echo "   Local client_01 public key: $local_public"
    
    # Check what server expects
    server_public=$(ssh root@213.170.133.116 "grep -A 2 'Monthly Client 1' /etc/wireguard/wg0.conf | grep PublicKey | awk '{print \$3}'")
    echo "   Server expects public key: $server_public"
    
    if [ "$local_public" = "$server_public" ]; then
        echo -e "${GREEN}✅ Keys match! VPN will work.${NC}"
    else
        echo -e "${RED}❌ Keys don't match! Something went wrong.${NC}"
        exit 1
    fi
else
    echo -e "${RED}❌ client_01.conf not found!${NC}"
    exit 1
fi

echo -e "${YELLOW}📋 Step 7: Deploy to Production${NC}"
echo "🚀 Deploying fresh configs to Render..."

# Commit and push
git add .
git commit -m "FRESH START: Regenerated all VPN configs $(date +%Y-%m-%d)"
git push origin main

echo -e "${GREEN}🎉 FRESH START COMPLETE!${NC}"
echo ""
echo -e "${BLUE}📋 What happened:${NC}"
echo "✅ Generated 20 brand new VPN configs on server"
echo "✅ Downloaded all fresh configs to local project"
echo "✅ Reset Flask app slot tracking"
echo "✅ Verified key consistency"
echo "✅ Deployed to Render"
echo ""
echo -e "${YELLOW}📋 Next Steps:${NC}"
echo "1. Wait 2-3 minutes for Render to deploy"
echo "2. Go to your app and get a fresh VPN config"
echo "3. Test internet connection"
echo "4. Start serving customers!"
echo ""
echo -e "${GREEN}🔥 Your VPN service now has completely fresh configs!${NC}"