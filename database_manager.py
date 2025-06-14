import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import uuid
import logging
import requests
import hashlib

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TunnelgrainDB:
    def __init__(self):
        # Get database URL from environment
        self.database_url = os.environ.get('DATABASE_URL')
        
        # VPS endpoints configuration
        self.vps_endpoints = {
            'vps_1': os.environ.get('VPS_1_ENDPOINT', 'http://213.170.133.116:8081')
        }
        
        if self.database_url:
            # PostgreSQL mode
            self.mode = 'postgresql'
            self.init_database()
            logger.info("✅ PostgreSQL database initialized")
        else:
            # Fallback to JSON mode
            self.mode = 'json'
            self.json_file = 'tunnelgrain_orders.json'
            self.init_json_db()
            logger.warning("⚠️ No DATABASE_URL found - using JSON fallback mode")
    
    def get_connection(self):
        """Get PostgreSQL connection"""
        if self.mode != 'postgresql':
            return None
        
        # Handle Render's DATABASE_URL format
        db_url = self.database_url
        if db_url.startswith('postgres://'):
            db_url = db_url.replace('postgres://', 'postgresql://', 1)
        
        return psycopg2.connect(db_url, sslmode='require')
    
    def init_database(self):
        """Initialize PostgreSQL database tables"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Create orders table
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
            
            # Drop old daily_limits table if it exists with wrong structure
            cursor.execute("DROP TABLE IF EXISTS daily_limits CASCADE;")
            
            # Create daily limits table with CORRECT composite primary key
            cursor.execute("""
                CREATE TABLE daily_limits (
                    fingerprint VARCHAR(64) NOT NULL,
                    date DATE NOT NULL,
                    test_count INTEGER DEFAULT 0,
                    last_test_at TIMESTAMP,
                    PRIMARY KEY (fingerprint, date)
                );
            """)
            
            # Create index for faster lookups
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_limits_date ON daily_limits (date);")
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info("✅ Database tables created/updated successfully")
            
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            raise
    
    def init_json_db(self):
        """Initialize JSON fallback database"""
        if not os.path.exists(self.json_file):
            with open(self.json_file, 'w') as f:
                json.dump({'orders': {}, 'daily_limits': {}}, f)
    
    def check_daily_limit(self, user_fingerprint, tier='test'):
        """Check if user has exceeded daily limits - FIXED VERSION"""
        if tier != 'test':
            return True  # No limits for paid tiers
        
        if not user_fingerprint:
            logger.warning("No fingerprint provided for daily limit check")
            return False  # Deny if no fingerprint for test
        
        today = datetime.now().date()
        
        if self.mode == 'postgresql':
            try:
                conn = self.get_connection()
                cursor = conn.cursor()
                
                # First, clean up old records (older than 7 days)
                cursor.execute("""
                    DELETE FROM daily_limits 
                    WHERE date < CURRENT_DATE - INTERVAL '7 days'
                """)
                
                # Check if record exists for today
                cursor.execute("""
                    SELECT test_count FROM daily_limits 
                    WHERE fingerprint = %s AND date = %s
                """, (user_fingerprint, today))
                
                result = cursor.fetchone()
                
                if result is None:
                    # No record exists, user can test
                    current_count = 0
                else:
                    current_count = result[0] if result[0] is not None else 0
                
                conn.commit()
                cursor.close()
                conn.close()
                
                can_test = current_count < 3
                logger.info(f"Daily limit check for {user_fingerprint[:8]}...: {current_count}/3 tests used today, can_test={can_test}")
                return can_test
                
            except Exception as e:
                logger.error(f"❌ Error checking daily limit: {e}")
                # On database error, allow the test to prevent blocking users
                return True
        else:
            # JSON mode
            try:
                with open(self.json_file, 'r') as f:
                    data = json.load(f)
                
                limits = data.get('daily_limits', {})
                today_key = today.isoformat()
                
                if user_fingerprint not in limits:
                    return True  # No record, can test
                
                current_count = limits[user_fingerprint].get(today_key, 0)
                return current_count < 3
            except Exception as e:
                logger.error(f"❌ JSON daily limit check error: {e}")
                return True  # Allow on error
    
    def increment_daily_limit(self, user_fingerprint):
        """Increment daily test count"""
        if not user_fingerprint:
            logger.warning("No fingerprint provided for increment")
            return
            
        today = datetime.now().date()
        
        if self.mode == 'postgresql':
            try:
                conn = self.get_connection()
                cursor = conn.cursor()
                
                # Use UPSERT to handle both insert and update
                cursor.execute("""
                    INSERT INTO daily_limits (fingerprint, date, test_count, last_test_at)
                    VALUES (%s, %s, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT (fingerprint, date) 
                    DO UPDATE SET 
                        test_count = daily_limits.test_count + 1,
                        last_test_at = CURRENT_TIMESTAMP
                """, (user_fingerprint, today))
                
                # Get the new count for logging
                cursor.execute("""
                    SELECT test_count FROM daily_limits 
                    WHERE fingerprint = %s AND date = %s
                """, (user_fingerprint, today))
                
                result = cursor.fetchone()
                new_count = result[0] if result else 1
                logger.info(f"Incremented daily limit for {user_fingerprint[:8]}...: now {new_count}/3")
                
                conn.commit()
                cursor.close()
                conn.close()
                
            except Exception as e:
                logger.error(f"❌ Error incrementing daily limit: {e}")
        else:
            # JSON mode
            try:
                with open(self.json_file, 'r') as f:
                    data = json.load(f)
                
                limits = data.get('daily_limits', {})
                today_key = today.isoformat()
                
                if user_fingerprint not in limits:
                    limits[user_fingerprint] = {}
                
                limits[user_fingerprint][today_key] = limits[user_fingerprint].get(today_key, 0) + 1
                
                data['daily_limits'] = limits
                with open(self.json_file, 'w') as f:
                    json.dump(data, f)
            except Exception as e:
                logger.error(f"❌ JSON increment error: {e}")
    
    def create_order(self, tier, config_id, user_fingerprint=None, 
                    vps_name='vps_1', vps_ip='213.170.133.116', 
                    stripe_session_id=None):
        """Create new VPN order with VPS timer integration"""
        try:
            # Check daily limits for test tier
            if tier == 'test' and user_fingerprint:
                if not self.check_daily_limit(user_fingerprint, tier):
                    logger.warning(f"Daily limit exceeded for {user_fingerprint}")
                    return None, None
            
            order_id = str(uuid.uuid4())
            
            # Generate order number based on tier
            if tier == 'test':
                order_number = f"72{uuid.uuid4().hex[:6].upper()}"
            else:
                order_number = f"42{uuid.uuid4().hex[:6].upper()}"
            
            # Calculate expiration and duration
            now = datetime.now()
            duration_map = {
                'test': (15, 'minutes', 0),  # 15 minutes, $0
                'monthly': (30 * 24 * 60, 'minutes', 499),  # 30 days, $4.99
                'quarterly': (90 * 24 * 60, 'minutes', 1299),  # 90 days, $12.99
                'biannual': (180 * 24 * 60, 'minutes', 2399),  # 180 days, $23.99
                'annual': (365 * 24 * 60, 'minutes', 3999),  # 365 days, $39.99
                'lifetime': (36500 * 24 * 60, 'minutes', 9999),  # 100 years, $99.99
            }
            
            duration_minutes, _, price_cents = duration_map.get(tier, (30 * 24 * 60, 'minutes', 499))
            
            if tier == 'test':
                expires_at = now + timedelta(minutes=15)
            else:
                expires_at = now + timedelta(minutes=duration_minutes)
            
            # Save to database FIRST
            if self.mode == 'postgresql':
                conn = self.get_connection()
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO vpn_orders 
                    (order_id, order_number, tier, vps_name, vps_ip, config_id, 
                     price_cents, stripe_session_id, user_fingerprint, expires_at, timer_started)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (order_id, order_number, tier, vps_name, vps_ip, config_id,
                      price_cents, stripe_session_id, user_fingerprint, expires_at, False))
                
                conn.commit()
                cursor.close()
                conn.close()
                
            else:
                # JSON mode
                with open(self.json_file, 'r') as f:
                    data = json.load(f)
                
                data['orders'][order_id] = {
                    'order_id': order_id,
                    'order_number': order_number,
                    'tier': tier,
                    'vps_name': vps_name,
                    'vps_ip': vps_ip,
                    'config_id': config_id,
                    'status': 'active',
                    'price_cents': price_cents,
                    'stripe_session_id': stripe_session_id,
                    'user_fingerprint': user_fingerprint,
                    'created_at': now.isoformat(),
                    'expires_at': expires_at.isoformat(),
                    'timer_started': False
                }
                
                with open(self.json_file, 'w') as f:
                    json.dump(data, f)
            
            # Increment daily limit for test orders AFTER successful creation
            if tier == 'test' and user_fingerprint:
                self.increment_daily_limit(user_fingerprint)
            
            # Try to start VPS timer but don't fail the order if it doesn't work
            try:
                timer_started = self.start_vps_timer(order_number, tier, duration_minutes, config_id, vps_name)
                if timer_started:
                    logger.info(f"✅ Order created: {order_number} ({tier}) with VPS timer")
                else:
                    logger.warning(f"⚠️ Order created: {order_number} ({tier}) but VPS timer failed - order still valid")
            except Exception as e:
                logger.warning(f"⚠️ VPS timer error (order still valid): {e}")
            
            return order_id, order_number
            
        except Exception as e:
            logger.error(f"❌ Error creating order: {e}")
            return None, None
    
    def start_vps_timer(self, order_number, tier, duration_minutes, config_id, vps_name='vps_1'):
        """Start expiration timer on VPS - non-critical operation"""
        try:
            vps_endpoint = self.vps_endpoints.get(vps_name)
            if not vps_endpoint:
                logger.error(f"No endpoint configured for {vps_name}")
                return False
            
            # Call VPS API to start timer with short timeout
            response = requests.post(
                f"{vps_endpoint}/api/start-timer",
                json={
                    'order_number': order_number,
                    'tier': tier,
                    'duration_minutes': duration_minutes,
                    'config_id': config_id
                },
                timeout=3  # Very short timeout
            )
            
            if response.status_code == 200:
                # Update timer_started flag
                if self.mode == 'postgresql':
                    conn = self.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE vpn_orders SET timer_started = TRUE 
                        WHERE order_number = %s
                    """, (order_number,))
                    conn.commit()
                    cursor.close()
                    conn.close()
                else:
                    # JSON mode
                    with open(self.json_file, 'r') as f:
                        data = json.load(f)
                    
                    for order in data['orders'].values():
                        if order.get('order_number') == order_number:
                            order['timer_started'] = True
                            break
                    
                    with open(self.json_file, 'w') as f:
                        json.dump(data, f)
                
                logger.info(f"✅ VPS timer started for {order_number}")
                return True
            else:
                logger.error(f"❌ VPS timer failed: {response.status_code}")
                return False
                
        except requests.exceptions.Timeout:
            logger.warning(f"⚠️ VPS timer timeout - continuing without timer")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ VPS connection error: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Error starting VPS timer: {e}")
            return False
    
    def get_order_by_number(self, order_number):
        """Get order by order number"""
        try:
            if self.mode == 'postgresql':
                conn = self.get_connection()
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                
                cursor.execute("""
                    SELECT * FROM vpn_orders WHERE order_number = %s
                """, (order_number,))
                
                result = cursor.fetchone()
                cursor.close()
                conn.close()
                
                return dict(result) if result else None
            else:
                # JSON mode
                with open(self.json_file, 'r') as f:
                    data = json.load(f)
                
                for order in data['orders'].values():
                    if order.get('order_number') == order_number:
                        return order
                
                return None
                
        except Exception as e:
            logger.error(f"❌ Error getting order: {e}")
            return None
    
    def get_all_orders(self):
        """Get all orders"""
        try:
            if self.mode == 'postgresql':
                conn = self.get_connection()
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                
                cursor.execute("""
                    SELECT * FROM vpn_orders 
                    ORDER BY created_at DESC 
                    LIMIT 100
                """)
                
                results = cursor.fetchall()
                cursor.close()
                conn.close()
                
                return [dict(row) for row in results]
            else:
                # JSON mode
                with open(self.json_file, 'r') as f:
                    data = json.load(f)
                
                orders = list(data['orders'].values())
                # Sort by created_at descending
                orders.sort(key=lambda x: x.get('created_at', ''), reverse=True)
                return orders[:100]
                
        except Exception as e:
            logger.error(f"❌ Error getting all orders: {e}")
            return []
    
    def cleanup_expired_orders(self):
        """Mark expired orders as expired"""
        try:
            now = datetime.now()
            
            if self.mode == 'postgresql':
                conn = self.get_connection()
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE vpn_orders 
                    SET status = 'expired'
                    WHERE status = 'active' AND expires_at < %s
                """, (now,))
                
                expired_count = cursor.rowcount
                conn.commit()
                cursor.close()
                conn.close()
            else:
                # JSON mode
                with open(self.json_file, 'r') as f:
                    data = json.load(f)
                
                expired_count = 0
                for order in data['orders'].values():
                    if order.get('status') == 'active':
                        try:
                            expires_at = datetime.fromisoformat(order['expires_at'])
                            if expires_at < now:
                                order['status'] = 'expired'
                                expired_count += 1
                        except:
                            pass
                
                with open(self.json_file, 'w') as f:
                    json.dump(data, f)
            
            if expired_count > 0:
                logger.info(f"✅ Marked {expired_count} orders as expired")
            
            return expired_count
            
        except Exception as e:
            logger.error(f"❌ Error cleaning up orders: {e}")
            return 0
    
    def get_vps_status(self, vps_name='vps_1'):
        """Get status from VPS"""
        try:
            vps_endpoint = self.vps_endpoints.get(vps_name)
            if not vps_endpoint:
                return {'error': f'No endpoint for {vps_name}'}
            
            response = requests.get(f"{vps_endpoint}/api/status", timeout=5)
            
            if response.status_code == 200:
                return response.json()
            else:
                return {'error': f'VPS returned {response.status_code}'}
                
        except Exception as e:
            logger.error(f"❌ Error getting VPS status: {e}")
            return {'error': str(e)}
    
    def health_check(self):
        """Check database health"""
        try:
            if self.mode == 'postgresql':
                conn = self.get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
                conn.close()
                return {'status': 'healthy', 'mode': 'postgresql'}
            else:
                return {'status': 'healthy', 'mode': 'json'}
                
        except Exception as e:
            logger.error(f"❌ Health check failed: {e}")
            return {'status': 'error', 'mode': self.mode, 'error': str(e)}