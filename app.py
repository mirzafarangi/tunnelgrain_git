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
from database_manager import EnhancedVPNManager
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

# Admin security key
ADMIN_KEY = os.environ.get('ADMIN_KEY', 'tunnelgrain_admin_secret_2024_xyz')

# Paths for local config storage (your existing structure)
LOCAL_CONFIG_BASE = 'data'
QR_CODE_BASE = 'static/qr_codes'

# Abuse Prevention - In-memory tracking
test_usage_tracker = defaultdict(list)

# Initialize Enhanced VPN Manager
vpn_manager = EnhancedVPNManager()

# Admin authentication decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        provided_key = request.args.get('key') or request.headers.get('X-Admin-Key')
        if provided_key != ADMIN_KEY:
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

def get_config_path(vps_name: str, ip_address: str, tier: str, order_number: str, file_type: str = 'config'):
    """Get path to config or QR code file based on your existing structure"""
    if file_type == 'config':
        return f"{LOCAL_CONFIG_BASE}/{vps_name}/ip_{ip_address}/{tier}/{order_number}.conf"
    else:  # QR code
        return f"{QR_CODE_BASE}/{vps_name}/ip_{ip_address}/{tier}/{order_number}.png"

# === MAIN ROUTES ===

@app.route('/')
def home():
    """Enhanced home page with multi-tier pricing"""
    service_tiers = vpn_manager.get_service_tiers()
    return render_template('home.html', service_tiers=service_tiers)

@app.route('/test')
def test():
    """Free test VPN page"""
    return render_template('test.html')

@app.route('/pricing')
def pricing():
    """Dedicated pricing page with all tiers"""
    service_tiers = vpn_manager.get_service_tiers()
    return render_template('pricing.html', service_tiers=service_tiers)

@app.route('/order')
def order():
    """Order selection page with IP choice"""
    service_tiers = vpn_manager.get_service_tiers()
    
    # Get available IPs for each tier (excluding test)
    available_ips = {}
    for tier_name in service_tiers.keys():
        if tier_name != 'test':  # Test doesn't need IP selection
            available_ips[tier_name] = vpn_manager.get_available_ips_for_tier(tier_name)
    
    return render_template('order.html', 
                         service_tiers=service_tiers, 
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
    # Cleanup expired orders first
    vpn_manager.cleanup_expired_orders()
    
    # Check for abuse
    allowed, message = check_test_vpn_abuse(request)
    if not allowed:
        return jsonify({
            'error': 'Test limit exceeded. You can try 3 test VPNs per day. For unlimited access, please purchase a VPN plan.',
            'limit_info': message
        }), 429
    
    # Get available test IPs
    available_ips = vpn_manager.get_available_ips_for_tier('test')
    if not available_ips:
        return jsonify({
            'error': 'No test slots available. Please try again in a few minutes.'
        }), 503
    
    # Select IP with most available slots
    selected_ip = available_ips[0]
    user_fingerprint = get_client_fingerprint(request)
    
    # Assign slot
    result = vpn_manager.assign_vpn_slot(
        tier='test',
        ip_address=selected_ip['ip_address'],
        vps_name=selected_ip['vps_name'],
        user_fingerprint=user_fingerprint
    )
    
    if not result:
        return jsonify({
            'error': 'Failed to assign test slot. Please try again.'
        }), 503
    
    order_id, order_number = result
    
    # Store in session for download
    session['test_slot'] = order_id
    session['test_order'] = order_number
    session['test_expires'] = (datetime.now() + timedelta(minutes=15)).isoformat()
    session['test_ip'] = selected_ip['ip_address']
    session['test_vps'] = selected_ip['vps_name']
    
    logger.info(f"[TEST] User {user_fingerprint} assigned {order_number}")
    
    return jsonify({
        'success': True,
        'order_id': order_id,
        'order_number': order_number,
        'expires_in_minutes': 15,
        'download_url': url_for('download_test_config'),
        'usage_info': message,
        'ip_address': selected_ip['ip_address']
    })

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    """Create Stripe checkout session for VPN purchase"""
    try:
        data = request.json
        tier = data.get('tier')
        ip_address = data.get('ip_address')
        
        # Validate tier
        tier_config = vpn_manager.get_tier_config(tier)
        if not tier_config or tier == 'test':
            return jsonify({'error': 'Invalid service tier'}), 400
        
        if not ip_address:
            return jsonify({'error': 'IP address selection required'}), 400
        
        # Check if IP has available slots
        available_ips = vpn_manager.get_available_ips_for_tier(tier)
        selected_ip_data = next((ip for ip in available_ips if ip['ip_address'] == ip_address), None)
        
        if not selected_ip_data:
            return jsonify({
                'error': f'Selected IP {ip_address} not available for {tier} tier'
            }), 503
        
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
                'vps_name': selected_ip_data['vps_name']
            }
        )
        
        return jsonify({'checkout_url': checkout_session.url})
    
    except Exception as e:
        logger.error(f"[CHECKOUT] Error creating session: {e}")
        return jsonify({'error': 'Payment system temporarily unavailable'}), 500

