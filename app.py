from flask import Flask, render_template, request, send_file, jsonify, session, redirect, url_for, abort
import os
import logging
from datetime import datetime, timedelta
import stripe
import uuid
import hashlib
from functools import wraps
import glob
import random
from database_manager import TunnelgrainDB

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-in-production-very-secret-key')

# Initialize database
try:
    db = TunnelgrainDB()
    logger.info("✅ Database initialized successfully")
except Exception as e:
    logger.error(f"❌ Database initialization failed: {e}")
    raise

# Stripe Configuration
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')

if not STRIPE_PUBLISHABLE_KEY or not STRIPE_SECRET_KEY:
    logger.error("❌ Stripe keys not configured - payments will not work")
    raise ValueError("Stripe keys are required")
else:
    stripe.api_key = STRIPE_SECRET_KEY
    logger.info("✅ Stripe configured successfully")

# Admin security key
ADMIN_KEY = os.environ.get('ADMIN_KEY', 'Freud@')

# VPS Configuration
VPS_IP = "213.170.133.116"
VPS_ENDPOINT = os.environ.get('VPS_1_ENDPOINT', f'http://{VPS_IP}:8080')
VPS_NAME = "primary_vps"

# Local file paths (for serving configs/QR codes)
DATA_DIR = "data/vps_1/ip_213.170.133.116"
QR_DIR = "static/qr_codes/vps_1/ip_213.170.133.116"

# Service Tiers
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

# Admin authentication decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        provided_key = request.args.get('key') or request.headers.get('X-Admin-Key')
        if provided_key != ADMIN_KEY:
            logger.warning(f"Admin access denied. Expected: {ADMIN_KEY}, Got: {provided_key}")
            abort(404)
        return f(*args, **kwargs)
    return decorated_function

# Utility functions
def get_client_fingerprint(request):
    """Create a privacy-respecting fingerprint for abuse prevention"""
    ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
    user_agent = request.headers.get('User-Agent', '')
    fingerprint_data = f"{ip}:{user_agent}"
    return hashlib.sha256(fingerprint_data.encode()).hexdigest()[:16]

def get_available_config_files(tier: str):
    """Get list of available config files for a tier"""
    config_dir = os.path.join(DATA_DIR, tier)
    if not os.path.exists(config_dir):
        logger.error(f"Config directory not found: {config_dir}")
        return []
    
    config_files = glob.glob(os.path.join(config_dir, "*.conf"))
    available_configs = []
    
    for config_path in config_files:
        config_filename = os.path.basename(config_path)
        config_id = config_filename.replace('.conf', '')
        available_configs.append(config_id)
    
    return available_configs

def get_random_config_id(tier: str):
    """Get a random available config ID for a tier"""
    available_configs = get_available_config_files(tier)
    if not available_configs:
        return None
    return random.choice(available_configs)

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
    """Assign a 15-minute test VPN with proper database tracking and real expiration"""
    try:
        # Clean up expired orders first
        db.cleanup_expired_orders()
        
        # Get available config
        config_id = get_random_config_id('test')
        if not config_id:
            return jsonify({
                'error': 'No test slots available. Please try again later or purchase a paid plan.',
                'suggestion': 'All test configurations are currently in use.'
            }), 503
        
        user_fingerprint = get_client_fingerprint(request)
        
        # Create order in database with VPS timer
        order_id, order_number = db.create_order(
            tier='test',
            config_id=config_id,
            user_fingerprint=user_fingerprint
        )
        
        if not order_id:
            return jsonify({
                'error': 'Failed to create test order. You may have exceeded the daily limit (3 tests per day).',
                'suggestion': 'Please try again tomorrow or purchase a paid plan.'
            }), 429
        
        # Store in session for download
        session['test_slot'] = order_id
        session['test_order'] = order_number
        session['test_config'] = config_id
        session['test_expires'] = (datetime.now() + timedelta(minutes=15)).isoformat()
        
        logger.info(f"✅ Test VPN assigned: {order_number} (config: {config_id})")
        
        return jsonify({
            'success': True,
            'order_id': order_id,
            'order_number': order_number,
            'config_id': config_id,
            'expires_in_minutes': 15,
            'download_url': url_for('download_test_config'),
            'message': 'Test VPN assigned successfully. Config will expire in 15 minutes.'
        })
        
    except Exception as e:
        logger.error(f"❌ Test VPN error: {e}")
        return jsonify({
            'error': 'Service temporarily unavailable. Please try again.',
            'technical_details': str(e) if app.debug else None
        }), 500

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    """Create Stripe checkout session for VPN purchase with proper error handling"""
    try:
        data = request.json
        tier = data.get('tier')
        ip_address = data.get('ip_address', VPS_IP)
        
        # Validate tier
        if tier not in SERVICE_TIERS or tier == 'test':
            return jsonify({'error': 'Invalid service tier'}), 400
        
        # Check availability
        config_id = get_random_config_id(tier)
        if not config_id:
            return jsonify({
                'error': f'No {tier} slots available. Please try again later or choose a different plan.',
                'suggestion': 'All configurations for this tier are currently in use.'
            }), 503
        
        tier_config = SERVICE_TIERS[tier]
        
        # Create Stripe checkout session with proper error handling
        try:
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {
                            'name': f"Tunnelgrain {tier_config['name']}",
                            'description': f"{tier_config['description']} on IP {ip_address}",
                            'images': []  # Add your logo URL here if you have one
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
                    'config_id': config_id,
                    'ip_address': ip_address,
                    'vps_name': VPS_NAME
                },
                billing_address_collection='auto',
                phone_number_collection={'enabled': False},
                customer_creation='if_required'
            )
            
            logger.info(f"✅ Stripe session created: {checkout_session.id} for tier {tier}")
            
            return jsonify({
                'checkout_url': checkout_session.url,
                'session_id': checkout_session.id
            })
            
        except stripe.error.CardError as e:
            logger.error(f"❌ Stripe card error: {e}")
            return jsonify({'error': 'Card was declined. Please try a different payment method.'}), 400
        
        except stripe.error.RateLimitError as e:
            logger.error(f"❌ Stripe rate limit: {e}")
            return jsonify({'error': 'Too many requests. Please try again in a moment.'}), 429
        
        except stripe.error.InvalidRequestError as e:
            logger.error(f"❌ Stripe invalid request: {e}")
            return jsonify({'error': 'Invalid payment request. Please try again.'}), 400
        
        except stripe.error.AuthenticationError as e:
            logger.error(f"❌ Stripe authentication error: {e}")
            return jsonify({'error': 'Payment system configuration error. Please contact support.'}), 500
        
        except stripe.error.APIConnectionError as e:
            logger.error(f"❌ Stripe connection error: {e}")
            return jsonify({'error': 'Unable to connect to payment system. Please try again.'}), 503
        
        except stripe.error.StripeError as e:
            logger.error(f"❌ Generic Stripe error: {e}")
            return jsonify({'error': 'Payment system temporarily unavailable. Please try again.'}), 500
    
    except Exception as e:
        logger.error(f"❌ Checkout session creation error: {e}")
        return jsonify({
            'error': 'Service temporarily unavailable. Please try again.',
            'technical_details': str(e) if app.debug else None
        }), 500

