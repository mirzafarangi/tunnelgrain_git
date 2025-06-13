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

# VPS Configuration
VPS_ENDPOINT = os.environ.get('VPS_1_ENDPOINT', 'http://213.170.133.116:8080')
VPS_NAME = os.environ.get('VPS_1_NAME', 'primary_vps')

# Service Tiers - MUST MATCH YOUR VPS SETUP EXACTLY
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

# Simple slot tracking for fallback (if database not available)
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
        "last_cleanup": datetime.now().isoformat()
    }

def save_slots_data(data):
    """Save slots data to JSON file"""
    try:
        with open(SLOTS_FILE, 'w') as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"Error saving slots: {e}")

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

def get_vps_status():
    """Get status from VPS API"""
    try:
        import requests
        response = requests.get(f"{VPS_ENDPOINT}/api/status", timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.error(f"VPS status error: {e}")
    
    return None

def assign_vpn_slot(tier: str, user_fingerprint: str):
    """Assign VPN slot - simplified version"""
    try:
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
            "ip_address": "213.170.133.116",  # Your VPS IP
            "vps_name": VPS_NAME,
            "status": "active",
            "assigned_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "user_fingerprint": user_fingerprint
        }
        
        save_slots_data(slots_data)
        
        logger.info(f"Assigned {tier} slot {order_number} to {user_fingerprint}")
        return order_id, order_number
        
    except Exception as e:
        logger.error(f"Error assigning slot: {e}")
        return None

