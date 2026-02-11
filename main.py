import os
import subprocess
import sqlite3
import telebot
import threading
import time
import uuid
import signal
import random
import platform
import zipfile
import json
import logging
from pathlib import Path
from telebot import types
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from concurrent.futures import ThreadPoolExecutor
import shutil

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('zenx_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Database lock for thread safety
db_lock = threading.RLock()

# Configuration
class Config:
    TOKEN = os.environ.get('BOT_TOKEN', '8494225623:AAG_HRSHoBpt36bdeUvYJL4ONnh-2bf6BnY')
    ADMIN_ID = int(os.environ.get('ADMIN_ID', 7832264582))
    PROJECT_DIR = 'projects'
    DB_NAME = 'cyber_v2.db'
    BACKUP_DIR = 'backups'
    LOGS_DIR = 'logs'
    EXPORTS_DIR = 'exports'
    PORT = int(os.environ.get('PORT', 10000))
    MAINTENANCE = False
    ADMIN_USERNAME = 'zerox6t9'
    BOT_USERNAME = 'zen_xbot'
    MAX_BOTS_PER_USER = 5
    MAX_CONCURRENT_DEPLOYMENTS = 4
    AUTO_RESTART_BOTS = True
    BACKUP_INTERVAL = 3600
    BOT_TIMEOUT = 300
    MAX_LOG_SIZE = 10000
    
    # Updated to 300 capacity nodes
    HOSTING_NODES = [
        {"name": "Node-1", "status": "active", "capacity": 300, "region": "Asia"},
        {"name": "Node-2", "status": "active", "capacity": 300, "region": "Asia"},
        {"name": "Node-3", "status": "active", "capacity": 300, "region": "Europe"}
    ]

# Create bot instance
try:
    bot = telebot.TeleBot(Config.TOKEN, parse_mode="Markdown")
    logger.info("TeleBot instance created successfully")
except Exception as e:
    logger.error(f"Failed to create TeleBot instance: {e}")
    raise

project_path = Path(Config.PROJECT_DIR)
project_path.mkdir(exist_ok=True)

# Thread pool for concurrent operations
executor = ThreadPoolExecutor(max_workers=5)

# User session management
user_sessions = {}
user_message_history = {}
bot_monitors = {}

# Database helper functions with thread safety
def get_db():
    """Get database connection with thread safety"""
    with db_lock:
        conn = sqlite3.connect(Config.DB_NAME, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

def execute_db(query, params=(), fetchone=False, fetchall=False, commit=False):
    """Execute database query with thread safety"""
    with db_lock:
        conn = sqlite3.connect(Config.DB_NAME, check_same_thread=False)
        conn.row_factory = sqlite3.Row
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

# Database Functions
def init_db():
    """Initialize database with recovery support"""
    try:
        db_exists = os.path.exists(Config.DB_NAME)
        
        conn = get_db()
        c = conn.cursor()
        
        # Create tables
        c.execute('''CREATE TABLE IF NOT EXISTS users 
                    (id INTEGER PRIMARY KEY, username TEXT, expiry TEXT, file_limit INTEGER, 
                     is_prime INTEGER, join_date TEXT, last_renewal TEXT, total_bots_deployed INTEGER DEFAULT 0,
                     total_deployments INTEGER DEFAULT 0, last_active TEXT, bot_username TEXT)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS keys 
                    (key TEXT PRIMARY KEY, duration_days INTEGER, file_limit INTEGER, created_date TEXT, 
                     used_by TEXT, used_date TEXT, is_used INTEGER DEFAULT 0)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS deployments 
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, bot_name TEXT, 
                     filename TEXT, pid INTEGER, start_time TEXT, status TEXT, 
                     cpu_usage REAL, ram_usage REAL, last_active TEXT, node_id INTEGER,
                     logs TEXT, restart_count INTEGER DEFAULT 0, auto_restart INTEGER DEFAULT 1,
                     created_at TEXT, updated_at TEXT, bot_username TEXT, is_banned INTEGER DEFAULT 0,
                     token TEXT, metadata TEXT)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS nodes
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, status TEXT, 
                     capacity INTEGER, current_load INTEGER DEFAULT 0, last_check TEXT,
                     region TEXT, total_deployed INTEGER DEFAULT 0)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS server_logs
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, 
                     event TEXT, details TEXT, user_id INTEGER)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS bot_logs
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, bot_id INTEGER, timestamp TEXT,
                     log_type TEXT, message TEXT)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS notifications
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, message TEXT,
                     is_read INTEGER DEFAULT 0, created_at TEXT)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS bot_backups
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, bot_id INTEGER, backup_name TEXT,
                     backup_path TEXT, created_at TEXT, size_kb REAL)''')
        
        # Check if admin exists
        c.execute("SELECT * FROM users WHERE id=?", (Config.ADMIN_ID,))
        admin_exists = c.fetchone()
        
        if not admin_exists:
            join_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            expiry_date = (datetime.now() + timedelta(days=3650)).strftime('%Y-%m-%d %H:%M:%S')
            c.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                     (Config.ADMIN_ID, 'admin', expiry_date, 100, 1, join_date, join_date, 0, 0, join_date, Config.ADMIN_USERNAME))
        
        # Check if nodes exist
        c.execute("SELECT COUNT(*) FROM nodes")
        node_count = c.fetchone()[0]
        
        if node_count == 0:
            join_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for i, node in enumerate(Config.HOSTING_NODES, 1):
                c.execute("INSERT INTO nodes (name, status, capacity, last_check, region) VALUES (?, ?, ?, ?, ?)",
                         (node['name'], node['status'], node['capacity'], join_date, node.get('region', 'Global')))
        
        # Update all running bots to "Stopped" status for recovery
        if db_exists:
            c.execute("UPDATE deployments SET status='Stopped', pid=0, updated_at=? WHERE status='Running'",
                     (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),))
        
        conn.commit()
        conn.close()
        
        logger.info("Database initialized successfully")
        
    except Exception as e:
        logger.error(f"Error initializing database: {e}")

# Helper Functions
def get_user(user_id):
    return execute_db("SELECT * FROM users WHERE id=?", (user_id,), fetchone=True)

def update_user_bot_count(user_id):
    """Update user's bot count"""
    count = execute_db("SELECT COUNT(*) FROM deployments WHERE user_id=?", (user_id,), fetchone=True)
    if count:
        count = count[0] or 0
    else:
        count = 0
        
    deployments = execute_db("SELECT COUNT(*) FROM deployments WHERE user_id=? AND status='Running'", (user_id,), fetchone=True)
    if deployments:
        deployments = deployments[0] or 0
    else:
        deployments = 0
        
    execute_db("UPDATE users SET total_bots_deployed=?, total_deployments=total_deployments+1 WHERE id=?", 
              (count, user_id), commit=True)

def is_prime(user_id):
    user = get_user(user_id)
    if user and user['expiry']:
        try:
            expiry = datetime.strptime(user['expiry'], '%Y-%m-%d %H:%M:%S')
            return expiry > datetime.now()
        except:
            return False
    return False

def get_user_bots(user_id):
    bots = execute_db("""
        SELECT id, bot_name, filename, pid, start_time, status, node_id, 
               restart_count, auto_restart, created_at, bot_username, is_banned 
        FROM deployments 
        WHERE user_id=? 
        ORDER BY status DESC, id DESC
    """, (user_id,), fetchall=True)
    
    if bots:
        return bots
    return []

def get_all_bots():
    """Get all bots for admin"""
    bots = execute_db("""
        SELECT d.*, u.username as user_username 
        FROM deployments d 
        LEFT JOIN users u ON d.user_id = u.id 
        ORDER BY d.id DESC
    """, fetchall=True)
    
    return bots or []

def update_bot_stats(bot_id, cpu, ram):
    last_active = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    execute_db("UPDATE deployments SET cpu_usage=?, ram_usage=?, last_active=?, updated_at=? WHERE id=?", 
              (cpu, ram, last_active, last_active, bot_id), commit=True)

def generate_random_key():
    prefix = "ZENX-"
    random_chars = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=12))
    return f"{prefix}{random_chars}"

