#!/usr/bin/env python3
"""
Tunnelgrain Database Debug & Fix Script
Run this to diagnose and fix database issues
"""

import os
import psycopg2
from datetime import datetime

# Your database URL
DATABASE_URL = "postgresql://tunnelgrain_db_user:L69lcg8I8gjiD1LBeqqjpW1uJwcC1jsw@dpg-d169gsuuk2gs73f4q04g-a.frankfurt-postgres.render.com/tunnelgrain_db"

def test_connection():
    """Test database connection"""
    try:
        # Fix the URL format
        db_url = DATABASE_URL
        if db_url.startswith('postgres://'):
            db_url = db_url.replace('postgres://', 'postgresql://', 1)
        
        print("🔍 Testing database connection...")
        conn = psycopg2.connect(db_url, sslmode='require')
        cursor = conn.cursor()
        
        # Test query
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        print("✅ Database connection successful!")
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False

def check_tables():
    """Check if tables exist"""
    try:
        db_url = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
        conn = psycopg2.connect(db_url, sslmode='require')
        cursor = conn.cursor()
        
        print("\n🔍 Checking tables...")
        
        # Check vpn_orders table
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'vpn_orders'
            );
        """)
        orders_exists = cursor.fetchone()[0]
        print(f"vpn_orders table: {'✅ Exists' if orders_exists else '❌ Missing'}")
        
        # Check daily_limits table
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'daily_limits'
            );
        """)
        limits_exists = cursor.fetchone()[0]
        print(f"daily_limits table: {'✅ Exists' if limits_exists else '❌ Missing'}")
        
        cursor.close()
        conn.close()
        
        return orders_exists and limits_exists
        
    except Exception as e:
        print(f"❌ Error checking tables: {e}")
        return False

def create_tables():
    """Create missing tables"""
    try:
        db_url = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
        conn = psycopg2.connect(db_url, sslmode='require')
        cursor = conn.cursor()
        
        print("\n🔨 Creating/updating tables...")
        
        # Create vpn_orders table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vpn_orders (
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
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON vpn_orders (status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_number ON vpn_orders (order_number);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_expires ON vpn_orders (expires_at);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_created ON vpn_orders (created_at DESC);")
        
        # Create daily_limits table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_limits (
                fingerprint VARCHAR(64),
                date DATE NOT NULL,
                test_count INTEGER DEFAULT 0,
                last_test_at TIMESTAMP,
                PRIMARY KEY (fingerprint, date)
            );
        """)
        
        conn.commit()
        print("✅ Tables created/updated successfully!")
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        return False

def check_daily_limits():
    """Check daily limits data"""
    try:
        db_url = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
        conn = psycopg2.connect(db_url, sslmode='require')
        cursor = conn.cursor()
        
        print("\n🔍 Checking daily limits...")
        
        # Count records
        cursor.execute("SELECT COUNT(*) FROM daily_limits")
        count = cursor.fetchone()[0]
        print(f"Total daily limit records: {count}")
        
        # Check today's records
        cursor.execute("""
            SELECT fingerprint, test_count, last_test_at 
            FROM daily_limits 
            WHERE date = CURRENT_DATE
            ORDER BY test_count DESC
            LIMIT 5
        """)
        
        today_records = cursor.fetchall()
        if today_records:
            print("\nToday's test usage:")
            for fp, count, last_test in today_records:
                print(f"  Fingerprint: {fp[:16]}... - Count: {count} - Last: {last_test}")
        else:
            print("No test usage today")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Error checking daily limits: {e}")

def reset_daily_limits():
    """Reset all daily limits for testing"""
    try:
        db_url = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
        conn = psycopg2.connect(db_url, sslmode='require')
        cursor = conn.cursor()
        
        print("\n🔄 Resetting daily limits...")
        
        # Delete all daily limit records
        cursor.execute("DELETE FROM daily_limits")
        deleted = cursor.rowcount
        
        conn.commit()
        print(f"✅ Deleted {deleted} daily limit records")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Error resetting daily limits: {e}")

def check_orders():
    """Check orders in database"""
    try:
        db_url = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
        conn = psycopg2.connect(db_url, sslmode='require')
        cursor = conn.cursor()
        
        print("\n🔍 Checking orders...")
        
        # Count orders by status
        cursor.execute("""
            SELECT status, tier, COUNT(*) 
            FROM vpn_orders 
            GROUP BY status, tier
            ORDER BY status, tier
        """)
        
        results = cursor.fetchall()
        if results:
            print("\nOrder statistics:")
            for status, tier, count in results:
                print(f"  {status} - {tier}: {count}")
        else:
            print("No orders found in database")
        
        # Recent orders
        cursor.execute("""
            SELECT order_number, tier, status, created_at 
            FROM vpn_orders 
            ORDER BY created_at DESC 
            LIMIT 5
        """)
        
        recent = cursor.fetchall()
        if recent:
            print("\nRecent orders:")
            for order_num, tier, status, created in recent:
                print(f"  {order_num} - {tier} - {status} - {created}")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Error checking orders: {e}")

def main():
    """Run all diagnostics"""
    print("🚀 Tunnelgrain Database Diagnostics")
    print("=" * 50)
    
    # Test connection
    if not test_connection():
        print("\n❌ Cannot proceed without database connection")
        return
    
    # Check tables
    tables_exist = check_tables()
    
    if not tables_exist:
        # Create tables
        if create_tables():
            print("✅ Tables created successfully")
        else:
            print("❌ Failed to create tables")
            return
    
    # Check data
    check_orders()
    check_daily_limits()
    
    # Ask to reset daily limits
    print("\n" + "=" * 50)
    response = input("\n🤔 Reset daily limits to allow testing? (y/n): ")
    if response.lower() == 'y':
        reset_daily_limits()
    
    print("\n✅ Diagnostics complete!")

if __name__ == "__main__":
    main()