@app.route('/payment-success')
def payment_success():
    """Handle successful payment with enhanced order tracking"""
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
        
        # Check if already processed (prevent duplicate assignments)
        existing_order = vpn_manager.find_order_by_stripe_session(session_id)
        if existing_order:
            # Already processed - show success page
            session['purchase_order'] = existing_order['order_number']
            session['purchase_tier'] = tier
            session['purchase_ip'] = ip_address
            session['purchase_vps'] = vps_name
            
            logger.info(f"[PAYMENT] Returning existing order: {existing_order['order_number']}")
            return render_template('payment_success.html', 
                                 order_data=existing_order, 
                                 tier_config=vpn_manager.get_tier_config(tier))
        
        # First time processing - assign new slot
        user_fingerprint = get_client_fingerprint(request)
        result = vpn_manager.assign_vpn_slot(
            tier=tier,
            ip_address=ip_address,
            vps_name=vps_name,
            stripe_session_id=session_id,
            user_fingerprint=user_fingerprint
        )
        
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
            
            logger.info(f"[PAYMENT] New assignment: {order_number}, tier: {tier}, IP: {ip_address}")
            
            return render_template('payment_success.html', 
                                 order_data=order_data, 
                                 tier_config=vpn_manager.get_tier_config(tier))
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
    ip_address = session.get('test_ip')
    vps_name = session.get('test_vps')
    
    # Get config file path
    config_path = get_config_path(vps_name, ip_address, 'test', order_number, 'config')
    
    if not os.path.exists(config_path):
        return "Config file not found. Please contact support.", 404
    
    return send_file(config_path, as_attachment=True, 
                    download_name=f'tunnelgrain_{order_number}.conf')

@app.route('/download-test-qr')
def download_test_qr():
    """Download test VPN QR code"""
    if 'test_order' not in session:
        return "No test VPN assigned", 404
    
    order_number = session['test_order']
    ip_address = session.get('test_ip')
    vps_name = session.get('test_vps')
    
    # Get QR code file path
    qr_path = get_config_path(vps_name, ip_address, 'test', order_number, 'qr')
    
    if not os.path.exists(qr_path):
        return "QR code not found. Please contact support.", 404
    
    return send_file(qr_path, as_attachment=True, 
                    download_name=f'tunnelgrain_{order_number}_qr.png')

@app.route('/download-purchase-config')
def download_purchase_config():
    """Download purchased VPN config"""
    if 'purchase_order' not in session:
        return "No VPN purchased", 404
    
    order_number = session['purchase_order']
    tier = session.get('purchase_tier')
    ip_address = session.get('purchase_ip')
    vps_name = session.get('purchase_vps')
    
    # Get config file path
    config_path = get_config_path(vps_name, ip_address, tier, order_number, 'config')
    
    if not os.path.exists(config_path):
        return "Config file not found. Please contact support.", 404
    
    return send_file(config_path, as_attachment=True, 
                    download_name=f'tunnelgrain_{order_number}.conf')

