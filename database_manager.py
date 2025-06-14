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
        
        # Define available configs per tier (static allocation)
        self.AVAILABLE_CONFIGS = {
            'test': [f'72100{i:03X}' for i in range(1, 51)],  # 50 test configs
            'monthly': [f'42100{i:03X}' for i in range(51, 81)],  # 30 monthly
            'quarterly': [f'42100{i:03X}' for i in range(81, 101)],  # 20 quarterly
            'biannual': [f'42100{i:03X}' for i in range(101, 116)],  # 15 biannual
            'annual': [f'42100{i:03X}' for i in range(116, 126)],  # 10 annual
            'lifetime': [f'42100{i:03X}' for i in range(126, 131)],  # 5 lifetime
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
        
        try:
            return psycopg2.connect(db_url, sslmode='require')
        except Exception as e:
            logger.error(f"❌ Database connection failed: {e}")
            raise
    
    def init_database(self):
        """Initialize PostgreSQL database tables"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Create orders table with better structure
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
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_config ON vpn_orders (config_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_tier_status ON vpn_orders (tier, status);")
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info("✅ Database tables created/verified successfully")
            
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            raise
    
    def init_json_db(self):
        """Initialize JSON fallback database"""
        if not os.path.exists(self.json_file):
            initial_data = {
                'orders': {},
                'metadata': {
                    'created_at': datetime.now().isoformat(),
                    'version': '2.0'
                }
            }
            with open(self.json_file, 'w') as f:
                json.dump(initial_data, f, indent=2)
            logger.info("✅ Created new JSON database file")
    
    def get_used_configs(self, tier):
        """Get list of config IDs currently in use for a tier"""
        try:
            if self.mode == 'postgresql':
                conn = self.get_connection()
                cursor = conn.cursor()
                
                # Get all active configs for this tier
                cursor.execute("""
                    SELECT config_id FROM vpn_orders 
                    WHERE tier = %s AND status = 'active'
                """, (tier,))
                
                used_configs = [row[0] for row in cursor.fetchall()]
                cursor.close()
                conn.close()
                
                return used_configs
            else:
                # JSON mode
                with open(self.json_file, 'r') as f:
                    data = json.load(f)
                
                used_configs = []
                for order in data['orders'].values():
                    if order.get('tier') == tier and order.get('status') == 'active':
                        used_configs.append(order.get('config_id'))
                
                return used_configs
                
        except Exception as e:
            logger.error(f"❌ Error getting used configs: {e}")
            return []
    
    def get_available_config(self, tier):
        """Get an available config ID for the given tier"""
        try:
            # First cleanup expired orders
            self.cleanup_expired_orders()
            
            # Get all configs for this tier
            all_configs = self.AVAILABLE_CONFIGS.get(tier, [])
            if not all_configs:
                logger.error(f"No configs defined for tier: {tier}")
                return None
            
            # Get currently used configs
            used_configs = set(self.get_used_configs(tier))
            
            # Find available configs
            available_configs = [c for c in all_configs if c not in used_configs]
            
            logger.info(f"Tier {tier}: {len(available_configs)}/{len(all_configs)} configs available")
            
            if not available_configs:
                logger.warning(f"No available configs for tier {tier}")
                return None
            
            # Return the first available config
            return available_configs[0]
            
        except Exception as e:
            logger.error(f"❌ Error getting available config: {e}")
            return None
    
    def create_order(self, tier, config_id=None, user_fingerprint=None, 
                    vps_name='vps_1', vps_ip='213.170.133.116', 
                    stripe_session_id=None):
        """Create new VPN order with automatic config assignment"""
        try:
            # If no config_id provided, get an available one
            if not config_id:
                config_id = self.get_available_config(tier)
                if not config_id:
                    logger.error(f"No available configs for tier {tier}")
                    return None, None
            
            order_id = str(uuid.uuid4())
            
            # Generate order number based on tier
            if tier == 'test':
                order_number = f"72{uuid.uuid4().hex[:6].upper()}"
            else:
                order_number = f"42{uuid.uuid4().hex[:6].upper()}"
            
            # Calculate expiration
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
            
            # Save to database
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
                    json.dump(data, f, indent=2)
            
            logger.info(f"✅ Order created: {order_number} (tier: {tier}, config: {config_id})")
            
            # Try to start VPS timer but don't fail if it doesn't work
            try:
                self.start_vps_timer(order_number, tier, duration_minutes, config_id, vps_name)
            except Exception as e:
                logger.warning(f"⚠️ VPS timer failed (non-critical): {e}")
            
            return order_id, order_number
            
        except Exception as e:
            logger.error(f"❌ Error creating order: {e}", exc_info=True)
            return None, None
    
    def start_vps_timer(self, order_number, tier, duration_minutes, config_id, vps_name='vps_1'):
        """Start expiration timer on VPS - non-critical operation"""
        try:
            vps_endpoint = self.vps_endpoints.get(vps_name)
            if not vps_endpoint:
                logger.warning(f"No endpoint configured for {vps_name}")
                return False
            
            # Skip VPS timer for now if it's causing issues
            logger.info(f"⚠️ VPS timer skipped for {order_number} - manual expiration will handle cleanup")
            return False
            
            # Original VPS timer code (disabled for now)
            """
            response = requests.post(
                f"{vps_endpoint}/api/start-timer",
                json={
                    'order_number': order_number,
                    'tier': tier,
                    'duration_minutes': duration_minutes,
                    'config_id': config_id
                },
                timeout=2
            )
            
            if response.status_code == 200:
                # Update timer_started flag
                if self.mode == 'postgresql':
                    conn = self.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("UPDATE vpn_orders SET timer_started = TRUE WHERE order_number = %s", 
                                 (order_number,))
                    conn.commit()
                    cursor.close()
                    conn.close()
                
                logger.info(f"✅ VPS timer started for {order_number}")
                return True
            """
                
        except Exception as e:
            logger.error(f"❌ VPS timer error: {e}")
            return False
    
    def get_order_by_number(self, order_number):
        """Get order by order number"""
        try:
            if self.mode == 'postgresql':
                conn = self.get_connection()
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                
                cursor.execute("SELECT * FROM vpn_orders WHERE order_number = %s", (order_number,))
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
                orders.sort(key=lambda x: x.get('created_at', ''), reverse=True)
                return orders[:100]
                
        except Exception as e:
            logger.error(f"❌ Error getting all orders: {e}")
            return []
    
    def cleanup_expired_orders(self):
        """Mark expired orders as expired"""
        try:
            now = datetime.now()
            expired_count = 0
            
            if self.mode == 'postgresql':
                conn = self.get_connection()
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE vpn_orders 
                    SET status = 'expired'
                    WHERE status = 'active' AND expires_at < %s
                    RETURNING order_id
                """, (now,))
                
                expired_orders = cursor.fetchall()
                expired_count = len(expired_orders)
                
                conn.commit()
                cursor.close()
                conn.close()
            else:
                # JSON mode
                with open(self.json_file, 'r') as f:
                    data = json.load(f)
                
                for order in data['orders'].values():
                    if order.get('status') == 'active':
                        try:
                            expires_at = datetime.fromisoformat(order['expires_at'].replace('Z', '+00:00'))
                            if expires_at < now:
                                order['status'] = 'expired'
                                expired_count += 1
                        except:
                            pass
                
                with open(self.json_file, 'w') as f:
                    json.dump(data, f, indent=2)
            
            if expired_count > 0:
                logger.info(f"✅ Marked {expired_count} orders as expired")
            
            return expired_count
            
        except Exception as e:
            logger.error(f"❌ Error cleaning up orders: {e}")
            return 0
    
    def get_slot_availability(self):
        """Get available slots per tier"""
        try:
            availability = {}
            
            for tier, all_configs in self.AVAILABLE_CONFIGS.items():
                used_configs = len(self.get_used_configs(tier))
                total_configs = len(all_configs)
                available = total_configs - used_configs
                
                availability[tier] = {
                    'total': total_configs,
                    'used': used_configs,
                    'available': available
                }
            
            return availability
            
        except Exception as e:
            logger.error(f"❌ Error getting slot availability: {e}")
            return {}
    
    def get_vps_status(self, vps_name='vps_1'):
        """Get status from VPS"""
        try:
            # For now, return a mock status
            return {
                'status': 'healthy',
                'server_ip': '213.170.133.116',
                'wireguard': 'active'
            }
            
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