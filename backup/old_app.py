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
from database_manager import OrderBasedSlotManager

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-in-production'

# Configuration
STRIPE_PUBLISHABLE_KEY = 'pk_test_51RYReqCaYnJXNs8zB2jfDn9rtFbLPbsBq8jTTk6Emd35rAWS2Day8r3lf7h4sTVY8q6tpDSZi48Eun82bgnQnEzy002KTbJdLE'
STRIPE_SECRET_KEY = 'sk_test_51RYReqCaYnJXNs8zU5CjyDM7yLagaQMRHbOkXdZnbZ4gUoz2JyEEt7JkDSXqkdFieRFX3EYCKmtpJiTyZ6SQpEet00WX5WINZX'
stripe.api_key = STRIPE_SECRET_KEY

# Admin security key (set as environment variable in production)
ADMIN_KEY = os.environ.get('ADMIN_KEY', 'tunnelgrain_admin_secret_2024_xyz')

# Paths
MONTHLY_DIR = 'data/monthly'
TEST_DIR = 'data/test'
QR_DIR = 'static/qr_codes'
SLOTS_FILE = 'slots.json'

# Abuse Prevention - In-memory tracking (for production, use Redis or database)
test_usage_tracker = defaultdict(list)
ip_usage_tracker = defaultdict(list)

# Admin authentication decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check for admin key in URL parameter or header
        provided_key = request.args.get('key') or request.headers.get('X-Admin-Key')
        if provided_key != ADMIN_KEY:
            abort(404)  # Return 404 instead of 403 to hide existence
        return f(*args, **kwargs)
    return decorated_function

# Order number generation
def generate_order_number():
    """Generate unique order number starting with 42"""
    return f"42{str(uuid.uuid4()).replace('-', '')[:6].upper()}"

def hash_email(email):
    """Create hash of email for privacy"""
    return hashlib.sha256(email.encode()).hexdigest()[:12]

# Abuse Prevention Functions
def get_client_fingerprint(request):
    """Create a privacy-respecting fingerprint"""
    # Use IP + User-Agent hash for basic tracking
    ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
    user_agent = request.headers.get('User-Agent', '')
    
    # Hash to protect privacy
    fingerprint_data = f"{ip}:{user_agent}"
    return hashlib.sha256(fingerprint_data.encode()).hexdigest()[:16]

def check_test_vpn_abuse(request):
    """Check if user has exceeded test VPN limits"""
    fingerprint = get_client_fingerprint(request)
    now = datetime.now()
    
    # Clean old entries (older than 24 hours)
    cutoff_time = now - timedelta(hours=24)
    test_usage_tracker[fingerprint] = [
        timestamp for timestamp in test_usage_tracker[fingerprint] 
        if timestamp > cutoff_time
    ]
    
    # Check limits
    usage_count = len(test_usage_tracker[fingerprint])
    
    # Limits: 3 test VPNs per 24 hours per fingerprint
    if usage_count >= 3:
        return False, f"Test limit reached. You can try {3 - usage_count} more test VPNs today."
    
    # Record this usage
    test_usage_tracker[fingerprint].append(now)
    
    return True, f"Test VPN granted. {3 - len(test_usage_tracker[fingerprint])} remaining today."

# Initialize OrderBasedSlotManager
slot_manager = OrderBasedSlotManager()

# Main routes
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/test')
def test():
    return render_template('test.html')

@app.route('/refund')
def refund():
    return render_template('refund.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/order-lookup')
def order_lookup():
    return render_template('order_lookup.html')

