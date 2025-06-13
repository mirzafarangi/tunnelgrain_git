from flask import Flask, render_template, request, send_file, jsonify, session, redirect, url_for, abort
import json
import os
import time
from datetime import datetime, timedelta
import qrcode
from io import BytesIO
import stripe
import uuid
import hashlib
from functools import wraps
from collections import defaultdict
import logging
from dotenv import load_dotenv
import glob
import random

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-in-production-very-secret-key')

# Stripe Configuration
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')

if not STRIPE_PUBLISHABLE_KEY or not STRIPE_SECRET_KEY:
    logger.warning("⚠️ Stripe keys not configured - payments will not work")
else:
    stripe.api_key = STRIPE_SECRET_KEY
    logger.info("✅ Stripe configured successfully")

# Admin security key from environment
ADMIN_KEY = os.environ.get('ADMIN_KEY', 'Freud@')

# VPS Configuration - LOCAL FILE SERVING
VPS_IP = "213.170.133.116"
VPS_NAME = "primary_vps"

# Local file paths
DATA_DIR = "data/vps_1/ip_213.170.133.116"
QR_DIR = "static/qr_codes/vps_1/ip_213.170.133.116"

# Service Tiers - MUST MATCH YOUR LOCAL FILE STRUCTURE
SERVICE_TIERS = {
    'test': {
        'name': 'Free Test',
        'duration_days': 0,  # 15 minutes
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

# Abuse Prevention - In-memory tracking
test_usage_tracker = defaultdict(list)

# Enhanced slot tracking
SLOTS_FILE = 'enhanced_slots.json'

def load_slots_data():
    """Load slots data from JSON file"""
    if os.path.exists(SLOTS_FILE):
        try:
            with open(SLOTS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading slots: {e}")
    
    # Create initial structure
    return {
        "orders": {},
        "assigned_configs": {},  # Track which config files are assigned
        "last_cleanup": datetime.now().isoformat()
    }

def save_slots_data(data):
    """Save slots data to JSON file"""
    try:
        with open(SLOTS_FILE, 'w') as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"Error saving slots: {e}")

def get_available_config_files(tier: str):
    """Get list of available config files for a tier"""
    config_dir = os.path.join(DATA_DIR, tier)
    if not os.path.exists(config_dir):
        logger.error(f"Config directory not found: {config_dir}")
        return []
    
    config_files = glob.glob(os.path.join(config_dir, "*.conf"))
    available_configs = []
    
    # Load current assignments
    slots_data = load_slots_data()
    assigned_configs = slots_data.get("assigned_configs", {})
    
    for config_path in config_files:
        config_filename = os.path.basename(config_path)
        config_id = config_filename.replace('.conf', '')
        
        # Check if this config is already assigned and active
        if config_id in assigned_configs:
            order_id = assigned_configs[config_id]
            order_data = slots_data.get("orders", {}).get(order_id)
            
            if order_data and order_data.get("status") == "active":
                # Check if expired
                try:
                    expires_at = datetime.fromisoformat(order_data["expires_at"])
                    if datetime.now() > expires_at:
                        # Config is expired, available for reuse
                        available_configs.append(config_id)
                except:
                    available_configs.append(config_id)
            else:
                # Order doesn't exist or not active, config is available
                available_configs.append(config_id)
        else:
            # Config not assigned, available
            available_configs.append(config_id)
    
    return available_configs

def assign_specific_config(tier: str, user_fingerprint: str):
    """Assign a specific config file to a user"""
    try:
        # Get available configs
        available_configs = get_available_config_files(tier)
        
        if not available_configs:
            logger.error(f"No available config files for tier: {tier}")
            return None
        
        # Choose a random available config
        config_id = random.choice(available_configs)
        
        # Load current data
        slots_data = load_slots_data()
        
        # Generate order details
        order_id = str(uuid.uuid4())
        order_number = generate_order_number(tier)
        
        # Calculate expiration
        now = datetime.now()
        if tier == 'test':
            expires_at = now + timedelta(minutes=15)
        else:
            tier_config = SERVICE_TIERS[tier]
            expires_at = now + timedelta(days=tier_config['duration_days'])
        
        # Store order
        slots_data["orders"][order_id] = {
            "order_number": order_number,
            "tier": tier,
            "ip_address": VPS_IP,
            "vps_name": VPS_NAME,
            "config_id": config_id,  # Store which config file is assigned
            "status": "active",
            "assigned_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "user_fingerprint": user_fingerprint
        }
        
        # Mark config as assigned
        slots_data["assigned_configs"][config_id] = order_id
        
        save_slots_data(slots_data)
        
        logger.info(f"Assigned {tier} config {config_id} (order {order_number}) to {user_fingerprint}")
        return order_id, order_number, config_id
        
    except Exception as e:
        logger.error(f"Error assigning config: {e}")
        return None

# Admin authentication decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        provided_key = request.args.get('key') or request.headers.get('X-Admin-Key')
        if provided_key != ADMIN_KEY:
            logger.warning(f"Admin access denied. Expected: {ADMIN_KEY}, Got: {provided_key}")
            abort(404)  # Return 404 instead of 403 to hide existence
        return f(*args, **kwargs)
    return decorated_function

# Utility functions
def get_client_fingerprint(request):
    """Create a privacy-respecting fingerprint for abuse prevention"""
    ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
    user_agent = request.headers.get('User-Agent', '')
    fingerprint_data = f"{ip}:{user_agent}"
    return hashlib.sha256(fingerprint_data.encode()).hexdigest()[:16]

def check_test_vpn_abuse(request):
    """Check if user has exceeded test VPN limits (3 per 24 hours)"""
    fingerprint = get_client_fingerprint(request)
    now = datetime.now()
    
    # Clean old entries (older than 24 hours)
    cutoff_time = now - timedelta(hours=24)
    test_usage_tracker[fingerprint] = [
        timestamp for timestamp in test_usage_tracker[fingerprint] 
        if timestamp > cutoff_time
    ]
    
    usage_count = len(test_usage_tracker[fingerprint])
    
    # Limit: 3 test VPNs per 24 hours per fingerprint
    if usage_count >= 3:
        return False, f"Test limit reached. You can try {3 - usage_count} more test VPNs today."
    
    # Record this usage
    test_usage_tracker[fingerprint].append(now)
    
    return True, f"Test VPN granted. {3 - len(test_usage_tracker[fingerprint])} remaining today."

def generate_order_number(tier: str) -> str:
    """Generate order number with tier-specific prefix"""
    tier_config = SERVICE_TIERS.get(tier, {})
    prefix = tier_config.get('order_prefix', '42')
    return f"{prefix}{str(uuid.uuid4()).replace('-', '')[:6].upper()}"

def cleanup_expired_orders():
    """Clean up expired orders and free up config files"""
    try:
        slots_data = load_slots_data()
        now = datetime.now()
        expired_count = 0
        
        for order_id, order_data in list(slots_data["orders"].items()):
            if order_data.get("status") == "active":
                try:
                    expires_at = datetime.fromisoformat(order_data["expires_at"])
                    if now > expires_at:
                        order_data["status"] = "expired"
                        expired_count += 1
                        
                        # Free up the config file
                        config_id = order_data.get("config_id")
                        if config_id and config_id in slots_data.get("assigned_configs", {}):
                            del slots_data["assigned_configs"][config_id]
                            logger.info(f"Freed config {config_id} from expired order {order_data.get('order_number')}")
                            
                except Exception as e:
                    logger.error(f"Error processing order {order_id}: {e}")
        
        if expired_count > 0:
            save_slots_data(slots_data)
            logger.info(f"Expired {expired_count} orders and freed their configs")
            
        return expired_count
    except Exception as e:
        logger.error(f"Cleanup error: {e}")
        return 0

# === MAIN ROUTES ===

@app.route('/')
def home():
    """Home page with all service tiers"""
    return render_template('home.html', service_tiers=SERVICE_TIERS)

@app.route('/test')
def test():
    """Free test VPN page"""
    return render_template('test.html')

@app.route('/pricing')
def pricing():
    """Pricing page with all tiers"""
    return render_template('pricing.html', service_tiers=SERVICE_TIERS)

@app.route('/order')
def order():
    """Order page for purchasing VPN"""
    # Get available slots per tier
    available_slots = {}
    for tier_name, tier_config in SERVICE_TIERS.items():
        if tier_name != 'test':
            available_configs = get_available_config_files(tier_name)
            available_slots[tier_name] = len(available_configs)
    
    # Simplified available IPs structure
    available_ips = {
        tier_name: [{'ip_address': VPS_IP, 'vps_name': VPS_NAME, 'available_slots': available_slots.get(tier_name, 0)}]
        for tier_name in SERVICE_TIERS.keys() if tier_name != 'test'
    }
    
    return render_template('order.html', 
                         service_tiers=SERVICE_TIERS, 
                         available_ips=available_ips,
                         stripe_publishable_key=STRIPE_PUBLISHABLE_KEY)

@app.route('/refund')
def refund():
    """Service policy page"""
    return render_template('refund.html')

@app.route('/contact')
def contact():
    """Contact support page"""
    return render_template('contact.html')

@app.route('/order-lookup')
def order_lookup():
    """Order lookup page"""
    return render_template('order_lookup.html')

# === VPN SERVICE ROUTES ===

@app.route('/get-test-vpn', methods=['POST'])
def get_test_vpn():
    """Assign a 15-minute test VPN with abuse prevention"""
    cleanup_expired_orders()
    
    # Check for abuse
    allowed, message = check_test_vpn_abuse(request)
    if not allowed:
        return jsonify({
            'error': 'Test limit exceeded. You can try 3 test VPNs per day. For unlimited access, please purchase a VPN plan.',
            'limit_info': message
        }), 429
    
    user_fingerprint = get_client_fingerprint(request)
    
    # Assign slot with specific config
    result = assign_specific_config('test', user_fingerprint)
    
    if not result:
        return jsonify({
            'error': 'No test slots available. Please try again later or purchase a paid plan.',
            'suggestion': 'All test configurations are currently in use.'
        }), 503
    
    order_id, order_number, config_id = result
    
    # Store in session for download
    session['test_slot'] = order_id
    session['test_order'] = order_number
    session['test_config'] = config_id
    session['test_expires'] = (datetime.now() + timedelta(minutes=15)).isoformat()
    
    logger.info(f"[TEST] User {user_fingerprint} assigned config {config_id} (order {order_number})")
    
    return jsonify({
        'success': True,
        'order_id': order_id,
        'order_number': order_number,
        'config_id': config_id,
        'expires_in_minutes': 15,
        'download_url': url_for('download_test_config'),
        'usage_info': message
    })

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    """Create Stripe checkout session for VPN purchase"""
    try:
        data = request.json
        tier = data.get('tier')
        ip_address = data.get('ip_address', VPS_IP)
        
        # Validate tier
        if tier not in SERVICE_TIERS or tier == 'test':
            return jsonify({'error': 'Invalid service tier'}), 400
        
        # Check availability
        available_configs = get_available_config_files(tier)
        if not available_configs:
            return jsonify({'error': f'No {tier} slots available. Please try again later or choose a different plan.'}), 503
        
        tier_config = SERVICE_TIERS[tier]
        
        # Create Stripe checkout session
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': f"Tunnelgrain {tier_config['name']}",
                        'description': f"{tier_config['description']} on IP {ip_address}"
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
                'ip_address': ip_address,
                'vps_name': VPS_NAME
            }
        )
        
        return jsonify({'checkout_url': checkout_session.url})
    
    except stripe.error.StripeError as e:
        logger.error(f"[STRIPE] Error creating session: {e}")
        return jsonify({'error': 'Payment system temporarily unavailable. Please try again.'}), 500
    except Exception as e:
        logger.error(f"[CHECKOUT] Error creating session: {e}")
        return jsonify({'error': 'Payment system temporarily unavailable'}), 500