def create_progress_bar(percentage, length=10):
    """Create a graphical progress bar"""
    filled = int(percentage * length / 100)
    return "█" * filled + "░" * (length - filled)

def create_zip_file(bot_id, bot_name, filename, user_id):
    """Create a zip file for bot export"""
    try:
        export_dir = Path(Config.EXPORTS_DIR)
        export_dir.mkdir(exist_ok=True)
        
        zip_filename = f"bot_export_{bot_id}_{int(time.time())}.zip"
        zip_path = export_dir / zip_filename
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            bot_file_path = project_path / filename
            if bot_file_path.exists():
                zipf.write(bot_file_path, arcname=filename)
            
            # Add metadata
            bot_info = execute_db("SELECT * FROM deployments WHERE id=?", (bot_id,), fetchone=True)
            user_info = get_user(user_id)
            
            metadata = {
                'bot_id': bot_id,
                'bot_name': bot_name,
                'filename': filename,
                'user_id': user_id,
                'user_username': user_info['username'] if user_info else 'Unknown',
                'bot_username': bot_info['bot_username'] if bot_info else '',
                'status': bot_info['status'] if bot_info else '',
                'export_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'version': 'ZEN X HOST BOT v3.3.2',
                'node_info': '300-Capacity Multi-Node Hosting',
                'recovery_info': 'Auto-recovery enabled',
                'token': bot_info['token'] if bot_info else ''
            }
            
            metadata_str = json.dumps(metadata, indent=4)
            zipf.writestr('metadata.json', metadata_str)
            
            # Add bot logs if exist
            log_file = Path(Config.LOGS_DIR) / f"bot_{bot_id}.log"
            if log_file.exists():
                zipf.write(log_file, arcname='bot_logs.log')
        
        # Save backup record
        size_kb = zip_path.stat().st_size / 1024
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        execute_db("INSERT INTO bot_backups (bot_id, backup_name, backup_path, created_at, size_kb) VALUES (?, ?, ?, ?, ?)",
                  (bot_id, zip_filename, str(zip_path), created_at, size_kb), commit=True)
        
        return zip_path
    except Exception as e:
        logger.error(f"Error creating zip: {e}")
        return None

def check_prime_expiry(user_id):
    """Check if prime has expired"""
    user = get_user(user_id)
    if user and user['expiry']:
        try:
            expiry = datetime.strptime(user['expiry'], '%Y-%m-%d %H:%M:%S')
            now = datetime.now()
            if expiry > now:
                days_left = (expiry - now).days
                hours_left = (expiry - now).seconds // 3600
                return {
                    'expired': False,
                    'days_left': days_left,
                    'hours_left': hours_left,
                    'expiry_date': expiry.strftime('%Y-%m-%d %H:%M:%S')
                }
            else:
                days_expired = (now - expiry).days
                return {
                    'expired': True,
                    'days_expired': days_expired,
                    'expiry_date': expiry.strftime('%Y-%m-%d %H:%M:%S'),
                    'message': f"Your Prime subscription expired {days_expired} day(s) ago."
                }
        except:
            return {'expired': True, 'message': 'Invalid expiry date format'}
    return {'expired': True, 'message': 'No Prime subscription found'}

def get_user_session(user_id):
    """Get user session data"""
    if user_id in user_sessions:
        return user_sessions[user_id]
    return {'state': 'main_menu'}

def set_user_session(user_id, data):
    """Set user session data"""
    user_sessions[user_id] = data

def clear_user_session(user_id):
    """Clear user session"""
    if user_id in user_sessions:
        del user_sessions[user_id]

def update_message_history(user_id, message_id):
    """Update user's message history"""
    if user_id not in user_message_history:
        user_message_history[user_id] = []
    
    user_message_history[user_id].append(message_id)
    
    if len(user_message_history[user_id]) > 5:
        user_message_history[user_id] = user_message_history[user_id][-5:]

def cleanup_old_messages(user_id):
    """Cleanup old messages for user"""
    if user_id in user_message_history:
        del user_message_history[user_id]

def extract_bot_token_from_file(filename):
    """Extract bot token from Python file"""
    try:
        file_path = project_path / filename
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Look for token patterns
        patterns = [
            r"token\s*=\s*['\"]([^'\"]+)['\"]",
            r"BOT_TOKEN\s*=\s*['\"]([^'\"]+)['\"]",
            r"TOKEN\s*=\s*['\"]([^'\"]+)['\"]",
            r"bot_token\s*=\s*['\"]([^'\"]+)['\"]",
            r"telebot\.TeleBot\(['\"]([^'\"]+)['\"]"
        ]
        
        for pattern in patterns:
            import re
            match = re.search(pattern, content)
            if match:
                return match.group(1)
        
        return None
    except Exception as e:
        logger.error(f"Error extracting token: {e}")
        return None

def extract_bot_username_from_file(filename):
    """Extract bot username from Python file"""
    try:
        file_path = project_path / filename
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Look for username patterns
        patterns = [
            r"@(\w+)",  # @username
            r"username\s*=\s*['\"]([^'\"]+)['\"]",
            r"BOT_USERNAME\s*=\s*['\"]([^'\"]+)['\"]"
        ]
        
        for pattern in patterns:
            import re
            match = re.search(pattern, content)
            if match:
                username = match.group(1)
                if not username.startswith('@'):
                    username = '@' + username
                return username
        
        return None
    except Exception as e:
        logger.error(f"Error extracting username: {e}")
        return None

def get_bot_backups(bot_id):
    """Get all backups for a bot"""
    backups = execute_db("SELECT * FROM bot_backups WHERE bot_id=? ORDER BY id DESC", (bot_id,), fetchall=True)
    return backups or []

def create_bot_backup(bot_id):
    """Create a backup for a bot"""
    bot_info = execute_db("SELECT * FROM deployments WHERE id=?", (bot_id,), fetchone=True)
    if not bot_info:
        return None
    
    return create_zip_file(bot_id, bot_info['bot_name'], bot_info['filename'], bot_info['user_id'])

def ban_bot(bot_id):
    """Ban a bot"""
    bot_info = execute_db("SELECT * FROM deployments WHERE id=?", (bot_id,), fetchone=True)
    if not bot_info:
        return False
    
    # Stop bot if running
    if bot_info['pid']:
        try:
            os.kill(bot_info['pid'], signal.SIGTERM)
        except:
            pass
    
    execute_db("UPDATE deployments SET status='Banned', is_banned=1, updated_at=? WHERE id=?", 
              (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), bot_id), commit=True)
    
    # Update node load
    if bot_info['node_id']:
        execute_db("UPDATE nodes SET current_load=current_load-1 WHERE id=?", (bot_info['node_id'],), commit=True)
    
    return True

def unban_bot(bot_id):
    """Unban a bot"""
    execute_db("UPDATE deployments SET status='Stopped', is_banned=0, updated_at=? WHERE id=?", 
              (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), bot_id), commit=True)
    return True

def visit_bot_user(bot_info):
    """Generate visit link for bot"""
    if not bot_info['bot_username']:
        return None
    
    username = bot_info['bot_username']
    if not username.startswith('@'):
        username = '@' + username
    
    return f"https://t.me/{username.lstrip('@')}"

# Keyboard Functions
def get_main_keyboard(user_id):
    """Get main menu keyboard"""
    user = get_user(user_id)
    prime_status = check_prime_expiry(user_id)
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    if not prime_status['expired']:
        buttons = [
            "📤 Upload Bot",
            "🤖 My Bots",
            "🚀 Deploy Bot",
            "📊 Dashboard",
            "⚙️ Settings",
            "👑 Prime Info",
            "🔔 Notifications",
            "📈 Statistics",
            "💾 Backup/Restore"
        ]
    else:
        buttons = [
            "🔑 Activate Prime",
            "👑 Prime Info",
            "📞 Contact Admin",
            "ℹ️ Help",
            "📊 Free Dashboard"
        ]
    
    for i in range(0, len(buttons), 2):
        row = buttons[i:i+2]
        markup.add(*[types.KeyboardButton(btn) for btn in row])
    
    if user_id == Config.ADMIN_ID:
        markup.add(types.KeyboardButton("👑 Admin Panel"))
    
    return markup