# VPN service routes
@app.route('/get-test-vpn', methods=['POST'])
def get_test_vpn():
    """Assign a 15-minute test VPN with abuse prevention"""
    slot_manager.cleanup_expired_slots()
    
    # Check for abuse
    allowed, message = check_test_vpn_abuse(request)
    if not allowed:
        return jsonify({
            'error': 'Test limit exceeded. You can try 3 test VPNs per day. For unlimited access, please purchase a monthly VPN.',
            'limit_info': message
        }), 429
    
    result = slot_manager.assign_slot('test')
    if not result:
        return jsonify({'error': 'No test slots available. Please try again later.'}), 503
    
    slot_id, order_number = result
    
    # Store in session for download
    session['test_slot'] = slot_id
    session['test_order'] = order_number
    session['test_expires'] = (datetime.now() + timedelta(minutes=15)).isoformat()
    
    # Log usage for monitoring
    fingerprint = get_client_fingerprint(request)
    print(f"[TEST] User {fingerprint[:8]} assigned {slot_id}, order: {order_number}")
    
    return jsonify({
        'success': True,
        'slot_id': slot_id,
        'order_number': order_number,
        'expires_in_minutes': 15,
        'download_url': url_for('download_test_config'),
        'usage_info': message
    })

@app.route('/download-test-config')
def download_test_config():
    """Download test VPN config using order number"""
    if 'test_slot' not in session:
        return "No test VPN assigned", 404
    
    slot_id = session['test_slot']
    order_number = session.get('test_order')
    
    # Try order number first, then fall back to slot_id
    if order_number and order_number.startswith('72'):
        config_path = os.path.join(TEST_DIR, f'{order_number}.conf')
        filename = f'tunnelgrain_{order_number}.conf'
    else:
        config_path = os.path.join(TEST_DIR, f'{slot_id}.conf')
        filename = f'tunnelgrain_{slot_id}.conf'
    
    if not os.path.exists(config_path):
        return "Config file not found", 404
    
    return send_file(config_path, as_attachment=True, download_name=filename)

@app.route('/download-test-qr')
def download_test_qr():
    """Download test VPN QR code using order number"""
    if 'test_slot' not in session:
        return "No test VPN assigned", 404
    
    slot_id = session['test_slot']
    order_number = session.get('test_order')
    
    # Try order number first, then fall back to slot_id  
    if order_number and order_number.startswith('72'):
        qr_path = os.path.join(QR_DIR, f'{order_number}.png')
        filename = f'tunnelgrain_{order_number}_qr.png'
    else:
        qr_path = os.path.join(QR_DIR, f'{slot_id}.png')
        filename = f'tunnelgrain_{slot_id}_qr.png'
    
    if not os.path.exists(qr_path):
        return "QR code not found", 404
    
    return send_file(qr_path, as_attachment=True, download_name=filename)

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    """Create Stripe checkout session for monthly VPN"""
    try:
        slot_manager.cleanup_expired_slots()
        
        # Check if slots available
        if not slot_manager.get_available_slot('monthly'):
            return jsonify({'error': 'No monthly slots available. Please try again later.'}), 503
        
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Tunnelgrain Monthly VPN',
                        'description': 'Private WireGuard VPN access for 30 days'
                    },
                    'unit_amount': 499,  # $4.99 in cents
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=url_for('payment_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('home', _external=True),
            metadata={
                'product_type': 'monthly_vpn'
            }
        )
        
        return jsonify({'checkout_url': checkout_session.url})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/payment-success')
def payment_success():
    """Handle successful payment with order tracking - DATABASE VERSION"""
    session_id = request.args.get('session_id')
    
    if not session_id:
        return "Invalid payment session", 400
    
    try:
        # Retrieve the session from Stripe
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        
        if checkout_session.payment_status != 'paid':
            return "Payment not completed", 400
        
        # CHECK IF WE ALREADY PROCESSED THIS PAYMENT SESSION (Flask session)
        if 'monthly_slot' in session and session.get('payment_session') == session_id:
            # Already processed - just show the success page
            slot_id = session['monthly_slot']
            order_number = session['order_number']
            print(f"[PAYMENT] Returning existing slot {slot_id} for session {session_id}")
            return render_template('payment_success.html', 
                                 slot_id=slot_id, 
                                 order_number=order_number)
        
        # CHECK DATABASE FOR EXISTING PAYMENT SESSION
        slots = slot_manager.get_slots()
        for slot_id, slot_data in slots['monthly'].items():
            if slot_data.get('stripe_session_id') == session_id:
                # This payment was already processed!
                print(f"[PAYMENT] Session {session_id} already processed for slot {slot_id}")
                
                # Store in current session for download access
                session['monthly_slot'] = slot_id
                session['payment_session'] = session_id
                session['order_number'] = slot_data['order_number']
                
                return render_template('payment_success.html', 
                                     slot_id=slot_id, 
                                     order_number=slot_data['order_number'])
        
        # FIRST TIME PROCESSING THIS PAYMENT - ASSIGN NEW SLOT
        result = slot_manager.assign_slot('monthly', duration_days=30, stripe_session_id=session_id)
        
        if result:
            slot_id, order_number = result
            
            # Store in session for download access
            session['monthly_slot'] = slot_id
            session['payment_session'] = session_id
            session['order_number'] = order_number
            
            print(f"[PAYMENT] NEW assignment: slot {slot_id}, order {order_number}, session {session_id}")
            
            return render_template('payment_success.html', 
                                 slot_id=slot_id, 
                                 order_number=order_number)
        else:
            return "No slots available - contact support", 503
            
    except Exception as e:
        print(f"[PAYMENT] Error processing payment: {str(e)}")
        return f"Error processing payment: {str(e)}", 500