@app.route('/download-purchase-qr')
def download_purchase_qr():
    """Download purchased VPN QR code"""
    if 'purchase_order' not in session:
        return "No VPN purchased", 404
    
    order_number = session['purchase_order']
    tier = session.get('purchase_tier')
    ip_address = session.get('purchase_ip')
    vps_name = session.get('purchase_vps')
    
    # Get QR code file path
    qr_path = get_config_path(vps_name, ip_address, tier, order_number, 'qr')
    
    if not os.path.exists(qr_path):
        return "QR code not found. Please contact support.", 404
    
    return send_file(qr_path, as_attachment=True, 
                    download_name=f'tunnelgrain_{order_number}_qr.png')

# === ORDER LOOKUP ===

@app.route('/check-order', methods=['POST'])
def check_order():
    """Enhanced order check with detailed status"""
    order_number = request.form.get('order_number', '').strip().upper()
    
    # Validate order number format
    if not (order_number.startswith('42') or order_number.startswith('72')) or len(order_number) != 8:
        return jsonify({'error': 'Invalid order number format'})
    
    # Clean up expired orders first
    vpn_manager.cleanup_expired_orders()
    
    # Find order
    order_data = vpn_manager.get_order_status(order_number)
    
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
    
    # Generate download URLs if order is active
    download_urls = {}
    if status == 'active':
        # Store in session temporarily for download access
        session[f'recovery_{order_number}_tier'] = order_data['tier']
        session[f'recovery_{order_number}_ip'] = order_data['ip_address']
        session[f'recovery_{order_number}_vps'] = order_data['vps_name']
        
        download_urls = {
            'config_url': url_for('download_recovery_config', order_number=order_number),
            'qr_url': url_for('download_recovery_qr', order_number=order_number)
        }
    
    # Get tier information
    tier_info = vpn_manager.get_tier_config(order_data['tier'])
    
    return jsonify({
        'order_found': True,
        'tier': order_data['tier'],
        'tier_name': tier_info.get('name', 'Unknown') if tier_info else 'Unknown',
        'status': status,
        'time_remaining': time_remaining,
        'assigned_at': order_data.get('assigned_at', 'unknown'),
        'ip_address': order_data.get('ip_address', 'unknown'),
        'download_urls': download_urls
    })

# === RECOVERY DOWNLOAD ROUTES ===

@app.route('/recovery/<order_number>/config')
def download_recovery_config(order_number):
    """Download config file via order number recovery"""
    if f'recovery_{order_number}_tier' not in session:
        return "Recovery session expired. Please check order again.", 404
    
    tier = session[f'recovery_{order_number}_tier']
    ip_address = session[f'recovery_{order_number}_ip']
    vps_name = session[f'recovery_{order_number}_vps']
    
    config_path = get_config_path(vps_name, ip_address, tier, order_number, 'config')
    
    if not os.path.exists(config_path):
        return "Config file not found", 404
    
    return send_file(config_path, as_attachment=True, 
                    download_name=f'tunnelgrain_{order_number}.conf')

@app.route('/recovery/<order_number>/qr')
def download_recovery_qr(order_number):
    """Download QR code via order number recovery"""
    if f'recovery_{order_number}_tier' not in session:
        return "Recovery session expired. Please check order again.", 404
    
    tier = session[f'recovery_{order_number}_tier']
    ip_address = session[f'recovery_{order_number}_ip']
    vps_name = session[f'recovery_{order_number}_vps']
    
    qr_path = get_config_path(vps_name, ip_address, tier, order_number, 'qr')
    
    if not os.path.exists(qr_path):
        return "QR code not found", 404
    
    return send_file(qr_path, as_attachment=True, 
                    download_name=f'tunnelgrain_{order_number}_qr.png')

# === ADMIN ROUTES ===

@app.route('/admin')
@admin_required
def admin():
    """Main admin panel for order monitoring"""
    # Get recent orders from database
    vpn_manager.cleanup_expired_orders()
    
    # Get VPS status
    vps_report = vpn_manager.get_vps_status_report()
    
    return render_template('admin.html', 
                         vps_report=vps_report,
                         service_tiers=vpn_manager.get_service_tiers())

@app.route('/admin/servers')
@admin_required
def admin_servers():
    """VPS health monitoring dashboard"""
    vps_report = vpn_manager.get_vps_status_report()
    return render_template('admin_servers.html', vps_report=vps_report)