def get_admin_keyboard():
    """Get admin keyboard"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    buttons = [
        "🎫 Generate Key",
        "👥 All Users",
        "🤖 All Bots",
        "📈 Statistics",
        "🗄️ View Database",
        "💾 Backup DB",
        "⚙️ Maintenance",
        "🌐 Nodes Status",
        "🔧 Server Logs",
        "📊 System Info",
        "🔔 Broadcast",
        "🔄 Cleanup",
        "🚫 Banned Bots"
    ]
    
    for i in range(0, len(buttons), 2):
        row = buttons[i:i+2]
        markup.add(*[types.KeyboardButton(btn) for btn in row])
    
    markup.add(types.KeyboardButton("🏠 Main Menu"))
    return markup

def get_bot_actions_keyboard(bot_id, is_admin=False):
    """Get bot actions inline keyboard"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    if is_admin:
        markup.add(
            types.InlineKeyboardButton("🛑 Stop", callback_data=f"stop_{bot_id}"),
            types.InlineKeyboardButton("🚫 Ban", callback_data=f"ban_{bot_id}"),
            types.InlineKeyboardButton("📥 Export", callback_data=f"export_{bot_id}"),
            types.InlineKeyboardButton("🗑️ Delete", callback_data=f"delete_{bot_id}"),
            types.InlineKeyboardButton("📜 Logs", callback_data=f"logs_{bot_id}"),
            types.InlineKeyboardButton("👤 Visit Bot", callback_data=f"visit_{bot_id}")
        )
        markup.add(
            types.InlineKeyboardButton("🔄 Restart", callback_data=f"restart_{bot_id}"),
            types.InlineKeyboardButton("🔁 Auto-Restart", callback_data=f"autorestart_{bot_id}"),
            types.InlineKeyboardButton("💾 Backup Now", callback_data=f"backup_{bot_id}")
        )
    else:
        markup.add(
            types.InlineKeyboardButton("🛑 Stop", callback_data=f"stop_{bot_id}"),
            types.InlineKeyboardButton("🔄 Restart", callback_data=f"restart_{bot_id}"),
            types.InlineKeyboardButton("📥 Export", callback_data=f"export_{bot_id}"),
            types.InlineKeyboardButton("🗑️ Delete", callback_data=f"delete_{bot_id}"),
            types.InlineKeyboardButton("📜 Logs", callback_data=f"logs_{bot_id}"),
            types.InlineKeyboardButton("🔁 Auto-Restart", callback_data=f"autorestart_{bot_id}")
        )
        markup.add(
            types.InlineKeyboardButton("💾 Backups", callback_data=f"backups_{bot_id}"),
            types.InlineKeyboardButton("👤 Bot Info", callback_data=f"info_{bot_id}")
        )
    
    markup.add(types.InlineKeyboardButton("🔙 Back to Bots", callback_data="my_bots"))
    return markup