@app.route('/download-monthly-config')
def download_monthly_config():
    """Download monthly VPN config using order number"""
    if 'monthly_slot' not in session:
        return "No monthly VPN purchased", 404
    
    slot_id = session['monthly_slot']
    order_number = session.get('order_number')
    
    # Try order number first, then fall back to slot_id
    if order_number and order_number.startswith('42'):
        config_path = os.path.join(MONTHLY_DIR, f'{order_number}.conf')
        filename = f'tunnelgrain_{order_number}.conf'
    else:
        config_path = os.path.join(MONTHLY_DIR, f'{slot_id}.conf')
        filename = f'tunnelgrain_{slot_id}.conf'
    
    if not os.path.exists(config_path):
        return "Config file not found", 404
    
    return send_file(config_path, as_attachment=True, download_name=filename)

@app.route('/download-monthly-qr')
def download_monthly_qr():
    """Download monthly VPN QR code using order number"""
    if 'monthly_slot' not in session:
        return "No monthly VPN purchased", 404
    
    slot_id = session['monthly_slot']
    order_number = session.get('order_number')
    
    # Try order number first, then fall back to slot_id
    if order_number and order_number.startswith('42'):
        qr_path = os.path.join(QR_DIR, f'{order_number}.png')
        filename = f'tunnelgrain_{order_number}_qr.png'
    else:
        qr_path = os.path.join(QR_DIR, f'{slot_id}.png')
        filename = f'tunnelgrain_{slot_id}_qr.png'
    
    if not os.path.exists(qr_path):
        return "QR code not found", 404
    
    return send_file(qr_path, as_attachment=True, download_name=filename)

