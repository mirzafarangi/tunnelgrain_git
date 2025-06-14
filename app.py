from flask import Flask, render_template, request, send_file, jsonify, session, redirect, url_for, abort
import os
import logging
from datetime import datetime, timedelta
import stripe
import uuid
import hashlib
from functools import wraps
import io
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
VPS_ENDPOINT = os.environ.get('VPS_1_ENDPOINT', f'http://{VPS_IP}:8081')
VPS_NAME = "primary_vps"

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
            logger.warning(f"Admin access denied. Key mismatch")
            abort(404)
        return f(*args, **kwargs)
    return decorated_function

# Utility functions
def get_client_fingerprint(request):
    """Create a privacy-respecting fingerprint for abuse prevention"""
    real_ip = None
    
    # Try different headers that Render might use
    for header in ['X-Real-IP', 'X-Forwarded-For', 'CF-Connecting-IP', 'True-Client-Ip']:
        ip_value = request.headers.get(header)
        if ip_value:
            real_ip = ip_value.split(',')[0].strip()
            break
    
    if not real_ip:
        real_ip = request.remote_addr
    
    user_agent = request.headers.get('User-Agent', 'unknown')
    fingerprint_data = f"{real_ip}:{user_agent}"
    fingerprint = hashlib.sha256(fingerprint_data.encode()).hexdigest()[:16]
    
    logger.info(f"Fingerprint created: {fingerprint} from IP: {real_ip}")
    return fingerprint

def get_real_config_path(config_id, tier, vps_name='vps_1', vps_ip='213.170.133.116'):
    """Get the path to the real config file"""
    config_path = f"data/{vps_name}/ip_{vps_ip}/{tier}/{config_id}.conf"
    return config_path

def get_real_qr_path(config_id, tier, vps_name='vps_1', vps_ip='213.170.133.116'):
    """Get the path to the real QR code file"""
    qr_path = f"static/qr_codes/{vps_name}/ip_{vps_ip}/{tier}/{config_id}.png"
    return qr_path

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
    # Get available slots from database
    availability = db.get_slot_availability()
    
    available_slots = {}
    for tier_name, tier_data in SERVICE_TIERS.items():
        if tier_name != 'test':
            available_slots[tier_name] = availability.get(tier_name, {}).get('available', 0)
    
    # Simplified available IPs structure
    available_ips = {
        tier_name: [{'ip_address': VPS_IP, 'vps_name': VPS_NAME, 'available_slots': available_slots.get(tier_name, 0)}]
        for tier_name in SERVICE_TIERS.keys() if tier_name != 'test'
    }
    
    logger.info(f"Order page loaded with availability: {available_slots}")
    
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
    """Assign a 15-minute test VPN"""
    try:
        # Clean up expired orders first
        db.cleanup_expired_orders()
        
        # Get user fingerprint
        user_fingerprint = get_client_fingerprint(request)
        logger.info(f"Test VPN request from fingerprint: {user_fingerprint}")
        
        # Create order in database (config will be auto-assigned)
        order_id, order_number = db.create_order(
            tier='test',
            user_fingerprint=user_fingerprint
        )
        
        if not order_id:
            logger.error(f"Failed to create test order")
            return jsonify({
                'error': 'No test slots available. Please try again later.',
                'suggestion': 'All test slots are currently in use.'
            }), 503
        
        # Get the order details to find the assigned config
        order_data = db.get_order_by_number(order_number)
        if not order_data:
            logger.error(f"Created order {order_number} but can't retrieve it")
            return jsonify({
                'error': 'Order creation error. Please try again.',
                'suggestion': 'Database synchronization issue.'
            }), 500
        
        config_id = order_data.get('config_id')
        
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
        logger.error(f"❌ Test VPN error: {e}", exc_info=True)
        return jsonify({
            'error': 'Service temporarily unavailable. Please try again.',
            'technical_details': str(e)
        }), 500

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
        availability = db.get_slot_availability()
        tier_availability = availability.get(tier, {})
        
        if tier_availability.get('available', 0) <= 0:
            return jsonify({
                'error': f'No {tier} slots available. Please try again later.',
                'suggestion': 'All slots for this tier are currently in use.'
            }), 503
        
        tier_config = SERVICE_TIERS[tier]
        
        # Create Stripe checkout session
        try:
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {
                            'name': f"Tunnelgrain {tier_config['name']}",
                            'description': f"{tier_config['description']} on IP {ip_address}",
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
                },
                billing_address_collection='auto',
                customer_creation='if_required'
            )
            
            logger.info(f"✅ Stripe session created: {checkout_session.id} for tier {tier}")
            
            return jsonify({
                'checkout_url': checkout_session.url,
                'session_id': checkout_session.id
            })
            
        except stripe.error.StripeError as e:
            logger.error(f"❌ Stripe error: {e}")
            return jsonify({'error': 'Payment system error. Please try again.'}), 500
    
    except Exception as e:
        logger.error(f"❌ Checkout session creation error: {e}")
        return jsonify({
            'error': 'Service temporarily unavailable. Please try again.',
            'technical_details': str(e) if app.debug else None
        }), 500

