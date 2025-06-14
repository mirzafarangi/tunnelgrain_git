#!/usr/bin/env python3
"""
Debug script to identify why test VPN creation is failing
"""

import os
import sys
import json
from datetime import datetime

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database_manager import TunnelgrainDB
from app import get_available_config_files, DATA_DIR, QR_DIR

def check_environment():
    """Check environment setup"""
    print("=== ENVIRONMENT CHECK ===")
    print(f"DATABASE_URL set: {bool(os.environ.get('DATABASE_URL'))}")
    print(f"Current directory: {os.getcwd()}")
    print(f"DATA_DIR: {DATA_DIR}")
    print(f"QR_DIR: {QR_DIR}")
    print()

def check_directories():
    """Check if required directories exist"""
    print("=== DIRECTORY CHECK ===")
    
    # Check data directory
    data_exists = os.path.exists(DATA_DIR)
    print(f"Data directory exists: {data_exists}")
    if data_exists:
        print(f"Data directory contents:")
        for tier in ['test', 'monthly', 'quarterly', 'biannual', 'annual', 'lifetime']:
            tier_path = os.path.join(DATA_DIR, tier)
            if os.path.exists(tier_path):
                files = len(os.listdir(tier_path))
                print(f"  - {tier}: {files} files")
    
    # Check QR directory
    qr_exists = os.path.exists(QR_DIR)
    print(f"\nQR directory exists: {qr_exists}")
    print()

def check_database():
    """Check database functionality"""
    print("=== DATABASE CHECK ===")
    
    try:
        db = TunnelgrainDB()
        print(f"Database mode: {db.mode}")
        
        # Check health
        health = db.health_check()
        print(f"Database health: {health}")
        
        # If JSON mode, check file
        if db.mode == 'json':
            json_file = 'tunnelgrain_orders.json'
            if os.path.exists(json_file):
                print(f"JSON file exists: {json_file}")
                try:
                    with open(json_file, 'r') as f:
                        data = json.load(f)
                    print(f"JSON structure valid: True")
                    print(f"Orders count: {len(data.get('orders', {}))}")
                except Exception as e:
                    print(f"JSON parse error: {e}")
            else:
                print(f"JSON file missing: {json_file}")
        
        print()
        return db
    except Exception as e:
        print(f"Database initialization error: {e}")
        print()
        return None

def test_config_availability():
    """Test config file availability"""
    print("=== CONFIG AVAILABILITY CHECK ===")
    
    test_configs = get_available_config_files('test')
    print(f"Available test configs: {len(test_configs)}")
    if test_configs:
        print(f"Sample configs: {test_configs[:5]}")
    print()
    
    return test_configs

def test_order_creation(db, test_configs):
    """Test order creation"""
    print("=== ORDER CREATION TEST ===")
    
    if not db:
        print("Database not initialized, skipping order test")
        return
    
    if not test_configs:
        print("No test configs available, skipping order test")
        return
    
    # Try to create a test order
    try:
        import random
        config_id = random.choice(test_configs)
        print(f"Testing with config: {config_id}")
        
        order_id, order_number = db.create_order(
            tier='test',
            config_id=config_id,
            user_fingerprint='debug_test_fingerprint'
        )
        
        if order_id:
            print(f"✅ Order created successfully!")
            print(f"  Order ID: {order_id}")
            print(f"  Order Number: {order_number}")
            
            # Verify order exists
            order_data = db.get_order_by_number(order_number)
            if order_data:
                print(f"✅ Order verified in database")
            else:
                print(f"❌ Order not found in database after creation")
        else:
            print(f"❌ Order creation failed - returned None")
            
    except Exception as e:
        print(f"❌ Order creation exception: {e}")
        import traceback
        traceback.print_exc()
    
    print()

def check_file_permissions():
    """Check file permissions"""
    print("=== FILE PERMISSION CHECK ===")
    
    # Check if we can write to current directory
    test_file = 'test_write_permission.tmp'
    try:
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
        print("✅ Can write to current directory")
    except Exception as e:
        print(f"❌ Cannot write to current directory: {e}")
    
    # Check JSON file permissions if it exists
    json_file = 'tunnelgrain_orders.json'
    if os.path.exists(json_file):
        print(f"\nJSON file permissions:")
        import stat
        st = os.stat(json_file)
        print(f"  Owner: {st.st_uid}")
        print(f"  Group: {st.st_gid}")
        print(f"  Mode: {oct(st.st_mode)}")
        print(f"  Readable: {os.access(json_file, os.R_OK)}")
        print(f"  Writable: {os.access(json_file, os.W_OK)}")
    
    print()

def fix_json_database():
    """Attempt to fix JSON database if corrupted"""
    print("=== ATTEMPTING JSON FIX ===")
    
    json_file = 'tunnelgrain_orders.json'
    
    # Backup existing file if it exists
    if os.path.exists(json_file):
        backup_file = f'tunnelgrain_orders.backup.{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        try:
            with open(json_file, 'r') as f:
                content = f.read()
            with open(backup_file, 'w') as f:
                f.write(content)
            print(f"✅ Backed up existing file to: {backup_file}")
        except Exception as e:
            print(f"❌ Backup failed: {e}")
    
    # Create fresh JSON structure
    try:
        fresh_data = {
            'orders': {},
            'daily_limits': {}
        }
        with open(json_file, 'w') as f:
            json.dump(fresh_data, f, indent=2)
        print("✅ Created fresh JSON database")
        
        # Set proper permissions
        os.chmod(json_file, 0o666)
        print("✅ Set file permissions to 666")
        
    except Exception as e:
        print(f"❌ Failed to create fresh JSON: {e}")
    
    print()

def main():
    """Run all debug checks"""
    print("🔍 TUNNELGRAIN DEBUG SCRIPT")
    print("=" * 50)
    print()
    
    # Run checks
    check_environment()
    check_directories()
    check_file_permissions()
    
    db = check_database()
    test_configs = test_config_availability()
    
    # If database issues, try to fix
    if db and db.mode == 'json':
        json_file = 'tunnelgrain_orders.json'
        needs_fix = False
        
        if not os.path.exists(json_file):
            print("⚠️  JSON file missing - will create")
            needs_fix = True
        else:
            try:
                with open(json_file, 'r') as f:
                    json.load(f)
            except:
                print("⚠️  JSON file corrupted - will recreate")
                needs_fix = True
        
        if needs_fix:
            fix_json_database()
            # Reinitialize database
            db = check_database()
    
    # Test order creation
    test_order_creation(db, test_configs)
    
    print("\n=== RECOMMENDATIONS ===")
    if db and db.mode == 'json' and not os.path.exists('tunnelgrain_orders.json'):
        print("1. JSON database file is missing. Run this script again to create it.")
    
    if not test_configs:
        print("2. No test configs found. Check that files exist in: data/vps_1/ip_213.170.133.116/test/")
    
    if db and db.mode == 'postgresql':
        print("3. Using PostgreSQL. Ensure DATABASE_URL is correct and database is accessible.")
    
    print("\nDebug complete!")

if __name__ == '__main__':
    main()