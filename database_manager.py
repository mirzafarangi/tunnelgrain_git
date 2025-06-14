#!/usr/bin/env python3
"""
Tunnelgrain VPS Expiration Daemon - ACTUALLY DISABLES CONFIGS
This runs on your VPS and enforces real expiration by removing peers from WireGuard
"""

import time
import json
import subprocess
import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, request, jsonify

# Configuration
CONFIG_BASE = "/opt/tunnelgrain"
TIMER_FILE = f"{CONFIG_BASE}/active_timers.json"
LOG_FILE = f"{CONFIG_BASE}/logs/expiration.log"
PEER_MAP_FILE = f"{CONFIG_BASE}/peer_mapping.txt"

# Setup logging
os.makedirs(f"{CONFIG_BASE}/logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Flask app for API
app = Flask(__name__)

class ExpirationManager:
    def __init__(self):
        self.active_timers = {}
        self.load_timers()
        
    def load_timers(self):
        """Load active timers from disk"""
        if os.path.exists(TIMER_FILE):
            try:
                with open(TIMER_FILE, 'r') as f:
                    self.active_timers = json.load(f)
                logger.info(f"Loaded {len(self.active_timers)} active timers")
            except Exception as e:
                logger.error(f"Error loading timers: {e}")
                self.active_timers = {}
    
    def save_timers(self):
        """Save timers to disk"""
        try:
            with open(TIMER_FILE, 'w') as f:
                json.dump(self.active_timers, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error saving timers: {e}")
    
    def add_timer(self, order_number, tier, duration_minutes):
        """Add expiration timer"""
        expires_at = datetime.now() + timedelta(minutes=duration_minutes)
        
        self.active_timers[order_number] = {
            'tier': tier,
            'expires_at': expires_at.isoformat(),
            'duration_minutes': duration_minutes,
            'status': 'active',
            'added_at': datetime.now().isoformat()
        }
        
        self.save_timers()
        logger.info(f"⏰ Timer added: {order_number} expires in {duration_minutes} minutes")
        return True
    
    def get_peer_public_key(self, order_number):
        """Find public key for order number in peer mapping"""
        if not os.path.exists(PEER_MAP_FILE):
            logger.error(f"Peer mapping file not found: {PEER_MAP_FILE}")
            return None
        
        try:
            with open(PEER_MAP_FILE, 'r') as f:
                for line in f:
                    if line.strip().startswith(order_number + ':'):
                        parts = line.strip().split(':')
                        if len(parts) >= 2:
                            return parts[1]  # public key
        except Exception as e:
            logger.error(f"Error reading peer mapping: {e}")
        
        return None
    
    def remove_peer_from_wireguard(self, public_key):
        """Actually remove peer from WireGuard interface"""
        try:
            # Remove peer from WireGuard
            result = subprocess.run([
                'wg', 'set', 'wg0', 'peer', public_key, 'remove'
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.info(f"✅ Peer {public_key[:16]}... removed from WireGuard")
                return True
            else:
                logger.error(f"❌ Failed to remove peer: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error removing peer: {e}")
            return False
    
    def expire_config(self, order_number):
        """Expire a config by removing it from WireGuard"""
        try:
            # Get public key
            public_key = self.get_peer_public_key(order_number)
            if not public_key:
                logger.error(f"❌ Public key not found for {order_number}")
                return False
            
            # Remove from WireGuard
            if self.remove_peer_from_wireguard(public_key):
                # Update timer status
                if order_number in self.active_timers:
                    self.active_timers[order_number]['status'] = 'expired'
                    self.active_timers[order_number]['expired_at'] = datetime.now().isoformat()
                    self.save_timers()
                
                logger.info(f"✅ Config {order_number} successfully expired and disabled")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ Error expiring config {order_number}: {e}")
            return False
    
    def check_expirations(self):
        """Check and process expired configs"""
        now = datetime.now()
        expired_count = 0
        
        for order_number, timer_data in list(self.active_timers.items()):
            if timer_data.get('status') != 'active':
                continue
            
            try:
                expires_at = datetime.fromisoformat(timer_data['expires_at'])
                
                if now >= expires_at:
                    logger.info(f"⏰ Order {order_number} has expired, disabling...")
                    
                    if self.expire_config(order_number):
                        expired_count += 1
                    else:
                        logger.error(f"❌ Failed to expire {order_number}")
                        
            except Exception as e:
                logger.error(f"❌ Error checking expiration for {order_number}: {e}")
        
        return expired_count
    
    def get_status(self):
        """Get daemon status"""
        active_count = len([t for t in self.active_timers.values() if t.get('status') == 'active'])
        expired_count = len([t for t in self.active_timers.values() if t.get('status') == 'expired'])
        
        return {
            'active_timers': active_count,
            'expired_timers': expired_count,
            'total_timers': len(self.active_timers),
            'last_check': datetime.now().isoformat()
        }

# Global expiration manager
expiration_manager = ExpirationManager()

# API Routes
@app.route('/api/start-timer', methods=['POST'])
def start_timer():
    """Start expiration timer for order"""
    try:
        data = request.json
        order_number = data.get('order_number')
        tier = data.get('tier')
        duration_minutes = data.get('duration_minutes')
        
        if not all([order_number, tier, duration_minutes]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        success = expiration_manager.add_timer(order_number, tier, duration_minutes)
        
        if success:
            return jsonify({
                'success': True,
                'order_number': order_number,
                'tier': tier,
                'duration_minutes': duration_minutes,
                'message': f'Timer started for {order_number}'
            })
        else:
            return jsonify({'error': 'Failed to start timer'}), 500
            
    except Exception as e:
        logger.error(f"❌ Error starting timer: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/check-timer/<order_number>', methods=['GET'])
def check_timer(order_number):
    """Check timer status"""
    try:
        if order_number not in expiration_manager.active_timers:
            return jsonify({'error': 'Timer not found'}), 404
        
        timer_data = expiration_manager.active_timers[order_number]
        
        return jsonify({
            'order_number': order_number,
            'tier': timer_data.get('tier'),
            'status': timer_data.get('status'),
            'expires_at': timer_data.get('expires_at'),
            'duration_minutes': timer_data.get('duration_minutes')
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/daemon-status', methods=['GET'])
def daemon_status():
    """Get daemon status"""
    try:
        status = expiration_manager.get_status()
        
        # Add WireGuard status
        try:
            wg_result = subprocess.run(['wg', 'show', 'wg0'], 
                                     capture_output=True, text=True, timeout=5)
            active_peers = len([line for line in wg_result.stdout.split('\n') 
                              if line.strip().startswith('peer:')])
            status['wireguard_active_peers'] = active_peers
            status['wireguard_status'] = 'active'
        except:
            status['wireguard_active_peers'] = 0
            status['wireguard_status'] = 'error'
        
        return jsonify({
            'daemon': 'running',
            'timestamp': datetime.now().isoformat(),
            **status
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def run_expiration_checker():
    """Background thread for checking expirations"""
    logger.info("🚀 Expiration checker started")
    
    while True:
        try:
            expired_count = expiration_manager.check_expirations()
            if expired_count > 0:
                logger.info(f"✅ Processed {expired_count} expirations")
            
            # Check every 30 seconds
            time.sleep(30)
            
        except Exception as e:
            logger.error(f"❌ Expiration checker error: {e}")
            time.sleep(60)

if __name__ == '__main__':
    # Start expiration checker in background thread
    checker_thread = threading.Thread(target=run_expiration_checker, daemon=True)
    checker_thread.start()
    
    logger.info("🚀 Starting Tunnelgrain Expiration Daemon")
    
    # Start Flask API
    app.run(host='0.0.0.0', port=8080, debug=False)