@app.route('/payment-success')
def payment_success():
    """Handle successful payment"""
    session_id = request.args.get('session_id')
    
    if not session_id:
        logger.error("❌ Payment success called without session_id")
        return "Invalid payment session", 400
    
    try:
        # Retrieve the session from Stripe
        checkout_session = stripe.checkout.Session.retrieve(
            session_id,
            expand=['customer', 'payment_intent']
        )
        
        if checkout_session.payment_status != 'paid':
            logger.error(f"❌ Payment not completed for session {session_id}")
            return f"Payment not completed. Status: {checkout_session.payment_status}", 400
        
        # Extract metadata
        metadata = checkout_session.metadata
        tier = metadata.get('tier')
        ip_address = metadata.get('ip_address', VPS_IP)
        vps_name = metadata.get('vps_name', VPS_NAME)
        
        if not tier:
            logger.error(f"❌ Missing tier in session {session_id}")
            return "Invalid payment data", 400
        
        # Create order (config will be auto-assigned)
        user_fingerprint = get_client_fingerprint(request)
        order_id, order_number = db.create_order(
            tier=tier,
            user_fingerprint=user_fingerprint,
            stripe_session_id=session_id
        )
        
        show_support_message = False
        
        if order_id:
            # Get the order details to find the assigned config
            order_data = db.get_order_by_number(order_number)
            if order_data:
                config_id = order_data.get('config_id')
                
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
            else:
                show_support_message = True
                order_data = {
                    'order_id': str(uuid.uuid4()),
                    'order_number': f"SUPPORT-{uuid.uuid4().hex[:6].upper()}",
                    'tier': tier,
                    'config_id': 'ERROR',
                    'ip_address': ip_address,
                    'vps_name': vps_name
                }
        else:
            logger.error(f"❌ Failed to create order for paid session {session_id}")
            show_support_message = True
            order_data = {
                'order_id': str(uuid.uuid4()),
                'order_number': f"SUPPORT-{uuid.uuid4().hex[:6].upper()}",
                'tier': tier,
                'config_id': 'ERROR',
                'ip_address': ip_address,
                'vps_name': vps_name
            }
        
        return render_template('payment_success.html', 
                             order_data=order_data, 
                             tier_config=SERVICE_TIERS[tier],
                             show_support_message=show_support_message)
            
    except Exception as e:
        logger.error(f"❌ Payment success processing error: {e}", exc_info=True)
        return f"Error processing payment: {str(e)}", 500

# === DOWNLOAD ROUTES ===

