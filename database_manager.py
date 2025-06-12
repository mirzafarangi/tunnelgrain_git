import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import uuid

class DatabaseSlotManager:
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        self.use_database = bool(self.database_url)
        
        if self.use_database:
            print("[DB] Initializing PostgreSQL database...")
            self.init_database()
        else:
            print("[DB] No DATABASE_URL found, using fallback JSON file...")
            self.fallback_to_json()
    
    def init_database(self):
        """Initialize PostgreSQL database for slot management"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Create slots table if it doesn't exist
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS vpn_slots (
                    slot_id VARCHAR(20) PRIMARY KEY,
                    slot_type VARCHAR(10) NOT NULL,
                    available BOOLEAN DEFAULT TRUE,
                    assigned_at TIMESTAMP,
                    expires_at TIMESTAMP,
                    order_number VARCHAR(20),
                    stripe_session_id VARCHAR(200),
                    auto_managed BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # Create index for faster queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_vpn_slots_type_available 
                ON vpn_slots (slot_type, available);
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_vpn_slots_expires 
                ON vpn_slots (expires_at) WHERE expires_at IS NOT NULL;
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_vpn_slots_order 
                ON vpn_slots (order_number) WHERE order_number IS NOT NULL;
            """)
            
            # Check if slots exist, if not populate initial data
            cursor.execute("SELECT COUNT(*) FROM vpn_slots;")
            count = cursor.fetchone()[0]
            
            if count == 0:
                print("[DB] Populating initial slot configuration...")
                self.populate_initial_slots(cursor)
            else:
                print(f"[DB] Found {count} existing slots in database")
            
            conn.commit()
            cursor.close()
            conn.close()
            
            print("[DB] ✅ Database initialized successfully")
            
        except Exception as e:
            print(f"[DB] ❌ Database initialization error: {e}")
            print("[DB] Falling back to JSON file...")
            self.use_database = False
            self.fallback_to_json()
    
    def populate_initial_slots(self, cursor):
        """Populate database with initial slot configuration"""
        # Monthly slots (client_01 to client_10)
        for i in range(1, 11):
            slot_id = f"client_{i:02d}"
            cursor.execute("""
                INSERT INTO vpn_slots (slot_id, slot_type, available, auto_managed)
                VALUES (%s, %s, %s, %s)
            """, (slot_id, 'monthly', True, True))
        
        # Test slots (test_01 to test_10)
        for i in range(1, 11):
            slot_id = f"test_{i:02d}"
            cursor.execute("""
                INSERT INTO vpn_slots (slot_id, slot_type, available, auto_managed)
                VALUES (%s, %s, %s, %s)
            """, (slot_id, 'test', True, True))
        
        print("[DB] ✅ Populated 20 initial slots (10 monthly + 10 test)")
    
    def get_connection(self):
        """Get database connection"""
        if not self.database_url:
            raise Exception("DATABASE_URL not configured")
        
        return psycopg2.connect(self.database_url, sslmode='require')
    
    def get_slots(self):
        """Get all slots in the format expected by the Flask app"""
        if self.use_database:
            try:
                conn = self.get_connection()
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("SELECT * FROM vpn_slots ORDER BY slot_id;")
                rows = cursor.fetchall()
                cursor.close()
                conn.close()
                
                # Convert to the expected format
                slots = {'monthly': {}, 'test': {}}
                for row in rows:
                    slot_data = {
                        'available': row['available'],
                        'assigned_at': row['assigned_at'].isoformat() if row['assigned_at'] else None,
                        'expires_at': row['expires_at'].isoformat() if row['expires_at'] else None,
                        'order_number': row['order_number'],
                        'slot_type': row['slot_type'],
                        'auto_managed': row['auto_managed'],
                        'stripe_session_id': row.get('stripe_session_id')
                    }
                    slots[row['slot_type']][row['slot_id']] = slot_data
                
                return slots
                
            except Exception as e:
                print(f"[DB] Error fetching slots: {e}")
                return self.get_fallback_slots()
        else:
            return self.get_fallback_slots()
    
    def get_available_slot(self, slot_type='monthly'):
        """Get next available slot"""
        if self.use_database:
            try:
                conn = self.get_connection()
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT slot_id FROM vpn_slots 
                    WHERE slot_type = %s AND available = TRUE 
                    ORDER BY slot_id LIMIT 1
                """, (slot_type,))
                
                result = cursor.fetchone()
                cursor.close()
                conn.close()
                
                return result[0] if result else None
                
            except Exception as e:
                print(f"[DB] Error getting available slot: {e}")
                return None
        else:
            return self.get_fallback_available_slot(slot_type)
    
    def assign_slot(self, slot_type='monthly', duration_days=30, order_number=None, stripe_session_id=None):
        """Assign a slot using database"""
        if self.use_database:
            try:
                conn = self.get_connection()
                cursor = conn.cursor()
                
                # Find available slot
                cursor.execute("""
                    SELECT slot_id FROM vpn_slots 
                    WHERE slot_type = %s AND available = TRUE 
                    ORDER BY slot_id LIMIT 1
                    FOR UPDATE
                """, (slot_type,))
                
                result = cursor.fetchone()
                if not result:
                    cursor.close()
                    conn.close()
                    return None
                
                slot_id = result[0]
                
                # Generate order number if not provided
                if not order_number:
                    order_number = f"42{str(uuid.uuid4()).replace('-', '')[:6].upper()}"
                
                # Calculate expiration
                now = datetime.now()
                if slot_type == 'test':
                    expires_at = now + timedelta(minutes=15)
                else:
                    expires_at = now + timedelta(days=duration_days)
                
                # Update slot
                cursor.execute("""
                    UPDATE vpn_slots 
                    SET available = FALSE, 
                        assigned_at = %s,
                        expires_at = %s,
                        order_number = %s,
                        stripe_session_id = %s,
                        updated_at = %s
                    WHERE slot_id = %s
                """, (now, expires_at, order_number, stripe_session_id, now, slot_id))
                
                conn.commit()
                cursor.close()
                conn.close()
                
                print(f"[DB] ✅ Assigned {slot_type} slot {slot_id}, order: {order_number}, expires: {expires_at}")
                return slot_id, order_number
                
            except Exception as e:
                print(f"[DB] ❌ Error assigning slot: {e}")
                return None
        else:
            return self.assign_fallback_slot(slot_type, duration_days, order_number, stripe_session_id)
    
    def cleanup_expired_slots(self):
        """Clean up expired slots"""
        if self.use_database:
            try:
                conn = self.get_connection()
                cursor = conn.cursor()
                
                # Get expired slots before cleaning
                cursor.execute("""
                    SELECT slot_id, slot_type FROM vpn_slots 
                    WHERE available = FALSE 
                    AND expires_at IS NOT NULL 
                    AND expires_at < CURRENT_TIMESTAMP
                """)
                expired_slots = cursor.fetchall()
                
                # Clean expired slots
                cursor.execute("""
                    UPDATE vpn_slots 
                    SET available = TRUE,
                        assigned_at = NULL,
                        expires_at = NULL,
                        order_number = NULL,
                        stripe_session_id = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE available = FALSE 
                    AND expires_at IS NOT NULL 
                    AND expires_at < CURRENT_TIMESTAMP
                """)
                
                cleaned_count = cursor.rowcount
                conn.commit()
                cursor.close()
                conn.close()
                
                if expired_slots:
                    cleaned_slots = [f"{row[1]}:{row[0]}" for row in expired_slots]
                    print(f"[DB] ✅ Auto-released {cleaned_count} expired slots: {cleaned_slots}")
                    return cleaned_slots
                
                return []
                
            except Exception as e:
                print(f"[DB] ❌ Error cleaning expired slots: {e}")
                return []
        else:
            return self.cleanup_fallback_slots()
    
    def release_slot(self, slot_type, slot_id):
        """Release a slot back to available pool"""
        if self.use_database:
            try:
                conn = self.get_connection()
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE vpn_slots 
                    SET available = TRUE,
                        assigned_at = NULL,
                        expires_at = NULL,
                        order_number = NULL,
                        stripe_session_id = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE slot_id = %s AND slot_type = %s
                """, (slot_id, slot_type))
                
                conn.commit()
                cursor.close()
                conn.close()
                
                print(f"[DB] ✅ Released slot {slot_type}:{slot_id}")
                
            except Exception as e:
                print(f"[DB] ❌ Error releasing slot: {e}")
        else:
            self.release_fallback_slot(slot_type, slot_id)
    
    def find_slot_by_order(self, order_number):
        """Find slot by order number"""
        if self.use_database:
            try:
                conn = self.get_connection()
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("""
                    SELECT * FROM vpn_slots 
                    WHERE order_number = %s
                """, (order_number,))
                
                row = cursor.fetchone()
                cursor.close()
                conn.close()
                
                if row:
                    slot_data = {
                        'available': row['available'],
                        'assigned_at': row['assigned_at'].isoformat() if row['assigned_at'] else None,
                        'expires_at': row['expires_at'].isoformat() if row['expires_at'] else None,
                        'order_number': row['order_number'],
                        'slot_type': row['slot_type'],
                        'auto_managed': row['auto_managed']
                    }
                    return row['slot_type'], row['slot_id'], slot_data
                else:
                    return None, None, None
                    
            except Exception as e:
                print(f"[DB] ❌ Error finding slot by order: {e}")
                return None, None, None
        else:
            return self.find_fallback_slot_by_order(order_number)
    
    # === FALLBACK METHODS (for when database is not available) ===
    
    def fallback_to_json(self):
        """Initialize fallback JSON file system"""
        self.slots_file = 'slots.json'
        self.load_fallback_slots()
    
    def load_fallback_slots(self):
        """Load slots from JSON file (fallback)"""
        if os.path.exists(self.slots_file):
            try:
                with open(self.slots_file, 'r') as f:
                    self.fallback_slots = json.load(f)
                print(f"[FALLBACK] Loaded slots from {self.slots_file}")
            except Exception as e:
                print(f"[FALLBACK] Error loading slots file: {e}")
                self.create_initial_fallback_slots()
        else:
            print(f"[FALLBACK] Creating initial {self.slots_file}")
            self.create_initial_fallback_slots()
    
    def create_initial_fallback_slots(self):
        """Create initial slots structure"""
        self.fallback_slots = {
            'monthly': {f'client_{i:02d}': {
                'available': True, 
                'assigned_at': None, 
                'expires_at': None,
                'order_number': None,
                'slot_type': 'monthly',
                'auto_managed': True
            } for i in range(1, 11)},
            'test': {f'test_{i:02d}': {
                'available': True, 
                'assigned_at': None, 
                'expires_at': None,
                'order_number': None,
                'slot_type': 'test',
                'auto_managed': True
            } for i in range(1, 11)}
        }
        self.save_fallback_slots()
    
    def save_fallback_slots(self):
        """Save slots to JSON file (fallback)"""
        try:
            with open(self.slots_file, 'w') as f:
                json.dump(self.fallback_slots, f, indent=2)
        except Exception as e:
            print(f"[FALLBACK] Error saving slots: {e}")
    
    def get_fallback_slots(self):
        return getattr(self, 'fallback_slots', {})
    
    def get_fallback_available_slot(self, slot_type):
        slots = self.get_fallback_slots()
        for slot_id, slot_data in slots.get(slot_type, {}).items():
            if slot_data.get('available', True):
                return slot_id
        return None
    
    def assign_fallback_slot(self, slot_type, duration_days, order_number, stripe_session_id):
        # Implement fallback slot assignment
        slots = self.get_fallback_slots()
        slot_id = self.get_fallback_available_slot(slot_type)
        
        if not slot_id:
            return None
        
        if not order_number:
            order_number = f"42{str(uuid.uuid4()).replace('-', '')[:6].upper()}"
        
        now = datetime.now()
        if slot_type == 'test':
            expires_at = now + timedelta(minutes=15)
        else:
            expires_at = now + timedelta(days=duration_days)
        
        slots[slot_type][slot_id].update({
            'available': False,
            'assigned_at': now.isoformat(),
            'expires_at': expires_at.isoformat(),
            'order_number': order_number,
            'stripe_session_id': stripe_session_id
        })
        
        self.fallback_slots = slots
        self.save_fallback_slots()
        
        return slot_id, order_number
    
    def cleanup_fallback_slots(self):
        # Implement fallback cleanup
        now = datetime.now()
        cleaned_slots = []
        slots = self.get_fallback_slots()
        
        for slot_type in ['monthly', 'test']:
            for slot_id, slot_data in slots.get(slot_type, {}).items():
                if not slot_data.get('available', True) and slot_data.get('expires_at'):
                    try:
                        expires_at = datetime.fromisoformat(slot_data['expires_at'])
                        if now > expires_at:
                            slot_data.update({
                                'available': True,
                                'assigned_at': None,
                                'expires_at': None,
                                'order_number': None,
                                'stripe_session_id': None
                            })
                            cleaned_slots.append(f"{slot_type}:{slot_id}")
                    except Exception:
                        pass
        
        if cleaned_slots:
            self.fallback_slots = slots
            self.save_fallback_slots()
        
        return cleaned_slots
    
    def release_fallback_slot(self, slot_type, slot_id):
        slots = self.get_fallback_slots()
        if slot_id in slots.get(slot_type, {}):
            slots[slot_type][slot_id].update({
                'available': True,
                'assigned_at': None,
                'expires_at': None,
                'order_number': None,
                'stripe_session_id': None
            })
            self.fallback_slots = slots
            self.save_fallback_slots()
    
    def find_fallback_slot_by_order(self, order_number):
        slots = self.get_fallback_slots()
        for slot_type in ['monthly', 'test']:
            for slot_id, slot_data in slots.get(slot_type, {}).items():
                if slot_data.get('order_number') == order_number:
                    return slot_type, slot_id, slot_data
        return None, None, None


