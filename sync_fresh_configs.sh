#!/bin/bash
echo "🔄 Syncing Fresh Configs from VPS"
echo "=================================="
echo "Date: $(date)"
echo "Syncing from: 213.170.133.116"
echo ""

# VPS connection test
echo "🔗 Testing VPS connection..."
if ! ssh -o ConnectTimeout=10 root@213.170.133.116 "echo 'Connection successful'" 2>/dev/null; then
    echo "❌ Cannot connect to VPS. Please check:"
    echo "  - SSH connection"
    echo "  - VPS is running"
    echo "  - SSH key authentication"
    exit 1
fi
echo "✅ VPS connection successful"
echo ""

# Create directories
echo "📁 Creating local directories..."
mkdir -p data/vps_1/ip_213.170.133.116/{test,monthly,quarterly,biannual,annual,lifetime}
mkdir -p static/qr_codes/vps_1/ip_213.170.133.116/{test,monthly,quarterly,biannual,annual,lifetime}

# Remove old configs (they're invalid after VPS rebuild)
echo "🗑️  Removing old configs..."
rm -f data/vps_1/ip_213.170.133.116/*/*.conf
rm -f static/qr_codes/vps_1/ip_213.170.133.116/*/*.png

echo "✅ Old configs removed"
echo ""

# Verify VPS has configs
echo "🔍 Verifying VPS has fresh configs..."
vps_config_count=$(ssh root@213.170.133.116 "find /opt/tunnelgrain/configs -name '*.conf' | wc -l" 2>/dev/null || echo "0")
vps_qr_count=$(ssh root@213.170.133.116 "find /opt/tunnelgrain/qr_codes -name '*.png' | wc -l" 2>/dev/null || echo "0")

echo "VPS has $vps_config_count configs and $vps_qr_count QR codes"

if [ "$vps_config_count" -lt 100 ]; then
    echo "⚠️ Warning: VPS has fewer configs than expected"
    echo "Expected: 130 configs (50 test + 30 monthly + 20 quarterly + 15 biannual + 10 annual + 5 lifetime)"
    echo "Found: $vps_config_count configs"
    echo ""
    read -p "Continue anyway? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Sync cancelled"
        exit 1
    fi
fi
echo ""

echo "📥 Downloading fresh configs..."

# Download configs for each tier with progress
tiers=("test" "monthly" "quarterly" "biannual" "annual" "lifetime")

for tier in "${tiers[@]}"; do
    echo "  📋 Syncing $tier configs..."
    
    # Download configs
    config_result=$(scp -q "root@213.170.133.116:/opt/tunnelgrain/configs/$tier/*" "./data/vps_1/ip_213.170.133.116/$tier/" 2>&1)
    config_count=$(ls data/vps_1/ip_213.170.133.116/$tier/*.conf 2>/dev/null | wc -l)
    
    # Download QR codes
    qr_result=$(scp -q "root@213.170.133.116:/opt/tunnelgrain/qr_codes/$tier/*" "./static/qr_codes/vps_1/ip_213.170.133.116/$tier/" 2>&1)
    qr_count=$(ls static/qr_codes/vps_1/ip_213.170.133.116/$tier/*.png 2>/dev/null | wc -l)
    
    if [ "$config_count" -gt 0 ] && [ "$qr_count" -gt 0 ]; then
        echo "    ✅ $tier: $config_count configs, $qr_count QR codes"
    else
        echo "    ⚠️ $tier: $config_count configs, $qr_count QR codes (some files may be missing)"
    fi
done

echo ""
echo "📊 Final sync summary:"
echo "======================"

total_configs=0
total_qrs=0

for tier in "${tiers[@]}"; do
    config_count=$(ls data/vps_1/ip_213.170.133.116/$tier/*.conf 2>/dev/null | wc -l)
    qr_count=$(ls static/qr_codes/vps_1/ip_213.170.133.116/$tier/*.png 2>/dev/null | wc -l)
    
    echo "  $tier: $config_count configs, $qr_count QR codes"
    
    total_configs=$((total_configs + config_count))
    total_qrs=$((total_qrs + qr_count))
done

echo "  ────────────────────────────────"
echo "  TOTAL: $total_configs configs, $total_qrs QR codes"
echo ""

# Verify expected counts
expected_configs=130
expected_qrs=130

if [ "$total_configs" -eq "$expected_configs" ] && [ "$total_qrs" -eq "$expected_qrs" ]; then
    echo "✅ SYNC SUCCESSFUL - All files downloaded correctly!"
elif [ "$total_configs" -eq "$expected_configs" ]; then
    echo "✅ CONFIGS OK - All $total_configs config files downloaded"
    echo "⚠️ QR CODES - Only $total_qrs/$expected_qrs QR codes (may be normal)"
else
    echo "⚠️ PARTIAL SYNC - Expected $expected_configs configs, got $total_configs"
    echo "This may indicate issues with the VPS setup"
fi

echo ""
echo "🧪 Quick verification:"
echo "======================"

# Test a random config file
if [ "$total_configs" -gt 0 ]; then
    sample_config=$(find data/vps_1/ip_213.170.133.116 -name "*.conf" | head -1)
    if [ -f "$sample_config" ]; then
        echo "📄 Sample config: $(basename "$sample_config")"
        echo "   Size: $(wc -c < "$sample_config") bytes"
        if grep -q "Tunnelgrain VPN Configuration" "$sample_config"; then
            echo "   ✅ Valid Tunnelgrain config format"
        else
            echo "   ⚠️ Unexpected config format"
        fi
    fi
fi

echo ""
echo "🔗 Next steps:"
echo "=============="
echo "1. Deploy your app to Render: git add . && git commit -m 'Fresh configs' && git push"
echo "2. Test VPN functionality: Get a test VPN and verify internet works"
echo "3. Test expiration: curl http://213.170.133.116:8081/api/status"
echo ""
echo "✅ Config sync complete! Your app now has fresh, working configs."