@app.route('/payment-success')
def payment_success():
    """Handle successful payment"""
    session_id = request.args.get('session_id')
    
    if not session_id:
        return "Invalid payment session", 400
    
    try:
        # Retrieve the session from Stripe
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        
        if checkout_session.payment_status != 'paid':
            return "Payment not completed", 400
        
        # Extract metadata
        metadata = checkout_session.metadata
        tier = metadata.get('tier')
        ip_address = metadata.get('ip_address')
        vps_name = metadata.get('vps_name')
        
        # Assign new slot with specific config
        user_fingerprint = get_client_fingerprint(request)
        result = assign_specific_config(tier, user_fingerprint)
        
        if result:
            order_id, order_number, config_id = result
            
            # Store in session for download access
            session['purchase_order'] = order_number
            session['purchase_tier'] = tier
            session['purchase_config'] = config_id
            session['purchase_ip'] = ip_address
            session['purchase_vps'] = vps_name
            
            order_data = {
                'order_id': order_id,
                'order_number': order_number,
                'tier': tier,
                'config_id': config_id,
                'ip_address': ip_address,
                'vps_name': vps_name
            }
            
            logger.info(f"[PAYMENT] New assignment: {order_number}, tier: {tier}, config: {config_id}")
            
            return render_template('payment_success.html', 
                                 order_data=order_data, 
                                 tier_config=SERVICE_TIERS[tier])
        else:
            logger.error(f"[PAYMENT] No available configs for {tier} - session {session_id}")
            return "No slots available for selected plan - contact support", 503
            
    except stripe.error.StripeError as e:
        logger.error(f"[PAYMENT] Stripe error processing payment: {e}")
        return f"Payment verification failed: {str(e)}", 500
    except Exception as e:
        logger.error(f"[PAYMENT] Error processing payment: {e}")
        return f"Error processing payment: {str(e)}", 500

