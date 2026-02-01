# app.py - Q-FAD Trading Platform
# Clean main entry point with UI and Server separation

import os
from shiny import App

from ui import create_app_ui
from server import define_server


def main():
    """Initialize and run the Q-FAD Trading Application."""
    app_ui = create_app_ui()
    
    app = App(
        app_ui,
        define_server,
        static_assets=os.path.join(os.path.dirname(__file__), "static")
    )
    
    return app


app = main()

if __name__ == "__main__":
    print("🚀 Starting Q-FAD Upstox Algo Trading App...")
    print("Run with: shiny run --reload app.py")