def cleanup_expired_orders():
    """Clean up expired orders"""
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
                except Exception:
                    pass
        
        if expired_count > 0:
            save_slots_data(slots_data)
            logger.info(f"Expired {expired_count} orders")
            
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
    # Get available IPs (simplified - just your one VPS)
    available_ips = {
        'monthly': [{'ip_address': '213.170.133.116', 'vps_name': VPS_NAME, 'available_slots': 30}],
        'quarterly': [{'ip_address': '213.170.133.116', 'vps_name': VPS_NAME, 'available_slots': 20}],
        'biannual': [{'ip_address': '213.170.133.116', 'vps_name': VPS_NAME, 'available_slots': 15}],
        'annual': [{'ip_address': '213.170.133.116', 'vps_name': VPS_NAME, 'available_slots': 10}],
        'lifetime': [{'ip_address': '213.170.133.116', 'vps_name': VPS_NAME, 'available_slots': 5}],
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
    
    # Assign slot
    result = assign_vpn_slot('test', user_fingerprint)
    
    if not result:
        return jsonify({
            'error': 'Failed to assign test slot. Please try again.'
        }), 503
    
    order_id, order_number = result
    
    # Store in session for download
    session['test_slot'] = order_id
    session['test_order'] = order_number
    session['test_expires'] = (datetime.now() + timedelta(minutes=15)).isoformat()
    
    logger.info(f"[TEST] User {user_fingerprint} assigned {order_number}")
    
    return jsonify({
        'success': True,
        'order_id': order_id,
        'order_number': order_number,
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
        ip_address = data.get('ip_address', '213.170.133.116')
        
        # Validate tier
        if tier not in SERVICE_TIERS or tier == 'test':
            return jsonify({'error': 'Invalid service tier'}), 400
        
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
        
        # Assign new slot
        user_fingerprint = get_client_fingerprint(request)
        result = assign_vpn_slot(tier, user_fingerprint)
        
        if result:
            order_id, order_number = result
            
            # Store in session for download access
            session['purchase_order'] = order_number
            session['purchase_tier'] = tier
            session['purchase_ip'] = ip_address
            session['purchase_vps'] = vps_name
            
            order_data = {
                'order_id': order_id,
                'order_number': order_number,
                'tier': tier,
                'ip_address': ip_address,
                'vps_name': vps_name
            }
            
            logger.info(f"[PAYMENT] New assignment: {order_number}, tier: {tier}")
            
            return render_template('payment_success.html', 
                                 order_data=order_data, 
                                 tier_config=SERVICE_TIERS[tier])
        else:
            logger.error(f"[PAYMENT] Failed to assign slot for session {session_id}")
            return "No slots available - contact support", 503
            
    except Exception as e:
        logger.error(f"[PAYMENT] Error processing payment: {e}")
        return f"Error processing payment: {str(e)}", 500

# === DOWNLOAD ROUTES ===

@app.route('/download-test-config')
def download_test_config():
    """Download test VPN config"""
    if 'test_order' not in session:
        return "No test VPN assigned", 404
    
    order_number = session['test_order']
    
    # Config file should be downloaded from VPS or stored locally
    # For now, serve from VPS API
    try:
        import requests
        config_url = f"{VPS_ENDPOINT}/api/config/test/{order_number}"
        response = requests.get(config_url, timeout=30)
        
        if response.status_code == 200:
            return response.content, 200, {
                'Content-Type': 'application/octet-stream',
                'Content-Disposition': f'attachment; filename=tunnelgrain_{order_number}.conf'
            }
        else:
            return "Config file not found. Please contact support.", 404
            
    except Exception as e:
        logger.error(f"Error downloading test config: {e}")
        return "Config file not available. Please contact support.", 500

@app.route('/download-test-qr')
def download_test_qr():
    """Download test VPN QR code"""
    if 'test_order' not in session:
        return "No test VPN assigned", 404
    
    order_number = session['test_order']
    
    try:
        import requests
        qr_url = f"{VPS_ENDPOINT}/api/qr/test/{order_number}"
        response = requests.get(qr_url, timeout=30)
        
        if response.status_code == 200:
            return response.content, 200, {
                'Content-Type': 'image/png',
                'Content-Disposition': f'attachment; filename=tunnelgrain_{order_number}_qr.png'
            }
        else:
            return "QR code not found. Please contact support.", 404
            
    except Exception as e:
        logger.error(f"Error downloading test QR: {e}")
        return "QR code not available. Please contact support.", 500

@app.route('/download-purchase-config')
def download_purchase_config():
    """Download purchased VPN config"""
    if 'purchase_order' not in session:
        return "No VPN purchased", 404
    
    order_number = session['purchase_order']
    tier = session.get('purchase_tier')
    
    try:
        import requests
        config_url = f"{VPS_ENDPOINT}/api/config/{tier}/{order_number}"
        response = requests.get(config_url, timeout=30)
        
        if response.status_code == 200:
            return response.content, 200, {
                'Content-Type': 'application/octet-stream',
                'Content-Disposition': f'attachment; filename=tunnelgrain_{order_number}.conf'
            }
        else:
            return "Config file not found. Please contact support.", 404
            
    except Exception as e:
        logger.error(f"Error downloading purchase config: {e}")
        return "Config file not available. Please contact support.", 500

@app.route('/download-purchase-qr')
def download_purchase_qr():
    """Download purchased VPN QR code"""
    if 'purchase_order' not in session:
        return "No VPN purchased", 404
    
    order_number = session['purchase_order']
    tier = session.get('purchase_tier')
    
    try:
        import requests
        qr_url = f"{VPS_ENDPOINT}/api/qr/{tier}/{order_number}"
        response = requests.get(qr_url, timeout=30)
        
        if response.status_code == 200:
            return response.content, 200, {
                'Content-Type': 'image/png',
                'Content-Disposition': f'attachment; filename=tunnelgrain_{order_number}_qr.png'
            }
        else:
            return "QR code not found. Please contact support.", 404
            
    except Exception as e:
        logger.error(f"Error downloading purchase QR: {e}")
        return "QR code not available. Please contact support.", 500

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
        'ip_address': order_data.get('ip_address', 'unknown')
    })

# === ADMIN ROUTES ===

@app.route('/admin')
@admin_required
def admin():
    """Main admin panel"""
    cleanup_expired_orders()
    
    # Get VPS status
    vps_status = get_vps_status()
    
    # Get current orders
    slots_data = load_slots_data()
    
    return render_template('admin.html', 
                         vps_report={'vps_status': {VPS_NAME: vps_status} if vps_status else {}},
                         service_tiers=SERVICE_TIERS,
                         orders=slots_data.get('orders', {}))

@app.route('/admin/servers')
@admin_required
def admin_servers():
    """VPS health monitoring dashboard"""
    vps_status = get_vps_status()
    vps_report = {
        'vps_status': {VPS_NAME: vps_status} if vps_status else {},
        'summary': {
            'total_vps': 1,
            'revenue_potential': sum(tier['price_cents'] * tier['capacity'] 
                                   for tier in SERVICE_TIERS.values() if tier['price_cents'] > 0)
        }
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
            'message': f'Cleaned up {expired_count} expired orders'
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
        vps_status = get_vps_status()
        
        # Build tier availability from VPS status or fallback
        tier_availability = {}
        for tier_name, tier_config in SERVICE_TIERS.items():
            if vps_status and 'tiers' in vps_status:
                vps_tier_data = vps_status['tiers'].get(tier_name, {})
                available = vps_tier_data.get('available', tier_config['capacity'])
            else:
                available = tier_config['capacity']
            
            tier_availability[tier_name] = {
                'available': available,
                'capacity': tier_config['capacity'],
                'price_cents': tier_config['price_cents']
            }
        
        return jsonify({
            'status': 'operational',
            'timestamp': datetime.now().isoformat(),
            'tiers': tier_availability,
            'vps_count': 1,
            'database_type': 'JSON Fallback'
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
        'version': '3.0.0',
        'timestamp': datetime.now().isoformat(),
        'admin_key_configured': bool(ADMIN_KEY)
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
    
    # Log startup information
    logger.info("🚀 Tunnelgrain VPN Service Starting...")
    logger.info(f"Admin Key: {'Configured' if ADMIN_KEY else 'Not Set'}")
    logger.info(f"Stripe: {'Configured' if STRIPE_PUBLISHABLE_KEY else 'Not Configured'}")
    logger.info(f"VPS Endpoint: {VPS_ENDPOINT}")
    logger.info(f"Service Tiers: {list(SERVICE_TIERS.keys())}")
    
    app.run(debug=True, host='0.0.0.0', port=5000)