@app.route('/payment-success')
def payment_success():
    """Handle successful payment with proper validation"""
    session_id = request.args.get('session_id')
    
    if not session_id:
        logger.error("❌ Payment success called without session_id")
        return "Invalid payment session", 400
    
    try:
        # Retrieve the session from Stripe with expanded data
        checkout_session = stripe.checkout.Session.retrieve(
            session_id,
            expand=['customer', 'payment_intent']
        )
        
        if checkout_session.payment_status != 'paid':
            logger.error(f"❌ Payment not completed for session {session_id}: {checkout_session.payment_status}")
            return f"Payment not completed. Status: {checkout_session.payment_status}", 400
        
        # Extract metadata
        metadata = checkout_session.metadata
        tier = metadata.get('tier')
        config_id = metadata.get('config_id')
        ip_address = metadata.get('ip_address', VPS_IP)
        vps_name = metadata.get('vps_name', VPS_NAME)
        
        if not all([tier, config_id]):
            logger.error(f"❌ Missing metadata in session {session_id}")
            return "Invalid payment data", 400
        
        # Create order with VPS timer
        user_fingerprint = get_client_fingerprint(request)
        order_id, order_number = db.create_order(
            tier=tier,
            config_id=config_id,
            user_fingerprint=user_fingerprint,
            stripe_session_id=session_id
        )
        
        if order_id:
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
            
            logger.info(f"✅ Payment successful: {order_number}, tier: {tier}, config: {config_id}")
            
            return render_template('payment_success.html', 
                                 order_data=order_data, 
                                 tier_config=SERVICE_TIERS[tier])
        else:
            logger.error(f"❌ Failed to create order for paid session {session_id}")
            return "Order creation failed - please contact support with your payment confirmation", 500
            
    except stripe.error.StripeError as e:
        logger.error(f"❌ Stripe error during payment success: {e}")
        return f"Payment verification failed: {str(e)}", 500
    except Exception as e:
        logger.error(f"❌ Payment success processing error: {e}")
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
        logger.error(f"❌ Test config file not found: {config_path}")
        return "Config file not found. Please contact support.", 404
    
    try:
        logger.info(f"✅ Serving test config: {order_number} ({config_id})")
        return send_file(
            config_path,
            as_attachment=True,
            download_name=f"tunnelgrain_{order_number}.conf",
            mimetype='application/octet-stream'
        )
    except Exception as e:
        logger.error(f"❌ Error serving test config: {e}")
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
        logger.error(f"❌ Test QR file not found: {qr_path}")
        return "QR code not found. Please contact support.", 404
    
    try:
        logger.info(f"✅ Serving test QR: {order_number} ({config_id})")
        return send_file(
            qr_path,
            as_attachment=True,
            download_name=f"tunnelgrain_{order_number}_qr.png",
            mimetype='image/png'
        )
    except Exception as e:
        logger.error(f"❌ Error serving test QR: {e}")
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
        logger.error(f"❌ Purchase config file not found: {config_path}")
        return "Config file not found. Please contact support.", 404
    
    try:
        logger.info(f"✅ Serving purchase config: {order_number} ({tier}/{config_id})")
        return send_file(
            config_path,
            as_attachment=True,
            download_name=f"tunnelgrain_{order_number}.conf",
            mimetype='application/octet-stream'
        )
    except Exception as e:
        logger.error(f"❌ Error serving purchase config: {e}")
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
        logger.error(f"❌ Purchase QR file not found: {qr_path}")
        return "QR code not found. Please contact support.", 404
    
    try:
        logger.info(f"✅ Serving purchase QR: {order_number} ({tier}/{config_id})")
        return send_file(
            qr_path,
            as_attachment=True,
            download_name=f"tunnelgrain_{order_number}_qr.png",
            mimetype='image/png'
        )
    except Exception as e:
        logger.error(f"❌ Error serving purchase QR: {e}")
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
    db.cleanup_expired_orders()
    
    # Get order from database
    order_data = db.get_order_by_number(order_number)
    
    if not order_data:
        return jsonify({
            'order_found': False,
            'error': 'Order not found'
        })
    
    # Calculate time remaining
    status = 'unknown'
    time_remaining = 'unknown'
    
    expires_at = order_data.get('expires_at')
    if expires_at:
        try:
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            
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
        except Exception as e:
            logger.error(f"❌ Error calculating time remaining: {e}")
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
        'assigned_at': order_data.get('created_at', 'unknown'),
        'ip_address': order_data.get('vps_ip', 'unknown'),
        'config_id': order_data.get('config_id', 'unknown'),
        'timer_started': order_data.get('timer_started', False)
    })

