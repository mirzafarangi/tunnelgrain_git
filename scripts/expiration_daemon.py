#!/usr/bin/env python3
"""
Tunnelgrain VPS Expiration Daemon
Runs on VPS server to enforce config expiration by removing peers from WireGuard
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
PEER_MAP_FILE = f"{CONFIG_BASE}/peer_mapping.json"

# Create directories
os.makedirs(f"{CONFIG_BASE}/logs", exist_ok=True)

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

# Flask app for API
app = Flask(__name__)

class ExpirationManager:
    def __init__(self):
        self.active_timers = {}
        self.peer_mapping = {}
        self.lock = threading.Lock()
        self.load_data()
        
    def load_data(self):
        """Load active timers and peer mapping from disk"""
        # Load timers
        if os.path.exists(TIMER_FILE):
            try:
                with open(TIMER_FILE, 'r') as f:
                    self.active_timers = json.load(f)
                logger.info(f"Loaded {len(self.active_timers)} active timers")
            except Exception as e:
                logger.error(f"Error loading timers: {e}")
                self.active_timers = {}
        
        # Load peer mapping
        if os.path.exists(PEER_MAP_FILE):
            try:
                with open(PEER_MAP_FILE, 'r') as f:
                    self.peer_mapping = json.load(f)
                logger.info(f"Loaded {len(self.peer_mapping)} peer mappings")
            except Exception as e:
                logger.error(f"Error loading peer mapping: {e}")
                self.peer_mapping = {}
    
    def save_data(self):
        """Save timers and peer mapping to disk"""
        try:
            # Save timers
            with open(TIMER_FILE, 'w') as f:
                json.dump(self.active_timers, f, indent=2, default=str)
            
            # Save peer mapping
            with open(PEER_MAP_FILE, 'w') as f:
                json.dump(self.peer_mapping, f, indent=2)
                
        except Exception as e:
            logger.error(f"Error saving data: {e}")
    
    def extract_public_key_from_config(self, config_id, tier):
        """Extract public key from config file"""
        try:
            config_path = f"{CONFIG_BASE}/configs/{tier}/{config_id}.conf"
            
            if not os.path.exists(config_path):
                logger.error(f"Config file not found: {config_path}")
                return None
            
            # Read config and extract PublicKey
            with open(config_path, 'r') as f:
                for line in f:
                    if line.strip().startswith('PublicKey'):
                        # Format: PublicKey = <key>
                        parts = line.strip().split('=', 1)
                        if len(parts) == 2:
                            return parts[1].strip()
            
            logger.error(f"PublicKey not found in {config_path}")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting public key: {e}")
            return None
    
    def add_timer(self, order_number, tier, duration_minutes, config_id):
        """Add expiration timer and map to peer"""
        with self.lock:
            try:
                # Extract public key from config
                public_key = self.extract_public_key_from_config(config_id, tier)
                if not public_key:
                    logger.error(f"Failed to extract public key for {order_number}")
                    return False
                
                # Calculate expiration
                expires_at = datetime.now() + timedelta(minutes=duration_minutes)
                
                # Add timer
                self.active_timers[order_number] = {
                    'tier': tier,
                    'config_id': config_id,
                    'expires_at': expires_at.isoformat(),
                    'duration_minutes': duration_minutes,
                    'status': 'active',
                    'added_at': datetime.now().isoformat(),
                    'public_key': public_key
                }
                
                # Add peer mapping
                self.peer_mapping[order_number] = {
                    'public_key': public_key,
                    'config_id': config_id,
                    'tier': tier
                }
                
                self.save_data()
                logger.info(f"⏰ Timer added: {order_number} expires in {duration_minutes} minutes")
                return True
                
            except Exception as e:
                logger.error(f"Error adding timer: {e}")
                return False
    
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
        with self.lock:
            try:
                # Get timer data
                timer_data = self.active_timers.get(order_number)
                if not timer_data:
                    logger.error(f"No timer found for {order_number}")
                    return False
                
                # Get public key
                public_key = timer_data.get('public_key')
                if not public_key:
                    # Try from peer mapping
                    peer_data = self.peer_mapping.get(order_number, {})
                    public_key = peer_data.get('public_key')
                
                if not public_key:
                    logger.error(f"No public key found for {order_number}")
                    return False
                
                # Remove from WireGuard
                if self.remove_peer_from_wireguard(public_key):
                    # Update timer status
                    timer_data['status'] = 'expired'
                    timer_data['expired_at'] = datetime.now().isoformat()
                    self.save_data()
                    
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
        
        with self.lock:
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
        
        # Get WireGuard peer count
        try:
            result = subprocess.run(['wg', 'show', 'wg0'], 
                                  capture_output=True, text=True, timeout=5)
            peer_count = len([line for line in result.stdout.split('\n') 
                            if line.strip().startswith('peer:')])
        except:
            peer_count = -1
        
        return {
            'active_timers': active_count,
            'expired_timers': expired_count,
            'total_timers': len(self.active_timers),
            'wireguard_peers': peer_count,
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
        
        # Extract config_id from order number (last 8 chars of order match config_id)
        # This assumes config_id is embedded in order_number
        config_id = data.get('config_id', order_number[-8:])
        
        if not all([order_number, tier, duration_minutes]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Validate duration
        duration_minutes = int(duration_minutes)
        if duration_minutes <= 0:
            return jsonify({'error': 'Invalid duration'}), 400
        
        success = expiration_manager.add_timer(order_number, tier, duration_minutes, config_id)
        
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
        timer_data = expiration_manager.active_timers.get(order_number)
        
        if not timer_data:
            return jsonify({'error': 'Timer not found'}), 404
        
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
            'status': timer_data.get('status', 'expired' if is_expired else 'active'),
            'expires_at': timer_data.get('expires_at'),
            'time_remaining_seconds': time_remaining,
            'time_remaining_minutes': time_remaining / 60
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/status', methods=['GET'])
def get_status():
    """Get comprehensive VPS status"""
    try:
        status = expiration_manager.get_status()
        
        # Add config file counts
        config_counts = {}
        base_path = Path(CONFIG_BASE) / 'configs'
        
        if base_path.exists():
            for tier_dir in base_path.iterdir():
                if tier_dir.is_dir():
                    tier_name = tier_dir.name
                    config_count = len(list(tier_dir.glob('*.conf')))
                    config_counts[tier_name] = config_count
        
        return jsonify({
            'daemon': 'running',
            'timestamp': datetime.now().isoformat(),
            'server_ip': '213.170.133.116',
            'timers': status,
            'configs': config_counts,
            'wireguard': {
                'status': 'active' if status['wireguard_peers'] >= 0 else 'error',
                'active_peers': status['wireguard_peers']
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/force-expire/<order_number>', methods=['POST'])
def force_expire(order_number):
    """Force expire a specific order"""
    try:
        success = expiration_manager.expire_config(order_number)
        
        if success:
            return jsonify({
                'success': True,
                'order_number': order_number,
                'message': f'Order {order_number} has been expired'
            })
        else:
            return jsonify({'error': 'Failed to expire order'}), 500
            
    except Exception as e:
        logger.error(f"❌ Error forcing expiration: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health():
    """Simple health check"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    })

def run_expiration_checker():
    """Background thread for checking expirations"""
    logger.info("🚀 Expiration checker thread started")
    
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
    
    logger.info("🚀 Starting Tunnelgrain VPS Expiration Daemon")
    logger.info(f"Config base: {CONFIG_BASE}")
    logger.info(f"Timer file: {TIMER_FILE}")
    logger.info(f"Peer mapping: {PEER_MAP_FILE}")
    
    # Start Flask API
    app.run(host='0.0.0.0', port=8080, debug=False)