def get_all_bots_keyboard(bots, page=0, per_page=10):
    """Get keyboard for all bots with pagination"""
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    start_idx = page * per_page
    end_idx = start_idx + per_page
    
    for bot in bots[start_idx:end_idx]:
        status_icon = "🟢" if bot['status'] == "Running" else "🔴"
        banned_icon = "🚫" if bot.get('is_banned', 0) == 1 else ""
        username = bot.get('bot_username', 'No username')
        
        btn_text = f"{status_icon}{banned_icon} {bot['bot_name']} ({username})"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"admin_bot_{bot['id']}"))
    
    # Pagination buttons
    row_buttons = []
    if page > 0:
        row_buttons.append(types.InlineKeyboardButton("⬅️ Previous", callback_data=f"allbots_page_{page-1}"))
    
    if end_idx < len(bots):
        row_buttons.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"allbots_page_{page+1}"))
    
    if row_buttons:
        markup.row(*row_buttons)
    
    markup.add(types.InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel"))
    return markup

def get_backup_keyboard(bot_id):
    """Get backup management keyboard"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("💾 Create Backup", callback_data=f"create_backup_{bot_id}"),
        types.InlineKeyboardButton("📦 List Backups", callback_data=f"list_backups_{bot_id}"),
        types.InlineKeyboardButton("📥 Import Backup", callback_data=f"import_backup_{bot_id}"),
        types.InlineKeyboardButton("🔙 Back", callback_data=f"bot_{bot_id}")
    )
    return markup

# Message Editing Helper
def edit_or_send_message(chat_id, message_id, text, reply_markup=None, parse_mode="Markdown"):
    """Edit existing message or send new one"""
    try:
        if message_id:
            try:
                return bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup, parse_mode=parse_mode)
            except telebot.apihelper.ApiException as e:
                if "message can't be edited" in str(e):
                    msg = bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
                    update_message_history(chat_id, msg.message_id)
                    return msg
                else:
                    raise
        else:
            msg = bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
            update_message_history(chat_id, msg.message_id)
            return msg
    except Exception as e:
        logger.error(f"Error editing/sending message: {e}")
        msg = bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
        update_message_history(chat_id, msg.message_id)
        return msg

# Message Handlers
@bot.message_handler(commands=['start', 'menu', 'help'])
def handle_commands(message):
    uid = message.from_user.id
    username = message.from_user.username or "User"
    
    if Config.MAINTENANCE and uid != Config.ADMIN_ID:
        bot.send_message(message.chat.id, "🛠 **System Maintenance**\n\nWe're currently upgrading our servers. Please try again later.")
        return
    
    user = get_user(uid)
    if not user:
        join_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        execute_db("INSERT OR IGNORE INTO users (id, username, expiry, file_limit, is_prime, join_date, last_renewal, last_active, bot_username) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                  (uid, username, None, 1, 0, join_date, None, join_date, username), commit=True)
        user = get_user(uid)
    
    clear_user_session(uid)
    cleanup_old_messages(uid)
    
    prime_status = check_prime_expiry(uid)
    
    if prime_status['expired']:
        status = "EXPIRED ⚠️"
        expiry_msg = prime_status.get('message', 'Not Activated')
        plan = "Free"
    else:
        status = "PRIME 👑"
        expiry_msg = f"{prime_status['days_left']} days left"
        plan = "Prime"
    
    unread_notifications = execute_db("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0", 
                                     (uid,), fetchone=True)
    if unread_notifications:
        unread_notifications = unread_notifications[0] or 0
    else:
        unread_notifications = 0
    
    text = f"""
🤖 **ZEN X HOST BOT v3.3.2**
*Auto-Recovery System Enabled*
━━━━━━━━━━━━━━━━━━━━
👤 **User:** @{username}
🆔 **ID:** `{uid}`
💎 **Status:** {status}
📅 **Join Date:** {user['join_date'] if user else 'N/A'}
🔔 **Notifications:** {unread_notifications} unread
━━━━━━━━━━━━━━━━━━━━
📊 **Account Details:**
• Plan: {plan}
• File Limit: `{user['file_limit'] if user else 1}` files
• Expiry: {expiry_msg}
• Total Bots: {user['total_bots_deployed'] or 0 if user else 0}
• Total Deployments: {user['total_deployments'] or 0 if user else 0}
━━━━━━━━━━━━━━━━━━━━
💡 *Use keyboard buttons below:*
"""
    
    msg = edit_or_send_message(message.chat.id, None, text, reply_markup=get_main_keyboard(uid))
    update_message_history(uid, msg.message_id)

@bot.message_handler(commands=['admin'])
def handle_admin(message):
    uid = message.from_user.id
    if uid == Config.ADMIN_ID:
        set_user_session(uid, {'state': 'admin_panel'})
        cleanup_old_messages(uid)
        text = """
👑 **ADMIN CONTROL PANEL v3.3.2**
━━━━━━━━━━━━━━━━━━━━
*Auto-Recovery System: ACTIVE*
━━━━━━━━━━━━━━━━━━━━
Welcome to the admin dashboard.
Select an option from the keyboard below:
━━━━━━━━━━━━━━━━━━━━
"""
        msg = edit_or_send_message(message.chat.id, None, text, reply_markup=get_admin_keyboard())
        update_message_history(uid, msg.message_id)
    else:
        bot.reply_to(message, "⛔ **Access Denied!**")

# New feature: Backup/Restore handler
@bot.message_handler(func=lambda message: message.text == "💾 Backup/Restore")
def handle_backup_restore(message):
    uid = message.from_user.id
    last_msg_id = user_message_history.get(uid, [None])[-1] if user_message_history.get(uid) else None
    
    text = """
💾 **BACKUP & RESTORE SYSTEM**
━━━━━━━━━━━━━━━━━━━━
Choose an option:
━━━━━━━━━━━━━━━━━━━━
1. **Backup My Bots** - Create backups of all your bots
2. **Restore Bot** - Restore bot from backup file
3. **Manage Backups** - View and manage your backups
4. **Export All** - Export all bots as ZIP
━━━━━━━━━━━━━━━━━━━━
"""
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📦 Backup All Bots", callback_data="backup_all"),
        types.InlineKeyboardButton("📥 Restore Bot", callback_data="restore_bot"),
        types.InlineKeyboardButton("📋 My Backups", callback_data="my_backups"),
        types.InlineKeyboardButton("📤 Export All", callback_data="export_all")
    )
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="main_menu"))
    
    edit_or_send_message(message.chat.id, last_msg_id, text, reply_markup=markup)

# New feature: Banned Bots handler for admin
@bot.message_handler(func=lambda message: message.text == "🚫 Banned Bots")
def handle_banned_bots(message):
    uid = message.from_user.id
    if uid != Config.ADMIN_ID:
        return
    
    last_msg_id = user_message_history.get(uid, [None])[-1] if user_message_history.get(uid) else None
    
    banned_bots = execute_db("""
        SELECT d.*, u.username as user_username 
        FROM deployments d 
        LEFT JOIN users u ON d.user_id = u.id 
        WHERE d.is_banned = 1 
        ORDER BY d.id DESC
    """, fetchall=True) or []
    
    if not banned_bots:
        text = "🚫 **No banned bots found.**"
        edit_or_send_message(message.chat.id, last_msg_id, text)
        return
    
    text = f"""
🚫 **BANNED BOTS**
━━━━━━━━━━━━━━━━━━━━
Total Banned: {len(banned_bots)}
━━━━━━━━━━━━━━━━━━━━
"""
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    for bot in banned_bots[:10]:
        btn_text = f"🚫 {bot['bot_name']} (User: {bot['user_username'] or 'Unknown'})"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"view_banned_{bot['id']}"))
    
    if len(banned_bots) > 10:
        markup.add(types.InlineKeyboardButton("📄 Show More...", callback_data="banned_bots_more"))
    
    markup.add(types.InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel"))
    
    edit_or_send_message(message.chat.id, last_msg_id, text, reply_markup=markup)

# File Upload Handler with improved features
@bot.message_handler(content_types=['document'])
def handle_document(message):
    uid = message.from_user.id
    session = get_user_session(uid)
    
    if session.get('state') == 'waiting_for_backup_file':
        handle_backup_upload(message)
        return
    
    if session.get('state') != 'waiting_for_file':
        return
    
    try:
        file_name = message.document.file_name.lower()
        
        if not (file_name.endswith('.py') or file_name.endswith('.zip')):
            bot.reply_to(message, "❌ **Invalid File Type!**\n\nOnly Python (.py) or ZIP (.zip) files allowed.")
            return
        
        if message.document.file_size > 5.5 * 1024 * 1024:
            bot.reply_to(message, "❌ **File Too Large!**\n\nMaximum file size is 5.5MB.")
            return
        
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        original_name = message.document.file_name
        
        # Handle ZIP file
        if file_name.endswith('.zip'):
            temp_zip_path = project_path / f"temp_{uid}_{int(time.time())}.zip"
            temp_zip_path.write_bytes(downloaded)
            
            extract_dir = project_path / f"extracted_{uid}_{int(time.time())}"
            extract_dir.mkdir(exist_ok=True)
            
            if extract_zip_file(temp_zip_path, extract_dir):
                py_files = list(extract_dir.glob('*.py'))
                
                if not py_files:
                    bot.reply_to(message, "❌ **No Python file found in ZIP!**")
                    temp_zip_path.unlink(missing_ok=True)
                    import shutil
                    shutil.rmtree(extract_dir, ignore_errors=True)
                    return
                
                py_file = py_files[0]
                safe_name = secure_filename(py_file.name)
                
                counter = 1
                original_safe_name = safe_name
                while (project_path / safe_name).exists():
                    name_parts = original_safe_name.rsplit('.', 1)
                    safe_name = f"{name_parts[0]}_{counter}.{name_parts[1]}"
                    counter += 1
                
                target_path = project_path / safe_name
                import shutil
                shutil.copy2(py_file, target_path)
                
                temp_zip_path.unlink(missing_ok=True)
                shutil.rmtree(extract_dir, ignore_errors=True)
                
                bot.reply_to(message, f"""
✅ **File extracted successfully!**
━━━━━━━━━━━━━━━━━━━━
**Original:** {original_name}
**Extracted:** {py_file.name}
**Saved as:** {safe_name}
━━━━━━━━━━━━━━━━━━━━
                """)
                
                # Extract bot token and username
                bot_token = extract_bot_token_from_file(safe_name)
                bot_username = extract_bot_username_from_file(safe_name)
                
                set_user_session(uid, {
                    'state': 'waiting_for_bot_name',
                    'filename': safe_name,
                    'original_name': f"{original_name} (extracted: {py_file.name})",
                    'bot_token': bot_token,
                    'bot_username': bot_username
                })
                
                msg = bot.send_message(message.chat.id, f"""
🤖 **BOT NAME SETUP**
━━━━━━━━━━━━━━━━━━━━
*Auto-recovery will be enabled by default*
━━━━━━━━━━━━━━━━━━━━
Enter a name for your bot (max 30 chars):
Example: `News Bot`, `Music Bot`, `Assistant`
━━━━━━━━━━━━━━━━━━━━
Detected Info:
• Token: {'✅ Found' if bot_token else '❌ Not found'}
• Username: {bot_username or 'Not found'}
━━━━━━━━━━━━━━━━━━━━
                """)
                update_message_history(uid, msg.message_id)
                bot.register_next_step_handler(msg, process_bot_name_input)
                return
            
        # Handle regular Python file
        safe_name = secure_filename(original_name)
        
        counter = 1
        original_safe_name = safe_name
        while (project_path / safe_name).exists():
            name_parts = original_safe_name.rsplit('.', 1)
            safe_name = f"{name_parts[0]}_{counter}.{name_parts[1]}"
            counter += 1
        
        file_path = project_path / safe_name
        file_path.write_bytes(downloaded)
        
        # Extract bot token and username
        bot_token = extract_bot_token_from_file(safe_name)
        bot_username = extract_bot_username_from_file(safe_name)
        
        set_user_session(uid, {
            'state': 'waiting_for_bot_name',
            'filename': safe_name,
            'original_name': original_name,
            'bot_token': bot_token,
            'bot_username': bot_username
        })
        
        msg = bot.send_message(message.chat.id, f"""
🤖 **BOT NAME SETUP**
━━━━━━━━━━━━━━━━━━━━
*Auto-recovery will be enabled by default*
━━━━━━━━━━━━━━━━━━━━
Enter a name for your bot (max 30 chars):
Example: `News Bot`, `Music Bot`, `Assistant`
━━━━━━━━━━━━━━━━━━━━
Detected Info:
• Token: {'✅ Found' if bot_token else '❌ Not found'}
• Username: {bot_username or 'Not found'}
━━━━━━━━━━━━━━━━━━━━
        """)
        update_message_history(uid, msg.message_id)
        bot.register_next_step_handler(msg, process_bot_name_input)
        
    except Exception as e:
        logger.error(f"Upload error: {e}")
        bot.reply_to(message, f"❌ **Error:** {str(e)[:100]}")

def handle_backup_upload(message):
    """Handle backup file upload for restoration"""
    uid = message.from_user.id
    chat_id = message.chat.id
    
    try:
        file_name = message.document.file_name.lower()
        
        if not file_name.endswith('.zip'):
            bot.reply_to(message, "❌ **Invalid File Type!**\n\nOnly ZIP (.zip) backup files allowed.")
            return
        
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        
        # Save backup file
        backup_dir = Path('restored_backups')
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / f"restore_{uid}_{int(time.time())}.zip"
        backup_path.write_bytes(downloaded)
        
        # Extract metadata
        try:
            with zipfile.ZipFile(backup_path, 'r') as zipf:
                if 'metadata.json' in zipf.namelist():
                    metadata_str = zipf.read('metadata.json').decode('utf-8')
                    metadata = json.loads(metadata_str)
                    
                    bot_name = metadata.get('bot_name', 'Restored Bot')
                    filename = metadata.get('filename', '')
                    
                    # Extract bot file
                    if filename in zipf.namelist():
                        zipf.extract(filename, project_path)
                        
                        # Check if file already exists
                        counter = 1
                        original_name = filename
                        while (project_path / filename).exists():
                            name_parts = original_name.rsplit('.', 1)
                            filename = f"{name_parts[0]}_{counter}.{name_parts[1]}"
                            counter += 1
                        
                        # Rename if necessary
                        if filename != original_name:
                            old_path = project_path / original_name
                            new_path = project_path / filename
                            old_path.rename(new_path)
                        
                        # Save to database
                        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        bot_username = metadata.get('bot_username', '')
                        token = metadata.get('token', '')
                        
                        execute_db("""
                            INSERT INTO deployments 
                            (user_id, bot_name, filename, pid, start_time, status, last_active, 
                             auto_restart, created_at, updated_at, bot_username, token, metadata) 
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            uid, bot_name, filename, 0, None, "Uploaded", created_at, 
                            1, created_at, created_at, bot_username, token, metadata_str
                        ), commit=True)
                        
                        update_user_bot_count(uid)
                        
                        text = f"""
✅ **BOT RESTORED SUCCESSFULLY**
━━━━━━━━━━━━━━━━━━━━
🤖 **Bot Name:** {bot_name}
📁 **File:** `{filename}`
📊 **Status:** Ready for deployment
🔁 **Auto-Restart:** Enabled
📅 **Restored:** {created_at}
━━━━━━━━━━━━━━━━━━━━
"""
                        bot.reply_to(message, text)
                        clear_user_session(uid)
                    else:
                        bot.reply_to(message, "❌ Bot file not found in backup!")
                else:
                    bot.reply_to(message, "❌ Invalid backup file: metadata missing!")
        except Exception as e:
            logger.error(f"Backup extraction error: {e}")
            bot.reply_to(message, f"❌ Error extracting backup: {str(e)[:100]}")
        
        # Cleanup
        backup_path.unlink(missing_ok=True)
        
    except Exception as e:
        logger.error(f"Backup upload error: {e}")
        bot.reply_to(message, f"❌ **Error:** {str(e)[:100]}")

