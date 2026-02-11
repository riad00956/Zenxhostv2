#!/bin/bash

# Install gunicorn if not installed
pip install gunicorn

# Create necessary directories
mkdir -p projects backups logs exports

# Start the Telegram bot in background
python main.py &

# Start the Flask web server
gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 120
