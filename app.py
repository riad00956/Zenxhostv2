from flask import Flask, jsonify, request
import sqlite3
import threading
from pathlib import Path
import logging
from datetime import datetime
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
class Config:
    DB_NAME = 'cyber_v2.db'
    PORT = 10000

app = Flask(__name__)

# Database lock
db_lock = threading.RLock()

def get_db():
    with db_lock:
        conn = sqlite3.connect(Config.DB_NAME, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

def execute_db(query, params=(), fetchone=False, fetchall=False, commit=False):
    with db_lock:
        conn = get_db()
        c = conn.cursor()
        try:
            c.execute(query, params)
            if commit:
                conn.commit()
            if fetchone:
                result = c.fetchone()
            elif fetchall:
                result = c.fetchall()
            else:
                result = None
            conn.close()
            return result
        except Exception as e:
            logger.error(f"Database error: {e}")
            conn.close()
            return None

@app.route('/')
def index():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>ZEN X Bot Hosting v3.3.2</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                margin: 0;
                padding: 20px;
                min-height: 100vh;
            }
            .container {
                max-width: 1200px;
                margin: 0 auto;
                background: rgba(255, 255, 255, 0.1);
                backdrop-filter: blur(10px);
                border-radius: 20px;
                padding: 30px;
                box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.37);
            }
            .header {
                text-align: center;
                margin-bottom: 40px;
            }
            h1 {
                font-size: 2.5em;
                margin-bottom: 10px;
            }
            .subtitle {
                font-size: 1.2em;
                opacity: 0.9;
                margin-bottom: 30px;
            }
            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 20px;
                margin-bottom: 40px;
            }
            .stat-card {
                background: rgba(255, 255, 255, 0.15);
                border-radius: 15px;
                padding: 20px;
                text-align: center;
                transition: transform 0.3s;
            }
            .stat-card:hover {
                transform: translateY(-5px);
                background: rgba(255, 255, 255, 0.2);
            }
            .stat-value {
                font-size: 2em;
                font-weight: bold;
                margin: 10px 0;
            }
            .stat-label {
                font-size: 0.9em;
                opacity: 0.8;
            }
            .api-links {
                display: flex;
                flex-wrap: wrap;
                gap: 10px;
                justify-content: center;
                margin-top: 30px;
            }
            .api-link {
                background: rgba(255, 255, 255, 0.2);
                padding: 10px 20px;
                border-radius: 25px;
                text-decoration: none;
                color: white;
                transition: background 0.3s;
            }
            .api-link:hover {
                background: rgba(255, 255, 255, 0.3);
            }
            .status-online {
                color: #4ade80;
                font-weight: bold;
            }
            .status-offline {
                color: #f87171;
                font-weight: bold;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🤖 ZEN X Bot Hosting v3.3.2</h1>
                <div class="subtitle">Auto-Recovery System • 300-Capacity Nodes • Professional Hosting</div>
                <div class="status-online">● ONLINE</div>
            </div>
            
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-label">Total Users</div>
                    <div class="stat-value" id="totalUsers">0</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Active Bots</div>
                    <div class="stat-value" id="activeBots">0</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Total Nodes</div>
                    <div class="stat-value" id="totalNodes">3</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Server Uptime</div>
                    <div class="stat-value" id="uptime">100%</div>
                </div>
            </div>
            
            <div class="api-links">
                <a href="/status" class="api-link">System Status</a>
                <a href="/api/deployments" class="api-link">Deployments API</a>
                <a href="/api/nodes" class="api-link">Nodes API</a>
                <a href="/api/stats" class="api-link">Statistics API</a>
                <a href="/api/bots" class="api-link">All Bots API</a>
                <a href="/api/users" class="api-link">Users API</a>
            </div>
        </div>
        
        <script>
            async function loadStats() {
                try {
                    const response = await fetch('/api/stats');
                    const data = await response.json();
                    
                    document.getElementById('totalUsers').textContent = data.total_users || 0;
                    document.getElementById('activeBots').textContent = data.running_bots || 0;
                    document.getElementById('totalNodes').textContent = data.total_nodes || 3;
                    document.getElementById('uptime').textContent = data.uptime_percent || '100%';
                } catch (error) {
                    console.error('Error loading stats:', error);
                }
            }
            
            // Load stats on page load
            loadStats();
            
            // Refresh stats every 30 seconds
            setInterval(loadStats, 30000);
        </script>
    </body>
    </html>
    """

@app.route('/status')
def status():
    """System status endpoint"""
    try:
        total_bots = execute_db("SELECT COUNT(*) FROM deployments", fetchone=True)[0] or 0
        running_bots = execute_db("SELECT COUNT(*) FROM deployments WHERE status='Running'", fetchone=True)[0] or 0
        total_users = execute_db("SELECT COUNT(*) FROM users", fetchone=True)[0] or 0
        total_nodes = execute_db("SELECT COUNT(*) FROM nodes", fetchone=True)[0] or 0
        
        return jsonify({
            'status': 'online',
            'version': '3.3.2',
            'auto_recovery': True,
            'total_bots': total_bots,
            'running_bots': running_bots,
            'total_users': total_users,
            'total_nodes': total_nodes,
            'uptime_percent': '99.9%',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/deployments')
def get_deployments():
    """Get all deployments"""
    try:
        deployments = execute_db("""
            SELECT d.id, d.bot_name, d.status, d.start_time, u.username, 
                   d.cpu_usage, d.ram_usage, d.restart_count, d.bot_username,
                   d.created_at, d.node_id, d.is_banned
            FROM deployments d
            LEFT JOIN users u ON d.user_id = u.id
            ORDER BY d.status DESC, d.id DESC
            LIMIT 100
        """, fetchall=True) or []
        
        result = []
        for dep in deployments:
            result.append({
                'id': dep['id'],
                'bot_name': dep['bot_name'],
                'status': dep['status'],
                'username': dep['username'],
                'bot_username': dep['bot_username'],
                'cpu_usage': dep['cpu_usage'],
                'ram_usage': dep['ram_usage'],
                'restart_count': dep['restart_count'],
                'start_time': dep['start_time'],
                'created_at': dep['created_at'],
                'node_id': dep['node_id'],
                'is_banned': bool(dep['is_banned'])
            })
        
        return jsonify({'deployments': result, 'count': len(result)})
    except Exception as e:
        logger.error(f"Error getting deployments: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/nodes')
def get_nodes():
    """Get all nodes information"""
    try:
        nodes = execute_db("SELECT * FROM nodes", fetchall=True) or []
        
        result = []
        for node in nodes:
            result.append({
                'id': node['id'],
                'name': node['name'],
                'status': node['status'],
                'capacity': node['capacity'],
                'current_load': node['current_load'],
                'region': node['region'],
                'total_deployed': node['total_deployed'],
                'last_check': node['last_check']
            })
        
        return jsonify({'nodes': result})
    except Exception as e:
        logger.error(f"Error getting nodes: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/stats')
def api_stats():
    """Get system statistics"""
    try:
        total_bots = execute_db("SELECT COUNT(*) FROM deployments", fetchone=True)[0] or 0
        running_bots = execute_db("SELECT COUNT(*) FROM deployments WHERE status='Running'", fetchone=True)[0] or 0
        total_users = execute_db("SELECT COUNT(*) FROM users", fetchone=True)[0] or 0
        prime_users = execute_db("SELECT COUNT(*) FROM users WHERE is_prime=1", fetchone=True)[0] or 0
        total_nodes = execute_db("SELECT COUNT(*) FROM nodes", fetchone=True)[0] or 0
        
        # Get today's stats
        today = datetime.now().strftime('%Y-%m-%d')
        new_users_today = execute_db("SELECT COUNT(*) FROM users WHERE DATE(join_date)=?", (today,), fetchone=True)[0] or 0
        deployments_today = execute_db("SELECT COUNT(*) FROM deployments WHERE DATE(created_at)=?", (today,), fetchone=True)[0] or 0
        
        # Get banned bots count
        banned_bots = execute_db("SELECT COUNT(*) FROM deployments WHERE is_banned=1", fetchone=True)[0] or 0
        
        return jsonify({
            'total_bots': total_bots,
            'running_bots': running_bots,
            'stopped_bots': total_bots - running_bots,
            'banned_bots': banned_bots,
            'total_users': total_users,
            'prime_users': prime_users,
            'free_users': total_users - prime_users,
            'total_nodes': total_nodes,
            'new_users_today': new_users_today,
            'deployments_today': deployments_today,
            'uptime_percent': '99.9%',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/bots')
def get_all_bots():
    """Get all bots with pagination"""
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        offset = (page - 1) * limit
        
        bots = execute_db("""
            SELECT d.*, u.username as user_username 
            FROM deployments d 
            LEFT JOIN users u ON d.user_id = u.id 
            ORDER BY d.id DESC 
            LIMIT ? OFFSET ?
        """, (limit, offset), fetchall=True) or []
        
        total_bots = execute_db("SELECT COUNT(*) FROM deployments", fetchone=True)[0] or 0
        
        result = []
        for bot in bots:
            result.append({
                'id': bot['id'],
                'bot_name': bot['bot_name'],
                'user_id': bot['user_id'],
                'user_username': bot['user_username'],
                'filename': bot['filename'],
                'status': bot['status'],
                'bot_username': bot['bot_username'],
                'is_banned': bool(bot['is_banned']),
                'created_at': bot['created_at'],
                'last_active': bot['last_active']
            })
        
        return jsonify({
            'bots': result,
            'total': total_bots,
            'page': page,
            'limit': limit,
            'total_pages': (total_bots + limit - 1) // limit
        })
    except Exception as e:
        logger.error(f"Error getting bots: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/users')
def get_all_users():
    """Get all users"""
    try:
        users = execute_db("""
            SELECT id, username, expiry, file_limit, is_prime, 
                   join_date, total_bots_deployed, total_deployments, last_active
            FROM users 
            ORDER BY id DESC
            LIMIT 100
        """, fetchall=True) or []
        
        result = []
        for user in users:
            # Calculate if prime is active
            is_active = False
            if user['expiry']:
                try:
                    expiry = datetime.strptime(user['expiry'], '%Y-%m-%d %H:%M:%S')
                    is_active = expiry > datetime.now()
                except:
                    pass
            
            result.append({
                'id': user['id'],
                'username': user['username'],
                'expiry': user['expiry'],
                'file_limit': user['file_limit'],
                'is_prime': bool(user['is_prime']),
                'is_active': is_active,
                'join_date': user['join_date'],
                'total_bots': user['total_bots_deployed'],
                'total_deployments': user['total_deployments'],
                'last_active': user['last_active']
            })
        
        return jsonify({'users': result, 'count': len(result)})
    except Exception as e:
        logger.error(f"Error getting users: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/bot/<int:bot_id>')
def get_bot_details(bot_id):
    """Get details of a specific bot"""
    try:
        bot = execute_db("""
            SELECT d.*, u.username as user_username 
            FROM deployments d 
            LEFT JOIN users u ON d.user_id = u.id 
            WHERE d.id=?
        """, (bot_id,), fetchone=True)
        
        if not bot:
            return jsonify({'error': 'Bot not found'}), 404
        
        # Get backups for this bot
        backups = execute_db("SELECT * FROM bot_backups WHERE bot_id=? ORDER BY id DESC", (bot_id,), fetchall=True) or []
        
        result = {
            'id': bot['id'],
            'bot_name': bot['bot_name'],
            'user_id': bot['user_id'],
            'user_username': bot['user_username'],
            'filename': bot['filename'],
            'status': bot['status'],
            'bot_username': bot['bot_username'],
            'is_banned': bool(bot['is_banned']),
            'token': bot['token'] and '***' + bot['token'][-10:] if bot['token'] else None,
            'created_at': bot['created_at'],
            'last_active': bot['last_active'],
            'start_time': bot['start_time'],
            'node_id': bot['node_id'],
            'restart_count': bot['restart_count'],
            'auto_restart': bool(bot['auto_restart']),
            'backups_count': len(backups),
            'backups': [
                {
                    'id': backup['id'],
                    'backup_name': backup['backup_name'],
                    'created_at': backup['created_at'],
                    'size_kb': backup['size_kb']
                }
                for backup in backups[:5]  # Limit to 5 most recent
            ]
        }
        
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error getting bot details: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/backup/<int:bot_id>', methods=['POST'])
def create_backup(bot_id):
    """Create a backup for a bot"""
    try:
        # In a real implementation, this would call the backup creation function
        return jsonify({
            'success': True,
            'message': f'Backup creation requested for bot {bot_id}',
            'bot_id': bot_id,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error creating backup: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health_check():
    """Health check endpoint for monitoring"""
    try:
        # Basic health check
        execute_db("SELECT 1", fetchone=True)
        
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'database': 'disconnected',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=Config.PORT, debug=False)
