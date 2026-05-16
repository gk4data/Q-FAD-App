# app.py - Q-FAD Trading Platform
# Clean main entry point with UI and Server separation

import os
import logging
from logging.handlers import TimedRotatingFileHandler
from shiny import App

from ui import create_app_ui
from server import define_server


def main():
    """Initialize and run the Q-FAD Trading Application."""
    # Ensure live_data directory exists for logs
    log_dir = os.path.join(os.path.dirname(__file__), "live_data")
    os.makedirs(log_dir, exist_ok=True)
    
    # Create timed rotating file handler for broker communications (5-day rolling)
    log_file = os.path.join(log_dir, "broker_communications.log")
    file_handler = TimedRotatingFileHandler(
        log_file, 
        when="midnight",  # Rotate at midnight
        interval=1,       # Every day
        backupCount=4,    # Keep 5 days (current + 4 previous days)
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_formatter)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
    console_handler.setFormatter(console_formatter)
    
    # Configure root logger with both handlers
    logging.basicConfig(
        level=logging.INFO,
        handlers=[console_handler, file_handler],
        force=True,
    )
    app_ui = create_app_ui()
    
    app = App(
        app_ui,
        define_server,
        static_assets={
            "/static": os.path.join(os.path.dirname(__file__), "static")
        }
    )
    
    return app


app = main()

if __name__ == "__main__":
    print("🚀 Starting Q-FAD: Algo & HFT Trading Platform...")
    print("Run with: shiny run --reload app.py")
