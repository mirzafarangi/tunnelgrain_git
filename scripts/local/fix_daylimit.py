#!/usr/bin/env python3
"""
Fix Tunnelgrain Database Structure
Run this script to fix the daily_limits table structure
"""

import os
import psycopg2
from datetime import datetime

# Your database URL
DATABASE_URL = os.environ.get('DATABASE_URL', "postgresql://tunnelgrain_db_user:L69lcg8I8gjiD1LBeqqjpW1uJwcC1jsw@dpg-d169gsuuk2gs73f4q04g-a.frankfurt-postgres.render.com/tunnelgrain_db")

def fix_database():
    """Fix the database structure"""
    try:
        # Fix the URL format
        db_url = DATABASE_URL
        if db_url.startswith('postgres://'):
            db_url = db_url.replace('postgres://', 'postgresql://', 1)
        
        print("🔧 Connecting to database...")
        conn = psycopg2.connect(db_url, sslmode='require')
        cursor = conn.cursor()
        
        print("🔍 Checking current table structure...")
        
        # Check if daily_limits exists
        cursor.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'daily_limits'
            ORDER BY ordinal_position;
        """)
        
        columns = cursor.fetchall()
        if columns:
            print("Current daily_limits columns:")
            for col in columns:
                print(f"  - {col[0]}: {col[1]}")
        
        # Drop the old table
        print("\n🗑️ Dropping old daily_limits table...")
        cursor.execute("DROP TABLE IF EXISTS daily_limits CASCADE;")
        
        # Create new table with correct structure
        print("🔨 Creating new daily_limits table with composite primary key...")
        cursor.execute("""
            CREATE TABLE daily_limits (
                fingerprint VARCHAR(64) NOT NULL,
                date DATE NOT NULL,
                test_count INTEGER DEFAULT 0,
                last_test_at TIMESTAMP,
                PRIMARY KEY (fingerprint, date)
            );
        """)
        
        # Create index
        print("📇 Creating index...")
        cursor.execute("CREATE INDEX idx_daily_limits_date ON daily_limits (date);")
        
        # Verify the new structure
        cursor.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns 
            WHERE table_name = 'daily_limits'
            ORDER BY ordinal_position;
        """)
        
        new_columns = cursor.fetchall()
        print("\n✅ New daily_limits structure:")
        for col in new_columns:
            print(f"  - {col[0]}: {col[1]} (nullable: {col[2]})")
        
        # Check primary key
        cursor.execute("""
            SELECT constraint_name, column_name
            FROM information_schema.key_column_usage
            WHERE table_name = 'daily_limits' AND constraint_name LIKE '%pkey%'
            ORDER BY ordinal_position;
        """)
        
        pk_columns = cursor.fetchall()
        print("\n🔑 Primary key columns:")
        for pk in pk_columns:
            print(f"  - {pk[1]}")
        
        # Test insert
        print("\n🧪 Testing insert...")
        cursor.execute("""
            INSERT INTO daily_limits (fingerprint, date, test_count, last_test_at)
            VALUES ('test_fingerprint', CURRENT_DATE, 1, CURRENT_TIMESTAMP)
            ON CONFLICT (fingerprint, date) DO NOTHING;
        """)
        
        # Clean up test
        cursor.execute("DELETE FROM daily_limits WHERE fingerprint = 'test_fingerprint';")
        
        print("✅ Insert test successful!")
        
        # Check VPN orders
        cursor.execute("SELECT COUNT(*) FROM vpn_orders;")
        order_count = cursor.fetchone()[0]
        print(f"\n📊 Total VPN orders in database: {order_count}")
        
        # Check for any test orders today
        cursor.execute("""
            SELECT COUNT(*) FROM vpn_orders 
            WHERE tier = 'test' AND created_at::date = CURRENT_DATE;
        """)
        today_test_count = cursor.fetchone()[0]
        print(f"📊 Test orders today: {today_test_count}")
        
        # Commit changes
        conn.commit()
        print("\n✅ Database structure fixed successfully!")
        
        cursor.close()
        conn.close()
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error fixing database: {e}")
        return False

def test_daily_limits():
    """Test the daily limits functionality"""
    try:
        db_url = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
        conn = psycopg2.connect(db_url, sslmode='require')
        cursor = conn.cursor()
        
        print("\n🧪 Testing daily limits functionality...")
        
        test_fingerprint = "test_fp_12345"
        
        # Test check
        cursor.execute("""
            SELECT test_count FROM daily_limits 
            WHERE fingerprint = %s AND date = CURRENT_DATE
        """, (test_fingerprint,))
        
        result = cursor.fetchone()
        current_count = result[0] if result else 0
        print(f"Current count for test fingerprint: {current_count}")
        
        # Test increment
        cursor.execute("""
            INSERT INTO daily_limits (fingerprint, date, test_count, last_test_at)
            VALUES (%s, CURRENT_DATE, 1, CURRENT_TIMESTAMP)
            ON CONFLICT (fingerprint, date) 
            DO UPDATE SET 
                test_count = daily_limits.test_count + 1,
                last_test_at = CURRENT_TIMESTAMP
        """, (test_fingerprint,))
        
        # Check new count
        cursor.execute("""
            SELECT test_count FROM daily_limits 
            WHERE fingerprint = %s AND date = CURRENT_DATE
        """, (test_fingerprint,))
        
        new_count = cursor.fetchone()[0]
        print(f"New count after increment: {new_count}")
        
        # Clean up
        cursor.execute("DELETE FROM daily_limits WHERE fingerprint = %s", (test_fingerprint,))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print("✅ Daily limits functionality working correctly!")
        
    except Exception as e:
        print(f"❌ Error testing daily limits: {e}")

if __name__ == "__main__":
    print("🚀 Tunnelgrain Database Structure Fix")
    print("=" * 50)
    
    if fix_database():
        test_daily_limits()
        print("\n🎉 All done! Your database is now properly configured.")
        print("You can now restart your application.")
    else:
        print("\n❌ Fix failed. Please check the error messages above.")