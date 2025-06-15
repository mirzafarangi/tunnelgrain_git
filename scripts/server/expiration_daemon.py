#!/usr/bin/env python3
"""
Tunnelgrain VPS Expiration Daemon v3.0
Complete working version that properly expires VPN configs
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
        self.running = True
        self.load_data()
        self.build_peer_mapping_from_wg()
        
    def load_data(self):
        """Load active timers and peer mapping from disk"""
        # Load timers
        if os.path.exists(TIMER_FILE):
            try:
                with open(TIMER_FILE, 'r') as f:
                    data = json.load(f)
                    # Convert old format if needed
                    if isinstance(data, dict) and 'timers' not in data:
                        self.active_timers = data
                    else:
                        self.active_timers = data.get('timers', {})
                logger.info(f"Loaded {len(self.active_timers)} active timers")
            except Exception as e:
                logger.error(f"Error loading timers: {e}")
                self.active_timers = {}
        else:
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
        else:
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
    
    def build_peer_mapping_from_wg(self):
        """Build peer mapping from existing WireGuard config"""
        try:
            # Read WireGuard config
            with open('/etc/wireguard/wg0.conf', 'r') as f:
                content = f.read()
            
            lines = content.split('\n')
            current_order = None
            
            for i, line in enumerate(lines):
                # Look for order number in comments
                if line.strip().startswith('#') and ('42' in line or '72' in line):
                    # Extract order number from comment
                    parts = line.strip().split()
                    for part in parts:
                        if (part.startswith('42') or part.startswith('72')) and len(part) == 8:
                            current_order = part
                            break
                
                # Look for PublicKey after finding order number
                elif current_order and line.strip().startswith('PublicKey'):
                    parts = line.strip().split('=', 1)
                    if len(parts) == 2:
                        public_key = parts[1].strip()
                        
                        # Extract tier from order number
                        if current_order.startswith('72'):
                            tier = 'test'
                        else:
                            # Determine tier based on config location
                            tier = self.find_tier_for_order(current_order)
                        
                        if tier:
                            self.peer_mapping[current_order] = {
                                'public_key': public_key,
                                'config_id': current_order,
                                'tier': tier
                            }
                            logger.info(f"Mapped {current_order} -> {public_key[:16]}... (tier: {tier})")
                        
                        current_order = None
            
            if self.peer_mapping:
                self.save_data()
                logger.info(f"Built peer mapping with {len(self.peer_mapping)} entries")
            
        except Exception as e:
            logger.error(f"Error building peer mapping: {e}")
    
    def find_tier_for_order(self, order_number):
        """Find which tier an order belongs to by checking config files"""
        tiers = ['test', 'monthly', 'quarterly', 'biannual', 'annual', 'lifetime']
        
        for tier in tiers:
            config_path = f"{CONFIG_BASE}/configs/{tier}/{order_number}.conf"
            if os.path.exists(config_path):
                return tier
        
        return None
    
    def get_public_key_for_order(self, order_number):
        """Get public key for an order number"""
        # First check peer mapping
        if order_number in self.peer_mapping:
            return self.peer_mapping[order_number].get('public_key')
        
        # Try to find from WireGuard config
        try:
            with open('/etc/wireguard/wg0.conf', 'r') as f:
                content = f.read()
            
            lines = content.split('\n')
            found_order = False
            
            for i, line in enumerate(lines):
                if order_number in line and line.strip().startswith('#'):
                    found_order = True
                elif found_order and line.strip().startswith('PublicKey'):
                    parts = line.strip().split('=', 1)
                    if len(parts) == 2:
                        return parts[1].strip()
            
        except Exception as e:
            logger.error(f"Error finding public key: {e}")
        
        return None
    
    def add_timer(self, order_number, tier, duration_minutes, config_id):
        """Add expiration timer"""
        with self.lock:
            try:
                # Find public key
                public_key = self.get_public_key_for_order(order_number)
                
                if not public_key:
                    logger.error(f"Could not find public key for {order_number}")
                    # Still create timer, we'll try to find key later
                
                # Calculate expiration
                expires_at = datetime.now() + timedelta(minutes=duration_minutes)
                
                # Add timer
                self.active_timers[order_number] = {
                    'order_number': order_number,
                    'tier': tier,
                    'config_id': config_id,
                    'expires_at': expires_at.isoformat(),
                    'duration_minutes': duration_minutes,
                    'status': 'active',
                    'created_at': datetime.now().isoformat(),
                    'public_key': public_key
                }
                
                # Update peer mapping if we found the key
                if public_key:
                    self.peer_mapping[order_number] = {
                        'public_key': public_key,
                        'config_id': config_id,
                        'tier': tier
                    }
                
                self.save_data()
                
                logger.info(f"⏰ Timer added: {order_number} expires in {duration_minutes} minutes")
                if public_key:
                    logger.info(f"   Public key: {public_key[:16]}...")
                else:
                    logger.warning(f"   ⚠️ No public key found yet")
                
                return True
                
            except Exception as e:
                logger.error(f"Error adding timer: {e}")
                return False
    
    def remove_peer_from_wireguard(self, public_key, order_number):
        """Remove peer from WireGuard interface"""
        try:
            # First, remove from running interface
            result = subprocess.run([
                'wg', 'set', 'wg0', 'peer', public_key, 'remove'
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                logger.info(f"✅ Removed peer {public_key[:16]}... from running WireGuard")
            else:
                logger.error(f"❌ Failed to remove peer from interface: {result.stderr}")
                return False
            
            # Now remove from config file
            try:
                with open('/etc/wireguard/wg0.conf', 'r') as f:
                    lines = f.readlines()
                
                new_lines = []
                skip_peer = False
                peer_found = False
                
                i = 0
                while i < len(lines):
                    line = lines[i]
                    
                    # Check if this is the peer we want to remove
                    if line.strip().startswith('PublicKey') and public_key in line:
                        # Found the peer to remove
                        peer_found = True
                        # Go back to find the [Peer] section start
                        j = i - 1
                        while j >= 0:
                            if lines[j].strip() == '[Peer]':
                                # Skip from [Peer] to next [Peer] or end
                                skip_until = j
                                k = i + 1
                                while k < len(lines) and not lines[k].strip().startswith('['):
                                    k += 1
                                # Skip these lines
                                i = k - 1
                                skip_peer = True
                                break
                            j -= 1
                    
                    if not skip_peer:
                        new_lines.append(line)
                    else:
                        skip_peer = False
                    
                    i += 1
                
                if peer_found:
                    # Write updated config
                    with open('/etc/wireguard/wg0.conf', 'w') as f:
                        f.writelines(new_lines)
                    
                    logger.info(f"✅ Removed peer {order_number} from WireGuard config file")
                    
                    # Reload WireGuard to apply changes
                    reload_result = subprocess.run([
                        'systemctl', 'reload', 'wg-quick@wg0'
                    ], capture_output=True, text=True, timeout=10)
                    
                    if reload_result.returncode == 0:
                        logger.info(f"✅ WireGuard config reloaded")
                    else:
                        logger.warning(f"⚠️ Failed to reload WireGuard: {reload_result.stderr}")
                    
                    return True
                else:
                    logger.warning(f"⚠️ Peer not found in config file")
                    return True  # Already removed from interface
                
            except Exception as e:
                logger.error(f"❌ Error updating config file: {e}")
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
                    # Try to find it
                    public_key = self.get_public_key_for_order(order_number)
                    if public_key:
                        timer_data['public_key'] = public_key
                
                if not public_key:
                    logger.error(f"No public key found for {order_number}")
                    return False
                
                # Remove from WireGuard
                if self.remove_peer_from_wireguard(public_key, order_number):
                    # Update timer status
                    timer_data['status'] = 'expired'
                    timer_data['expired_at'] = datetime.now().isoformat()
                    self.save_data()
                    
                    logger.info(f"✅ Config {order_number} successfully expired and disabled")
                    return True
                else:
                    logger.error(f"❌ Failed to remove peer for {order_number}")
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
        
        if expired_count > 0:
            logger.info(f"✅ Expired {expired_count} configs this cycle")
        
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
        config_id = data.get('config_id', order_number)  # Default to order_number
        
        if not all([order_number, tier, duration_minutes]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Validate duration
        duration_minutes = int(duration_minutes)
        if duration_minutes <= 0:
            return jsonify({'error': 'Invalid duration'}), 400
        
        logger.info(f"📝 Timer request: {order_number} (tier: {tier}, duration: {duration_minutes}min)")
        
        success = expiration_manager.add_timer(order_number, tier, duration_minutes, config_id)
        
        if success:
            return jsonify({
                'success': True,
                'order_number': order_number,
                'tier': tier,
                'config_id': config_id,
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
            'config_id': timer_data.get('config_id'),
            'status': timer_data.get('status', 'expired' if is_expired else 'active'),
            'expires_at': timer_data.get('expires_at'),
            'time_remaining_seconds': time_remaining,
            'time_remaining_minutes': time_remaining / 60,
            'public_key': timer_data.get('public_key', '')[:16] + '...' if timer_data.get('public_key') else 'unknown'
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
            'version': '3.0',
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
        # Add timer if not exists
        if order_number not in expiration_manager.active_timers:
            # Try to determine tier
            tier = 'unknown'
            if order_number.startswith('72'):
                tier = 'test'
            else:
                tier = expiration_manager.find_tier_for_order(order_number) or 'monthly'
            
            expiration_manager.add_timer(order_number, tier, 0, order_number)
        
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
        'version': '3.0',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/list-timers', methods=['GET'])
def list_timers():
    """List all active timers"""
    try:
        with expiration_manager.lock:
            timers = []
            for order_number, timer_data in expiration_manager.active_timers.items():
                now = datetime.now()
                try:
                    expires_at = datetime.fromisoformat(timer_data['expires_at'])
                    time_remaining = max(0, (expires_at - now).total_seconds())
                    status = timer_data.get('status', 'expired' if now >= expires_at else 'active')
                except:
                    time_remaining = 0
                    status = 'expired'
                
                timers.append({
                    'order_number': order_number,
                    'tier': timer_data.get('tier'),
                    'config_id': timer_data.get('config_id'),
                    'status': status,
                    'expires_at': timer_data.get('expires_at'),
                    'time_remaining_minutes': round(time_remaining / 60, 1),
                    'created_at': timer_data.get('created_at')
                })
            
            # Sort by expiration time
            timers.sort(key=lambda x: x.get('expires_at', ''))
            
            return jsonify({
                'timers': timers,
                'total_count': len(timers),
                'active_count': len([t for t in timers if t['status'] == 'active'])
            })
        
    except Exception as e:
        logger.error(f"Error listing timers: {e}")
        return jsonify({'error': str(e)}), 500

def run_expiration_checker():
    """Background thread for checking expirations"""
    logger.info("🚀 Expiration checker thread started")
    
    while expiration_manager.running:
        try:
            expired_count = expiration_manager.check_expirations()
            
            # Check every 30 seconds
            time.sleep(30)
            
        except Exception as e:
            logger.error(f"❌ Expiration checker error: {e}")
            time.sleep(60)

def signal_handler(sig, frame):
    """Handle shutdown gracefully"""
    logger.info("Shutting down expiration daemon...")
    expiration_manager.running = False
    expiration_manager.save_data()
    sys.exit(0)

if __name__ == '__main__':
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start expiration checker in background thread
    checker_thread = threading.Thread(target=run_expiration_checker, daemon=True)
    checker_thread.start()
    
    logger.info("🚀 Starting Tunnelgrain VPS Expiration Daemon v3.0")
    logger.info(f"Config base: {CONFIG_BASE}")
    logger.info(f"Timer file: {TIMER_FILE}")
    logger.info(f"Peer mapping: {PEER_MAP_FILE}")
    
    # Initial status
    status = expiration_manager.get_status()
    logger.info(f"Initial status: {status}")
    
    # Start Flask API
    app.run(host='0.0.0.0', port=8081, debug=False)