def process_bot_name_input(message):
    uid = message.from_user.id
    chat_id = message.chat.id
    
    if message.text.lower() == 'cancel':
        clear_user_session(uid)
        bot.reply_to(message, "❌ Cancelled.", reply_markup=get_main_keyboard(uid))
        return
    
    session = get_user_session(uid)
    if 'filename' not in session:
        bot.reply_to(message, "❌ Session expired. Please upload again.")
        return
    
    bot_name = message.text.strip()[:50]
    filename = session['filename']
    original_name = session['original_name']
    bot_token = session.get('bot_token', '')
    bot_username = session.get('bot_username', '')
    
    # Save to database
    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    execute_db("""
        INSERT INTO deployments 
        (user_id, bot_name, filename, pid, start_time, status, last_active, 
         auto_restart, created_at, updated_at, bot_username, token) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        uid, bot_name, filename, 0, None, "Uploaded", created_at, 
        1, created_at, created_at, bot_username, bot_token
    ), commit=True)
    
    update_user_bot_count(uid)
    
    clear_user_session(uid)
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📚 Install Libraries", callback_data="install_libs"))
    markup.add(types.InlineKeyboardButton("🚀 Deploy Now", callback_data="deploy_new"))
    markup.add(types.InlineKeyboardButton("🤖 My Bots", callback_data="my_bots"))
    
    text = f"""
✅ **FILE UPLOADED SUCCESSFULLY**
━━━━━━━━━━━━━━━━━━━━
*Auto-recovery: ENABLED ✅*
━━━━━━━━━━━━━━━━━━━━
🤖 **Bot Name:** {bot_name}
📁 **File:** `{original_name}`
👤 **Bot Username:** {bot_username or 'Not set'}
🔑 **Token:** {'✅ Found' if bot_token else '❌ Not found'}
📊 **Status:** Ready for setup
🔁 **Auto-Restart:** Enabled
📅 **Uploaded:** {created_at}
━━━━━━━━━━━━━━━━━━━━
"""
    
    edit_or_send_message(chat_id, None, text, reply_markup=markup)
    send_notification(uid, f"Bot '{bot_name}' uploaded successfully!")

# Callback Query Handler with new features
@bot.callback_query_handler(func=lambda call: True)
def callback_manager(call):
    uid = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    
    try:
        # Existing callbacks
        if call.data == "activate_prime":
            handle_activate_prime_callback(call)
        elif call.data == "upload":
            handle_upload_request(call.message, message_id)
        elif call.data == "my_bots":
            handle_my_bots(call.message, message_id)
        elif call.data == "deploy_new":
            handle_deploy_new(call.message, message_id)
        elif call.data == "dashboard":
            handle_dashboard(call.message, message_id)
        elif call.data == "settings":
            handle_settings(call.message, message_id)
        elif call.data == "install_libs":
            ask_for_libraries(call)
        elif call.data == "cancel":
            clear_user_session(uid)
            edit_or_send_message(chat_id, message_id, "❌ Cancelled.")
            handle_commands(call.message)
        elif call.data == "user_stats":
            handle_user_statistics(call.message, message_id)
        elif call.data == "notif_settings":
            handle_notifications(call.message, message_id)
        elif call.data == "clear_notifications":
            clear_notifications(call)
        elif call.data == "refresh_notifications":
            handle_notifications(call.message, message_id)
        elif call.data == "main_menu":
            handle_commands(call.message)
        elif call.data == "admin_panel":
            handle_admin_panel(call.message, message_id)
        
        # Bot management
        elif call.data.startswith("bot_"):
            bot_id = call.data.split("_")[1]
            show_bot_details(call, bot_id)
        
        elif call.data.startswith("admin_bot_"):
            bot_id = call.data.split("_")[2]
            show_admin_bot_details(call, bot_id)
        
        elif call.data.startswith("select_"):
            file_id = call.data.split("_")[1]
            start_deployment(call, file_id)
        
        elif call.data.startswith("stop_"):
            bot_id = call.data.split("_")[1]
            stop_bot(call, bot_id)
        
        elif call.data.startswith("restart_"):
            bot_id = call.data.split("_")[1]
            restart_bot(call, bot_id)
        
        elif call.data.startswith("delete_"):
            bot_id = call.data.split("_")[1]
            confirm_delete_bot(call, bot_id)
        
        elif call.data.startswith("confirm_delete_"):
            parts = call.data.split("_")
            bot_id = parts[2]
            confirm_delete_action(call, bot_id)
        
        elif call.data.startswith("export_"):
            bot_id = call.data.split("_")[1]
            export_bot(call, bot_id)
        
        elif call.data.startswith("logs_"):
            bot_id = call.data.split("_")[1]
            show_bot_logs(call, bot_id)
        
        elif call.data.startswith("autorestart_"):
            bot_id = call.data.split("_")[1]
            toggle_auto_restart(call, bot_id)
        
        elif call.data.startswith("stats_"):
            if call.data.startswith("stats_"):
                parts = call.data.split("_")
                if len(parts) == 2:
                    bot_id = parts[1]
                    show_bot_stats(call, bot_id)
        
        # New features
        elif call.data.startswith("ban_"):
            bot_id = call.data.split("_")[1]
            confirm_ban_bot(call, bot_id)
        
        elif call.data.startswith("confirm_ban_"):
            parts = call.data.split("_")
            bot_id = parts[2]
            ban_bot_action(call, bot_id)
        
        elif call.data.startswith("unban_"):
            bot_id = call.data.split("_")[1]
            unban_bot_action(call, bot_id)
        
        elif call.data.startswith("visit_"):
            bot_id = call.data.split("_")[1]
            visit_bot_user_action(call, bot_id)
        
        elif call.data.startswith("info_"):
            bot_id = call.data.split("_")[1]
            show_bot_info(call, bot_id)
        
        elif call.data.startswith("backup_"):
            bot_id = call.data.split("_")[1]
            handle_backup_options(call, bot_id)
        
        elif call.data.startswith("create_backup_"):
            bot_id = call.data.split("_")[2]
            create_bot_backup_action(call, bot_id)
        
        elif call.data.startswith("list_backups_"):
            bot_id = call.data.split("_")[2]
            list_bot_backups(call, bot_id)
        
        elif call.data.startswith("import_backup_"):
            bot_id = call.data.split("_")[2]
            start_backup_import(call, bot_id)
        
        elif call.data.startswith("backups_"):
            bot_id = call.data.split("_")[1]
            show_backup_menu(call, bot_id)
        
        # Backup/Restore system
        elif call.data == "backup_all":
            backup_all_bots(call)
        
        elif call.data == "restore_bot":
            start_restore_process(call)
        
        elif call.data == "my_backups":
            show_my_backups(call)
        
        elif call.data == "export_all":
            export_all_bots(call)
        
        # All bots view for admin
        elif call.data == "all_bots":
            show_all_bots_admin(call.message, message_id)
        
        elif call.data.startswith("allbots_page_"):
            page_num = int(call.data.split("_")[2])
            show_all_bots_page(call, page_num)
        
        # Banned bots
        elif call.data.startswith("view_banned_"):
            bot_id = call.data.split("_")[2]
            view_banned_bot(call, bot_id)
        
        elif call.data == "banned_bots_more":
            show_more_banned_bots(call)
        
        # Database pages
        elif call.data.startswith("page_"):
            page_num = int(call.data.split("_")[1])
            view_database_page(call, page_num)
        
        # Admin actions
        elif call.data.startswith("msguser_"):
            user_id = call.data.split("_")[1]
            message_user(call, user_id)
        
        elif call.data.startswith("viewuser_"):
            user_id = call.data.split("_")[1]
            view_user_bots(call, user_id)
        
        elif call.data.startswith("resetlimit_"):
            user_id = call.data.split("_")[1]
            reset_user_limit(call, user_id)
        
        elif call.data == "gen_key":
            if uid == Config.ADMIN_ID:
                gen_key_step1(call)
        
        elif call.data == "back_main":
            edit_or_send_message(chat_id, message_id, "🏠 **Main Menu**", reply_markup=get_main_keyboard(uid))
        
    except Exception as e:
        logger.error(f"Callback error: {e}")
        bot.answer_callback_query(call.id, "⚠️ Error occurred!")

# New Feature Functions
def show_admin_bot_details(call, bot_id):
    """Show bot details for admin with extra options"""
    bot_info = execute_db("""
        SELECT d.*, u.username as user_username, u.id as user_id 
        FROM deployments d 
        LEFT JOIN users u ON d.user_id = u.id 
        WHERE d.id=?
    """, (bot_id,), fetchone=True)
    
    if not bot_info:
        bot.answer_callback_query(call.id, "❌ Bot not found!")
        return
    
    bot_name = bot_info['bot_name']
    filename = bot_info['filename']
    pid = bot_info['pid']
    start_time = bot_info['start_time']
    status = bot_info['status']
    node_id = bot_info['node_id']
    restart_count = bot_info['restart_count']
    auto_restart = bot_info['auto_restart']
    created_at = bot_info['created_at']
    bot_username = bot_info['bot_username']
    is_banned = bot_info['is_banned']
    user_username = bot_info['user_username']
    user_id = bot_info['user_id']
    
    # Check if process is running
    is_running = get_process_stats(pid) if pid else False
    
    # Get node info
    node_info = execute_db("SELECT name, region FROM nodes WHERE id=?", (node_id,), fetchone=True) if node_id else None
    node_text = f"{node_info['name']} ({node_info['region']})" if node_info else "N/A"
    
    text = f"""
🤖 **BOT DETAILS (ADMIN VIEW)**
━━━━━━━━━━━━━━━━━━━━
*Status: {"🚫 BANNED" if is_banned == 1 else "🟢 ACTIVE"}*
━━━━━━━━━━━━━━━━━━━━
**Name:** {bot_name}
**User:** @{user_username or 'Unknown'} (ID: {user_id})
**File:** `{filename}`
**Status:** {"🟢 Running" if is_running else "🔴 Stopped"}
**Node:** {node_text}
**Username:** {bot_username or 'Not set'}
**Created:** {created_at}
━━━━━━━━━━━━━━━━━━━━
📊 **Statistics:**
• PID: `{pid if pid else "N/A"}`
• Uptime: {calculate_uptime(start_time) if start_time else "N/A"}
• Restarts: {restart_count}
• Auto-Restart: {'Yes' if auto_restart == 1 else 'No'}
━━━━━━━━━━━━━━━━━━━━
"""
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    if is_banned == 1:
        markup.add(
            types.InlineKeyboardButton("✅ Unban Bot", callback_data=f"unban_{bot_id}"),
            types.InlineKeyboardButton("🗑️ Delete", callback_data=f"delete_{bot_id}"),
            types.InlineKeyboardButton("📥 Export", callback_data=f"export_{bot_id}"),
            types.InlineKeyboardButton("📜 Logs", callback_data=f"logs_{bot_id}")
        )
    else:
        markup.add(
            types.InlineKeyboardButton("🛑 Stop", callback_data=f"stop_{bot_id}"),
            types.InlineKeyboardButton("🚫 Ban Bot", callback_data=f"ban_{bot_id}"),
            types.InlineKeyboardButton("📥 Export", callback_data=f"export_{bot_id}"),
            types.InlineKeyboardButton("🗑️ Delete", callback_data=f"delete_{bot_id}"),
            types.InlineKeyboardButton("📜 Logs", callback_data=f"logs_{bot_id}"),
            types.InlineKeyboardButton("👤 Visit Bot", callback_data=f"visit_{bot_id}")
        )
        markup.add(
            types.InlineKeyboardButton("🔄 Restart", callback_data=f"restart_{bot_id}"),
            types.InlineKeyboardButton("🔁 Auto-Restart", callback_data=f"autorestart_{bot_id}"),
            types.InlineKeyboardButton("💾 Backup", callback_data=f"backup_{bot_id}"),
            types.InlineKeyboardButton("📊 Stats", callback_data=f"stats_{bot_id}")
        )
    
    markup.add(types.InlineKeyboardButton("👤 Message User", callback_data=f"msguser_{user_id}"))
    markup.add(types.InlineKeyboardButton("🔙 Back to All Bots", callback_data="all_bots"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

def confirm_ban_bot(call, bot_id):
    """Confirm ban bot action"""
    bot_info = execute_db("SELECT bot_name FROM deployments WHERE id=?", (bot_id,), fetchone=True)
    
    if not bot_info:
        return
    
    bot_name = bot_info['bot_name']
    
    text = f"""
⚠️ **CONFIRM BAN BOT**
━━━━━━━━━━━━━━━━━━━━
Are you sure you want to ban this bot?
━━━━━━━━━━━━━━━━━━━━
🤖 **Bot:** {bot_name}
━━━━━━━━━━━━━━━━━━━━
**This will:**
• Stop the bot immediately
• Mark it as banned
• User won't be able to restart it
━━━━━━━━━━━━━━━━━━━━
"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Yes, Ban", callback_data=f"confirm_ban_{bot_id}"),
        types.InlineKeyboardButton("❌ Cancel", callback_data=f"admin_bot_{bot_id}")
    )
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