@app.route('/download-test-config')
def download_test_config():
    """Download test VPN config"""
    if 'test_config' not in session:
        return "No test VPN assigned", 404
    
    config_id = session['test_config']
    order_number = session.get('test_order', 'unknown')
    
    try:
        # Get path to real config file
        config_path = get_real_config_path(config_id, 'test')
        
        # Check if file exists
        if not os.path.exists(config_path):
            logger.error(f"Config file not found: {config_path}")
            return "Config file not found. Please contact support.", 404
        
        logger.info(f"✅ Serving test config: {order_number} ({config_id}) from {config_path}")
        
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
    """Download test VPN QR code"""
    if 'test_config' not in session:
        return "No test VPN assigned", 404
    
    config_id = session['test_config']
    order_number = session.get('test_order', 'unknown')
    
    try:
        # Get path to real QR file
        qr_path = get_real_qr_path(config_id, 'test')
        
        # Check if file exists
        if not os.path.exists(qr_path):
            logger.error(f"QR file not found: {qr_path}")
            return "QR code not found. Please contact support.", 404
        
        logger.info(f"✅ Serving test QR: {order_number} ({config_id}) from {qr_path}")
        
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
    """Download purchased VPN config"""
    if 'purchase_config' not in session:
        return "No VPN purchased", 404
    
    config_id = session['purchase_config']
    tier = session.get('purchase_tier')
    order_number = session.get('purchase_order', 'unknown')
    
    try:
        # Get path to real config file
        config_path = get_real_config_path(config_id, tier)
        
        # Check if file exists
        if not os.path.exists(config_path):
            logger.error(f"Config file not found: {config_path}")
            return "Config file not found. Please contact support.", 404
        
        logger.info(f"✅ Serving purchase config: {order_number} ({tier}/{config_id}) from {config_path}")
        
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
    """Download purchased VPN QR code"""
    if 'purchase_config' not in session:
        return "No VPN purchased", 404
    
    config_id = session['purchase_config']
    tier = session.get('purchase_tier')
    order_number = session.get('purchase_order', 'unknown')
    
    try:
        # Get path to real QR file
        qr_path = get_real_qr_path(config_id, tier)
        
        # Check if file exists
        if not os.path.exists(qr_path):
            logger.error(f"QR file not found: {qr_path}")
            return "QR code not found. Please contact support.", 404
        
        logger.info(f"✅ Serving purchase QR: {order_number} ({tier}/{config_id}) from {qr_path}")
        
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
    """Check order status"""
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
    """Main admin panel"""
    try:
        db.cleanup_expired_orders()
        
        # Get current orders
        orders = db.get_all_orders()
        
        # Convert to dict format
        orders_dict = {}
        for order in orders:
            if order and order.get('order_id'):
                order_copy = order.copy()
                for key, value in order_copy.items():
                    if isinstance(value, datetime):
                        order_copy[key] = value.isoformat()
                orders_dict[order['order_id']] = order_copy
        
        # Get availability statistics
        availability = db.get_slot_availability()
        
        availability_stats = {}
        for tier_name, tier_data in availability.items():
            availability_stats[tier_name] = {
                'available': tier_data.get('available', 0),
                'capacity': tier_data.get('total', SERVICE_TIERS[tier_name]['capacity'])
            }
        
        vps_report = {
            'vps_status': {VPS_NAME: {
                'status': 'healthy',
                'ip': VPS_IP,
                'tiers': availability_stats
            }},
            'summary': {
                'total_vps': 1,
                'config_files_total': sum(data['total'] for data in availability.values())
            }
        }
        
        return render_template('admin.html', 
                             vps_report=vps_report,
                             service_tiers=SERVICE_TIERS,
                             orders=orders_dict)
    except Exception as e:
        logger.error(f"❌ Admin panel error: {e}", exc_info=True)
        return f"Admin panel error: {str(e)}", 500

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

@app.route('/admin/servers')
@admin_required  
def admin_servers():
    """VPS health dashboard"""
    vps_status = db.get_vps_status()
    
    # Get availability
    availability = db.get_slot_availability()
    
    # Build report structure
    vps_report = {
        'vps_status': {
            VPS_NAME: {
                'status': 'healthy' if not vps_status.get('error') else 'error',
                'ip': VPS_IP,
                'server_ip': VPS_IP,
                'timestamp': datetime.now().isoformat(),
                'error': vps_status.get('error'),
                'tiers': {}
            }
        },
        'summary': {
            'total_vps': 1,
            'active_orders': len([o for o in db.get_all_orders() if o.get('status') == 'active']),
            'revenue_potential': sum(SERVICE_TIERS[tier]['price_cents'] * SERVICE_TIERS[tier]['capacity'] 
                                   for tier in SERVICE_TIERS if tier != 'test')
        },
        'timestamp': datetime.now().isoformat()
    }
    
    # Add tier statistics
    for tier_name, tier_data in availability.items():
        vps_report['vps_status'][VPS_NAME]['tiers'][tier_name] = {
            'available': tier_data.get('available', 0),
            'capacity': tier_data.get('total', SERVICE_TIERS[tier_name]['capacity'])
        }
    
    return render_template('admin_servers.html',
                         vps_report=vps_report,
                         service_tiers=SERVICE_TIERS)

