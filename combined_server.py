import os
import threading
import logging
from main import main as start_bot
from app import app as flask_app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def start_flask():
    """Start Flask web server"""
    try:
        port = int(os.environ.get('PORT', 10000))
        logger.info(f"Starting Flask server on port {port}")
        flask_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Flask server error: {e}")

def start_telegram_bot():
    """Start Telegram bot"""
    try:
        logger.info("Starting Telegram bot...")
        start_bot()
    except Exception as e:
        logger.error(f"Telegram bot error: {e}")

if __name__ == '__main__':
    # Create necessary directories
    os.makedirs('projects', exist_ok=True)
    os.makedirs('backups', exist_ok=True)
    os.makedirs('logs', exist_ok=True)
    os.makedirs('exports', exist_ok=True)
    
    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    
    # Start Telegram bot in main thread
    start_telegram_bot()