def ban_bot_action(call, bot_id):
    """Execute ban bot action"""
    if ban_bot(bot_id):
        bot.answer_callback_query(call.id, "✅ Bot banned successfully!")
        send_notification(Config.ADMIN_ID, f"Bot ID {bot_id} has been banned")
        
        # Get bot info for notification
        bot_info = execute_db("SELECT user_id, bot_name FROM deployments WHERE id=?", (bot_id,), fetchone=True)
        if bot_info:
            send_notification(bot_info['user_id'], f"Your bot '{bot_info['bot_name']}' has been banned by admin")
        
        show_admin_bot_details(call, bot_id)
    else:
        bot.answer_callback_query(call.id, "❌ Failed to ban bot!")

def unban_bot_action(call, bot_id):
    """Unban a bot"""
    if unban_bot(bot_id):
        bot.answer_callback_query(call.id, "✅ Bot unbanned successfully!")
        show_admin_bot_details(call, bot_id)
    else:
        bot.answer_callback_query(call.id, "❌ Failed to unban bot!")

def visit_bot_user_action(call, bot_id):
    """Visit bot's Telegram profile"""
    bot_info = execute_db("SELECT bot_username FROM deployments WHERE id=?", (bot_id,), fetchone=True)
    
    if not bot_info or not bot_info['bot_username']:
        bot.answer_callback_query(call.id, "❌ Bot username not available!")
        return
    
    username = bot_info['bot_username']
    if not username.startswith('@'):
        username = '@' + username
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("👤 Visit Bot", url=f"https://t.me/{username.lstrip('@')}"))
    
    text = f"""
👤 **BOT USERNAME**
━━━━━━━━━━━━━━━━━━━━
Username: {username}
━━━━━━━━━━━━━━━━━━━━
Click the button below to visit the bot:
"""
    bot.send_message(call.message.chat.id, text, reply_markup=markup)
    bot.answer_callback_query(call.id, "✅ Check your messages!")

