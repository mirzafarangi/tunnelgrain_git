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

logger = logging.getLogger(__name__)

class EnhancedVPNManager:
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        self.use_database = bool(self.database_url)
        
        if self.use_database:
            logger.info("[DB] Using PostgreSQL database")
            self.init_database()
        else:
            logger.info("[DB] No DATABASE_URL found, using fallback JSON")
            self.fallback_to_json()
            
        # VPS configuration from environment
        self.vps_endpoints = self.load_vps_config()
    
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
        """Initialize PostgreSQL database schema"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Create orders table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS vpn_orders (
                    order_id VARCHAR(20) PRIMARY KEY,
                    order_number VARCHAR(20) UNIQUE NOT NULL,
                    tier VARCHAR(20) NOT NULL,
                    duration_days INTEGER NOT NULL,
                    ip_address VARCHAR(45) NOT NULL,
                    vps_name VARCHAR(50) NOT NULL,
                    status VARCHAR(20) DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    assigned_at TIMESTAMP,
                    expires_at TIMESTAMP,
                    stripe_session_id VARCHAR(200),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # Create indexes for performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_expires ON vpn_orders (expires_at) WHERE expires_at IS NOT NULL;")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON vpn_orders (status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_tier ON vpn_orders (tier);")
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info("[DB] ✅ PostgreSQL database initialized")
            
        except Exception as e:
            logger.error(f"[DB] ❌ Database error: {e}")
            self.use_database = False
            self.fallback_to_json()
    
    def get_connection(self):
        """Get database connection"""
        if not self.database_url:
            raise Exception("DATABASE_URL not configured")
        return psycopg2.connect(self.database_url, sslmode='require')
    
    def assign_vpn_slot(self, tier: str, ip_address: str, vps_name: str = "vps_1", 
                       stripe_session_id: str = None) -> Optional[Tuple[str, str]]:
        """Assign VPN slot for customer"""
        if self.use_database:
            try:
                conn = self.get_connection()
                cursor = conn.cursor()
                
                # Generate IDs
                order_id = str(uuid.uuid4())
                order_number = self.generate_order_number(tier)
                
                # Calculate duration
                duration_days = self.get_tier_duration(tier)
                now = datetime.now()
                
                if tier == 'test':
                    expires_at = now + timedelta(minutes=15)
                else:
                    expires_at = now + timedelta(days=duration_days)
                
                # Insert order
                cursor.execute("""
                    INSERT INTO vpn_orders 
                    (order_id, order_number, tier, duration_days, ip_address, 
                     vps_name, assigned_at, expires_at, stripe_session_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (order_id, order_number, tier, duration_days, ip_address, 
                      vps_name, now, expires_at, stripe_session_id))
                
                conn.commit()
                cursor.close()
                conn.close()
                
                # Notify VPS
                self.notify_vps_start_timer(vps_name, order_number, tier, ip_address)
                
                logger.info(f"[ASSIGN] ✅ {tier} slot {order_number} assigned")
                return order_id, order_number
                
            except Exception as e:
                logger.error(f"[ASSIGN] ❌ Error: {e}")
                return None
        else:
            return self.assign_fallback_slot(tier, ip_address, vps_name, stripe_session_id)
    
    def get_tier_duration(self, tier: str) -> int:
        """Get duration in days for tier"""
        durations = {
            'test': 0,
            'monthly': 30,
            'quarterly': 90,
            'biannual': 180,
            'annual': 365,
            'lifetime': 36500
        }
        return durations.get(tier, 30)
    
    def generate_order_number(self, tier: str) -> str:
        """Generate order number based on tier"""
        prefix = "72" if tier == 'test' else "42"
        return f"{prefix}{str(uuid.uuid4()).replace('-', '')[:6].upper()}"
    
    def notify_vps_start_timer(self, vps_name: str, order_number: str, tier: str, ip_address: str):
        """Notify VPS to start expiration timer"""
        try:
            vps_config = self.vps_endpoints.get(vps_name)
            if not vps_config:
                return
                
            endpoint = f"{vps_config['endpoint']}/api/start-timer"
            payload = {
                "order_number": order_number,
                "tier": tier,
                "ip_address": ip_address,
                "duration_seconds": 900 if tier == 'test' else self.get_tier_duration(tier) * 24 * 3600
            }
            
            response = requests.post(endpoint, json=payload, timeout=10)
            if response.status_code == 200:
                logger.info(f"[VPS] ✅ Timer started for {order_number}")
            
        except Exception as e:
            logger.warning(f"[VPS] ⚠️ Notification failed: {e}")
    
    def get_order_status(self, order_number: str) -> Optional[Dict]:
        """Get order status"""
        if self.use_database:
            try:
                conn = self.get_connection()
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("SELECT * FROM vpn_orders WHERE order_number = %s", (order_number,))
                result = cursor.fetchone()
                cursor.close()
                conn.close()
                return dict(result) if result else None
            except Exception as e:
                logger.error(f"[ORDER] ❌ Error: {e}")
                return None
        else:
            return self.get_fallback_order_status(order_number)
    
    def cleanup_expired_orders(self) -> int:
        """Clean up expired orders"""
        if not self.use_database:
            return 0
            
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Count expired orders
            cursor.execute("""
                SELECT COUNT(*) FROM vpn_orders 
                WHERE status = 'active' AND expires_at < CURRENT_TIMESTAMP
            """)
            expired_count = cursor.fetchone()[0]
            
            if expired_count > 0:
                # Update to expired status
                cursor.execute("""
                    UPDATE vpn_orders 
                    SET status = 'expired', updated_at = CURRENT_TIMESTAMP
                    WHERE status = 'active' AND expires_at < CURRENT_TIMESTAMP
                """)
                conn.commit()
                logger.info(f"[CLEANUP] ✅ Expired {expired_count} orders")
            
            cursor.close()
            conn.close()
            return expired_count
            
        except Exception as e:
            logger.error(f"[CLEANUP] ❌ Error: {e}")
            return 0
    
    def get_vps_status_report(self) -> Dict:
        """Get status report from all VPS"""
        report = {
            "timestamp": datetime.now().isoformat(),
            "vps_status": {}
        }
        
        for vps_name, vps_config in self.vps_endpoints.items():
            try:
                endpoint = f"{vps_config['endpoint']}/api/status"
                response = requests.get(endpoint, timeout=10)
                
                if response.status_code == 200:
                    report["vps_status"][vps_name] = response.json()
                else:
                    report["vps_status"][vps_name] = {"error": f"HTTP {response.status_code}"}
                    
            except Exception as e:
                report["vps_status"][vps_name] = {"error": str(e)}
        
        return report
    
    def get_available_ips_for_tier(self, tier: str) -> List[Dict]:
        """Get available IPs for a tier"""
        try:
            vps_report = self.get_vps_status_report()
            available_ips = []
            
            for vps_name, vps_data in vps_report["vps_status"].items():
                if "error" not in vps_data and "tiers" in vps_data:
                    tier_data = vps_data["tiers"].get(tier, {})
                    if tier_data.get("available", 0) > 0:
                        for ip in self.vps_endpoints[vps_name]["ips"]:
                            available_ips.append({
                                "ip_address": ip,
                                "vps_name": vps_name,
                                "available_slots": tier_data["available"]
                            })
            
            return available_ips
            
        except Exception as e:
            logger.error(f"[AVAILABILITY] ❌ Error: {e}")
            return []
    
    # Fallback JSON methods (for when database is unavailable)
    def fallback_to_json(self):
        self.slots_file = 'enhanced_slots.json'
        self.load_fallback_data()
    
    def load_fallback_data(self):
        if os.path.exists(self.slots_file):
            try:
                with open(self.slots_file, 'r') as f:
                    self.fallback_data = json.load(f)
            except Exception as e:
                logger.error(f"[FALLBACK] Error loading: {e}")
                self.create_fallback_data()
        else:
            self.create_fallback_data()
    
    def create_fallback_data(self):
        self.fallback_data = {"orders": {}, "last_cleanup": datetime.now().isoformat()}
        self.save_fallback_data()
    
    def save_fallback_data(self):
        try:
            with open(self.slots_file, 'w') as f:
                json.dump(self.fallback_data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"[FALLBACK] Save error: {e}")
    
    def assign_fallback_slot(self, tier: str, ip_address: str, vps_name: str, stripe_session_id: str):
        order_id = str(uuid.uuid4())
        order_number = self.generate_order_number(tier)
        
        now = datetime.now()
        if tier == 'test':
            expires_at = now + timedelta(minutes=15)
        else:
            expires_at = now + timedelta(days=self.get_tier_duration(tier))
        
        self.fallback_data["orders"][order_id] = {
            "order_number": order_number,
            "tier": tier,
            "ip_address": ip_address,
            "vps_name": vps_name,
            "status": "active",
            "assigned_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "stripe_session_id": stripe_session_id
        }
        
        self.save_fallback_data()
        self.notify_vps_start_timer(vps_name, order_number, tier, ip_address)
        
        return order_id, order_number
    
    def get_fallback_order_status(self, order_number: str):
        for order_data in self.fallback_data.get("orders", {}).values():
            if order_data.get("order_number") == order_number:
                return order_data
        return None