# === DOWNLOAD ROUTES ===

@app.route('/download-test-config')
def download_test_config():
    """Download test VPN config from local files"""
    if 'test_config' not in session:
        return "No test VPN assigned", 404
    
    config_id = session['test_config']
    order_number = session.get('test_order', 'unknown')
    
    # Build local file path
    config_path = os.path.join(DATA_DIR, 'test', f"{config_id}.conf")
    
    if not os.path.exists(config_path):
        logger.error(f"Test config file not found: {config_path}")
        return "Config file not found. Please contact support.", 404
    
    try:
        return send_file(
            config_path,
            as_attachment=True,
            download_name=f"tunnelgrain_{order_number}.conf",
            mimetype='application/octet-stream'
        )
    except Exception as e:
        logger.error(f"Error serving test config: {e}")
        return "Error serving config file. Please contact support.", 500

@app.route('/download-test-qr')
def download_test_qr():
    """Download test VPN QR code from local files"""
    if 'test_config' not in session:
        return "No test VPN assigned", 404
    
    config_id = session['test_config']
    order_number = session.get('test_order', 'unknown')
    
    # Build local file path
    qr_path = os.path.join(QR_DIR, 'test', f"{config_id}.png")
    
    if not os.path.exists(qr_path):
        logger.error(f"Test QR file not found: {qr_path}")
        return "QR code not found. Please contact support.", 404
    
    try:
        return send_file(
            qr_path,
            as_attachment=True,
            download_name=f"tunnelgrain_{order_number}_qr.png",
            mimetype='image/png'
        )
    except Exception as e:
        logger.error(f"Error serving test QR: {e}")
        return "Error serving QR code. Please contact support.", 500