# === API ENDPOINTS ===

@app.route('/api/status')
def api_status():
    """Public API endpoint for service status"""
    try:
        # Get real availability from database
        availability = db.get_slot_availability()
        
        tier_availability = {}
        for tier_name, tier_data in availability.items():
            tier_availability[tier_name] = {
                'available': tier_data.get('available', 0),
                'capacity': tier_data.get('total', SERVICE_TIERS[tier_name]['capacity']),
                'price_cents': SERVICE_TIERS[tier_name]['price_cents']
            }
        
        return jsonify({
            'status': 'operational',
            'timestamp': datetime.now().isoformat(),
            'tiers': tier_availability,
            'vps_count': 1,
            'vps_ip': VPS_IP,
            'database_type': db.mode if db else 'unknown',
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
            'service': 'tunnelgrain-v2',
            'version': '2.0.0',
            'timestamp': datetime.now().isoformat(),
            'admin_key_configured': bool(ADMIN_KEY),
            'stripe_configured': bool(STRIPE_PUBLISHABLE_KEY and STRIPE_SECRET_KEY),
            'stripe_mode': 'test' if STRIPE_PUBLISHABLE_KEY and 'test' in STRIPE_PUBLISHABLE_KEY else 'live',
            'database': db_health,
            'vps_endpoint': VPS_ENDPOINT
        })
        
    except Exception as e:
        logger.error(f"❌ Health check error: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

# === DEBUG ENDPOINTS ===

@app.route('/api/debug-fingerprint')
def debug_fingerprint():
    """Debug endpoint to check fingerprinting"""
    fp = get_client_fingerprint(request)
    headers = dict(request.headers)
    
    return jsonify({
        'fingerprint': fp,
        'remote_addr': request.remote_addr,
        'headers': headers,
        'x_forwarded_for': request.headers.get('X-Forwarded-For'),
        'x_real_ip': request.headers.get('X-Real-IP'),
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/debug-db')
def debug_db():
    """Debug database state"""
    try:
        availability = db.get_slot_availability()
        orders = db.get_all_orders()
        
        active_orders = [o for o in orders if o.get('status') == 'active']
        
        return jsonify({
            'database_mode': db.mode,
            'availability': availability,
            'total_orders': len(orders),
            'active_orders': len(active_orders),
            'recent_orders': orders[:5] if orders else []
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# === ERROR HANDLERS ===

@app.errorhandler(404)
def not_found(error):
    logger.warning(f"404 error: {request.url}")
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"❌ 500 Internal error: {error}")
    return render_template('500.html'), 500

# === MAIN EXECUTION ===

if __name__ == '__main__':
    logger.info("🚀 Tunnelgrain VPN Service Starting...")
    logger.info(f"Database Mode: {db.mode if db else 'Not initialized'}")
    logger.info(f"Admin Key: {'✅ Configured' if ADMIN_KEY else '❌ Not Set'}")
    logger.info(f"Stripe: {'✅ Configured' if STRIPE_PUBLISHABLE_KEY else '❌ Not Configured'}")
    logger.info(f"VPS IP: {VPS_IP}")
    logger.info(f"VPS Endpoint: {VPS_ENDPOINT}")
    
    # Check slot availability
    try:
        availability = db.get_slot_availability()
        for tier, data in availability.items():
            logger.info(f"Tier {tier}: {data['available']}/{data['total']} slots available")
    except Exception as e:
        logger.error(f"❌ Failed to check availability: {e}")
    
    app.run(debug=True, host='0.0.0.0', port=5000)