class OrderBasedSlotManager(DatabaseSlotManager):
    """Enhanced slot manager with order-number-based file naming"""
    
    def __init__(self):
        super().__init__()
        self.order_to_slot_mapping = self.load_order_mapping()
        self.slot_to_order_mapping = {v: k for k, v in self.order_to_slot_mapping.items()}
    
    def load_order_mapping(self):
        """Load order number to slot_id mapping"""
        mapping = {}
        
        # Monthly mapping (slot_id -> 42XXXXXX)
        for i in range(1, 11):
            slot_id = f"client_{i:02d}"
            order_number = f"42{(0x100000 + i):06X}"
            mapping[slot_id] = order_number
        
        # Test mapping (slot_id -> 72XXXXXX)
        for i in range(1, 11):
            slot_id = f"test_{i:02d}"
            order_number = f"72{(0x100000 + i):06X}"
            mapping[slot_id] = order_number
        
        return mapping
    
    def get_order_number_for_slot(self, slot_id):
        """Get the predefined order number for a slot"""
        return self.order_to_slot_mapping.get(slot_id)
    
    def get_slot_for_order_number(self, order_number):
        """Get the slot_id for a predefined order number"""
        return self.slot_to_order_mapping.get(order_number)
    
    def assign_slot(self, slot_type='monthly', duration_days=30, order_number=None, stripe_session_id=None):
        """Enhanced slot assignment using predefined order numbers"""
        if self.use_database:
            try:
                conn = self.get_connection()
                cursor = conn.cursor()
                
                # Find available slot
                cursor.execute("""
                    SELECT slot_id FROM vpn_slots 
                    WHERE slot_type = %s AND available = TRUE 
                    ORDER BY slot_id LIMIT 1
                    FOR UPDATE
                """, (slot_type,))
                
                result = cursor.fetchone()
                if not result:
                    cursor.close()
                    conn.close()
                    return None
                
                slot_id = result[0]
                
                # Use predefined order number for this slot
                predefined_order = self.get_order_number_for_slot(slot_id)
                if not predefined_order:
                    # Fallback to generated order if mapping fails
                    if slot_type == 'test':
                        predefined_order = f"72{str(uuid.uuid4()).replace('-', '')[:6].upper()}"
                    else:
                        predefined_order = f"42{str(uuid.uuid4()).replace('-', '')[:6].upper()}"
                
                # Calculate expiration
                now = datetime.now()
                if slot_type == 'test':
                    expires_at = now + timedelta(minutes=15)
                else:
                    expires_at = now + timedelta(days=duration_days)
                
                # Update slot with predefined order number
                cursor.execute("""
                    UPDATE vpn_slots 
                    SET available = FALSE, 
                        assigned_at = %s,
                        expires_at = %s,
                        order_number = %s,
                        stripe_session_id = %s,
                        updated_at = %s
                    WHERE slot_id = %s
                """, (now, expires_at, predefined_order, stripe_session_id, now, slot_id))
                
                conn.commit()
                cursor.close()
                conn.close()
                
                print(f"[DB] ✅ Assigned {slot_type} slot {slot_id} with order: {predefined_order}")
                return slot_id, predefined_order
                
            except Exception as e:
                print(f"[DB] ❌ Error assigning slot: {e}")
                return None
        else:
            return self.assign_fallback_slot_with_predefined_order(slot_type, duration_days, order_number, stripe_session_id)
    
    def assign_fallback_slot_with_predefined_order(self, slot_type, duration_days, order_number, stripe_session_id):
        """Fallback slot assignment with predefined order numbers"""
        slots = self.get_fallback_slots()
        slot_id = self.get_fallback_available_slot(slot_type)
        
        if not slot_id:
            return None
        
        # Use predefined order number
        predefined_order = self.get_order_number_for_slot(slot_id)
        if not predefined_order:
            if slot_type == 'test':
                predefined_order = f"72{str(uuid.uuid4()).replace('-', '')[:6].upper()}"
            else:
                predefined_order = f"42{str(uuid.uuid4()).replace('-', '')[:6].upper()}"
        
        now = datetime.now()
        if slot_type == 'test':
            expires_at = now + timedelta(minutes=15)
        else:
            expires_at = now + timedelta(days=duration_days)
        
        slots[slot_type][slot_id].update({
            'available': False,
            'assigned_at': now.isoformat(),
            'expires_at': expires_at.isoformat(),
            'order_number': predefined_order,
            'stripe_session_id': stripe_session_id
        })
        
        self.fallback_slots = slots
        self.save_fallback_slots()
        
        print(f"[FALLBACK] ✅ Assigned {slot_type} slot {slot_id} with order: {predefined_order}")
        return slot_id, predefined_order