@app.route('/download-purchase-config')
def download_purchase_config():
    """Download purchased VPN config from local files"""
    if 'purchase_config' not in session:
        return "No VPN purchased", 404
    
    config_id = session['purchase_config']
    tier = session.get('purchase_tier')
    order_number = session.get('purchase_order', 'unknown')
    
    # Build local file path
    config_path = os.path.join(DATA_DIR, tier, f"{config_id}.conf")
    
    if not os.path.exists(config_path):
        logger.error(f"Purchase config file not found: {config_path}")
        return "Config file not found. Please contact support.", 404
    
    try:
        return send_file(
            config_path,
            as_attachment=True,
            download_name=f"tunnelgrain_{order_number}.conf",
            mimetype='application/octet-stream'
        )
    except Exception as e:
        logger.error(f"Error serving purchase config: {e}")
        return "Error serving config file. Please contact support.", 500

@app.route('/download-purchase-qr')
def download_purchase_qr():
    """Download purchased VPN QR code from local files"""
    if 'purchase_config' not in session:
        return "No VPN purchased", 404
    
    config_id = session['purchase_config']
    tier = session.get('purchase_tier')
    order_number = session.get('purchase_order', 'unknown')
    
    # Build local file path
    qr_path = os.path.join(QR_DIR, tier, f"{config_id}.png")
    
    if not os.path.exists(qr_path):
        logger.error(f"Purchase QR file not found: {qr_path}")
        return "QR code not found. Please contact support.", 404
    
    try:
        return send_file(
            qr_path,
            as_attachment=True,
            download_name=f"tunnelgrain_{order_number}_qr.png",
            mimetype='image/png'
        )
    except Exception as e:
        logger.error(f"Error serving purchase QR: {e}")
        return "Error serving QR code. Please contact support.", 500

