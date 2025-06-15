#!/bin/bash
echo "🔄 Syncing Fresh Configs from VPS"

# Create directories
mkdir -p data/vps_1/ip_213.170.133.116/{test,monthly,quarterly,biannual,annual,lifetime}
mkdir -p static/qr_codes/vps_1/ip_213.170.133.116/{test,monthly,quarterly,biannual,annual,lifetime}

# Remove old configs (they're invalid)
rm -f data/vps_1/ip_213.170.133.116/*/*.conf
rm -f static/qr_codes/vps_1/ip_213.170.133.116/*/*.png

echo "📥 Downloading fresh configs..."

# Download configs for each tier
scp "root@213.170.133.116:/opt/tunnelgrain/configs/test/*" "./data/vps_1/ip_213.170.133.116/test/" 2>/dev/null || echo "No test configs"
scp "root@213.170.133.116:/opt/tunnelgrain/configs/monthly/*" "./data/vps_1/ip_213.170.133.116/monthly/" 2>/dev/null || echo "No monthly configs"
scp "root@213.170.133.116:/opt/tunnelgrain/configs/quarterly/*" "./data/vps_1/ip_213.170.133.116/quarterly/" 2>/dev/null || echo "No quarterly configs"
scp "root@213.170.133.116:/opt/tunnelgrain/configs/biannual/*" "./data/vps_1/ip_213.170.133.116/biannual/" 2>/dev/null || echo "No biannual configs"
scp "root@213.170.133.116:/opt/tunnelgrain/configs/annual/*" "./data/vps_1/ip_213.170.133.116/annual/" 2>/dev/null || echo "No annual configs"
scp "root@213.170.133.116:/opt/tunnelgrain/configs/lifetime/*" "./data/vps_1/ip_213.170.133.116/lifetime/" 2>/dev/null || echo "No lifetime configs"

echo "📥 Downloading fresh QR codes..."

# Download QR codes for each tier
scp "root@213.170.133.116:/opt/tunnelgrain/qr_codes/test/*" "./static/qr_codes/vps_1/ip_213.170.133.116/test/" 2>/dev/null || echo "No test QRs"
scp "root@213.170.133.116:/opt/tunnelgrain/qr_codes/monthly/*" "./static/qr_codes/vps_1/ip_213.170.133.116/monthly/" 2>/dev/null || echo "No monthly QRs"
scp "root@213.170.133.116:/opt/tunnelgrain/qr_codes/quarterly/*" "./static/qr_codes/vps_1/ip_213.170.133.116/quarterly/" 2>/dev/null || echo "No quarterly QRs"
scp "root@213.170.133.116:/opt/tunnelgrain/qr_codes/biannual/*" "./static/qr_codes/vps_1/ip_213.170.133.116/biannual/" 2>/dev/null || echo "No biannual QRs"
scp "root@213.170.133.116:/opt/tunnelgrain/qr_codes/annual/*" "./static/qr_codes/vps_1/ip_213.170.133.116/annual/" 2>/dev/null || echo "No annual QRs"
scp "root@213.170.133.116:/opt/tunnelgrain/qr_codes/lifetime/*" "./static/qr_codes/vps_1/ip_213.170.133.116/lifetime/" 2>/dev/null || echo "No lifetime QRs"

echo "📊 Config sync summary:"
echo "Test configs: $(ls data/vps_1/ip_213.170.133.116/test/*.conf 2>/dev/null | wc -l)"
echo "Monthly configs: $(ls data/vps_1/ip_213.170.133.116/monthly/*.conf 2>/dev/null | wc -l)"
echo "Quarterly configs: $(ls data/vps_1/ip_213.170.133.116/quarterly/*.conf 2>/dev/null | wc -l)"
echo "Biannual configs: $(ls data/vps_1/ip_213.170.133.116/biannual/*.conf 2>/dev/null | wc -l)"
echo "Annual configs: $(ls data/vps_1/ip_213.170.133.116/annual/*.conf 2>/dev/null | wc -l)"
echo "Lifetime configs: $(ls data/vps_1/ip_213.170.133.116/lifetime/*.conf 2>/dev/null | wc -l)"

echo "✅ Config sync complete!"