#!/usr/bin/env python3
"""
Fix database issues for Tunnelgrain
"""

import os
import json
import sys
from datetime import datetime

def fix_json_database():
    """Create or fix the JSON database file"""
    json_file = 'tunnelgrain_orders.json'
    
    # Backup existing if present
    if os.path.exists(json_file):
        backup_name = f'backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}_{json_file}'
        print(f"📁 Backing up existing database to: {backup_name}")
        try:
            with open(json_file, 'r') as f:
                content = f.read()
            with open(backup_name, 'w') as f:
                f.write(content)
        except Exception as e:
            print(f"⚠️  Backup failed: {e}")
    
    # Create proper structure
    data = {
        'orders': {},
        'daily_limits': {}
    }
    
    try:
        with open(json_file, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"✅ Created/fixed {json_file}")
        
        # Set permissions
        os.chmod(json_file, 0o666)
        print("✅ Set file permissions")
        
        return True
    except Exception as e:
        print(f"❌ Failed to create database: {e}")
        return False

def check_directories():
    """Ensure all required directories exist"""
    base_dirs = [
        'data',
        'data/vps_1',
        'data/vps_1/ip_213.170.133.116',
        'static',
        'static/qr_codes',
        'static/qr_codes/vps_1',
        'static/qr_codes/vps_1/ip_213.170.133.116'
    ]
    
    for dir_path in base_dirs:
        if not os.path.exists(dir_path):
            try:
                os.makedirs(dir_path)
                print(f"📁 Created directory: {dir_path}")
            except Exception as e:
                print(f"❌ Failed to create {dir_path}: {e}")

def test_database_operations():
    """Test basic database operations"""
    print("\n🧪 Testing database operations...")
    
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    
    try:
        from database_manager import TunnelgrainDB
        
        db = TunnelgrainDB()
        print(f"✅ Database initialized in {db.mode} mode")
        
        # Test order creation
        order_id, order_number = db.create_order(
            tier='test',
            config_id='72100001',
            user_fingerprint='test_fix_script'
        )
        
        if order_id:
            print(f"✅ Test order created: {order_number}")
            
            # Verify retrieval
            order = db.get_order_by_number(order_number)
            if order:
                print("✅ Order retrieval successful")
            else:
                print("❌ Order retrieval failed")
        else:
            print("❌ Order creation failed")
            
    except Exception as e:
        print(f"❌ Database test failed: {e}")
        import traceback
        traceback.print_exc()

def main():
    print("🔧 TUNNELGRAIN DATABASE FIX")
    print("=" * 50)
    
    # Check and create directories
    print("\n📁 Checking directories...")
    check_directories()
    
    # Fix JSON database
    print("\n🗄️  Fixing database...")
    if fix_json_database():
        # Test operations
        test_database_operations()
    
    print("\n✅ Fix complete!")
    print("\n📝 Next steps:")
    print("1. Run your app: python app.py")
    print("2. Try the test VPN again")
    print("3. If using PostgreSQL in production, set DATABASE_URL environment variable")

if __name__ == '__main__':
    main()