# Enhanced Order lookup system
@app.route('/check-order', methods=['POST'])
def check_order():
    """Enhanced order check with slot info and download links"""
    order_number = request.form.get('order_number', '').strip().upper()
    
    if not order_number.startswith('42') or len(order_number) != 8:
        return jsonify({'error': 'Invalid order number format'})
    
    # Clean up expired slots first
    slot_manager.cleanup_expired_slots()
    
    # Find slot by order number
    slot_type, slot_id, slot_data = slot_manager.find_slot_by_order(order_number)
    
    if not slot_data:
        return jsonify({
            'order_found': False,
            'error': 'Order not found'
        })
    
    # Calculate time remaining
    status = 'unknown'
    time_remaining = 'unknown'
    
    if slot_data.get('expires_at'):
        try:
            expires_at = datetime.fromisoformat(slot_data['expires_at'])
            now = datetime.now()
            days_remaining = max(0, (expires_at - now).days)
            hours_remaining = max(0, (expires_at - now).seconds // 3600)
            
            if slot_type == 'test':
                minutes_remaining = max(0, (expires_at - now).seconds // 60)
                time_remaining = f"{minutes_remaining} minutes"
            else:
                time_remaining = f"{days_remaining} days" if days_remaining > 0 else f"{hours_remaining} hours"
            
            status = 'active' if expires_at > now else 'expired'
        except:
            time_remaining = 'unknown'
            status = 'unknown'
    
    # Generate download URLs if order is active
    download_urls = {}
    if status == 'active':
        # Store in session temporarily for download access
        session[f'recovery_{order_number}_slot'] = slot_id
        session[f'recovery_{order_number}_type'] = slot_type
        
        download_urls = {
            'config_url': url_for('download_recovery_config', order_number=order_number),
            'qr_url': url_for('download_recovery_qr', order_number=order_number)
        }
    
    return jsonify({
        'order_found': True,
        'slot_type': slot_type,
        'slot_id': slot_id,
        'status': status,
        'time_remaining': time_remaining,
        'assigned_at': slot_data.get('assigned_at', 'unknown'),
        'download_urls': download_urls
    })

# Recovery download routes
@app.route('/recovery/<order_number>/config')
def download_recovery_config(order_number):
    """Download config file via order number recovery"""
    if f'recovery_{order_number}_slot' not in session:
        return "Recovery session expired. Please check order again.", 404
    
    slot_id = session[f'recovery_{order_number}_slot']
    slot_type = session[f'recovery_{order_number}_type']
    
    # Try order-based filename first
    if order_number.startswith('42'):
        config_path = os.path.join(MONTHLY_DIR, f'{order_number}.conf')
    elif order_number.startswith('72'):
        config_path = os.path.join(TEST_DIR, f'{order_number}.conf')
    else:
        # Fallback to slot-based filename
        if slot_type == 'monthly':
            config_path = os.path.join(MONTHLY_DIR, f'{slot_id}.conf')
        else:
            config_path = os.path.join(TEST_DIR, f'{slot_id}.conf')
    
    if not os.path.exists(config_path):
        return "Config file not found", 404
    
    return send_file(config_path, as_attachment=True, 
                    download_name=f'tunnelgrain_{order_number}.conf')

@app.route('/recovery/<order_number>/qr')
def download_recovery_qr(order_number):
    """Download QR code via order number recovery"""
    if f'recovery_{order_number}_slot' not in session:
        return "Recovery session expired. Please check order again.", 404
    
    slot_id = session[f'recovery_{order_number}_slot']
    
    # Try order-based filename first
    if order_number.startswith(('42', '72')):
        qr_path = os.path.join(QR_DIR, f'{order_number}.png')
    else:
        # Fallback to slot-based filename
        qr_path = os.path.join(QR_DIR, f'{slot_id}.png')
    
    if not os.path.exists(qr_path):
        return "QR code not found", 404
    
    return send_file(qr_path, as_attachment=True, 
                    download_name=f'tunnelgrain_{order_number}_qr.png')

# Admin routes (protected)
@app.route('/admin')
@admin_required
def admin():
    """Secure admin panel to view slot status"""
    slot_manager.cleanup_expired_slots()
    return render_template('admin.html', slots=slot_manager.get_slots())

@app.route('/admin/database-reset', methods=['POST'])
@admin_required
def database_reset():
    """DANGER: Reset database to clean state - removes all customer data"""
    reset_type = request.form.get('reset_type', 'slots_only')
    
    try:
        if hasattr(slot_manager, 'use_database') and slot_manager.use_database:
            # Database reset
            conn = slot_manager.get_connection()
            cursor = conn.cursor()
            
            if reset_type == 'full_reset':
                # NUCLEAR OPTION: Drop and recreate table
                cursor.execute("DROP TABLE IF EXISTS vpn_slots;")
                
                cursor.execute("""
                    CREATE TABLE vpn_slots (
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
                
                # Recreate indexes
                cursor.execute("CREATE INDEX idx_vpn_slots_type_available ON vpn_slots (slot_type, available);")
                cursor.execute("CREATE INDEX idx_vpn_slots_expires ON vpn_slots (expires_at) WHERE expires_at IS NOT NULL;")
                cursor.execute("CREATE INDEX idx_vpn_slots_order ON vpn_slots (order_number) WHERE order_number IS NOT NULL;")
                
                # Repopulate slots
                slot_manager.populate_initial_slots(cursor)
                
            elif reset_type == 'clear_assignments':
                # Clear all assignments but keep structure
                cursor.execute("""
                    UPDATE vpn_slots SET 
                    available = TRUE,
                    assigned_at = NULL,
                    expires_at = NULL,
                    order_number = NULL,
                    stripe_session_id = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """)
            
            conn.commit()
            cursor.close()
            conn.close()
            
            return jsonify({
                'success': True,
                'message': f'Database {reset_type} completed',
                'reset_type': reset_type
            })
        
        else:
            # JSON file reset
            if reset_type == 'full_reset' or reset_type == 'clear_assignments':
                slot_manager.create_initial_fallback_slots()
                return jsonify({
                    'success': True,
                    'message': 'JSON slots reset completed',
                    'reset_type': reset_type
                })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/admin/database-status')
@admin_required 
def database_status():
    """Check database status and statistics"""
    try:
        slots = slot_manager.get_slots()
        
        stats = {
            'database_type': 'PostgreSQL' if (hasattr(slot_manager, 'use_database') and slot_manager.use_database) else 'JSON File',
            'total_slots': len(slots.get('monthly', {})) + len(slots.get('test', {})),
            'monthly_available': sum(1 for slot in slots.get('monthly', {}).values() if slot.get('available', True)),
            'test_available': sum(1 for slot in slots.get('test', {}).values() if slot.get('available', True)),
            'active_orders': [],
            'expired_orders': []
        }
        
        # Collect order information
        for slot_type in ['monthly', 'test']:
            for slot_id, slot_data in slots.get(slot_type, {}).items():
                if slot_data.get('order_number'):
                    order_info = {
                        'order_number': slot_data['order_number'],
                        'slot_id': slot_id,
                        'slot_type': slot_type,
                        'assigned_at': slot_data.get('assigned_at'),
                        'expires_at': slot_data.get('expires_at')
                    }
                    
                    # Check if expired
                    if slot_data.get('expires_at'):
                        try:
                            expires_at = datetime.fromisoformat(slot_data['expires_at'])
                            if datetime.now() > expires_at:
                                stats['expired_orders'].append(order_info)
                            else:
                                stats['active_orders'].append(order_info)
                        except:
                            stats['expired_orders'].append(order_info)
        
        return jsonify(stats)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# API endpoints
@app.route('/api/slot-status')
def slot_status():
    """API endpoint for slot availability"""
    slot_manager.cleanup_expired_slots()
    
    slots = slot_manager.get_slots()
    monthly_available = sum(1 for slot in slots['monthly'].values() if slot['available'])
    test_available = sum(1 for slot in slots['test'].values() if slot['available'])
    
    return jsonify({
        'monthly_available': monthly_available,
        'test_available': test_available,
        'total_monthly': 10,
        'total_test': 10
    })

@app.route('/api/active-slots')
def active_slots():
    """API endpoint for server automation - returns currently active slots"""
    slot_manager.cleanup_expired_slots()
    
    active_monthly = []
    active_test = []
    
    slots = slot_manager.get_slots()
    
    # Get active monthly slots
    for slot_id, slot_data in slots['monthly'].items():
        if not slot_data['available']:  # Slot is assigned/active
            active_monthly.append(slot_id)
    
    # Get active test slots
    for slot_id, slot_data in slots['test'].items():
        if not slot_data['available']:  # Slot is assigned/active
            active_test.append(slot_id)
    
    return jsonify({
        'monthly': active_monthly,
        'test': active_test,
        'total_active': len(active_monthly) + len(active_test),
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/force-cleanup', methods=['POST'])
@admin_required
def force_cleanup():
    """Force cleanup of expired slots - for manual management"""
    slots = slot_manager.get_slots()
    before_cleanup = {
        'monthly': len([s for s in slots['monthly'].values() if not s['available']]),
        'test': len([s for s in slots['test'].values() if not s['available']])
    }
    
    cleaned_slots = slot_manager.cleanup_expired_slots()
    
    slots = slot_manager.get_slots()
    after_cleanup = {
        'monthly': len([s for s in slots['monthly'].values() if not s['available']]),
        'test': len([s for s in slots['test'].values() if not s['available']])
    }
    
    return jsonify({
        'success': True,
        'before': before_cleanup,
        'after': after_cleanup,
        'cleaned_monthly': before_cleanup['monthly'] - after_cleanup['monthly'],
        'cleaned_test': before_cleanup['test'] - after_cleanup['test'],
        'cleaned_slots': cleaned_slots
    })

# Abuse statistics endpoint
@app.route('/api/abuse-stats')
@admin_required
def abuse_stats():
    """Show test VPN abuse statistics"""
    now = datetime.now()
    cutoff_24h = now - timedelta(hours=24)
    cutoff_1h = now - timedelta(hours=1)
    
    # Clean old data
    active_users_24h = 0
    active_users_1h = 0
    total_requests_24h = 0
    
    for fingerprint, timestamps in test_usage_tracker.items():
        # Clean old entries
        recent_timestamps = [t for t in timestamps if t > cutoff_24h]
        test_usage_tracker[fingerprint] = recent_timestamps
        
        if recent_timestamps:
            active_users_24h += 1
            total_requests_24h += len(recent_timestamps)
            
            if any(t > cutoff_1h for t in recent_timestamps):
                active_users_1h += 1
    
    return jsonify({
        'active_users_24h': active_users_24h,
        'active_users_1h': active_users_1h,
        'total_requests_24h': total_requests_24h,
        'unique_fingerprints': len([f for f, t in test_usage_tracker.items() if t]),
        'timestamp': now.isoformat()
    })

@app.route('/debug/deployment-info')
def deployment_info():
    """Debug endpoint to check deployment state"""
    import os
    import json
    from datetime import datetime
    
    debug_info = {
        'timestamp': datetime.now().isoformat(),
        'working_directory': os.getcwd(),
        'files_in_root': os.listdir('.'),
        'slots_json_exists': os.path.exists('slots.json'),
        'slots_json_size': os.path.getsize('slots.json') if os.path.exists('slots.json') else 0,
        'data_dir_exists': os.path.exists('data'),
        'static_dir_exists': os.path.exists('static'),
        'database_url_set': bool(os.environ.get('DATABASE_URL')),
        'slot_manager_type': type(slot_manager).__name__,
        'environment_vars': {
            'RENDER': os.environ.get('RENDER', 'Not set'),
            'NODE_ENV': os.environ.get('NODE_ENV', 'Not set'),
            'PYTHON_VERSION': os.environ.get('PYTHON_VERSION', 'Not set')
        }
    }
    
    # Check data directory contents
    if os.path.exists('data'):
        debug_info['data_contents'] = {
            'monthly': os.listdir('data/monthly') if os.path.exists('data/monthly') else [],
            'test': os.listdir('data/test') if os.path.exists('data/test') else []
        }
    
    # Check current slots via slot manager
    try:
        slots = slot_manager.get_slots()
        debug_info['slots_summary'] = {
            'monthly_available': sum(1 for slot in slots.get('monthly', {}).values() if slot.get('available', True)),
            'test_available': sum(1 for slot in slots.get('test', {}).values() if slot.get('available', True)),
            'total_monthly': len(slots.get('monthly', {})),
            'total_test': len(slots.get('test', {}))
        }
    except Exception as e:
        debug_info['slots_error'] = str(e)
    
    return f"""
    <html>
    <head><title>Deployment Debug Info</title></head>
    <body style="font-family: monospace; background: #f5f5f5; padding: 20px;">
        <h2>🔍 Deployment Debug Information</h2>
        <pre style="background: white; padding: 15px; border-radius: 5px; overflow-x: auto;">
{json.dumps(debug_info, indent=2, default=str)}
        </pre>
        <hr>
        <p><strong>Status:</strong></p>
        <ul>
            <li>Slot Manager: {type(slot_manager).__name__}</li>
            <li>Database Available: {'Yes' if os.environ.get('DATABASE_URL') else 'No (using fallback)'}</li>
        </ul>
        <p><a href="/">← Back to Home</a></p>
    </body>
    </html>
    """

if __name__ == '__main__':
    # Create directories if they don't exist
    os.makedirs(MONTHLY_DIR, exist_ok=True)
    os.makedirs(TEST_DIR, exist_ok=True)
    os.makedirs(QR_DIR, exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    
    app.run(debug=True, host='0.0.0.0', port=5000)