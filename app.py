from flask import Flask, render_template, request, send_file, jsonify, session, redirect, url_for
import json
import os
import time
from datetime import datetime, timedelta
import qrcode
from io import BytesIO
import stripe
import uuid

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-in-production'

# Configuration
STRIPE_PUBLISHABLE_KEY = 'pk_live_51RYReqCaYnJXNs8zKtZk9lQzn8ZCzKU5AzT3ZxZLwOypTEFst36TGxsv3UgCZqG9y6wGtLgaf450sNSL7xZQSlu000ygmqfy6I'  # Replace with your key
STRIPE_SECRET_KEY = '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'      # Replace with your key
stripe.api_key = STRIPE_SECRET_KEY

# Paths
MONTHLY_DIR = 'data/monthly'
TEST_DIR = 'data/test'
QR_DIR = 'static/qr_codes'
SLOTS_FILE = 'slots.json'

# Slot management
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
                'monthly': {f'client_{i:02d}': {'available': True, 'assigned_at': None, 'expires_at': None} 
                           for i in range(1, 11)},
                'test': {f'test_{i:02d}': {'available': True, 'assigned_at': None, 'expires_at': None} 
                        for i in range(1, 11)}
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
    
    def assign_slot(self, slot_type='monthly', duration_days=30):
        """Assign a slot and return slot_id"""
        slot_id = self.get_available_slot(slot_type)
        if not slot_id:
            return None
        
        now = datetime.now()
        expires_at = now + timedelta(days=duration_days)
        
        self.slots[slot_type][slot_id].update({
            'available': False,
            'assigned_at': now.isoformat(),
            'expires_at': expires_at.isoformat()
        })
        self.save_slots()
        return slot_id
    
    def release_slot(self, slot_type, slot_id):
        """Release a slot back to available pool"""
        if slot_id in self.slots[slot_type]:
            self.slots[slot_type][slot_id].update({
                'available': True,
                'assigned_at': None,
                'expires_at': None
            })
            self.save_slots()
    
    def cleanup_expired_slots(self):
        """Clean up expired slots"""
        now = datetime.now()
        for slot_type in ['monthly', 'test']:
            for slot_id, slot_data in self.slots[slot_type].items():
                if not slot_data['available'] and slot_data['expires_at']:
                    expires_at = datetime.fromisoformat(slot_data['expires_at'])
                    if now > expires_at:
                        self.release_slot(slot_type, slot_id)

slot_manager = SlotManager()

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

@app.route('/get-test-vpn', methods=['POST'])
def get_test_vpn():
    """Assign a 15-minute test VPN"""
    slot_manager.cleanup_expired_slots()
    
    slot_id = slot_manager.assign_slot('test', duration_days=0.01)  # ~15 minutes
    if not slot_id:
        return jsonify({'error': 'No test slots available. Try again later.'}), 503
    
    # Store in session for download
    session['test_slot'] = slot_id
    session['test_expires'] = (datetime.now() + timedelta(minutes=15)).isoformat()
    
    return jsonify({
        'success': True,
        'slot_id': slot_id,
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
    
    return send_file(config_path, as_attachment=True, download_name=f'{slot_id}.conf')

@app.route('/download-test-qr')
def download_test_qr():
    """Download test VPN QR code"""
    if 'test_slot' not in session:
        return "No test VPN assigned", 404
    
    slot_id = session['test_slot']
    qr_path = os.path.join(QR_DIR, f'{slot_id}.png')
    
    if not os.path.exists(qr_path):
        return "QR code not found", 404
    
    return send_file(qr_path, as_attachment=True, download_name=f'{slot_id}_qr.png')

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    """Create Stripe checkout session for monthly VPN"""
    try:
        slot_manager.cleanup_expired_slots()
        
        # Check if slots available
        if not slot_manager.get_available_slot('monthly'):
            return jsonify({'error': 'No monthly slots available'}), 503
        
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Monthly VPN Access',
                        'description': 'High-speed VPN access for 30 days'
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
    """Handle successful payment"""
    session_id = request.args.get('session_id')
    
    if not session_id:
        return "Invalid payment session", 400
    
    try:
        # Retrieve the session from Stripe
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        
        if checkout_session.payment_status == 'paid':
            # Assign VPN slot
            slot_id = slot_manager.assign_slot('monthly', duration_days=30)
            
            if slot_id:
                session['monthly_slot'] = slot_id
                session['payment_session'] = session_id
                return render_template('payment_success.html', slot_id=slot_id)
            else:
                return "No slots available - contact support for refund", 503
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
    
    return send_file(config_path, as_attachment=True, download_name=f'{slot_id}.conf')

@app.route('/download-monthly-qr')
def download_monthly_qr():
    """Download monthly VPN QR code"""
    if 'monthly_slot' not in session:
        return "No monthly VPN purchased", 404
    
    slot_id = session['monthly_slot']
    qr_path = os.path.join(QR_DIR, f'{slot_id}.png')
    
    if not os.path.exists(qr_path):
        return "QR code not found", 404
    
    return send_file(qr_path, as_attachment=True, download_name=f'{slot_id}_qr.png')

@app.route('/admin')
def admin():
    """Simple admin panel to view slot status"""
    slot_manager.cleanup_expired_slots()
    return render_template('admin.html', slots=slot_manager.slots)

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

if __name__ == '__main__':
    # Create directories if they don't exist
    os.makedirs(MONTHLY_DIR, exist_ok=True)
    os.makedirs(TEST_DIR, exist_ok=True)
    os.makedirs(QR_DIR, exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    
    app.run(debug=True, host='0.0.0.0', port=5000)