#!/usr/bin/env python3
"""
Tunnelgrain VPN Expiration Daemon
Actually disables configs when they expire
"""

import time
import json
import subprocess
import logging
from datetime import datetime, timedelta
from pathlib import Path
import threading
import os

# Configuration
CONFIG_BASE = "/opt/tunnelgrain"
TIMER_FILE = f"{CONFIG_BASE}/active_timers.json"
LOG_FILE = f"{CONFIG_BASE}/logs/expiration.log"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class ExpirationDaemon:
    def __init__(self):
        self.timers = {}
        self.load_timers()
    
    def load_timers(self):
        """Load active timers from disk"""
        if os.path.exists(TIMER_FILE):
            try:
                with open(TIMER_FILE, 'r') as f:
                    self.timers = json.load(f)
                logger.info(f"Loaded {len(self.timers)} active timers")
            except Exception as e:
                logger.error(f"Error loading timers: {e}")
                self.timers = {}
    
    def save_timers(self):
        """Save active timers to disk"""
        try:
            with open(TIMER_FILE, 'w') as f:
                json.dump(self.timers, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error saving timers: {e}")
    
    def add_timer(self, order_number, tier, duration_minutes):
        """Add new expiration timer"""
        expires_at = datetime.now() + timedelta(minutes=duration_minutes)
        
        self.timers[order_number] = {
            'tier': tier,
            'expires_at': expires_at.isoformat(),
            'duration_minutes': duration_minutes,
            'status': 'active'
        }
        
        self.save_timers()
        logger.info(f"Timer added: {order_number} expires in {duration_minutes} minutes")
        return True
    
    def expire_config(self, order_number, tier):
        """Actually expire a config by removing from WireGuard"""
        try:
            # Find the public key for this order in peer mapping
            peer_map_file = f"{CONFIG_BASE}/peer_mapping.txt"
            if not os.path.exists(peer_map_file):
                logger.error(f"Peer mapping file not found: {peer_map_file}")
                return False
            
            public_key = None
            with open(peer_map_file, 'r') as f:
                for line in f:
                    if line.strip().startswith(order_number + ':'):
                        parts = line.strip().split(':')
                        if len(parts) >= 2:
                            public_key = parts[1]
                            break
            
            if not public_key:
                logger.error(f"Public key not found for order {order_number}")
                return False
            
            # Remove peer from WireGuard
            result = subprocess.run([
                'wg', 'set', 'wg0', 'peer', public_key, 'remove'
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.info(f"✅ Config {order_number} expired and removed from WireGuard")
                
                # Update timer status
                if order_number in self.timers:
                    self.timers[order_number]['status'] = 'expired'
                    self.timers[order_number]['expired_at'] = datetime.now().isoformat()
                    self.save_timers()
                
                return True
            else:
                logger.error(f"Failed to remove peer: {result.stderr}")
                return False
        
        except Exception as e:
            logger.error(f"Error expiring config {order_number}: {e}")
            return False
    
    def check_expirations(self):
        """Check and process expired configs"""
        now = datetime.now()
        expired_orders = []
        
        for order_number, timer_data in list(self.timers.items()):
            if timer_data['status'] != 'active':
                continue
            
            try:
                expires_at = datetime.fromisoformat(timer_data['expires_at'])
                if now >= expires_at:
                    logger.info(f"⏰ Order {order_number} has expired")
                    
                    if self.expire_config(order_number, timer_data['tier']):
                        expired_orders.append(order_number)
                    
            except Exception as e:
                logger.error(f"Error checking expiration for {order_number}: {e}")
        
        return expired_orders
    
    def run(self):
        """Main daemon loop"""
        logger.info("🚀 Expiration daemon started")
        
        while True:
            try:
                expired = self.check_expirations()
                if expired:
                    logger.info(f"Processed {len(expired)} expirations")
                
                # Check every 30 seconds
                time.sleep(30)
                
            except KeyboardInterrupt:
                logger.info("🛑 Daemon stopped by user")
                break
            except Exception as e:
                logger.error(f"Daemon error: {e}")
                time.sleep(60)  # Wait longer if there's an error

if __name__ == '__main__':
    daemon = ExpirationDaemon()
    daemon.run()
```

**1.2 Enhanced VPS API** (`/opt/tunnelgrain/api/enhanced_api.py`)

```python
#!/usr/bin/env python3
"""
Enhanced Tunnelgrain VPS API with Expiration Management
"""

import os
import json
import logging
import subprocess
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_file
from pathlib import Path
import requests

# Configuration
CONFIG = {
    'base_dir': '/opt/tunnelgrain',
    'server_ip': '213.170.133.116',
    'timer_file': '/opt/tunnelgrain/active_timers.json'
}

app = Flask(__name__)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_timers():
    """Load active timers"""
    try:
        if os.path.exists(CONFIG['timer_file']):
            with open(CONFIG['timer_file'], 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading timers: {e}")
    return {}

def save_timers(timers):
    """Save timers to file"""
    try:
        with open(CONFIG['timer_file'], 'w') as f:
            json.dump(timers, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"Error saving timers: {e}")

@app.route('/api/start-timer', methods=['POST'])
def start_expiration_timer():
    """Start expiration timer for a config"""
    try:
        data = request.json
        order_number = data.get('order_number')
        tier = data.get('tier')
        duration_minutes = data.get('duration_minutes')
        
        if not all([order_number, tier, duration_minutes]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Load existing timers
        timers = load_timers()
        
        # Add new timer
        expires_at = datetime.now() + timedelta(minutes=duration_minutes)
        timers[order_number] = {
            'tier': tier,
            'expires_at': expires_at.isoformat(),
            'duration_minutes': duration_minutes,
            'status': 'active',
            'started_at': datetime.now().isoformat()
        }
        
        # Save timers
        save_timers(timers)
        
        logger.info(f"Timer started: {order_number} ({tier}) for {duration_minutes} minutes")
        
        return jsonify({
            'success': True,
            'order_number': order_number,
            'tier': tier,
            'expires_at': expires_at.isoformat(),
            'duration_minutes': duration_minutes
        })
        
    except Exception as e:
        logger.error(f"Error starting timer: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/check-timer/<order_number>', methods=['GET'])
def check_timer_status(order_number):
    """Check timer status for an order"""
    try:
        timers = load_timers()
        
        if order_number not in timers:
            return jsonify({'error': 'Timer not found'}), 404
        
        timer_data = timers[order_number]
        now = datetime.now()
        
        try:
            expires_at = datetime.fromisoformat(timer_data['expires_at'])
            is_expired = now >= expires_at
            time_remaining = max(0, (expires_at - now).total_seconds())
        except:
            is_expired = True
            time_remaining = 0
        
        return jsonify({
            'order_number': order_number,
            'tier': timer_data.get('tier'),
            'status': 'expired' if is_expired else 'active',
            'expires_at': timer_data.get('expires_at'),
            'time_remaining_seconds': time_remaining,
            'time_remaining_minutes': time_remaining / 60
        })
        
    except Exception as e:
        logger.error(f"Error checking timer: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/status', methods=['GET'])
def get_status():
    """Get comprehensive VPS status"""
    try:
        # Count configs by tier
        tier_stats = {}
        base_path = Path(CONFIG['base_dir']) / 'configs'
        
        for tier_dir in base_path.iterdir():
            if tier_dir.is_dir():
                tier_name = tier_dir.name
                config_count = len(list(tier_dir.glob('*.conf')))
                qr_count = len(list((Path(CONFIG['base_dir']) / 'qr_codes' / tier_name).glob('*.png')))
                
                tier_stats[tier_name] = {
                    'available': config_count,
                    'qr_codes': qr_count
                }
        
        # Get active timers
        timers = load_timers()
        active_timers = len([t for t in timers.values() if t.get('status') == 'active'])
        
        # WireGuard status
        try:
            wg_result = subprocess.run(['wg', 'show', 'wg0'], 
                                     capture_output=True, text=True, timeout=5)
            peer_count = len([line for line in wg_result.stdout.split('\n') 
                            if line.strip().startswith('peer:')])
            wg_status = 'active'
        except:
            peer_count = 0
            wg_status = 'error'
        
        return jsonify({
            'status': 'operational',
            'timestamp': datetime.now().isoformat(),
            'server_ip': CONFIG['server_ip'],
            'tiers': tier_stats,
            'active_timers': active_timers,
            'wireguard': {
                'status': wg_status,
                'active_peers': peer_count
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/<tier>/<order_number>', methods=['GET'])
def serve_config(tier, order_number):
    """Serve config file"""
    try:
        config_file = Path(CONFIG['base_dir']) / 'configs' / tier / f"{order_number}.conf"
        
        if config_file.exists():
            return send_file(str(config_file), 
                           as_attachment=True,
                           download_name=f"tunnelgrain_{order_number}.conf")
        
        return jsonify({'error': 'Config not found'}), 404
        
    except Exception as e:
        logger.error(f"Error serving config: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/qr/<tier>/<order_number>', methods=['GET'])
def serve_qr(tier, order_number):
    """Serve QR code"""
    try:
        qr_file = Path(CONFIG['base_dir']) / 'qr_codes' / tier / f"{order_number}.png"
        
        if qr_file.exists():
            return send_file(str(qr_file),
                           as_attachment=True,
                           download_name=f"tunnelgrain_{order_number}_qr.png")
        
        return jsonify({'error': 'QR not found'}), 404
        
    except Exception as e:
        logger.error(f"Error serving QR: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
```

**1.3 Create Systemd Service for Expiration Daemon**

```bash
# On VPS: Create /etc/systemd/system/tunnelgrain-expiration.service
[Unit]
Description=Tunnelgrain VPN Expiration Daemon
After=network.target wg-quick@wg0.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/tunnelgrain
ExecStart=/usr/bin/python3 /opt/tunnelgrain/scripts/expiration_daemon.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### **STEP 2: Enhanced Render Flask App**

**2.1 New Database Manager** (`database_manager.py`)

```python
import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import uuid
import logging
import requests

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TunnelgrainDB:
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        self.vps_endpoint = os.environ.get('VPS_1_ENDPOINT', 'http://213.170.133.116:8080')
        
        if self.database_url:
            self.init_database()
        else:
            logger.error("DATABASE_URL not found - check environment variables")
    
    def get_connection(self):
        """Get PostgreSQL connection"""
        return psycopg2.connect(self.database_url, sslmode='require')
    
    def init_database(self):
        """Initialize database tables"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Orders table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS vpn_orders (
                    order_id VARCHAR(36) PRIMARY KEY,
                    order_number VARCHAR(20) UNIQUE NOT NULL,
                    tier VARCHAR(20) NOT NULL,
                    vps_ip VARCHAR(45) NOT NULL,
                    config_id VARCHAR(50) NOT NULL,
                    status VARCHAR(20) DEFAULT 'active',
                    price_cents INTEGER DEFAULT 0,
                    stripe_session_id VARCHAR(200),
                    user_fingerprint VARCHAR(64),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    timer_started BOOLEAN DEFAULT FALSE
                );
            """)
            
            # Indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON vpn_orders (status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_number ON vpn_orders (order_number);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_expires ON vpn_orders (expires_at);")
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info("✅ Database initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            raise
    
    def create_order(self, tier, config_id, vps_ip='213.170.133.116', 
                    stripe_session_id=None, user_fingerprint=None):
        """Create new VPN order"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            order_id = str(uuid.uuid4())
            
            # Generate order number
            if tier == 'test':
                order_number = f"72{str(uuid.uuid4()).replace('-', '')[:6].upper()}"
            else:
                order_number = f"42{str(uuid.uuid4()).replace('-', '')[:6].upper()}"
            
            # Calculate expiration
            now = datetime.now()
            if tier == 'test':
                expires_at = now + timedelta(minutes=15)
                duration_minutes = 15
                price_cents = 0
            elif tier == 'monthly':
                expires_at = now + timedelta(days=30)
                duration_minutes = 30 * 24 * 60
                price_cents = 499
            elif tier == 'quarterly':
                expires_at = now + timedelta(days=90)
                duration_minutes = 90 * 24 * 60
                price_cents = 1299
            elif tier == 'biannual':
                expires_at = now + timedelta(days=180)
                duration_minutes = 180 * 24 * 60
                price_cents = 2399
            elif tier == 'annual':
                expires_at = now + timedelta(days=365)
                duration_minutes = 365 * 24 * 60
                price_cents = 3999
            elif tier == 'lifetime':
                expires_at = now + timedelta(days=36500)  # 100 years
                duration_minutes = 36500 * 24 * 60
                price_cents = 9999
            else:
                raise ValueError(f"Invalid tier: {tier}")
            
            # Insert order
            cursor.execute("""
                INSERT INTO vpn_orders 
                (order_id, order_number, tier, vps_ip, config_id, price_cents, 
                 stripe_session_id, user_fingerprint, expires_at, timer_started)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (order_id, order_number, tier, vps_ip, config_id, price_cents,
                  stripe_session_id, user_fingerprint, expires_at, False))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info(f"✅ Order created: {order_number} ({tier})")
            
            # Start VPS timer
            self.start_vps_timer(order_number, tier, duration_minutes)
            
            return order_id, order_number
            
        except Exception as e:
            logger.error(f"❌ Error creating order: {e}")
            return None, None
    
    def start_vps_timer(self, order_number, tier, duration_minutes):
        """Start expiration timer on VPS"""
        try:
            response = requests.post(f"{self.vps_endpoint}/api/start-timer", 
                                   json={
                                       'order_number': order_number,
                                       'tier': tier,
                                       'duration_minutes': duration_minutes
                                   }, timeout=10)
            
            if response.status_code == 200:
                # Mark timer as started in database
                conn = self.get_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE vpn_orders SET timer_started = TRUE 
                    WHERE order_number = %s
                """, (order_number,))
                conn.commit()
                cursor.close()
                conn.close()
                
                logger.info(f"✅ VPS timer started for {order_number}")
                return True
            else:
                logger.error(f"❌ VPS timer failed: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error starting VPS timer: {e}")
            return False
    
    def get_order_by_number(self, order_number):
        """Get order by order number"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT * FROM vpn_orders WHERE order_number = %s
            """, (order_number,))
            
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            
            return dict(result) if result else None
            
        except Exception as e:
            logger.error(f"❌ Error getting order: {e}")
            return None
    
    def get_available_configs(self, tier):
        """Get available config count for tier"""
        # This uses the local file system since configs are stored locally
        import glob
        
        config_dir = f"data/vps_1/ip_213.170.133.116/{tier}"
        if os.path.exists(config_dir):
            return len(glob.glob(f"{config_dir}/*.conf"))
        return 0
    
    def cleanup_expired_orders(self):
        """Mark expired orders as expired in database"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE vpn_orders 
                SET status = 'expired'
                WHERE status = 'active' AND expires_at < CURRENT_TIMESTAMP
            """)
            
            expired_count = cursor.rowcount
            conn.commit()
            cursor.close()
            conn.close()
            
            if expired_count > 0:
                logger.info(f"✅ Marked {expired_count} orders as expired")
            
            return expired_count
            
        except Exception as e:
            logger.error(f"❌ Error cleaning up orders: {e}")
            return 0
```

**2.2 Fixed Flask App** (`app.py`)

```python
from flask import Flask, render_template, request, send_file, jsonify, session, redirect, url_for
import os
import logging
from datetime import datetime, timedelta
import stripe
import uuid
from database_manager import TunnelgrainDB
import glob
import random

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-in-production')

# Initialize database
db = TunnelgrainDB()

# Stripe configuration
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
    logger.info("✅ Stripe configured")
else:
    logger.error("❌ Stripe keys not found")

# Service tiers
SERVICE_TIERS = {
    'test': {'name': 'Free Test', 'price_cents': 0, 'duration_days': 0, 'capacity': 50},
    'monthly': {'name': 'Monthly VPN', 'price_cents': 499, 'duration_days': 30, 'capacity': 30},
    'quarterly': {'name': '3-Month VPN', 'price_cents': 1299, 'duration_days': 90, 'capacity': 20},
    'biannual': {'name': '6-Month VPN', 'price_cents': 2399, 'duration_days': 180, 'capacity': 15},
    'annual': {'name': '12-Month VPN', 'price_cents': 3999, 'duration_days': 365, 'capacity': 10},
    'lifetime': {'name': 'Lifetime VPN', 'price_cents': 9999, 'duration_days': 36500, 'capacity': 5}
}

def get_client_fingerprint(request):
    """Create user fingerprint for abuse prevention"""
    import hashlib
    ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
    user_agent = request.headers.get('User-Agent', '')
    return hashlib.sha256(f"{ip}:{user_agent}".encode()).hexdigest()[:16]

def get_available_config(tier):
    """Get random available config for tier"""
    config_dir = f"data/vps_1/ip_213.170.133.116/{tier}"
    if not os.path.exists(config_dir):
        return None
    
    configs = glob.glob(f"{config_dir}/*.conf")
    if not configs:
        return None
    
    # Get random config filename (without extension)
    config_path = random.choice(configs)
    return os.path.basename(config_path).replace('.conf', '')

# Routes
@app.route('/')
def home():
    return render_template('home.html', service_tiers=SERVICE_TIERS)

@app.route('/test')
def test():
    return render_template('test.html')

@app.route('/order')
def order():
    # Get availability
    available_ips = {}
    for tier_name in SERVICE_TIERS.keys():
        if tier_name != 'test':
            available = db.get_available_configs(tier_name)
            available_ips[tier_name] = [{
                'ip_address': '213.170.133.116',
                'vps_name': 'primary_vps',
                'available_slots': available
            }]
    
    return render_template('order.html', 
                         service_tiers=SERVICE_TIERS,
                         available_ips=available_ips,
                         stripe_publishable_key=STRIPE_PUBLISHABLE_KEY)

@app.route('/get-test-vpn', methods=['POST'])
def get_test_vpn():
    """Get test VPN with proper database tracking"""
    try:
        # Get available config
        config_id = get_available_config('test')
        if not config_id:
            return jsonify({'error': 'No test slots available'}), 503
        
        user_fingerprint = get_client_fingerprint(request)
        
        # Create order in database
        order_id, order_number = db.create_order(
            tier='test',
            config_id=config_id,
            user_fingerprint=user_fingerprint
        )
        
        if not order_id:
            return jsonify({'error': 'Failed to create order'}), 500
        
        # Store in session
        session['test_order'] = order_number
        session['test_config'] = config_id
        
        logger.info(f"✅ Test VPN assigned: {order_number}")
        
        return jsonify({
            'success': True,
            'order_number': order_number,
            'config_id': config_id,
            'expires_in_minutes': 15
        })
        
    except Exception as e:
        logger.error(f"❌ Test VPN error: {e}")
        return jsonify({'error': 'Service temporarily unavailable'}), 500

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    """Create Stripe checkout with proper error handling"""
    try:
        data = request.json
        tier = data.get('tier')
        
        if tier not in SERVICE_TIERS or tier == 'test':
            return jsonify({'error': 'Invalid tier'}), 400
        
        # Check availability
        config_id = get_available_config(tier)
        if not config_id:
            return jsonify({'error': f'No {tier} slots available'}), 503
        
        tier_config = SERVICE_TIERS[tier]
        
        # Create Stripe session
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': f"Tunnelgrain {tier_config['name']}",
                        'description': f"{tier_config['name']} VPN Access"
                    },
                    'unit_amount': tier_config['price_cents'],
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=url_for('payment_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('order', _external=True),
            metadata={
                'tier': tier,
                'config_id': config_id
            }
        )
        
        return jsonify({'checkout_url': checkout_session.url})
        
    except stripe.error.StripeError as e:
        logger.error(f"❌ Stripe error: {e}")
        return jsonify({'error': 'Payment system error'}), 500
    except Exception as e:
        logger.error(f"❌ Checkout error: {e}")
        return jsonify({'error': 'Service error'}), 500

@app.route('/payment-success')
def payment_success():
    """Handle successful payment"""
    session_id = request.args.get('session_id')
    
    if not session_id:
        return "Invalid session", 400
    
    try:
        # Get session from Stripe
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        
        if checkout_session.payment_status != 'paid':
            return "Payment not completed", 400
        
        # Get metadata
        tier = checkout_session.metadata.get('tier')
        config_id = checkout_session.metadata.get('config_id')
        
        # Create order
        user_fingerprint = get_client_fingerprint(request)
        order_id, order_number = db.create_order(
            tier=tier,
            config_id=config_id,
            stripe_session_id=session_id,
            user_fingerprint=user_fingerprint
        )
        
        if order_id:
            # Store in session
            session['purchase_order'] = order_number
            session['purchase_tier'] = tier
            session['purchase_config'] = config_id
            
            return render_template('payment_success.html',
                                 order_data={
                                     'order_number': order_number,
                                     'tier': tier,
                                     'config_id': config_id,
                                     'ip_address': '213.170.133.116'
                                 },
                                 tier_config=SERVICE_TIERS[tier])
        else:
            return "Order creation failed", 500
            
    except Exception as e:
        logger.error(f"❌ Payment success error: {e}")
        return f"Error: {str(e)}", 500

@app.route('/download-test-config')
def download_test_config():
    """Download test config"""
    if 'test_config' not in session:
        return "No test VPN assigned", 404
    
    config_id = session['test_config']
    order_number = session.get('test_order', 'test')
    
    config_path = f"data/vps_1/ip_213.170.133.116/test/{config_id}.conf"
    
    if os.path.exists(config_path):
        return send_file(config_path,
                        as_attachment=True,
                        download_name=f"tunnelgrain_{order_number}.conf")
    
    return "Config not found", 404

@app.route('/download-test-qr')
def download_test_qr():
    """Download test QR"""
    if 'test_config' not in session:
        return "No test VPN assigned", 404
    
    config_id = session['test_config']
    order_number = session.get('test_order', 'test')
    
    qr_path = f"static/qr_codes/vps_1/ip_213.170.133.116/test/{config_id}.png"
    
    if os.path.exists(qr_path):
        return send_file(qr_path,
                        as_attachment=True,
                        download_name=f"tunnelgrain_{order_number}_qr.png")
    
    return "QR not found", 404

@app.route('/download-purchase-config')
def download_purchase_config():
    """Download purchased config"""
    if 'purchase_config' not in session:
        return "No purchase found", 404
    
    config_id = session['purchase_config']
    tier = session['purchase_tier']
    order_number = session.get('purchase_order', 'purchase')
    
    config_path = f"data/vps_1/ip_213.170.133.116/{tier}/{config_id}.conf"
    
    if os.path.exists(config_path):
        return send_file(config_path,
                        as_attachment=True,
                        download_name=f"tunnelgrain_{order_number}.conf")
    
    return "Config not found", 404

@app.route('/download-purchase-qr')
def download_purchase_qr():
    """Download purchased QR"""
    if 'purchase_config' not in session:
        return "No purchase found", 404
    
    config_id = session['purchase_config']
    tier = session['purchase_tier']
    order_number = session.get('purchase_order', 'purchase')
    
    qr_path = f"static/qr_codes/vps_1/ip_213.170.133.116/{tier}/{config_id}.png"
    
    if os.path.exists(qr_path):
        return send_file(qr_path,
                        as_attachment=True,
                        download_name=f"tunnelgrain_{order_number}_qr.png")
    
    return "QR not found", 404

@app.route('/api/status')
def api_status():
    """API status endpoint"""
    try:
        tier_availability = {}
        for tier_name, tier_config in SERVICE_TIERS.items():
            available = db.get_available_configs(tier_name)
            tier_availability[tier_name] = {
                'available': available,
                'capacity': tier_config['capacity'],
                'price_cents': tier_config['price_cents']
            }
        
        return jsonify({
            'status': 'operational',
            'timestamp': datetime.now().isoformat(),
            'tiers': tier_availability
        })
        
    except Exception as e:
        logger.error(f"❌ Status error: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)