# === ADMIN ROUTES ===

@app.route('/admin')
@admin_required
def admin():
    """Main admin panel with real database data"""
    db.cleanup_expired_orders()
    
    # Get current orders from database
    orders = db.get_all_orders()
    
    # Convert to dict format for template compatibility
    orders_dict = {order['order_id']: order for order in orders}
    
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
                         orders=orders_dict)

@app.route('/admin/force-cleanup', methods=['POST'])
@admin_required
def admin_force_cleanup():
    """Force cleanup of expired orders"""
    try:
        expired_count = db.cleanup_expired_orders()
        
        return jsonify({
            'success': True,
            'expired_count': expired_count,
            'message': f'Cleaned up {expired_count} expired orders'
        })
        
    except Exception as e:
        logger.error(f"❌ Admin force cleanup error: {e}")
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
            'database_type': 'PostgreSQL',
            'vps_endpoint': VPS_ENDPOINT
        })
        
    except Exception as e:
        logger.error(f"❌ API status error: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

@app.route('/api/health')
def api_health():
    """Health check endpoint"""
    try:
        db_health = db.health_check()
        
        return jsonify({
            'status': 'healthy',
            'service': 'tunnelgrain-fixed',
            'version': '4.1.0',
            'timestamp': datetime.now().isoformat(),
            'admin_key_configured': bool(ADMIN_KEY),
            'stripe_configured': bool(STRIPE_PUBLISHABLE_KEY and STRIPE_SECRET_KEY),
            'database': db_health,
            'vps_endpoint': VPS_ENDPOINT,
            'local_files': {
                'data_dir_exists': os.path.exists(DATA_DIR),
                'qr_dir_exists': os.path.exists(QR_DIR)
            }
        })
        
    except Exception as e:
        logger.error(f"❌ Health check error: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

# === ERROR HANDLERS ===

@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"❌ Internal error: {error}")
    return render_template('500.html'), 500

if __name__ == '__main__':
    # Verify setup
    logger.info("🚀 Tunnelgrain VPN Service Starting...")
    logger.info(f"Admin Key: {'✅ Configured' if ADMIN_KEY else '❌ Not Set'}")
    logger.info(f"Stripe: {'✅ Configured' if STRIPE_PUBLISHABLE_KEY else '❌ Not Configured'}")
    logger.info(f"VPS IP: {VPS_IP}")
    logger.info(f"VPS Endpoint: {VPS_ENDPOINT}")
    logger.info(f"Service Tiers: {list(SERVICE_TIERS.keys())}")
    
    # Check config file availability
    for tier_name in SERVICE_TIERS.keys():
        available = len(get_available_config_files(tier_name))
        capacity = SERVICE_TIERS[tier_name]['capacity']
        logger.info(f"Tier {tier_name}: {available}/{capacity} configs available")
    
    # Verify data directories exist
    if not os.path.exists(DATA_DIR):
        logger.error(f"❌ Data directory not found: {DATA_DIR}")
    else:
        logger.info(f"✅ Data directory found: {DATA_DIR}")
        
    if not os.path.exists(QR_DIR):
        logger.error(f"❌ QR code directory not found: {QR_DIR}")
    else:
        logger.info(f"✅ QR code directory found: {QR_DIR}")
    
    app.run(debug=True, host='0.0.0.0', port=5000)