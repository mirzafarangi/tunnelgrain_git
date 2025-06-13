import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import uuid
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SimplifiedVPNManager:
    """
    Simplified VPN management system for single VPS setup
    Can be extended later for multiple VPS/IP support
    """
    
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        self.use_database = bool(self.database_url)
        
        # Service tier configuration - MATCHES YOUR VPS SETUP
        self.service_tiers = {
            'test': {
                'name': 'Free Test',
                'duration_days': 0,  # Special: 15 minutes
                'price_cents': 0,
                'description': '15-minute free trial',
                'order_prefix': '72',
                'capacity': 50
            },
            'monthly': {
                'name': 'Monthly VPN',
                'duration_days': 30,
                'price_cents': 499,  # $4.99
                'description': '30 days unlimited access',
                'order_prefix': '42',
                'capacity': 30
            },
            'quarterly': {
                'name': '3-Month VPN',
                'duration_days': 90,
                'price_cents': 1299,  # $12.99
                'description': '90 days unlimited access',
                'order_prefix': '42',
                'capacity': 20
            },
            'biannual': {
                'name': '6-Month VPN',
                'duration_days': 180,
                'price_cents': 2399,  # $23.99
                'description': '180 days unlimited access',
                'order_prefix': '42',
                'capacity': 15
            },
            'annual': {
                'name': '12-Month VPN',
                'duration_days': 365,
                'price_cents': 3999,  # $39.99
                'description': '365 days unlimited access',
                'order_prefix': '42',
                'capacity': 10
            },
            'lifetime': {
                'name': 'Lifetime VPN',
                'duration_days': 36500,  # 100 years
                'price_cents': 9999,  # $99.99
                'description': 'Lifetime unlimited access',
                'order_prefix': '42',
                'capacity': 5
            }
        }
        
        # VPS configuration (single VPS for now)
        self.vps_config = {
            "endpoint": os.environ.get('VPS_1_ENDPOINT', 'http://213.170.133.116:8080'),
            "name": os.environ.get('VPS_1_NAME', 'primary_vps'),
            "ip": "213.170.133.116"
        }
        
        # Initialize database or fallback
        if self.use_database:
            logger.info("[DB] Attempting PostgreSQL connection...")
            try:
                self.init_database()
                logger.info("[DB] ✅ PostgreSQL connected successfully")
            except Exception as e:
                logger.error(f"[DB] ❌ PostgreSQL failed: {e}")
                self.use_database = False
                self.fallback_to_json()
        else:
            logger.info("[DB] No DATABASE_URL found, using JSON fallback...")
            self.fallback_to_json()
    
    def init_database(self):
        """Initialize PostgreSQL database with simple schema"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Simple orders table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vpn_orders (
                order_id VARCHAR(36) PRIMARY KEY,
                order_number VARCHAR(20) UNIQUE NOT NULL,
                tier VARCHAR(20) NOT NULL,
                duration_days INTEGER NOT NULL,
                ip_address VARCHAR(45) NOT NULL,
                vps_name VARCHAR(50) NOT NULL,
                status VARCHAR(20) DEFAULT 'active',
                price_cents INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                assigned_at TIMESTAMP,
                expires_at TIMESTAMP,
                stripe_session_id VARCHAR(200),
                user_fingerprint VARCHAR(64)
            );
        """)
        
        # Basic indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_expires ON vpn_orders (expires_at);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON vpn_orders (status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_number ON vpn_orders (order_number);")
        
        conn.commit()
        cursor.close()
        conn.close()
    
    def get_connection(self):
        """Get PostgreSQL database connection"""
        if not self.database_url:
            raise Exception("DATABASE_URL not configured")
        return psycopg2.connect(self.database_url, sslmode='require')
    
    def fallback_to_json(self):
        """Initialize JSON fallback system"""
        self.slots_file = 'simple_slots.json'
        self._load_fallback_data()
    
    def _load_fallback_data(self):
        """Load data from JSON file"""
        if os.path.exists(self.slots_file):
            try:
                with open(self.slots_file, 'r') as f:
                    self.fallback_data = json.load(f)
                logger.info(f"[FALLBACK] Loaded data from {self.slots_file}")
            except Exception as e:
                logger.error(f"[FALLBACK] Error loading data: {e}")
                self._create_fallback_data()
        else:
            self._create_fallback_data()
    
    def _create_fallback_data(self):
        """Create initial fallback data structure"""
        self.fallback_data = {
            "orders": {},
            "last_cleanup": datetime.now().isoformat()
        }
        self._save_fallback_data()
    
    def _save_fallback_data(self):
        """Save data to JSON file"""
        try:
            with open(self.slots_file, 'w') as f:
                json.dump(self.fallback_data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"[FALLBACK] Error saving data: {e}")
    
    def generate_order_number(self, tier: str) -> str:
        """Generate order number with tier-specific prefix"""
        tier_config = self.service_tiers.get(tier, {})
        prefix = tier_config.get('order_prefix', '42')
        return f"{prefix}{str(uuid.uuid4()).replace('-', '')[:6].upper()}"
    
    def assign_vpn_slot(self, tier: str, user_fingerprint: str, 
                       stripe_session_id: str = None) -> Optional[Tuple[str, str]]:
        """Assign VPN slot to customer"""
        if tier not in self.service_tiers:
            logger.error(f"[ASSIGN] Invalid tier: {tier}")
            return None
        
        if self.use_database:
            return self._assign_database_slot(tier, user_fingerprint, stripe_session_id)
        else:
            return self._assign_fallback_slot(tier, user_fingerprint, stripe_session_id)
    
    def _assign_database_slot(self, tier: str, user_fingerprint: str, 
                            stripe_session_id: str) -> Optional[Tuple[str, str]]:
        """Assign slot using PostgreSQL database"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Generate unique identifiers
            order_id = str(uuid.uuid4())
            order_number = self.generate_order_number(tier)
            
            # Get tier configuration
            tier_config = self.service_tiers[tier]
            duration_days = tier_config['duration_days']
            price_cents = tier_config['price_cents']
            
            # Calculate expiration
            now = datetime.now()
            if tier == 'test':
                expires_at = now + timedelta(minutes=15)
            else:
                expires_at = now + timedelta(days=duration_days)
            
            # Insert order record
            cursor.execute("""
                INSERT INTO vpn_orders 
                (order_id, order_number, tier, duration_days, ip_address, 
                 vps_name, price_cents, assigned_at, expires_at, stripe_session_id, user_fingerprint)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (order_id, order_number, tier, duration_days, self.vps_config["ip"], 
                  self.vps_config["name"], price_cents, now, expires_at, stripe_session_id, user_fingerprint))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info(f"[ASSIGN] ✅ {tier} slot {order_number} assigned to {self.vps_config['ip']}")
            return order_id, order_number
            
        except Exception as e:
            logger.error(f"[ASSIGN] ❌ Database error: {e}")
            return None
    
    def _assign_fallback_slot(self, tier: str, user_fingerprint: str, 
                            stripe_session_id: str) -> Optional[Tuple[str, str]]:
        """Assign slot using JSON fallback"""
        try:
            order_id = str(uuid.uuid4())
            order_number = self.generate_order_number(tier)
            
            tier_config = self.service_tiers[tier]
            duration_days = tier_config['duration_days']
            
            now = datetime.now()
            if tier == 'test':
                expires_at = now + timedelta(minutes=15)
            else:
                expires_at = now + timedelta(days=duration_days)
            
            # Store order
            self.fallback_data["orders"][order_id] = {
                "order_number": order_number,
                "tier": tier,
                "duration_days": duration_days,
                "ip_address": self.vps_config["ip"],
                "vps_name": self.vps_config["name"],
                "price_cents": tier_config['price_cents'],
                "status": "active",
                "assigned_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
                "stripe_session_id": stripe_session_id,
                "user_fingerprint": user_fingerprint
            }
            
            self._save_fallback_data()
            
            logger.info(f"[FALLBACK] ✅ {tier} slot {order_number} assigned")
            return order_id, order_number
            
        except Exception as e:
            logger.error(f"[FALLBACK] ❌ Error assigning slot: {e}")
            return None
    
    def get_order_status(self, order_number: str) -> Optional[Dict]:
        """Get detailed order status by order number"""
        if self.use_database:
            try:
                conn = self.get_connection()
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("""
                    SELECT * FROM vpn_orders WHERE order_number = %s
                """, (order_number,))
                
                result = cursor.fetchone()
                cursor.close()
                conn.close()
                
                if result:
                    order_data = dict(result)
                    tier_config = self.service_tiers.get(order_data['tier'], {})
                    order_data['tier_info'] = tier_config
                    return order_data
                
                return None
                
            except Exception as e:
                logger.error(f"[ORDER] ❌ Error getting order status: {e}")
                return None
        else:
            return self._get_fallback_order_status(order_number)
    
    def _get_fallback_order_status(self, order_number: str) -> Optional[Dict]:
        """Get order status from JSON fallback"""
        for order_data in self.fallback_data.get("orders", {}).values():
            if order_data.get("order_number") == order_number:
                tier = order_data.get("tier")
                if tier:
                    order_data['tier_info'] = self.service_tiers.get(tier, {})
                return order_data
        return None
    
    def cleanup_expired_orders(self) -> int:
        """Clean up expired orders"""
        if self.use_database:
            try:
                conn = self.get_connection()
                cursor = conn.cursor()
                
                # Get expired orders count
                cursor.execute("""
                    SELECT COUNT(*) FROM vpn_orders 
                    WHERE status = 'active' AND expires_at < CURRENT_TIMESTAMP
                """)
                expired_count = cursor.fetchone()[0]
                
                # Update status to expired
                cursor.execute("""
                    UPDATE vpn_orders 
                    SET status = 'expired'
                    WHERE status = 'active' AND expires_at < CURRENT_TIMESTAMP
                """)
                
                conn.commit()
                cursor.close()
                conn.close()
                
                if expired_count > 0:
                    logger.info(f"[CLEANUP] ✅ Expired {expired_count} orders")
                
                return expired_count
                
            except Exception as e:
                logger.error(f"[CLEANUP] ❌ Error cleaning up orders: {e}")
                return 0
        else:
            return self._cleanup_fallback_orders()
    
    def _cleanup_fallback_orders(self) -> int:
        """Clean up expired orders in JSON fallback"""
        now = datetime.now()
        expired_count = 0
        
        for order_id, order_data in list(self.fallback_data.get("orders", {}).items()):
            if order_data.get("status") == "active":
                try:
                    expires_at = datetime.fromisoformat(order_data["expires_at"])
                    if now > expires_at:
                        order_data["status"] = "expired"
                        expired_count += 1
                except Exception:
                    pass
        
        if expired_count > 0:
            self._save_fallback_data()
            logger.info(f"[FALLBACK] ✅ Expired {expired_count} orders")
            
        return expired_count
    
    def get_service_tiers(self) -> Dict:
        """Get all service tier configurations"""
        return self.service_tiers
    
    def get_tier_config(self, tier: str) -> Optional[Dict]:
        """Get configuration for specific tier"""
        return self.service_tiers.get(tier)
    
    def get_vps_status(self) -> Dict:
        """Get VPS status (simplified for single VPS)"""
        return {
            "vps_name": self.vps_config["name"],
            "ip_address": self.vps_config["ip"],
            "endpoint": self.vps_config["endpoint"],
            "status": "healthy",
            "tiers": self.service_tiers
        }