@app.route('/admin/database-reset', methods=['POST'])
@admin_required
def database_reset():
    """DANGER: Reset database (admin only)"""
    reset_type = request.form.get('reset_type', 'clear_assignments')
    
    try:
        success = vpn_manager.force_database_reset(reset_type)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Database {reset_type} completed successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Database reset failed'
            }), 500
            
    except Exception as e:
        logger.error(f"[ADMIN] Database reset error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/admin/force-cleanup', methods=['POST'])
@admin_required
def admin_force_cleanup():
    """Force cleanup of expired orders"""
    try:
        expired_count = vpn_manager.cleanup_expired_orders()
        
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
        # Get VPS status
        vps_report = vpn_manager.get_vps_status_report()
        
        # Calculate available slots per tier
        tier_availability = {}
        service_tiers = vpn_manager.get_service_tiers()
        
        for tier_name in service_tiers.keys():
            available_ips = vpn_manager.get_available_ips_for_tier(tier_name)
            total_available = sum(ip['available_slots'] for ip in available_ips)
            tier_availability[tier_name] = {
                'available': total_available,
                'ips': len(available_ips),
                'capacity': service_tiers[tier_name]['capacity']
            }
        
        return jsonify({
            'status': 'operational',
            'timestamp': datetime.now().isoformat(),
            'tiers': tier_availability,
            'vps_count': len(vps_report['vps_status']),
            'database_type': 'PostgreSQL' if vpn_manager.use_database else 'JSON Fallback'
        })
        
    except Exception as e:
        logger.error(f"[API] Status error: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

@app.route('/api/tiers')
def api_tiers():
    """Public API endpoint for service tiers"""
    try:
        service_tiers = vpn_manager.get_service_tiers()
        
        # Add availability information
        tiers_with_availability = {}
        for tier_name, tier_config in service_tiers.items():
            available_ips = vpn_manager.get_available_ips_for_tier(tier_name)
            total_available = sum(ip['available_slots'] for ip in available_ips)
            
            tiers_with_availability[tier_name] = {
                **tier_config,
                'available_slots': total_available,
                'available_ips': len(available_ips)
            }
        
        return jsonify({
            'tiers': tiers_with_availability,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"[API] Tiers error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/health')
def api_health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'tunnelgrain-enhanced',
        'version': '3.0.0',
        'timestamp': datetime.now().isoformat(),
        'database': 'connected' if vpn_manager.use_database else 'fallback'
    })

# === ERROR HANDLERS ===

@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal error: {error}")
    return render_template('500.html'), 500

# === DEVELOPMENT/DEBUG ROUTES ===

@app.route('/debug/info')
def debug_info():
    """Debug information (only in development)"""
    if app.debug or os.environ.get('FLASK_ENV') == 'development':
        return jsonify({
            'environment': os.environ.get('FLASK_ENV', 'production'),
            'database_configured': bool(vpn_manager.use_database),
            'stripe_configured': bool(STRIPE_PUBLISHABLE_KEY and STRIPE_SECRET_KEY),
            'vps_endpoints': list(vpn_manager.vps_endpoints.keys()),
            'service_tiers': list(vpn_manager.get_service_tiers().keys()),
            'local_config_base': LOCAL_CONFIG_BASE,
            'session_data': dict(session)
        })
    else:
        abort(404)

if __name__ == '__main__':
    # Create directories if they don't exist
    os.makedirs(LOCAL_CONFIG_BASE, exist_ok=True)
    os.makedirs(QR_CODE_BASE, exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    
    # Log startup information
    logger.info("🚀 Tunnelgrain Enhanced VPN Service Starting...")
    logger.info(f"Database: {'PostgreSQL' if vpn_manager.use_database else 'JSON Fallback'}")
    logger.info(f"Stripe: {'Configured' if STRIPE_PUBLISHABLE_KEY else 'Not Configured'}")
    logger.info(f"Service Tiers: {list(vpn_manager.get_service_tiers().keys())}")
    
    app.run(debug=True, host='0.0.0.0', port=5000)