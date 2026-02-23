"""
Jarvis — Main Entry Point
Run with: python main.py
"""
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

from app import create_app, socketio

app = create_app()

if __name__ == "__main__":
    logger = logging.getLogger("Jarvis")
    port = 5000
    logger.info(f"Starting Jarvis server on port {port}...")
    logger.info("Login at http://localhost:5000 with admin/jarvis2024")
    socketio.run(app, host="0.0.0.0", port=port, debug=app.config["DEBUG"], allow_unsafe_werkzeug=True)
