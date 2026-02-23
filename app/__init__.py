"""
Jarvis — AI Operating System
Flask app factory and initialization.
"""
import os
import logging
from flask import Flask
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_jwt_extended import JWTManager
from flask_socketio import SocketIO

from app.config import Config
from app.models import Database

logger = logging.getLogger("Jarvis")

# Global extensions
jwt = JWTManager()
socketio = SocketIO()
limiter = Limiter(key_func=get_remote_address, default_limits=["200 per minute"])
db = Database()


def create_app(config_class=Config):
    """Flask application factory."""
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"),
        static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "static"),
    )
    app.config.from_object(config_class)

    # Initialize extensions
    CORS(app, origins=app.config.get("ALLOWED_ORIGINS", "*").split(","))
    jwt.init_app(app)
    limiter.init_app(app)
    socketio.init_app(app, cors_allowed_origins="*", async_mode="threading")

    # Initialize database
    db.init(app.config["DATABASE_PATH"])
    db.create_tables()
    db.ensure_admin_user(
        app.config["ADMIN_USERNAME"],
        app.config["ADMIN_PASSWORD"],
    )

    # Create temp and backup dirs
    os.makedirs(Config.TEMP_DIR, exist_ok=True)
    os.makedirs(Config.BACKUP_DIR, exist_ok=True)

    # Register blueprints
    from app.auth import auth_bp
    from app.routes import main_bp
    from app.chat_routes import chat_bp
    from app.api_system import system_bp
    from app.api_docker import docker_bp
    from app.api_network import network_bp
    from app.api_security import security_bp
    from app.api_files import files_bp
    from app.api_packages import packages_bp
    from app.api_database import database_bp
    from app.gmail_routes import gmail_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(main_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(docker_bp)
    app.register_blueprint(network_bp)
    app.register_blueprint(security_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(packages_bp)
    app.register_blueprint(database_bp)
    app.register_blueprint(gmail_bp)

    # Register WebSocket handlers
    from app.websocket_handlers import register_handlers
    register_handlers(socketio)

    # Initialize scheduler
    from app.tools.scheduler_tools import init_scheduler
    init_scheduler(app, db)

    # Load all tool modules into TOOL_REGISTRY
    from app.tool_registry import load_all_tool_modules
    load_all_tool_modules()

    logger.info("Jarvis app initialized successfully.")
    return app