# === ORDER LOOKUP ===

@app.route('/check-order', methods=['POST'])
def check_order():
    """Enhanced order check with detailed status"""
    order_number = request.form.get('order_number', '').strip().upper()
    
    # Validate order number format
    if not (order_number.startswith('42') or order_number.startswith('72')) or len(order_number) != 8:
        return jsonify({'error': 'Invalid order number format'})
    
    # Clean up expired orders first
    cleanup_expired_orders()
    
    # Find order in slots data
    slots_data = load_slots_data()
    order_data = None
    
    for order_id, data in slots_data["orders"].items():
        if data.get("order_number") == order_number:
            order_data = data
            break
    
    if not order_data:
        return jsonify({
            'order_found': False,
            'error': 'Order not found'
        })
    
    # Calculate time remaining
    status = 'unknown'
    time_remaining = 'unknown'
    
    if order_data.get('expires_at'):
        try:
            expires_at = datetime.fromisoformat(order_data['expires_at'])
            now = datetime.now()
            
            if expires_at > now:
                status = 'active'
                time_delta = expires_at - now
                
                if order_data['tier'] == 'test':
                    minutes_remaining = max(0, time_delta.seconds // 60)
                    time_remaining = f"{minutes_remaining} minutes"
                else:
                    days_remaining = max(0, time_delta.days)
                    if days_remaining > 0:
                        time_remaining = f"{days_remaining} days"
                    else:
                        hours_remaining = max(0, time_delta.seconds // 3600)
                        time_remaining = f"{hours_remaining} hours"
            else:
                status = 'expired'
                time_remaining = 'Expired'
        except:
            status = 'unknown'
            time_remaining = 'Unknown'
    
    # Get tier information
    tier_info = SERVICE_TIERS.get(order_data['tier'], {})
    
    return jsonify({
        'order_found': True,
        'tier': order_data['tier'],
        'tier_name': tier_info.get('name', 'Unknown'),
        'status': status,
        'time_remaining': time_remaining,
        'assigned_at': order_data.get('assigned_at', 'unknown'),
        'ip_address': order_data.get('ip_address', 'unknown'),
        'config_id': order_data.get('config_id', 'unknown')
    })

# === ADMIN ROUTES ===

@app.route('/admin')
@admin_required
def admin():
    """Main admin panel"""
    cleanup_expired_orders()
    
    # Get current orders
    slots_data = load_slots_data()
    
    # Get availability statistics
    availability_stats = {}
    for tier_name in SERVICE_TIERS.keys():
        available_configs = get_available_config_files(tier_name)
        availability_stats[tier_name] = {
            'available': len(available_configs),
            'capacity': SERVICE_TIERS[tier_name]['capacity']
        }
    
    vps_report = {
        'vps_status': {VPS_NAME: {
            'status': 'healthy',
            'ip': VPS_IP,
            'tiers': availability_stats
        }},
        'summary': {
            'total_vps': 1,
            'config_files_total': sum(len(get_available_config_files(tier)) for tier in SERVICE_TIERS.keys())
        }
    }
    
    return render_template('admin.html', 
                         vps_report=vps_report,
                         service_tiers=SERVICE_TIERS,
                         orders=slots_data.get('orders', {}))

@app.route('/admin/servers')
@admin_required
def admin_servers():
    """VPS health monitoring dashboard"""
    # Get availability statistics
    availability_stats = {}
    for tier_name in SERVICE_TIERS.keys():
        available_configs = get_available_config_files(tier_name)
        availability_stats[tier_name] = {
            'available': len(available_configs),
            'capacity': SERVICE_TIERS[tier_name]['capacity']
        }
    
    vps_report = {
        'vps_status': {VPS_NAME: {
            'status': 'healthy',
            'server_ip': VPS_IP,
            'tiers': availability_stats,
            'timestamp': datetime.now().isoformat()
        }},
        'summary': {
            'total_vps': 1,
            'revenue_potential': sum(tier['price_cents'] * tier['capacity'] 
                                   for tier in SERVICE_TIERS.values() if tier['price_cents'] > 0)
        },
        'timestamp': datetime.now().isoformat()
    }
    return render_template('admin_servers.html', vps_report=vps_report)

@app.route('/admin/force-cleanup', methods=['POST'])
@admin_required
def admin_force_cleanup():
    """Force cleanup of expired orders"""
    try:
        expired_count = cleanup_expired_orders()
        
        return jsonify({
            'success': True,
            'expired_count': expired_count,
            'message': f'Cleaned up {expired_count} expired orders and freed their config files'
        })
        
    except Exception as e:
        logger.error(f"[ADMIN] Force cleanup error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# === API ENDPOINTS ===

@app.route('/api/status')
def api_status():
    """Public API endpoint for service status"""
    try:
        # Get real availability from local files
        tier_availability = {}
        for tier_name, tier_config in SERVICE_TIERS.items():
            available_configs = get_available_config_files(tier_name)
            tier_availability[tier_name] = {
                'available': len(available_configs),
                'capacity': tier_config['capacity'],
                'price_cents': tier_config['price_cents']
            }
        
        return jsonify({
            'status': 'operational',
            'timestamp': datetime.now().isoformat(),
            'tiers': tier_availability,
            'vps_count': 1,
            'vps_ip': VPS_IP,
            'database_type': 'JSON + Local Files'
        })
        
    except Exception as e:
        logger.error(f"[API] Status error: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

@app.route('/api/health')
def api_health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'tunnelgrain-enhanced',
        'version': '3.1.0',
        'timestamp': datetime.now().isoformat(),
        'admin_key_configured': bool(ADMIN_KEY),
        'stripe_configured': bool(STRIPE_PUBLISHABLE_KEY and STRIPE_SECRET_KEY),
        'local_files': {
            'data_dir_exists': os.path.exists(DATA_DIR),
            'qr_dir_exists': os.path.exists(QR_DIR)
        }
    })

# === ERROR HANDLERS ===

@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal error: {error}")
    return render_template('500.html'), 500

if __name__ == '__main__':
    # Create directories if they don't exist
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    
    # Verify local file structure
    if not os.path.exists(DATA_DIR):
        logger.error(f"❌ Data directory not found: {DATA_DIR}")
    else:
        logger.info(f"✅ Data directory found: {DATA_DIR}")
        
    if not os.path.exists(QR_DIR):
        logger.error(f"❌ QR code directory not found: {QR_DIR}")
    else:
        logger.info(f"✅ QR code directory found: {QR_DIR}")
    
    # Log startup information
    logger.info("🚀 Tunnelgrain VPN Service Starting...")
    logger.info(f"Admin Key: {'Configured' if ADMIN_KEY else 'Not Set'}")
    logger.info(f"Stripe: {'Configured' if STRIPE_PUBLISHABLE_KEY else 'Not Configured'}")
    logger.info(f"VPS IP: {VPS_IP}")
    logger.info(f"Service Tiers: {list(SERVICE_TIERS.keys())}")
    
    # Check config file availability
    for tier_name in SERVICE_TIERS.keys():
        available = len(get_available_config_files(tier_name))
        capacity = SERVICE_TIERS[tier_name]['capacity']
        logger.info(f"Tier {tier_name}: {available}/{capacity} configs available")
    
    app.run(debug=True, host='0.0.0.0', port=5000)