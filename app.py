# app.py - Q-FAD Trading Platform
# Clean main entry point with UI and Server separation

import os
import logging
from shiny import App

from ui import create_app_ui
from server import define_server


def main():
    """Initialize and run the Q-FAD Trading Application."""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler()],
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
