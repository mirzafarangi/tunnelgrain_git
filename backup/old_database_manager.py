import os
import json
import psycopg2
import requests
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import uuid
import logging

logger = logging.getLogger(__name__)

class EnhancedVPNManager:
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        self.use_database = bool(self.database_url)
        
        if self.use_database:
            logger.info("[DB] Initializing PostgreSQL database...")
            self.init_database()
        else:
            logger.info("[DB] No DATABASE_URL found, using fallback JSON file...")
            self.fallback_to_json()
            
        # VPS configuration
        self.vps_endpoints = self.load_vps_config()
    
    def load_vps_config(self) -> Dict:
        """Load VPS configuration from environment or config file"""
        # Default configuration - can be loaded from env vars or config file
        return {
            "vps_1": {
                "endpoint": "http://213.170.133.116:8080",
                "ips": ["213.170.133.116"],
                "name": "primary_vps"
            }
            # Add more VPS configurations as needed
        }
    
    def init_database(self):
        """Initialize enhanced PostgreSQL database schema"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Create main orders table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS vpn_orders (
                    order_id VARCHAR(20) PRIMARY KEY,
                    order_number VARCHAR(20) UNIQUE NOT NULL,
                    slot_type VARCHAR(20) NOT NULL,
                    duration_days INTEGER NOT NULL,
                    ip_address VARCHAR(45) NOT NULL,
                    vps_name VARCHAR(50) NOT NULL,
                    status VARCHAR(20) DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    assigned_at TIMESTAMP,
                    expires_at TIMESTAMP,
                    stripe_session_id VARCHAR(200),
                    user_fingerprint VARCHAR(64),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # Create VPS status tracking table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS vps_status (
                    vps_name VARCHAR(50) NOT NULL,
                    ip_address VARCHAR(45) NOT NULL,
                    category VARCHAR(20) NOT NULL,
                    in_production INTEGER DEFAULT 0,
                    archived INTEGER DEFAULT 0,
                    last_generated TIMESTAMP,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (vps_name, ip_address, category)
                );
            """)
            
            # Create expiration tracking table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS active_timers (
                    timer_id VARCHAR(50) PRIMARY KEY,
                    order_id VARCHAR(20) NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    vps_notified BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (order_id) REFERENCES vpn_orders(order_id)
                );
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_expires ON vpn_orders (expires_at) WHERE expires_at IS NOT NULL;")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON vpn_orders (status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_timers_expires ON active_timers (expires_at);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_vps_status_updated ON vps_status (last_updated);")
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info("[DB] ✅ Enhanced database initialized successfully")
            
        except Exception as e:
            logger.error(f"[DB] ❌ Database initialization error: {e}")
            self.use_database = False
            self.fallback_to_json()
    
    def get_connection(self):
        """Get database connection"""
        if not self.database_url:
            raise Exception("DATABASE_URL not configured")
        return psycopg2.connect(self.database_url, sslmode='require')
    
    def assign_vpn_slot(self, slot_type: str, duration_days: int, ip_address: str, 
                       vps_name: str, stripe_session_id: str = None) -> Optional[Tuple[str, str]]:
        """Assign a VPN slot with enhanced tracking"""
        if self.use_database:
            try:
                conn = self.get_connection()
                cursor = conn.cursor()
                
                # Generate unique identifiers
                order_id = str(uuid.uuid4())
                order_number = self.generate_order_number(slot_type)
                
                # Calculate expiration
                now = datetime.now()
                if slot_type == 'test':
                    expires_at = now + timedelta(minutes=15)
                else:
                    expires_at = now + timedelta(days=duration_days)
                
                # Insert order record
                cursor.execute("""
                    INSERT INTO vpn_orders 
                    (order_id, order_number, slot_type, duration_days, ip_address, 
                     vps_name, assigned_at, expires_at, stripe_session_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (order_id, order_number, slot_type, duration_days, ip_address, 
                      vps_name, now, expires_at, stripe_session_id))
                
                # Create expiration timer
                timer_id = f"{order_id}_{order_number}"
                cursor.execute("""
                    INSERT INTO active_timers (timer_id, order_id, expires_at)
                    VALUES (%s, %s, %s)
                """, (timer_id, order_id, expires_at))
                
                conn.commit()
                cursor.close()
                conn.close()
                
                # Notify VPS to start timer
                self.notify_vps_start_timer(vps_name, order_number, order_id, slot_type, 
                                          ip_address, duration_days * 24 * 3600 if slot_type != 'test' else 900)
                
                logger.info(f"[ASSIGN] ✅ Assigned {slot_type} slot: {order_number} on {ip_address}")
                return order_id, order_number
                
            except Exception as e:
                logger.error(f"[ASSIGN] ❌ Error assigning slot: {e}")
                return None
        else:
            return self.assign_fallback_slot(slot_type, duration_days, ip_address, vps_name, stripe_session_id)
    
    def notify_vps_start_timer(self, vps_name: str, order_number: str, order_id: str, 
                              slot_type: str, ip_address: str, duration_seconds: int):
        """Notify VPS to start expiration timer"""
        try:
            vps_config = self.vps_endpoints.get(vps_name)
            if not vps_config:
                logger.error(f"VPS config not found for: {vps_name}")
                return
                
            endpoint = f"{vps_config['endpoint']}/start-expiration-timer"
            payload = {
                "order_id": order_number,
                "slot_id": order_id,
                "config_type": slot_type,
                "ip_address": ip_address,
                "duration_seconds": duration_seconds
            }
            
            response = requests.post(endpoint, json=payload, timeout=10)
            if response.status_code == 200:
                logger.info(f"[VPS] ✅ Timer started on {vps_name} for {order_number}")
                
                # Update timer as notified
                if self.use_database:
                    conn = self.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE active_timers SET vps_notified = TRUE 
                        WHERE order_id = %s
                    """, (order_id,))
                    conn.commit()
                    cursor.close()
                    conn.close()
            else:
                logger.error(f"[VPS] ❌ Failed to notify {vps_name}: {response.status_code}")
                
        except Exception as e:
            logger.error(f"[VPS] ❌ Error notifying VPS: {e}")
    
    def generate_order_number(self, slot_type: str) -> str:
        """Generate order number based on slot type"""
        if slot_type == 'test':
            prefix = "72"
        else:
            prefix = "42"
        return f"{prefix}{str(uuid.uuid4()).replace('-', '')[:6].upper()}"
    
    def get_order_status(self, order_number: str) -> Optional[Dict]:
        """Get status of an order"""
        if self.use_database:
            try:
                conn = self.get_connection()
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("""
                    SELECT o.*, t.expires_at as timer_expires 
                    FROM vpn_orders o
                    LEFT JOIN active_timers t ON o.order_id = t.order_id
                    WHERE o.order_number = %s
                """, (order_number,))
                
                result = cursor.fetchone()
                cursor.close()
                conn.close()
                
                if result:
                    return dict(result)
                return None
                
            except Exception as e:
                logger.error(f"[ORDER] ❌ Error getting order status: {e}")
                return None
        else:
            return self.get_fallback_order_status(order_number)
    
    def cleanup_expired_orders(self) -> int:
        """Clean up expired orders and sync with VPS"""
        if not self.use_database:
            return self.cleanup_fallback_orders()
            
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Find expired orders
            cursor.execute("""
                SELECT order_id, order_number, vps_name 
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
                
                # Notify VPS for cleanup
                for order_id, order_number, vps_name in expired_orders:
                    self.notify_vps_cleanup(vps_name)
                
                logger.info(f"[CLEANUP] ✅ Expired {len(expired_orders)} orders")
            
            cursor.close()
            conn.close()
            return len(expired_orders)
            
        except Exception as e:
            logger.error(f"[CLEANUP] ❌ Error cleaning up: {e}")
            return 0
    
    def notify_vps_cleanup(self, vps_name: str):
        """Notify VPS to perform cleanup"""
        try:
            vps_config = self.vps_endpoints.get(vps_name)
            if not vps_config:
                return
                
            endpoint = f"{vps_config['endpoint']}/force-cleanup"
            response = requests.post(endpoint, timeout=10)
            
            if response.status_code == 200:
                logger.info(f"[VPS] ✅ Cleanup requested for {vps_name}")
            else:
                logger.error(f"[VPS] ❌ Cleanup failed for {vps_name}: {response.status_code}")
                
        except Exception as e:
            logger.error(f"[VPS] ❌ Error requesting cleanup: {e}")
    
    def get_vps_status_report(self) -> Dict:
        """Get comprehensive status from all VPS"""
        report = {
            "timestamp": datetime.now().isoformat(),
            "vps_status": {},
            "summary": {
                "total_ips": 0,
                "active_orders": 0,
                "available_slots": {}
            }
        }
        
        for vps_name, vps_config in self.vps_endpoints.items():
            try:
                endpoint = f"{vps_config['endpoint']}/status"
                response = requests.get(endpoint, timeout=10)
                
                if response.status_code == 200:
                    vps_status = response.json()
                    report["vps_status"][vps_name] = vps_status
                    
                    # Update our database with latest VPS status
                    self.update_vps_status_cache(vps_name, vps_status)
                    
                    # Update summary
                    if "ips" in vps_status:
                        report["summary"]["total_ips"] += len(vps_status["ips"])
                        
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
            report["summary"].update(self.get_database_summary())
        
        return report
    
    def update_vps_status_cache(self, vps_name: str, vps_status: Dict):
        """Update VPS status cache in database"""
        if not self.use_database:
            return
            
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            for ip_address, ip_data in vps_status.get("ips", {}).items():
                for category, cat_data in ip_data.get("categories", {}).items():
                    cursor.execute("""
                        INSERT INTO vps_status 
                        (vps_name, ip_address, category, in_production, archived, last_generated, last_updated)
                        VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (vps_name, ip_address, category)
                        DO UPDATE SET
                            in_production = EXCLUDED.in_production,
                            archived = EXCLUDED.archived,
                            last_generated = EXCLUDED.last_generated,
                            last_updated = CURRENT_TIMESTAMP
                    """, (
                        vps_name, ip_address, category,
                        cat_data.get("in_production", 0),
                        cat_data.get("archived", 0),
                        datetime.fromisoformat(cat_data.get("last_generated", "1970-01-01T00:00:00")) 
                        if cat_data.get("last_generated") != "never" else None
                    ))
            
            conn.commit()
            cursor.close()
            conn.close()
            
        except Exception as e:
            logger.error(f"[CACHE] ❌ Error updating VPS status cache: {e}")
    
    def get_database_summary(self) -> Dict:
        """Get summary statistics from database"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Count active orders
            cursor.execute("SELECT COUNT(*) FROM vpn_orders WHERE status = 'active'")
            active_orders = cursor.fetchone()[0]
            
            # Count by slot type
            cursor.execute("""
                SELECT slot_type, COUNT(*) 
                FROM vpn_orders 
                WHERE status = 'active' 
                GROUP BY slot_type
            """)
            slot_counts = dict(cursor.fetchall())
            
            # Count pending timers
            cursor.execute("SELECT COUNT(*) FROM active_timers")
            pending_timers = cursor.fetchone()[0]
            
            cursor.close()
            conn.close()
            
            return {
                "active_orders": active_orders,
                "slot_counts": slot_counts,
                "pending_timers": pending_timers
            }
            
        except Exception as e:
            logger.error(f"[SUMMARY] ❌ Error getting database summary: {e}")
            return {}
    
    def get_available_ips_for_slot_type(self, slot_type: str) -> List[Dict]:
        """Get available IPs for a specific slot type"""
        available_ips = []
        
        try:
            # Get latest VPS status
            vps_report = self.get_vps_status_report()
            
            for vps_name, vps_status in vps_report["vps_status"].items():
                if not vps_status.get("available", True):
                    continue
                    
                for ip_address, ip_data in vps_status.get("ips", {}).items():
                    category_data = ip_data.get("categories", {}).get(slot_type, {})
                    in_production = category_data.get("in_production", 0)
                    
                    # Consider IP available if it has configs in production
                    if in_production > 0:
                        available_ips.append({
                            "ip_address": ip_address,
                            "vps_name": vps_name,
                            "available_slots": in_production,
                            "last_generated": category_data.get("last_generated", "never")
                        })
            
            # Sort by available slots (descending)
            available_ips.sort(key=lambda x: x["available_slots"], reverse=True)
            
        except Exception as e:
            logger.error(f"[AVAILABILITY] ❌ Error getting available IPs: {e}")
        
        return available_ips
    
    def request_config_regeneration(self, vps_name: str, ip_address: str, category: str) -> bool:
        """Request config regeneration from VPS"""
        try:
            vps_config = self.vps_endpoints.get(vps_name)
            if not vps_config:
                return False
                
            endpoint = f"{vps_config['endpoint']}/regenerate"
            payload = {
                "ip_address": ip_address,
                "category": category,
                "count": self.get_regeneration_count(category)
            }
            
            response = requests.post(endpoint, json=payload, timeout=30)
            
            if response.status_code == 200:
                logger.info(f"[REGEN] ✅ Requested regeneration for {vps_name}/{ip_address}/{category}")
                return True
            else:
                logger.error(f"[REGEN] ❌ Regeneration failed: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"[REGEN] ❌ Error requesting regeneration: {e}")
            return False
    
    def get_regeneration_count(self, category: str) -> int:
        """Get the number of configs to generate for each category"""
        regeneration_counts = {
            "test": 100,
            "monthly": 80,
            "3_months": 50,
            "6_months": 40,
            "12_months": 20,
            "lifetime": 10
        }
        return regeneration_counts.get(category, 50)
    
    # Fallback methods for when database is not available
    def fallback_to_json(self):
        """Initialize fallback JSON file system"""
        self.slots_file = 'enhanced_slots.json'
        self.load_fallback_data()
    
    def load_fallback_data(self):
        """Load data from JSON file (fallback)"""
        if os.path.exists(self.slots_file):
            try:
                with open(self.slots_file, 'r') as f:
                    self.fallback_data = json.load(f)
                logger.info(f"[FALLBACK] Loaded data from {self.slots_file}")
            except Exception as e:
                logger.error(f"[FALLBACK] Error loading data file: {e}")
                self.create_initial_fallback_data()
        else:
            logger.info(f"[FALLBACK] Creating initial {self.slots_file}")
            self.create_initial_fallback_data()
    
    def create_initial_fallback_data(self):
        """Create initial fallback data structure"""
        self.fallback_data = {
            "orders": {},
            "vps_status": {},
            "active_timers": {}
        }
        self.save_fallback_data()
    
    def save_fallback_data(self):
        """Save data to JSON file (fallback)"""
        try:
            with open(self.slots_file, 'w') as f:
                json.dump(self.fallback_data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"[FALLBACK] Error saving data: {e}")
    
    def assign_fallback_slot(self, slot_type: str, duration_days: int, ip_address: str, 
                           vps_name: str, stripe_session_id: str = None) -> Optional[Tuple[str, str]]:
        """Fallback slot assignment using JSON"""
        try:
            order_id = str(uuid.uuid4())
            order_number = self.generate_order_number(slot_type)
            
            now = datetime.now()
            if slot_type == 'test':
                expires_at = now + timedelta(minutes=15)
            else:
                expires_at = now + timedelta(days=duration_days)
            
            # Store order
            self.fallback_data["orders"][order_id] = {
                "order_number": order_number,
                "slot_type": slot_type,
                "duration_days": duration_days,
                "ip_address": ip_address,
                "vps_name": vps_name,
                "status": "active",
                "created_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
                "stripe_session_id": stripe_session_id
            }
            
            # Store timer
            self.fallback_data["active_timers"][f"{order_id}_{order_number}"] = {
                "order_id": order_id,
                "expires_at": expires_at.isoformat()
            }
            
            self.save_fallback_data()
            
            # Notify VPS
            self.notify_vps_start_timer(vps_name, order_number, order_id, slot_type, 
                                      ip_address, duration_days * 24 * 3600 if slot_type != 'test' else 900)
            
            return order_id, order_number
            
        except Exception as e:
            logger.error(f"[FALLBACK] Error assigning slot: {e}")
            return None
    
    def get_fallback_order_status(self, order_number: str) -> Optional[Dict]:
        """Get order status from fallback JSON"""
        for order_id, order_data in self.fallback_data.get("orders", {}).items():
            if order_data.get("order_number") == order_number:
                return order_data
        return None
    
    def cleanup_fallback_orders(self) -> int:
        """Clean up expired orders in fallback mode"""
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
        
        # Clean up expired timers
        for timer_id, timer_data in list(self.fallback_data.get("active_timers", {}).items()):
            try:
                expires_at = datetime.fromisoformat(timer_data["expires_at"])
                if now > expires_at:
                    del self.fallback_data["active_timers"][timer_id]
            except Exception:
                pass
        
        if expired_count > 0:
            self.save_fallback_data()
            
        return expired_count