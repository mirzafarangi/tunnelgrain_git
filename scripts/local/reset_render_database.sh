#!/bin/bash
# Reset Render Database - Run this on your Mac terminal in your project folder

echo "🗑️ RESETTING RENDER DATABASE"
echo "============================"

# Check if we're in the right directory
if [ ! -f "database_manager.py" ]; then
    echo "❌ database_manager.py not found!"
    echo "Please run this script from your project folder"
    exit 1
fi

# Create the reset script
cat > reset_db.py << 'EOF'
#!/usr/bin/env python3
"""
Complete Database Reset for Tunnelgrain Render App
This will delete ALL orders and reset everything to factory state
"""

import os
import sys
from database_manager import TunnelgrainDB

def reset_database():
    """Reset the entire database"""
    print("🗑️ Initializing database connection...")
    
    try:
        db = TunnelgrainDB()
        
        if db.mode == 'postgresql':
            print("📊 PostgreSQL mode detected")
            
            # Get connection
            conn = db.get_connection()
            cursor = conn.cursor()
            
            # Drop and recreate the table (nuclear option)
            print("💥 Dropping existing table...")
            cursor.execute("DROP TABLE IF EXISTS vpn_orders CASCADE;")
            
            print("🔧 Creating fresh table...")
            cursor.execute("""
                CREATE TABLE vpn_orders (
                    order_id VARCHAR(36) PRIMARY KEY,
                    order_number VARCHAR(20) UNIQUE NOT NULL,
                    tier VARCHAR(20) NOT NULL,
                    vps_name VARCHAR(50) DEFAULT 'vps_1',
                    vps_ip VARCHAR(45) NOT NULL,
                    config_id VARCHAR(50) NOT NULL,
                    status VARCHAR(20) DEFAULT 'active',
                    price_cents INTEGER DEFAULT 0,
                    stripe_session_id VARCHAR(200),
                    user_fingerprint VARCHAR(64),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    timer_started BOOLEAN DEFAULT FALSE,
                    metadata JSONB DEFAULT '{}'::jsonb
                );
            """)
            
            # Recreate indexes
            print("📋 Creating indexes...")
            cursor.execute("CREATE INDEX idx_orders_status ON vpn_orders (status);")
            cursor.execute("CREATE INDEX idx_orders_number ON vpn_orders (order_number);")
            cursor.execute("CREATE INDEX idx_orders_expires ON vpn_orders (expires_at);")
            cursor.execute("CREATE INDEX idx_orders_config ON vpn_orders (config_id);")
            cursor.execute("CREATE INDEX idx_orders_tier_status ON vpn_orders (tier, status);")
            
            conn.commit()
            cursor.close()
            conn.close()
            
            print("✅ PostgreSQL database reset complete!")
            
        else:
            print("📄 JSON mode detected")
            
            # Reset JSON file
            if os.path.exists(db.json_file):
                os.remove(db.json_file)
                print(f"🗑️ Removed {db.json_file}")
            
            # Reinitialize
            db.init_json_db()
            print("✅ JSON database reset complete!")
        
        # Verify reset
        print("\n🔍 Verifying reset...")
        orders = db.get_all_orders()
        availability = db.get_slot_availability()
        
        print(f"📊 Total orders: {len(orders)}")
        print("📋 Slot availability:")
        for tier, slots in availability.items():
            print(f"   {tier}: {slots['available']}/{slots['total']} available")
        
        if len(orders) == 0:
            print("\n✅ DATABASE RESET SUCCESSFUL!")
            print("🎯 All slots are now available for new customers")
        else:
            print(f"\n⚠️ Warning: {len(orders)} orders still exist")
            
    except Exception as e:
        print(f"❌ Reset failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    print("⚠️ WARNING: This will DELETE ALL ORDERS!")
    print("This action cannot be undone!")
    print()
    
    confirm = input("Type 'RESET' to confirm: ")
    if confirm != 'RESET':
        print("❌ Reset cancelled")
        sys.exit(0)
    
    reset_database()
EOF

# Make it executable
chmod +x reset_db.py

echo "✅ Reset script created!"
echo ""
echo "To reset your Render database:"
echo "1. Make sure you have the correct DATABASE_URL environment variable"
echo "2. Run: python3 reset_db.py"
echo "3. Type 'RESET' when prompted"
echo ""
echo "This will completely wipe all orders and start fresh!"