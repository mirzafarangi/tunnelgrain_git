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

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-in-production'

# Configuration
STRIPE_PUBLISHABLE_KEY = 'pk_live_51RYReqCaYnJXNs8zKtZk9lQzn8ZCzKU5AzT3ZxZLwOypTEFst36TGxsv3UgCZqG9y6wGtLgaf450sNSL7xZQSlu000ygmqfy6I'
STRIPE_SECRET_KEY = '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'
stripe.api_key = STRIPE_SECRET_KEY

# Admin security key (set as environment variable in production)
ADMIN_KEY = os.environ.get('ADMIN_KEY', 'tunnelgrain_admin_secret_2024_xyz')

# Paths
MONTHLY_DIR = 'data/monthly'
TEST_DIR = 'data/test'
QR_DIR = 'static/qr_codes'
SLOTS_FILE = 'slots.json'

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

# Enhanced Slot management
class SlotManager:
    def __init__(self):
        self.slots_file = SLOTS_FILE
        self.load_slots()
    
    def load_slots(self):
        if os.path.exists(self.slots_file):
            with open(self.slots_file, 'r') as f:
                self.slots = json.load(f)
        else:
            # Initialize slots
            self.slots = {
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
            self.save_slots()
    
    def save_slots(self):
        with open(self.slots_file, 'w') as f:
            json.dump(self.slots, f, indent=2)
    
    def get_available_slot(self, slot_type='monthly'):
        """Get next available slot"""
        for slot_id, slot_data in self.slots[slot_type].items():
            if slot_data['available']:
                return slot_id
        return None
    
    def assign_slot(self, slot_type='monthly', duration_days=30, order_number=None):
        """Enhanced slot assignment with better tracking"""
        slot_id = self.get_available_slot(slot_type)
        if not slot_id:
            return None
        
        now = datetime.now()
        if slot_type == 'test':
            expires_at = now + timedelta(minutes=15)
        else:
            expires_at = now + timedelta(days=duration_days)
        
        # Generate order number if not provided
        if not order_number:
            order_number = generate_order_number()
        
        self.slots[slot_type][slot_id].update({
            'available': False,
            'assigned_at': now.isoformat(),
            'expires_at': expires_at.isoformat(),
            'order_number': order_number,
            'slot_type': slot_type,
            'duration_days': duration_days if slot_type == 'monthly' else 0,
            'auto_managed': True
        })
        self.save_slots()
        
        # Log assignment for tracking
        print(f"[SLOT] Assigned {slot_type} slot {slot_id}, order: {order_number}, expires: {expires_at}")
        
        return slot_id, order_number
    
    def release_slot(self, slot_type, slot_id):
        """Release a slot back to available pool"""
        if slot_id in self.slots[slot_type]:
            self.slots[slot_type][slot_id].update({
                'available': True,
                'assigned_at': None,
                'expires_at': None,
                'order_number': None
            })
            self.save_slots()
    
    def cleanup_expired_slots(self):
        """Enhanced cleanup with logging"""
        now = datetime.now()
        cleaned_slots = []
        
        for slot_type in ['monthly', 'test']:
            for slot_id, slot_data in self.slots[slot_type].items():
                if not slot_data['available'] and slot_data.get('expires_at'):
                    try:
                        expires_at = datetime.fromisoformat(slot_data['expires_at'])
                        if now > expires_at:
                            self.release_slot(slot_type, slot_id)
                            cleaned_slots.append(f"{slot_type}:{slot_id}")
                            print(f"[SLOT] Auto-released expired slot {slot_type}:{slot_id}")
                    except (ValueError, TypeError) as e:
                        print(f"[SLOT] Error parsing expiration for {slot_id}: {e}")
        
        return cleaned_slots
    
    def find_slot_by_order(self, order_number):
        """Find slot by order number"""
        for slot_type in ['monthly', 'test']:
            for slot_id, slot_data in self.slots[slot_type].items():
                if slot_data.get('order_number') == order_number:
                    return slot_type, slot_id, slot_data
        return None, None, None

slot_manager = SlotManager()

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
    """Assign a 15-minute test VPN"""
    slot_manager.cleanup_expired_slots()
    
    result = slot_manager.assign_slot('test')
    if not result:
        return jsonify({'error': 'No test slots available. Please try again later.'}), 503
    
    slot_id, order_number = result
    
    # Store in session for download
    session['test_slot'] = slot_id
    session['test_order'] = order_number
    session['test_expires'] = (datetime.now() + timedelta(minutes=15)).isoformat()
    
    return jsonify({
        'success': True,
        'slot_id': slot_id,
        'order_number': order_number,
        'expires_in_minutes': 15,
        'download_url': url_for('download_test_config')
    })

@app.route('/download-test-config')
def download_test_config():
    """Download test VPN config"""
    if 'test_slot' not in session:
        return "No test VPN assigned", 404
    
    slot_id = session['test_slot']
    config_path = os.path.join(TEST_DIR, f'{slot_id}.conf')
    
    if not os.path.exists(config_path):
        return "Config file not found", 404
    
    return send_file(config_path, as_attachment=True, download_name=f'tunnelgrain_{slot_id}.conf')

@app.route('/download-test-qr')
def download_test_qr():
    """Download test VPN QR code"""
    if 'test_slot' not in session:
        return "No test VPN assigned", 404
    
    slot_id = session['test_slot']
    qr_path = os.path.join(QR_DIR, f'{slot_id}.png')
    
    if not os.path.exists(qr_path):
        return "QR code not found", 404
    
    return send_file(qr_path, as_attachment=True, download_name=f'tunnelgrain_{slot_id}_qr.png')

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
                    'unit_amount': 999,  # $9.99 in cents
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
    """Handle successful payment with order tracking"""
    session_id = request.args.get('session_id')
    
    if not session_id:
        return "Invalid payment session", 400
    
    try:
        # Retrieve the session from Stripe
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        
        if checkout_session.payment_status == 'paid':
            # Assign VPN slot with order number
            result = slot_manager.assign_slot('monthly', duration_days=30)
            
            if result:
                slot_id, order_number = result
                
                # Store in session
                session['monthly_slot'] = slot_id
                session['payment_session'] = session_id
                session['order_number'] = order_number
                
                return render_template('payment_success.html', 
                                     slot_id=slot_id, 
                                     order_number=order_number)
            else:
                return "No slots available - contact support", 503
        else:
            return "Payment not completed", 400
            
    except Exception as e:
        return f"Error processing payment: {str(e)}", 500

@app.route('/download-monthly-config')
def download_monthly_config():
    """Download monthly VPN config"""
    if 'monthly_slot' not in session:
        return "No monthly VPN purchased", 404
    
    slot_id = session['monthly_slot']
    config_path = os.path.join(MONTHLY_DIR, f'{slot_id}.conf')
    
    if not os.path.exists(config_path):
        return "Config file not found", 404
    
    return send_file(config_path, as_attachment=True, download_name=f'tunnelgrain_{slot_id}.conf')

@app.route('/download-monthly-qr')
def download_monthly_qr():
    """Download monthly VPN QR code"""
    if 'monthly_slot' not in session:
        return "No monthly VPN purchased", 404
    
    slot_id = session['monthly_slot']
    qr_path = os.path.join(QR_DIR, f'{slot_id}.png')
    
    if not os.path.exists(qr_path):
        return "QR code not found", 404
    
    return send_file(qr_path, as_attachment=True, download_name=f'tunnelgrain_{slot_id}_qr.png')

# Order lookup system
@app.route('/check-order', methods=['POST'])
def check_order():
    """Check order status by order number"""
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
    
    # Calculate days remaining
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
    else:
        time_remaining = 'unknown'
        status = 'unknown'
    
    return jsonify({
        'order_found': True,
        'slot_type': slot_type,
        'slot_id': slot_id,
        'status': status,
        'time_remaining': time_remaining,
        'assigned_at': slot_data.get('assigned_at', 'unknown')
    })

# Admin routes (protected)
@app.route('/admin')
@admin_required
def admin():
    """Secure admin panel to view slot status"""
    slot_manager.cleanup_expired_slots()
    return render_template('admin.html', slots=slot_manager.slots)

# API endpoints
@app.route('/api/slot-status')
def slot_status():
    """API endpoint for slot availability"""
    slot_manager.cleanup_expired_slots()
    
    monthly_available = sum(1 for slot in slot_manager.slots['monthly'].values() if slot['available'])
    test_available = sum(1 for slot in slot_manager.slots['test'].values() if slot['available'])
    
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
    
    # Get active monthly slots
    for slot_id, slot_data in slot_manager.slots['monthly'].items():
        if not slot_data['available']:  # Slot is assigned/active
            active_monthly.append(slot_id)
    
    # Get active test slots
    for slot_id, slot_data in slot_manager.slots['test'].items():
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
    before_cleanup = {
        'monthly': len([s for s in slot_manager.slots['monthly'].values() if not s['available']]),
        'test': len([s for s in slot_manager.slots['test'].values() if not s['available']])
    }
    
    cleaned_slots = slot_manager.cleanup_expired_slots()
    
    after_cleanup = {
        'monthly': len([s for s in slot_manager.slots['monthly'].values() if not s['available']]),
        'test': len([s for s in slot_manager.slots['test'].values() if not s['available']])
    }
    
    return jsonify({
        'success': True,
        'before': before_cleanup,
        'after': after_cleanup,
        'cleaned_monthly': before_cleanup['monthly'] - after_cleanup['monthly'],
        'cleaned_test': before_cleanup['test'] - after_cleanup['test'],
        'cleaned_slots': cleaned_slots
    })

if __name__ == '__main__':
    # Create directories if they don't exist
    os.makedirs(MONTHLY_DIR, exist_ok=True)
    os.makedirs(TEST_DIR, exist_ok=True)
    os.makedirs(QR_DIR, exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    
    app.run(debug=True, host='0.0.0.0', port=5000)