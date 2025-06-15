#!/usr/bin/env python3
"""
Tunnelgrain VPS Expiration Daemon v4.0 CLEAN
Production-ready version with proper WireGuard handling
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
import signal
import sys
import re

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

# Flask app
app = Flask(__name__)

class ExpirationManager:
    def __init__(self):
        self.active_timers = {}
        self.peer_mapping = {}
        self.lock = threading.RLock()
        self.running = True
        self.load_data()
        self.build_peer_mapping()
        
    def load_data(self):
        """Load saved timer data"""
        if os.path.exists(TIMER_FILE):
            try:
                with open(TIMER_FILE, 'r') as f:
                    self.active_timers = json.load(f)
                logger.info(f"Loaded {len(self.active_timers)} timers")
            except:
                self.active_timers = {}
        
        if os.path.exists(PEER_MAP_FILE):
            try:
                with open(PEER_MAP_FILE, 'r') as f:
                    self.peer_mapping = json.load(f)
                logger.info(f"Loaded {len(self.peer_mapping)} peer mappings")
            except:
                self.peer_mapping = {}
    
    def save_data(self):
        """Save data to disk"""
        try:
            with self.lock:
                with open(TIMER_FILE, 'w') as f:
                    json.dump(self.active_timers, f, indent=2, default=str)
                with open(PEER_MAP_FILE, 'w') as f:
                    json.dump(self.peer_mapping, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving data: {e}")
    
    def build_peer_mapping(self):
        """Build mapping of order numbers to public keys from WireGuard config"""
        try:
            if not os.path.exists('/etc/wireguard/wg0.conf'):
                logger.warning("WireGuard config not found")
                return
            
            with open('/etc/wireguard/wg0.conf', 'r') as f:
                content = f.read()
            
            # Parse config for order numbers and public keys
            lines = content.split('\n')
            current_order = None
            
            for i, line in enumerate(lines):
                # Find order number in comment
                if line.strip().startswith('#'):
                    match = re.search(r'(42[A-F0-9]{6}|72[A-F0-9]{6})', line)
                    if match:
                        current_order = match.group(1)
                
                # Find public key
                elif current_order and line.strip().startswith('PublicKey'):
                    parts = line.split('=', 1)
                    if len(parts) == 2:
                        public_key = parts[1].strip()
                        tier = 'test' if current_order.startswith('72') else self.find_tier(current_order)
                        
                        self.peer_mapping[current_order] = {
                            'public_key': public_key,
                            'tier': tier,
                            'config_id': current_order
                        }
                        current_order = None
            
            self.save_data()
            logger.info(f"Built peer mapping with {len(self.peer_mapping)} entries")
            
        except Exception as e:
            logger.error(f"Error building peer mapping: {e}")
    
    def find_tier(self, order_number):
        """Find tier by checking config file location"""
        for tier in ['test', 'monthly', 'quarterly', 'biannual', 'annual', 'lifetime']:
            if os.path.exists(f"{CONFIG_BASE}/configs/{tier}/{order_number}.conf"):
                return tier
        return 'monthly'
    
    def get_public_key(self, order_number):
        """Get public key for an order"""
        # Check mapping first
        if order_number in self.peer_mapping:
            return self.peer_mapping[order_number].get('public_key')
        
        # Search in WireGuard config
        try:
            with open('/etc/wireguard/wg0.conf', 'r') as f:
                content = f.read()
            
            # Find the order number and get its public key
            if order_number in content:
                lines = content.split('\n')
                found_order = False
                
                for line in lines:
                    if order_number in line:
                        found_order = True
                    elif found_order and line.strip().startswith('PublicKey'):
                        parts = line.split('=', 1)
                        if len(parts) == 2:
                            return parts[1].strip()
        except:
            pass
        
        return None
    
    def add_timer(self, order_number, tier, duration_minutes, config_id=None):
        """Add expiration timer for a config"""
        try:
            # Get public key
            public_key = self.get_public_key(order_number)
            
            if not public_key:
                logger.warning(f"No public key found for {order_number} - will try later")
            
            # Calculate expiration
            expires_at = datetime.now() + timedelta(minutes=duration_minutes)
            
            with self.lock:
                self.active_timers[order_number] = {
                    'order_number': order_number,
                    'tier': tier,
                    'config_id': config_id or order_number,
                    'expires_at': expires_at.isoformat(),
                    'duration_minutes': duration_minutes,
                    'status': 'active',
                    'created_at': datetime.now().isoformat(),
                    'public_key': public_key
                }
                
                if public_key:
                    self.peer_mapping[order_number] = {
                        'public_key': public_key,
                        'tier': tier,
                        'config_id': config_id or order_number
                    }
            
            self.save_data()
            logger.info(f"⏰ Timer added: {order_number} ({tier}) expires in {duration_minutes} minutes")
            
            return True
            
        except Exception as e:
            logger.error(f"Error adding timer: {e}")
            return False
    
    def remove_peer(self, order_number):
        """Remove peer from WireGuard (both interface and config)"""
        try:
            # Get public key
            public_key = self.get_public_key(order_number)
            
            if not public_key:
                logger.error(f"No public key found for {order_number}")
                return False
            
            logger.info(f"Removing peer {order_number} (key: {public_key[:16]}...)")
            
            # 1. Remove from running interface
            result = subprocess.run([
                'wg', 'set', 'wg0', 'peer', public_key, 'remove'
            ], capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"Failed to remove from interface: {result.stderr}")
                # Continue anyway - might already be removed
            else:
                logger.info("✅ Removed from WireGuard interface")
            
            # 2. Remove from config file
            self.remove_from_config(order_number, public_key)
            
            return True
            
        except Exception as e:
            logger.error(f"Error removing peer: {e}")
            return False
    
    def remove_from_config(self, order_number, public_key):
        """Remove peer from WireGuard config file"""
        try:
            with open('/etc/wireguard/wg0.conf', 'r') as f:
                lines = f.readlines()
            
            new_lines = []
            skip = False
            i = 0
            
            while i < len(lines):
                line = lines[i]
                
                # Check if this is the peer section we want to remove
                if '[Peer]' in line:
                    # Look ahead to check if this peer contains our order number or public key
                    found = False
                    for j in range(i, min(i + 10, len(lines))):
                        if order_number in lines[j] or (public_key and public_key in lines[j]):
                            found = True
                            break
                    
                    if found:
                        skip = True
                        logger.info(f"Found peer section for {order_number}")
                        i += 1
                        continue
                
                # Stop skipping at next peer
                if skip and '[Peer]' in line:
                    skip = False
                
                if not skip:
                    new_lines.append(line)
                
                i += 1
            
            # Write updated config
            with open('/etc/wireguard/wg0.conf', 'w') as f:
                f.writelines(new_lines)
            
            logger.info("✅ Updated WireGuard config file")
            
            # Reload WireGuard to apply changes
            subprocess.run(['systemctl', 'reload', 'wg-quick@wg0'], capture_output=True)
            
        except Exception as e:
            logger.error(f"Error updating config file: {e}")
    
    def expire_config(self, order_number):
        """Expire a config by removing it from WireGuard"""
        try:
            with self.lock:
                timer_data = self.active_timers.get(order_number)
                
                if not timer_data:
                    logger.warning(f"No timer found for {order_number}")
                    # Still try to remove it
                
                # Remove from WireGuard
                if self.remove_peer(order_number):
                    # Update timer status
                    if timer_data:
                        timer_data['status'] = 'expired'
                        timer_data['expired_at'] = datetime.now().isoformat()
                    else:
                        # Create expired entry
                        self.active_timers[order_number] = {
                            'order_number': order_number,
                            'status': 'expired',
                            'expired_at': datetime.now().isoformat()
                        }
                    
                    self.save_data()
                    logger.info(f"✅ Config {order_number} expired successfully")
                    return True
                
                return False
                
        except Exception as e:
            logger.error(f"Error expiring config: {e}")
            return False
    
    def check_expirations(self):
        """Check for expired timers and remove them"""
        now = datetime.now()
        expired_count = 0
        
        with self.lock:
            for order_number, timer_data in list(self.active_timers.items()):
                if timer_data.get('status') != 'active':
                    continue
                
                try:
                    expires_at = datetime.fromisoformat(timer_data['expires_at'])
                    
                    if now >= expires_at:
                        logger.info(f"⏰ Timer expired for {order_number}")
                        
                        if self.expire_config(order_number):
                            expired_count += 1
                        
                except Exception as e:
                    logger.error(f"Error checking {order_number}: {e}")
        
        if expired_count > 0:
            logger.info(f"✅ Expired {expired_count} configs this cycle")
        
        return expired_count
    
    def get_status(self):
        """Get system status"""
        with self.lock:
            active = len([t for t in self.active_timers.values() if t.get('status') == 'active'])
            expired = len([t for t in self.active_timers.values() if t.get('status') == 'expired'])
        
        # Count WireGuard peers
        try:
            result = subprocess.run(['wg', 'show', 'wg0'], capture_output=True, text=True)
            peer_count = len([l for l in result.stdout.split('\n') if l.startswith('peer:')])
        except:
            peer_count = -1
        
        return {
            'daemon': 'running',
            'version': '4.0',
            'active_timers': active,
            'expired_timers': expired,
            'total_timers': len(self.active_timers),
            'wireguard_peers': peer_count,
            'timestamp': datetime.now().isoformat()
        }

# Create global manager
manager = ExpirationManager()

# API Routes
@app.route('/api/start-timer', methods=['POST'])
def start_timer():
    """Start expiration timer"""
    try:
        data = request.json
        success = manager.add_timer(
            data.get('order_number'),
            data.get('tier'),
            int(data.get('duration_minutes', 0)),
            data.get('config_id')
        )
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Timer started'
            })
        else:
            return jsonify({'error': 'Failed to start timer'}), 500
            
    except Exception as e:
        logger.error(f"Error in start-timer: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/force-expire/<order_number>', methods=['POST'])
def force_expire(order_number):
    """Force expire a config"""
    try:
        success = manager.expire_config(order_number)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Config {order_number} expired'
            })
        else:
            return jsonify({'error': 'Failed to expire config'}), 500
            
    except Exception as e:
        logger.error(f"Error in force-expire: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/status', methods=['GET'])
def get_status():
    """Get system status"""
    return jsonify(manager.get_status())

@app.route('/api/health', methods=['GET'])
def health():
    """Health check"""
    return jsonify({
        'status': 'healthy',
        'version': '4.0',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/list-timers', methods=['GET'])
def list_timers():
    """List all timers"""
    try:
        with manager.lock:
            timers = []
            now = datetime.now()
            
            for order_number, data in manager.active_timers.items():
                remaining = 0
                if 'expires_at' in data:
                    try:
                        expires_at = datetime.fromisoformat(data['expires_at'])
                        remaining = max(0, (expires_at - now).total_seconds())
                    except:
                        pass
                
                timers.append({
                    'order_number': order_number,
                    'tier': data.get('tier', 'unknown'),
                    'status': data.get('status', 'unknown'),
                    'time_remaining_minutes': round(remaining / 60, 1),
                    'expires_at': data.get('expires_at')
                })
        
        return jsonify({
            'timers': timers,
            'count': len(timers)
        })
        
    except Exception as e:
        logger.error(f"Error listing timers: {e}")
        return jsonify({'error': str(e)}), 500

def expiration_loop():
    """Background thread to check expirations"""
    logger.info("Starting expiration checker")
    
    while manager.running:
        try:
            manager.check_expirations()
            time.sleep(30)  # Check every 30 seconds
        except Exception as e:
            logger.error(f"Expiration loop error: {e}")
            time.sleep(60)

def signal_handler(sig, frame):
    """Graceful shutdown"""
    logger.info("Shutting down...")
    manager.running = False
    manager.save_data()
    sys.exit(0)

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start expiration checker
    checker = threading.Thread(target=expiration_loop, daemon=True)
    checker.start()
    
    logger.info("🚀 Tunnelgrain Expiration Daemon v4.0 starting")
    
    # Initial cleanup
    manager.check_expirations()
    
    # Start API
    app.run(host='0.0.0.0', port=8081, debug=False)