def show_bot_info(call, bot_id):
    """Show detailed bot information"""
    bot_info = execute_db("SELECT * FROM deployments WHERE id=?", (bot_id,), fetchone=True)
    
    if not bot_info:
        bot.answer_callback_query(call.id, "❌ Bot not found!")
        return
    
    bot_name = bot_info['bot_name']
    filename = bot_info['filename']
    status = bot_info['status']
    bot_username = bot_info['bot_username']
    token = bot_info['token']
    created_at = bot_info['created_at']
    restart_count = bot_info['restart_count']
    auto_restart = bot_info['auto_restart']
    
    # Check file size
    file_path = project_path / filename
    file_size = file_path.stat().st_size / 1024 if file_path.exists() else 0
    
    # Get last backup info
    backups = get_bot_backups(bot_id)
    last_backup = backups[0]['created_at'] if backups else "No backups"
    
    text = f"""
📋 **BOT INFORMATION**
━━━━━━━━━━━━━━━━━━━━
🤖 **Name:** {bot_name}
📁 **File:** `{filename}`
📊 **Status:** {status}
👤 **Username:** {bot_username or 'Not set'}
🔑 **Token:** {'✅ Available' if token else '❌ Not available'}
━━━━━━━━━━━━━━━━━━━━
📊 **Details:**
• File Size: {file_size:.2f} KB
• Created: {created_at}
• Restart Count: {restart_count}
• Auto-Restart: {'Enabled ✅' if auto_restart == 1 else 'Disabled ❌'}
• Last Backup: {last_backup}
• Total Backups: {len(backups)}
━━━━━━━━━━━━━━━━━━━━
"""
    
    if token:
        text += f"\n🔑 **Token Preview:** `{token[:15]}...`\n"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("💾 Create Backup", callback_data=f"create_backup_{bot_id}"),
        types.InlineKeyboardButton("📦 View Backups", callback_data=f"list_backups_{bot_id}")
    )
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data=f"bot_{bot_id}"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

def handle_backup_options(call, bot_id):
    """Show backup options for a bot"""
    text = """
💾 **BACKUP MANAGEMENT**
━━━━━━━━━━━━━━━━━━━━
Choose an option:
━━━━━━━━━━━━━━━━━━━━
1. **Create Backup** - Create a new backup
2. **List Backups** - View all backups
3. **Import Backup** - Restore from backup
━━━━━━━━━━━━━━━━━━━━
"""
    
    markup = get_backup_keyboard(bot_id)
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

def create_bot_backup_action(call, bot_id):
    """Create a backup for a bot"""
    bot.answer_callback_query(call.id, "⏳ Creating backup...")
    
    zip_path = create_bot_backup(bot_id)
    
    if zip_path and zip_path.exists():
        try:
            with open(zip_path, 'rb') as f:
                bot.send_document(call.message.chat.id, f, 
                                 caption=f"💾 **Backup Created Successfully**\n\nBot ID: {bot_id}\nDate: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\nSize: {zip_path.stat().st_size / 1024:.1f} KB")
            
            time.sleep(2)
            bot.answer_callback_query(call.id, "✅ Backup created and sent!")
            
        except Exception as e:
            logger.error(f"Error sending backup: {e}")
            bot.answer_callback_query(call.id, "❌ Error sending backup!")
    else:
        bot.answer_callback_query(call.id, "❌ Failed to create backup!")

def list_bot_backups(call, bot_id):
    """List all backups for a bot"""
    backups = get_bot_backups(bot_id)
    
    if not backups:
        text = "📭 **No backups found for this bot.**"
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id, "No backups found")
        return
    
    bot_info = execute_db("SELECT bot_name FROM deployments WHERE id=?", (bot_id,), fetchone=True)
    bot_name = bot_info['bot_name'] if bot_info else "Unknown"
    
    text = f"""
📦 **BACKUPS FOR: {bot_name}**
━━━━━━━━━━━━━━━━━━━━
Total Backups: {len(backups)}
━━━━━━━━━━━━━━━━━━━━
"""
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for backup in backups[:5]:
        backup_date = backup['created_at']
        size_mb = backup['size_kb'] / 1024
        btn_text = f"📦 {backup['backup_name']} ({size_mb:.1f} MB) - {backup_date}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"download_backup_{backup['id']}"))
    
    if len(backups) > 5:
        markup.add(types.InlineKeyboardButton("📄 Show More...", callback_data=f"more_backups_{bot_id}"))
    
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data=f"backup_{bot_id}"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

def start_backup_import(call, bot_id):
    """Start backup import process"""
    uid = call.from_user.id
    set_user_session(uid, {'state': 'waiting_for_backup_file'})
    
    text = """
📥 **IMPORT BACKUP**
━━━━━━━━━━━━━━━━━━━━
Please send the backup ZIP file.
━━━━━━━━━━━━━━━━━━━━
**Requirements:**
• Must be a valid backup ZIP file
• Contains metadata.json
• Contains bot Python file
━━━━━━━━━━━━━━━━━━━━
*Send the file now or type 'cancel' to abort*
"""
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id, "Please send the backup file")

def show_backup_menu(call, bot_id):
    """Show backup menu for a bot"""
    handle_backup_options(call, bot_id)

