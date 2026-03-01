"""
Jarvis Configuration — loads from .env
"""
import os
from datetime import timedelta
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))


class Config:
    """Application configuration."""

    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
    DEBUG = os.getenv("PRODUCTION", "false").lower() != "true"

    # JWT
    JWT_SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=24)

    # Gemini LLM
    GEMINI_API_KEYS = [k.strip() for k in os.getenv("GEMINI_API_KEYS", "").split(",") if k.strip()]
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    ENABLE_GEMINI = os.getenv("ENABLE_GEMINI", "true").strip().lower() == "true"

    # Groq LLM
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    GROQ_API_KEYS = [k.strip() for k in os.getenv("GROQ_API_KEYS", GROQ_API_KEY).split(",") if k.strip()]
    
    LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
    LLM_MODELS = [m.strip() for m in os.getenv("LLM_MODELS", (
        "llama-3.3-70b-versatile,"
        "meta-llama/llama-4-scout-17b-16e-instruct,"
        "qwen/qwen3-32b,"
        "llama-3.1-8b-instant,"
        "groq/compound"
    )).split(",") if m.strip()]

    # Azure AI Inference (OpenAI-compatible) — optional
    # Endpoint format example:
    #   https://<resource>.services.ai.azure.com/models/chat/completions
    # Version example:
    #   2024-05-01-preview
    AZURE_AI_ENDPOINT = os.getenv("AZURE_AI_ENDPOINT", "").strip()
    AZURE_AI_API_KEY = os.getenv("AZURE_AI_API_KEY", "").strip()
    AZURE_AI_API_VERSION = os.getenv("AZURE_AI_API_VERSION", "2024-05-01-preview").strip()
    AZURE_AI_MODEL = os.getenv("AZURE_AI_MODEL", "grok-4-1-fast-non-reasoning").strip()

    # Azure OpenAI-compatible endpoint (OpenAI SDK) — optional
    # Example base URL:
    #   https://<resource>.openai.azure.com/openai/v1
    AZURE_OPENAI_BASE_URL = os.getenv("AZURE_OPENAI_BASE_URL", "").strip()
    AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    AZURE_OPENAI_MODEL = os.getenv("AZURE_OPENAI_MODEL", "grok-4-1-fast-non-reasoning").strip()

    # Admin
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "jarvis2024")

    # WebSocket server (WhatsApp bridge)
    WS_SERVER_URL = os.getenv("WS_SERVER_URL", "ws://52.233.85.162:8080")

    # Telegram
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

    # CORS
    ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*")

    # Database
    DATABASE_PATH = os.getenv("DATABASE_PATH", "jarvis.db")

    # Working Directory
    ALLOWED_BASE_DIR = os.getenv("ALLOWED_BASE_DIR", "/root")
    DEFAULT_CWD = os.getenv("DEFAULT_CWD", "/root/projects")

    # File Manager
    ALLOWED_DIRS = [d.strip() for d in os.getenv("ALLOWED_DIRS", "/root/projects,/tmp,/var/log").split(",") if d.strip()]

    # Gmail
    GMAIL_SCOPES = [
        s.strip()
        for s in os.getenv(
            "GMAIL_SCOPES",
            "https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.send",
        ).split(",")
    ]

    # Rate Limits
    LOGIN_RATE_LIMIT = "5 per minute"
    MAX_FAILED_LOGINS = 5

    # Terminal
    TERMINAL_TIMEOUT = 120
    TERMINAL_BLOCKED_PATTERNS = [
        r"rm\s+-rf\s+/\s*$",
        r"chmod\s+777\s+/\s*$",
        r"curl.*\|.*bash",
        r"wget.*\|.*bash",
        r"\bdd\s+if=",
        r"\bmkfs\b",
        r":\(\)\s*\{.*\|.*&\s*\}\s*;",
        r">\s*/dev/sd",
    ]

    # Force-tool keywords
    FORCE_TOOL_KEYWORDS = [
        "create", "write", "delete", "run", "install", "deploy",
        "start", "stop", "build", "make", "execute", "mkdir", "touch",
        "npm", "pip", "git", "wget", "curl", "cd", "kill", "zip",
        "backup", "schedule", "scan", "open port", "close port",
        "email", "send email", "inbox", "reply", "mail", "fetch emails",
        "search web", "google", "lookup", "find news", "web search", "browse",
    ]

    # Temp directory for screenshots, backups, etc.
    TEMP_DIR = os.getenv("TEMP_DIR", "/tmp/jarvis")

    # Watchdog
    WATCHDOG_CHECK_INTERVAL = 30  # seconds

    # Backup
    BACKUP_DIR = os.getenv("BACKUP_DIR", "/root/backups/jarvis")
