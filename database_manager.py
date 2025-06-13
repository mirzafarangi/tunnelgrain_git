import os
import json
import psycopg2
import requests
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

class EnhancedVPNManager:
    """
    Complete VPN business management system
    Handles PostgreSQL database, VPS communication, and multi-tier operations
    """
    
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        self.use_database = bool(self.database_url)
        
        # Service tier configuration - MATCHES YOUR VPS SETUP EXACTLY
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
        
        # VPS configuration - matches your current setup
        self.vps_endpoints = self.load_vps_config()
        
        # Initialize database or fallback
        if self.use_database:
            logger.info("[DB] Initializing PostgreSQL database...")
            self.init_database()
        else:
            logger.info("[DB] No DATABASE_URL found, using JSON fallback...")
            self.fallback_to_json()
    
    def load_vps_config(self) -> Dict:
        """Load VPS configuration from environment variables"""
        return {
            "vps_1": {
                "endpoint": os.environ.get('VPS_1_ENDPOINT', 'http://213.170.133.116:8080'),
                "name": os.environ.get('VPS_1_NAME', 'primary_vps'),
                "ips": ["213.170.133.116"]
            }
        }
    
    def init_database(self):
        """Initialize PostgreSQL database with complete schema"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Main orders table
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
                    user_fingerprint VARCHAR(64),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # VPS status tracking table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS vps_status (
                    vps_name VARCHAR(50) NOT NULL,
                    ip_address VARCHAR(45) NOT NULL,
                    tier VARCHAR(20) NOT NULL,
                    available_configs INTEGER DEFAULT 0,
                    total_configs INTEGER DEFAULT 0,
                    last_generated TIMESTAMP,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (vps_name, ip_address, tier)
                );
            """)
            
            # Active timers for expiration tracking
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS active_timers (
                    timer_id VARCHAR(50) PRIMARY KEY,
                    order_id VARCHAR(36) NOT NULL,
                    order_number VARCHAR(20) NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    vps_notified BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (order_id) REFERENCES vpn_orders(order_id) ON DELETE CASCADE
                );
            """)
            
            # Performance indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_expires ON vpn_orders (expires_at) WHERE expires_at IS NOT NULL;")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON vpn_orders (status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_tier ON vpn_orders (tier);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_stripe ON vpn_orders (stripe_session_id) WHERE stripe_session_id IS NOT NULL;")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_timers_expires ON active_timers (expires_at);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_vps_status_updated ON vps_status (last_updated);")
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info("[DB] ✅ PostgreSQL database initialized successfully")
            
        except Exception as e:
            logger.error(f"[DB] ❌ Database initialization failed: {e}")
            self.use_database = False
            self.fallback_to_json()
    
    def get_connection(self):
        """Get PostgreSQL database connection"""
        if not self.database_url:
            raise Exception("DATABASE_URL not configured")
        return psycopg2.connect(self.database_url, sslmode='require')
    
    # === CORE VPN SLOT MANAGEMENT ===
    
    def assign_vpn_slot(self, tier: str, ip_address: str, vps_name: str = "vps_1", 
                       stripe_session_id: str = None, user_fingerprint: str = None) -> Optional[Tuple[str, str]]:
        """
        Assign VPN slot to customer with complete tracking
        Returns: (order_id, order_number) or None if failed
        """
        if tier not in self.service_tiers:
            logger.error(f"[ASSIGN] Invalid tier: {tier}")
            return None
        
        if self.use_database:
            return self._assign_database_slot(tier, ip_address, vps_name, stripe_session_id, user_fingerprint)
        else:
            return self._assign_fallback_slot(tier, ip_address, vps_name, stripe_session_id, user_fingerprint)
    
    def _assign_database_slot(self, tier: str, ip_address: str, vps_name: str, 
                            stripe_session_id: str, user_fingerprint: str) -> Optional[Tuple[str, str]]:
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
            """, (order_id, order_number, tier, duration_days, ip_address, 
                  vps_name, price_cents, now, expires_at, stripe_session_id, user_fingerprint))
            
            # Create expiration timer
            timer_id = f"{order_id}_{order_number}"
            cursor.execute("""
                INSERT INTO active_timers (timer_id, order_id, order_number, expires_at)
                VALUES (%s, %s, %s, %s)
            """, (timer_id, order_id, order_number, expires_at))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            # Notify VPS to start expiration timer
            duration_seconds = 900 if tier == 'test' else duration_days * 24 * 3600
            self.notify_vps_start_timer(vps_name, order_number, order_id, tier, ip_address, duration_seconds)
            
            logger.info(f"[ASSIGN] ✅ {tier} slot {order_number} assigned to {ip_address}")
            return order_id, order_number
            
        except Exception as e:
            logger.error(f"[ASSIGN] ❌ Database error: {e}")
            return None
    
    def generate_order_number(self, tier: str) -> str:
        """Generate order number with tier-specific prefix"""
        tier_config = self.service_tiers.get(tier, {})
        prefix = tier_config.get('order_prefix', '42')
        return f"{prefix}{str(uuid.uuid4()).replace('-', '')[:6].upper()}"
    
    def notify_vps_start_timer(self, vps_name: str, order_number: str, order_id: str, 
                              tier: str, ip_address: str, duration_seconds: int):
        """Notify VPS to start expiration timer for config"""
        try:
            vps_config = self.vps_endpoints.get(vps_name)
            if not vps_config:
                logger.warning(f"[VPS] VPS config not found: {vps_name}")
                return
            
            endpoint = f"{vps_config['endpoint']}/api/start-timer"
            
            payload = {
                "order_number": order_number,
                "tier": tier,
                "ip_address": ip_address,
                "duration_seconds": duration_seconds
            }
            
            response = requests.post(endpoint, json=payload, timeout=10)
            
            if response.status_code == 200:
                logger.info(f"[VPS] ✅ Timer started for {order_number} on {vps_name}")
                
                # Mark timer as notified in database
                if self.use_database:
                    try:
                        conn = self.get_connection()
                        cursor = conn.cursor()
                        cursor.execute("""
                            UPDATE active_timers SET vps_notified = TRUE 
                            WHERE order_id = %s
                        """, (order_id,))
                        conn.commit()
                        cursor.close()
                        conn.close()
                    except Exception as db_e:
                        logger.warning(f"[VPS] Failed to mark timer as notified: {db_e}")
            else:
                logger.warning(f"[VPS] ⚠️ Timer notification failed: HTTP {response.status_code}")
                
        except Exception as e:
            logger.warning(f"[VPS] ⚠️ Timer notification error: {e}")
    
    # === ORDER MANAGEMENT ===
    
    def get_order_status(self, order_number: str) -> Optional[Dict]:
        """Get detailed order status by order number"""
        if self.use_database:
            try:
                conn = self.get_connection()
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("""
                    SELECT o.*, t.timer_id, t.vps_notified
                    FROM vpn_orders o
                    LEFT JOIN active_timers t ON o.order_id = t.order_id
                    WHERE o.order_number = %s
                """, (order_number,))
                
                result = cursor.fetchone()
                cursor.close()
                conn.close()
                
                if result:
                    order_data = dict(result)
                    # Add tier information
                    tier_config = self.service_tiers.get(order_data['tier'], {})
                    order_data['tier_info'] = tier_config
                    return order_data
                
                return None
                
            except Exception as e:
                logger.error(f"[ORDER] ❌ Error getting order status: {e}")
                return None
        else:
            return self._get_fallback_order_status(order_number)
    
    def find_order_by_stripe_session(self, stripe_session_id: str) -> Optional[Dict]:
        """Find order by Stripe session ID (prevents duplicate payments)"""
        if not self.use_database:
            return None
            
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT * FROM vpn_orders 
                WHERE stripe_session_id = %s
            """, (stripe_session_id,))
            
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            
            return dict(result) if result else None
            
        except Exception as e:
            logger.error(f"[ORDER] ❌ Error finding order by Stripe session: {e}")
            return None
    
    def cleanup_expired_orders(self) -> int:
        """Clean up expired orders and notify VPS"""
        if not self.use_database:
            return self._cleanup_fallback_orders()
            
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Get expired orders
            cursor.execute("""
                SELECT order_id, order_number, vps_name, tier
                FROM vpn_orders 
                WHERE status = 'active' AND expires_at < CURRENT_TIMESTAMP
            """)
            expired_orders = cursor.fetchall()
            
            if expired_orders:
                # Update status to expired
                cursor.execute("""
                    UPDATE vpn_orders 
                    SET status = 'expired', updated_at = CURRENT_TIMESTAMP
                    WHERE status = 'active' AND expires_at < CURRENT_TIMESTAMP
                """)
                
                # Remove expired timers
                cursor.execute("""
                    DELETE FROM active_timers 
                    WHERE expires_at < CURRENT_TIMESTAMP
                """)
                
                conn.commit()
                
                # Notify VPS for cleanup (optional, VPS handles this automatically)
                unique_vps = set(order[2] for order in expired_orders)
                for vps_name in unique_vps:
                    self.notify_vps_cleanup(vps_name)
                
                logger.info(f"[CLEANUP] ✅ Expired {len(expired_orders)} orders")
            
            cursor.close()
            conn.close()
            return len(expired_orders)
            
        except Exception as e:
            logger.error(f"[CLEANUP] ❌ Error cleaning up orders: {e}")
            return 0
    
    def notify_vps_cleanup(self, vps_name: str):
        """Notify VPS to perform cleanup (optional, for immediate cleanup)"""
        try:
            vps_config = self.vps_endpoints.get(vps_name)
            if not vps_config:
                return
                
            endpoint = f"{vps_config['endpoint']}/api/cleanup"
            response = requests.post(endpoint, timeout=10)
            
            if response.status_code == 200:
                logger.info(f"[VPS] ✅ Cleanup requested for {vps_name}")
                
        except Exception as e:
            logger.debug(f"[VPS] Cleanup notification failed (not critical): {e}")
    
    # === VPS STATUS AND MONITORING ===
    
    def get_vps_status_report(self) -> Dict:
        """Get comprehensive status from all VPS servers"""
        report = {
            "timestamp": datetime.now().isoformat(),
            "vps_status": {},
            "summary": {
                "total_vps": len(self.vps_endpoints),
                "active_orders": 0,
                "revenue_potential": 0
            }
        }
        
        for vps_name, vps_config in self.vps_endpoints.items():
            try:
                endpoint = f"{vps_config['endpoint']}/api/status"
                response = requests.get(endpoint, timeout=10)
                
                if response.status_code == 200:
                    vps_data = response.json()
                    report["vps_status"][vps_name] = vps_data
                    
                    # Update local cache
                    self._update_vps_status_cache(vps_name, vps_data)
                    
                    # Update summary
                    if "summary" in vps_data:
                        vps_summary = vps_data["summary"]
                        report["summary"]["revenue_potential"] += vps_summary.get("revenue_potential_cents", 0)
                        
                else:
                    report["vps_status"][vps_name] = {
                        "error": f"HTTP {response.status_code}",
                        "available": False
                    }
                    
            except Exception as e:
                report["vps_status"][vps_name] = {
                    "error": str(e),
                    "available": False
                }
        
        # Add database statistics
        if self.use_database:
            db_summary = self._get_database_summary()
            report["summary"].update(db_summary)
        
        return report
    
    def _update_vps_status_cache(self, vps_name: str, vps_data: Dict):
        """Update VPS status cache in database"""
        if not self.use_database:
            return
            
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Extract tier information from VPS response
            tiers_data = vps_data.get("tiers", {})
            
            for tier, tier_data in tiers_data.items():
                # Get the first IP for this VPS
                ip_address = self.vps_endpoints[vps_name]["ips"][0] if self.vps_endpoints[vps_name]["ips"] else "unknown"
                
                available_configs = tier_data.get("available", 0)
                total_configs = tier_data.get("capacity", 0)
                
                cursor.execute("""
                    INSERT INTO vps_status 
                    (vps_name, ip_address, tier, available_configs, total_configs, last_updated)
                    VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (vps_name, ip_address, tier)
                    DO UPDATE SET
                        available_configs = EXCLUDED.available_configs,
                        total_configs = EXCLUDED.total_configs,
                        last_updated = CURRENT_TIMESTAMP
                """, (vps_name, ip_address, tier, available_configs, total_configs))
            
            conn.commit()
            cursor.close()
            conn.close()
            
        except Exception as e:
            logger.debug(f"[CACHE] Failed to update VPS status cache: {e}")
    
    def _get_database_summary(self) -> Dict:
        """Get summary statistics from database"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Active orders count
            cursor.execute("SELECT COUNT(*) FROM vpn_orders WHERE status = 'active'")
            active_orders = cursor.fetchone()[0]
            
            # Orders by tier
            cursor.execute("""
                SELECT tier, COUNT(*) 
                FROM vpn_orders 
                WHERE status = 'active' 
                GROUP BY tier
            """)
            tier_counts = dict(cursor.fetchall())
            
            # Revenue calculation
            cursor.execute("""
                SELECT SUM(price_cents) 
                FROM vpn_orders 
                WHERE status = 'active' AND tier != 'test'
            """)
            current_revenue = cursor.fetchone()[0] or 0
            
            # Pending timers
            cursor.execute("SELECT COUNT(*) FROM active_timers")
            pending_timers = cursor.fetchone()[0]
            
            cursor.close()
            conn.close()
            
            return {
                "active_orders": active_orders,
                "tier_counts": tier_counts,
                "current_revenue_cents": current_revenue,
                "pending_timers": pending_timers
            }
            
        except Exception as e:
            logger.error(f"[SUMMARY] ❌ Error getting database summary: {e}")
            return {}
    
    def get_available_ips_for_tier(self, tier: str) -> List[Dict]:
        """Get available IPs for a specific tier"""
        available_ips = []
        
        try:
            # Get latest VPS status
            vps_report = self.get_vps_status_report()
            
            for vps_name, vps_data in vps_report["vps_status"].items():
                if vps_data.get("available", True) and "tiers" in vps_data:
                    tier_data = vps_data["tiers"].get(tier, {})
                    available_slots = tier_data.get("available", 0)
                    
                    if available_slots > 0:
                        # Use the configured IPs for this VPS
                        for ip_address in self.vps_endpoints[vps_name]["ips"]:
                            available_ips.append({
                                "ip_address": ip_address,
                                "vps_name": vps_name,
                                "available_slots": available_slots,
                                "tier_info": tier_data
                            })
            
            # Sort by available slots (descending)
            available_ips.sort(key=lambda x: x["available_slots"], reverse=True)
            
        except Exception as e:
            logger.error(f"[AVAILABILITY] ❌ Error getting available IPs: {e}")
        
        return available_ips
    
    # === ADMIN AND UTILITIES ===
    
    def get_service_tiers(self) -> Dict:
        """Get all service tier configurations"""
        return self.service_tiers
    
    def get_tier_config(self, tier: str) -> Optional[Dict]:
        """Get configuration for specific tier"""
        return self.service_tiers.get(tier)
    
    def force_database_reset(self, reset_type: str = "clear_assignments"):
        """Force database reset (ADMIN ONLY - DANGEROUS)"""
        if not self.use_database:
            logger.warning("[RESET] Database not available for reset")
            return False
            
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            if reset_type == "full_reset":
                # NUCLEAR: Drop all tables
                cursor.execute("DROP TABLE IF EXISTS active_timers CASCADE;")
                cursor.execute("DROP TABLE IF EXISTS vps_status CASCADE;")
                cursor.execute("DROP TABLE IF EXISTS vpn_orders CASCADE;")
                
                # Recreate schema
                self.init_database()
                
            elif reset_type == "clear_assignments":
                # Clear all assignments but keep structure
                cursor.execute("DELETE FROM active_timers;")
                cursor.execute("UPDATE vpn_orders SET status = 'expired' WHERE status = 'active';")
                
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info(f"[RESET] ✅ Database reset completed: {reset_type}")
            return True
            
        except Exception as e:
            logger.error(f"[RESET] ❌ Database reset failed: {e}")
            return False
    
    # === FALLBACK METHODS (JSON) ===
    
    def fallback_to_json(self):
        """Initialize JSON fallback system"""
        self.slots_file = 'enhanced_slots.json'
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
            "active_timers": {},
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
    
    def _assign_fallback_slot(self, tier: str, ip_address: str, vps_name: str, 
                            stripe_session_id: str, user_fingerprint: str) -> Optional[Tuple[str, str]]:
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
                "ip_address": ip_address,
                "vps_name": vps_name,
                "price_cents": tier_config['price_cents'],
                "status": "active",
                "assigned_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
                "stripe_session_id": stripe_session_id,
                "user_fingerprint": user_fingerprint
            }
            
            # Store timer
            timer_id = f"{order_id}_{order_number}"
            self.fallback_data["active_timers"][timer_id] = {
                "order_id": order_id,
                "order_number": order_number,
                "expires_at": expires_at.isoformat()
            }
            
            self._save_fallback_data()
            
            # Notify VPS
            duration_seconds = 900 if tier == 'test' else duration_days * 24 * 3600
            self.notify_vps_start_timer(vps_name, order_number, order_id, tier, ip_address, duration_seconds)
            
            logger.info(f"[FALLBACK] ✅ {tier} slot {order_number} assigned")
            return order_id, order_number
            
        except Exception as e:
            logger.error(f"[FALLBACK] ❌ Error assigning slot: {e}")
            return None
    
    def _get_fallback_order_status(self, order_number: str) -> Optional[Dict]:
        """Get order status from JSON fallback"""
        for order_data in self.fallback_data.get("orders", {}).values():
            if order_data.get("order_number") == order_number:
                # Add tier information
                tier = order_data.get("tier")
                if tier:
                    order_data['tier_info'] = self.service_tiers.get(tier, {})
                return order_data
        return None
    
    def _cleanup_fallback_orders(self) -> int:
        """Clean up expired orders in JSON fallback"""
        now = datetime.now()
        expired_count = 0
        
        # Clean orders
        for order_id, order_data in list(self.fallback_data.get("orders", {}).items()):
            if order_data.get("status") == "active":
                try:
                    expires_at = datetime.fromisoformat(order_data["expires_at"])
                    if now > expires_at:
                        order_data["status"] = "expired"
                        expired_count += 1
                except Exception:
                    pass
        
        # Clean timers
        for timer_id, timer_data in list(self.fallback_data.get("active_timers", {}).items()):
            try:
                expires_at = datetime.fromisoformat(timer_data["expires_at"])
                if now > expires_at:
                    del self.fallback_data["active_timers"][timer_id]
            except Exception:
                pass
        
        if expired_count > 0:
            self._save_fallback_data()
            logger.info(f"[FALLBACK] ✅ Expired {expired_count} orders")
            
        return expired_count