def backup_all_bots(call):
    """Create backup of all user's bots"""
    uid = call.from_user.id
    bots = get_user_bots(uid)
    
    if not bots:
        bot.answer_callback_query(call.id, "❌ No bots to backup!")
        return
    
    bot.answer_callback_query(call.id, "⏳ Creating backups...")
    
    # Create individual backups
    backup_files = []
    for bot_info in bots:
        zip_path = create_bot_backup(bot_info['id'])
        if zip_path:
            backup_files.append(zip_path)
    
    if not backup_files:
        bot.send_message(call.message.chat.id, "❌ Failed to create backups!")
        return
    
    # Create master backup zip
    export_dir = Path(Config.EXPORTS_DIR)
    master_zip = export_dir / f"all_bots_backup_{uid}_{int(time.time())}.zip"
    
    with zipfile.ZipFile(master_zip, 'w', zipfile.ZIP_DEFLATED) as master_zipf:
        for backup_file in backup_files:
            master_zipf.write(backup_file, arcname=backup_file.name)
    
    # Send master backup
    try:
        with open(master_zip, 'rb') as f:
            bot.send_document(call.message.chat.id, f,
                             caption=f"📦 **All Bots Backup**\n\nTotal Bots: {len(backup_files)}\nDate: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\nSize: {master_zip.stat().st_size / 1024:.1f} KB")
    except Exception as e:
        logger.error(f"Error sending master backup: {e}")
    
    # Cleanup
    master_zip.unlink(missing_ok=True)
    for backup_file in backup_files:
        backup_file.unlink(missing_ok=True)

def start_restore_process(call):
    """Start bot restoration process"""
    uid = call.from_user.id
    set_user_session(uid, {'state': 'waiting_for_backup_file'})
    
    text = """
📥 **RESTORE BOT FROM BACKUP**
━━━━━━━━━━━━━━━━━━━━
Please send the backup ZIP file.
━━━━━━━━━━━━━━━━━━━━
The backup file will be extracted and added to your bot list.
━━━━━━━━━━━━━━━━━━━━
*Send the file now or type 'cancel' to abort*
"""
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id, "Please send the backup file")

def show_my_backups(call):
    """Show user's backups"""
    uid = call.from_user.id
    bots = get_user_bots(uid)
    
    if not bots:
        text = "📭 **No bots found.**\n\nUpload a bot first to create backups."
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id)
        return
    
    text = """
📋 **MY BACKUPS**
━━━━━━━━━━━━━━━━━━━━
Select a bot to view backups:
━━━━━━━━━━━━━━━━━━━━
"""
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    for bot_info in bots:
        backups = get_bot_backups(bot_info['id'])
        backup_count = len(backups)
        btn_text = f"🤖 {bot_info['bot_name']} ({backup_count} backups)"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"list_backups_{bot_info['id']}"))
    
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="main_menu"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

def export_all_bots(call):
    """Export all user's bots as individual files"""
    uid = call.from_user.id
    bots = get_user_bots(uid)
    
    if not bots:
        bot.answer_callback_query(call.id, "❌ No bots to export!")
        return
    
    # Create a zip with all bot files
    export_dir = Path(Config.EXPORTS_DIR)
    export_zip = export_dir / f"all_bots_export_{uid}_{int(time.time())}.zip"
    
    with zipfile.ZipFile(export_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for bot_info in bots:
            bot_file = project_path / bot_info['filename']
            if bot_file.exists():
                zipf.write(bot_file, arcname=f"bots/{bot_info['bot_name']}/{bot_info['filename']}")
    
    try:
        with open(export_zip, 'rb') as f:
            bot.send_document(call.message.chat.id, f,
                             caption=f"📤 **All Bots Export**\n\nTotal Bots: {len(bots)}\nDate: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    except Exception as e:
        logger.error(f"Error sending export: {e}")
        bot.answer_callback_query(call.id, "❌ Error exporting bots!")
    
    # Cleanup
    export_zip.unlink(missing_ok=True)

def show_all_bots_page(call, page_num):
    """Show paginated all bots for admin"""
    uid = call.from_user.id
    if uid != Config.ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Access Denied!")
        return
    
    bots = get_all_bots()
    per_page = 10
    
    start_idx = page_num * per_page
    end_idx = start_idx + per_page
    page_bots = bots[start_idx:end_idx]
    
    text = f"""
🤖 **ALL BOTS (ADMIN VIEW)**
━━━━━━━━━━━━━━━━━━━━
Total Bots: {len(bots)}
Page: {page_num + 1}/{(len(bots) + per_page - 1) // per_page}
━━━━━━━━━━━━━━━━━━━━
"""
    
    markup = get_all_bots_keyboard(bots, page_num, per_page)
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

def view_banned_bot(call, bot_id):
    """View details of a banned bot"""
    bot_info = execute_db("""
        SELECT d.*, u.username as user_username 
        FROM deployments d 
        LEFT JOIN users u ON d.user_id = u.id 
        WHERE d.id=? AND d.is_banned=1
    """, (bot_id,), fetchone=True)
    
    if not bot_info:
        bot.answer_callback_query(call.id, "❌ Bot not found!")
        return
    
    text = f"""
🚫 **BANNED BOT DETAILS**
━━━━━━━━━━━━━━━━━━━━
🤖 **Bot:** {bot_info['bot_name']}
👤 **User:** @{bot_info['user_username'] or 'Unknown'}
📁 **File:** `{bot_info['filename']}`
📅 **Banned Since:** {bot_info['updated_at']}
━━━━━━━━━━━━━━━━━━━━
"""
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Unban Bot", callback_data=f"unban_{bot_id}"),
        types.InlineKeyboardButton("🗑️ Delete Permanently", callback_data=f"delete_{bot_id}")
    )
    markup.add(types.InlineKeyboardButton("🔙 Back to Banned Bots", callback_data="banned_bots"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

def show_more_banned_bots(call):
    """Show more banned bots"""
    banned_bots = execute_db("""
        SELECT d.*, u.username as user_username 
        FROM deployments d 
        LEFT JOIN users u ON d.user_id = u.id 
        WHERE d.is_banned = 1 
        ORDER BY d.id DESC
    """, fetchall=True) or []
    
    if len(banned_bots) <= 10:
        bot.answer_callback_query(call.id, "No more bots to show!")
        return
    
    text = f"""
🚫 **BANNED BOTS (CONTINUED)**
━━━━━━━━━━━━━━━━━━━━
Total Banned: {len(banned_bots)}
━━━━━━━━━━━━━━━━━━━━
"""
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    for bot in banned_bots[10:20]:
        btn_text = f"🚫 {bot['bot_name']} (User: {bot['user_username'] or 'Unknown'})"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"view_banned_{bot['id']}"))
    
    markup.add(types.InlineKeyboardButton("🔙 Back to List", callback_data="banned_bots"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

# Existing functions (simplified for space)
def extract_zip_file(zip_path, extract_dir):
    """Extract ZIP file"""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        return True
    except Exception as e:
        logger.error(f"Error extracting ZIP: {e}")
        return False

def calculate_uptime(start_time_str):
    """Calculate uptime from start time"""
    if not start_time_str:
        return "0s"
    
    try:
        start_time = datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S')
        uptime = datetime.now() - start_time
        
        days = uptime.days
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"
    except:
        return "N/A"

def get_process_stats(pid):
    """Get process statistics"""
    try:
        if not pid:
            return None
            
        if platform.system() == "Windows":
            cmd = f'tasklist /FI "PID eq {pid}"'
        else:
            cmd = f'ps -p {pid} -o pid,pcpu,pmem,etime,comm'
            
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0 and str(pid) in result.stdout:
            return True
        return False
    except Exception as e:
        logger.error(f"Error getting process stats for PID {pid}: {e}")
        return None

# ... [Existing functions like handle_my_bots, handle_dashboard, etc.] ...

# Start the bot
def main():
    """Main function to start the bot"""
    logger.info("🤖 ZEN X Bot Hosting v3.3.2 Starting...")
    logger.info(f"Admin ID: {Config.ADMIN_ID}")
    logger.info(f"Bot Username: @{Config.BOT_USERNAME}")
    
    # Create necessary directories
    Path(Config.PROJECT_DIR).mkdir(exist_ok=True)
    Path(Config.BACKUP_DIR).mkdir(exist_ok=True)
    Path(Config.LOGS_DIR).mkdir(exist_ok=True)
    Path(Config.EXPORTS_DIR).mkdir(exist_ok=True)
    
    # Initialize database
    init_db()
    
    # Start the bot
    logger.info("Bot is now running...")
    while True:
        try:
            bot.polling(none_stop=True, timeout=60)
        except Exception as e:
            logger.error(f"Bot polling error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
