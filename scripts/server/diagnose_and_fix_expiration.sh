#!/bin/bash
# diagnose_and_fix_expiration.sh - Complete diagnostic and fix

echo "🔍 TUNNELGRAIN EXPIRATION DIAGNOSTIC"
echo "===================================="

# 1. Check current status
echo ""
echo "1. Current Daemon Status:"
echo "------------------------"
systemctl status tunnelgrain-expiration --no-pager | grep -E "(Active:|Main PID:)"

echo ""
echo "2. Check Recent Logs for Errors:"
echo "--------------------------------"
journalctl -u tunnelgrain-expiration -n 50 --no-pager | grep -E "(ERROR|Failed|Error|expired|Expired)" | tail -10

echo ""
echo "3. Current Timers Status:"
echo "------------------------"
TIMERS=$(curl -s http://localhost:8081/api/list-timers)
echo "$TIMERS" | jq -r '.timers[] | "\(.order_number) - Status: \(.status), Remaining: \(.time_remaining_minutes) min"'

echo ""
echo "4. WireGuard Peers Count:"
echo "------------------------"
PEER_COUNT=$(wg show wg0 | grep -c 'peer:' || echo 0)
echo "Active peers: $PEER_COUNT"

echo ""
echo "5. Test Force Expiration:"
echo "------------------------"
# Find an expired timer
EXPIRED_ORDER=$(echo "$TIMERS" | jq -r '.timers[] | select(.time_remaining_minutes == 0) | .order_number' | head -1)
if [ ! -z "$EXPIRED_ORDER" ]; then
    echo "Force expiring: $EXPIRED_ORDER"
    RESULT=$(curl -s -X POST http://localhost:8081/api/force-expire/$EXPIRED_ORDER)
    echo "Result: $RESULT"
else
    echo "No expired timers found to test"
fi

echo ""
echo "🔧 APPLYING FIXES..."
echo "===================="

# Stop current daemon
echo "Stopping current daemon..."
systemctl stop tunnelgrain-expiration

# Create fixed version with better logging
echo "Creating fixed expiration daemon..."
cat > /opt/tunnelgrain/expiration_daemon_fixed.py << 'DAEMON_EOF'
#!/usr/bin/env python3
"""
Tunnelgrain VPS Expiration Daemon v3.2 - FIXED
With proper expiration checking and debugging
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
import copy

# Configuration
CONFIG_BASE = "/opt/tunnelgrain"
TIMER_FILE = f"{CONFIG_BASE}/active_timers.json"
LOG_FILE = f"{CONFIG_BASE}/logs/expiration.log"
PEER_MAP_FILE = f"{CONFIG_BASE}/peer_mapping.json"

# Create directories
os.makedirs(f"{CONFIG_BASE}/logs", exist_ok=True)

# Setup logging with more detail
logging.basicConfig(
    level=logging.DEBUG,  # Changed to DEBUG for more info
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
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
        self.lock = threading.RLock()  # Use RLock to prevent deadlocks
        self.running = True
        self.checker_running = False  # Track if checker is running
        self.load_data()
        self.build_peer_mapping_from_wg()
        
    def load_data(self):
        """Load active timers and peer mapping from disk"""
        try:
            # Load timers
            if os.path.exists(TIMER_FILE):
                try:
                    with open(TIMER_FILE, 'r') as f:
                        data = json.load(f)
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
                logger.info("No existing timer file found")
            
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
                logger.info("No existing peer mapping file found")
                
        except Exception as e:
            logger.error(f"Critical error in load_data: {e}")
            self.active_timers = {}
            self.peer_mapping = {}
    
    def save_data(self):
        """Save timers and peer mapping to disk"""
        try:
            timers_copy = None
            peer_mapping_copy = None
            
            with self.lock:
                timers_copy = copy.deepcopy(self.active_timers)
                peer_mapping_copy = copy.deepcopy(self.peer_mapping)
            
            if timers_copy is not None:
                with open(TIMER_FILE, 'w') as f:
                    json.dump(timers_copy, f, indent=2, default=str)
            
            if peer_mapping_copy is not None:
                with open(PEER_MAP_FILE, 'w') as f:
                    json.dump(peer_mapping_copy, f, indent=2)
                    
        except Exception as e:
            logger.error(f"Error saving data: {e}")
    
    def build_peer_mapping_from_wg(self):
        """Build peer mapping from existing WireGuard config"""
        try:
            if not os.path.exists('/etc/wireguard/wg0.conf'):
                logger.warning("WireGuard config not found")
                return
                
            with open('/etc/wireguard/wg0.conf', 'r') as f:
                content = f.read()
            
            lines = content.split('\n')
            current_order = None
            new_mappings = {}
            
            for i, line in enumerate(lines):
                if line.strip().startswith('#') and ('42' in line or '72' in line):
                    parts = line.strip().split()
                    for part in parts:
                        if (part.startswith('42') or part.startswith('72')) and len(part) == 8:
                            current_order = part
                            break
                
                elif current_order and line.strip().startswith('PublicKey'):
                    parts = line.strip().split('=', 1)
                    if len(parts) == 2:
                        public_key = parts[1].strip()
                        
                        if current_order.startswith('72'):
                            tier = 'test'
                        else:
                            tier = self.find_tier_for_order(current_order)
                        
                        if tier:
                            new_mappings[current_order] = {
                                'public_key': public_key,
                                'config_id': current_order,
                                'tier': tier
                            }
                            logger.debug(f"Mapped {current_order} -> {public_key[:16]}... (tier: {tier})")
                        
                        current_order = None
            
            if new_mappings:
                with self.lock:
                    self.peer_mapping.update(new_mappings)
                self.save_data()
                logger.info(f"Built peer mapping with {len(new_mappings)} entries")
            
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
        with self.lock:
            if order_number in self.peer_mapping:
                return self.peer_mapping[order_number].get('public_key')
        
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
        try:
            public_key = self.get_public_key_for_order(order_number)
            
            if not public_key:
                logger.error(f"Could not find public key for {order_number}")
            
            expires_at = datetime.now() + timedelta(minutes=duration_minutes)
            
            with self.lock:
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
                
                if public_key:
                    self.peer_mapping[order_number] = {
                        'public_key': public_key,
                        'config_id': config_id,
                        'tier': tier
                    }
            
            self.save_data()
            
            logger.info(f"⏰ Timer added: {order_number} expires in {duration_minutes} minutes at {expires_at}")
            if public_key:
                logger.info(f"   Public key: {public_key[:16]}...")
            
            return True
            
        except Exception as e:
            logger.error(f"Error adding timer: {e}", exc_info=True)
            return False
    
    def remove_peer_from_wireguard(self, public_key, order_number):
        """Remove peer from WireGuard interface"""
        try:
            # First, remove from running interface
            logger.info(f"Removing peer {public_key[:16]}... for order {order_number}")
            
            result = subprocess.run([
                'wg', 'set', 'wg0', 'peer', public_key, 'remove'
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                logger.info(f"✅ Removed peer from WireGuard interface")
            else:
                logger.error(f"❌ Failed to remove peer: {result.stderr}")
                return False
            
            # Now remove from config file
            try:
                with open('/etc/wireguard/wg0.conf', 'r') as f:
                    lines = f.readlines()
                
                new_lines = []
                skip_section = False
                i = 0
                
                while i < len(lines):
                    line = lines[i]
                    
                    # Check if this section contains our public key
                    if line.strip() == '[Peer]':
                        # Look ahead for PublicKey
                        j = i + 1
                        found_key = False
                        while j < len(lines) and not lines[j].strip().startswith('['):
                            if lines[j].strip().startswith('PublicKey') and public_key in lines[j]:
                                found_key = True
                                break
                            j += 1
                        
                        if found_key:
                            # Skip this entire peer section
                            skip_section = True
                            logger.info(f"Found and removing peer section from config")
                        else:
                            skip_section = False
                    
                    if not skip_section:
                        new_lines.append(line)
                    elif line.strip().startswith('[') and line.strip() != '[Peer]':
                        # End of peer section, stop skipping
                        skip_section = False
                        new_lines.append(line)
                    
                    i += 1
                
                # Write updated config
                with open('/etc/wireguard/wg0.conf', 'w') as f:
                    f.writelines(new_lines)
                
                logger.info(f"✅ Updated WireGuard config file")
                
                # Reload WireGuard
                reload_result = subprocess.run([
                    'systemctl', 'reload', 'wg-quick@wg0'
                ], capture_output=True, text=True, timeout=10)
                
                if reload_result.returncode == 0:
                    logger.info(f"✅ WireGuard reloaded successfully")
                else:
                    logger.warning(f"⚠️ WireGuard reload failed: {reload_result.stderr}")
                
                return True
                
            except Exception as e:
                logger.error(f"❌ Error updating config: {e}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error removing peer: {e}")
            return False
    
    def expire_config(self, order_number):
        """Expire a config by removing it from WireGuard"""
        try:
            timer_data = None
            with self.lock:
                timer_data = self.active_timers.get(order_number)
                
            if not timer_data:
                logger.error(f"No timer found for {order_number}")
                return False
            
            public_key = timer_data.get('public_key')
            if not public_key:
                public_key = self.get_public_key_for_order(order_number)
                if public_key:
                    with self.lock:
                        if order_number in self.active_timers:
                            self.active_timers[order_number]['public_key'] = public_key
            
            if not public_key:
                logger.error(f"No public key found for {order_number}")
                return False
            
            logger.info(f"🔥 Expiring order {order_number} with key {public_key[:16]}...")
            
            if self.remove_peer_from_wireguard(public_key, order_number):
                with self.lock:
                    if order_number in self.active_timers:
                        self.active_timers[order_number]['status'] = 'expired'
                        self.active_timers[order_number]['expired_at'] = datetime.now().isoformat()
                
                self.save_data()
                
                logger.info(f"✅ Config {order_number} successfully expired")
                return True
            else:
                logger.error(f"❌ Failed to remove peer for {order_number}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error expiring config {order_number}: {e}", exc_info=True)
            return False
    
    def check_expirations(self):
        """Check and process expired configs"""
        logger.debug("🔍 Checking for expired configs...")
        now = datetime.now()
        expired_count = 0
        
        orders_to_expire = []
        with self.lock:
            for order_number, timer_data in list(self.active_timers.items()):
                if timer_data.get('status') != 'active':
                    continue
                
                try:
                    expires_at = datetime.fromisoformat(timer_data['expires_at'])
                    
                    if now >= expires_at:
                        logger.info(f"⏰ Found expired order: {order_number} (expired at {expires_at})")
                        orders_to_expire.append(order_number)
                        
                except Exception as e:
                    logger.error(f"Error checking expiration for {order_number}: {e}")
        
        # Expire orders without holding lock
        for order_number in orders_to_expire:
            logger.info(f"💀 Expiring order {order_number}...")
            
            if self.expire_config(order_number):
                expired_count += 1
                logger.info(f"✅ Successfully expired {order_number}")
            else:
                logger.error(f"❌ Failed to expire {order_number}")
        
        if expired_count > 0:
            logger.info(f"✅ Expired {expired_count} configs this cycle")
        else:
            logger.debug("No configs expired this cycle")
        
        return expired_count
    
    def get_status(self):
        """Get daemon status"""
        with self.lock:
            active_count = len([t for t in self.active_timers.values() if t.get('status') == 'active'])
            expired_count = len([t for t in self.active_timers.values() if t.get('status') == 'expired'])
            total_count = len(self.active_timers)
        
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
            'total_timers': total_count,
            'wireguard_peers': peer_count,
            'last_check': datetime.now().isoformat(),
            'checker_running': self.checker_running
        }

# Global expiration manager
expiration_manager = ExpirationManager()

# API Routes (same as before but with better error handling)
@app.route('/api/start-timer', methods=['POST'])
def start_timer():
    """Start expiration timer for order"""
    try:
        data = request.json
        order_number = data.get('order_number')
        tier = data.get('tier')
        duration_minutes = data.get('duration_minutes')
        config_id = data.get('config_id', order_number)
        
        if not all([order_number, tier, duration_minutes]):
            return jsonify({'error': 'Missing required fields'}), 400
        
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
        logger.error(f"❌ Error starting timer: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/check-timer/<order_number>', methods=['GET'])
def check_timer(order_number):
    """Check timer status"""
    try:
        with expiration_manager.lock:
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
        logger.error(f"Error in check_timer: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/status', methods=['GET'])
def get_status():
    """Get comprehensive VPS status"""
    try:
        status = expiration_manager.get_status()
        
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
            'version': '3.2',
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
        logger.error(f"Error getting status: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/force-expire/<order_number>', methods=['POST'])
def force_expire(order_number):
    """Force expire a specific order"""
    try:
        logger.info(f"🔨 Force expire request for {order_number}")
        
        with expiration_manager.lock:
            timer_exists = order_number in expiration_manager.active_timers
            
        if not timer_exists:
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
        logger.error(f"❌ Error forcing expiration: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health():
    """Simple health check"""
    return jsonify({
        'status': 'healthy',
        'version': '3.2',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/list-timers', methods=['GET'])
def list_timers():
    """List all active timers"""
    try:
        timers_copy = {}
        with expiration_manager.lock:
            timers_copy = copy.deepcopy(expiration_manager.active_timers)
        
        timers = []
        now = datetime.now()
        
        for order_number, timer_data in timers_copy.items():
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
        
        timers.sort(key=lambda x: x.get('expires_at', ''))
        
        return jsonify({
            'timers': timers,
            'total_count': len(timers),
            'active_count': len([t for t in timers if t['status'] == 'active'])
        })
        
    except Exception as e:
        logger.error(f"Error listing timers: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

def run_expiration_checker():
    """Background thread for checking expirations"""
    logger.info("🚀 Expiration checker thread started")
    expiration_manager.checker_running = True
    
    while expiration_manager.running:
        try:
            logger.debug("Running expiration check cycle...")
            expired_count = expiration_manager.check_expirations()
            
            # Check every 30 seconds
            time.sleep(30)
            
        except Exception as e:
            logger.error(f"❌ Expiration checker error: {e}", exc_info=True)
            time.sleep(60)
    
    expiration_manager.checker_running = False
    logger.info("Expiration checker thread stopped")

def signal_handler(sig, frame):
    """Handle shutdown gracefully"""
    logger.info("Shutting down expiration daemon...")
    expiration_manager.running = False
    expiration_manager.save_data()
    sys.exit(0)

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start expiration checker in background thread
    checker_thread = threading.Thread(target=run_expiration_checker, daemon=True)
    checker_thread.start()
    
    logger.info("🚀 Starting Tunnelgrain VPS Expiration Daemon v3.2")
    logger.info(f"Config base: {CONFIG_BASE}")
    logger.info(f"Timer file: {TIMER_FILE}")
    logger.info(f"Peer mapping: {PEER_MAP_FILE}")
    
    # Initial cleanup check
    logger.info("Running initial expiration check...")
    expired = expiration_manager.check_expirations()
    logger.info(f"Initial check expired {expired} configs")
    
    try:
        status = expiration_manager.get_status()
        logger.info(f"Initial status: {status}")
    except Exception as e:
        logger.error(f"Error getting initial status: {e}")
    
    # Start Flask API
    app.run(host='0.0.0.0', port=8081, debug=False)
DAEMON_EOF

# Make executable
chmod +x /opt/tunnelgrain/expiration_daemon_fixed.py

# Backup current daemon
mv /opt/tunnelgrain/expiration_daemon.py /opt/tunnelgrain/expiration_daemon.py.backup

# Replace with fixed version
mv /opt/tunnelgrain/expiration_daemon_fixed.py /opt/tunnelgrain/expiration_daemon.py

# Restart service
echo ""
echo "Restarting daemon with fixes..."
systemctl restart tunnelgrain-expiration

# Wait for startup
sleep 5

# Check if working
echo ""
echo "6. Verifying Fix:"
echo "----------------"
systemctl status tunnelgrain-expiration --no-pager | grep Active

echo ""
echo "7. Force Expire All Expired Timers:"
echo "-----------------------------------"
# Get all timers with 0 time remaining
EXPIRED_ORDERS=$(curl -s http://localhost:8081/api/list-timers | jq -r '.timers[] | select(.time_remaining_minutes == 0) | .order_number')

for order in $EXPIRED_ORDERS; do
    echo "Force expiring: $order"
    curl -s -X POST http://localhost:8081/api/force-expire/$order
    echo ""
done

echo ""
echo "8. Final Status:"
echo "---------------"
curl -s http://localhost:8081/api/status | jq .

echo ""
echo "✅ DIAGNOSTIC COMPLETE!"
echo ""
echo "The daemon should now properly expire configs."
echo "Monitor the logs with: journalctl -u tunnelgrain-expiration -f"