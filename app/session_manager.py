"""
Jarvis Session Manager — persistent working directory per session/thread.
"""
import os
import logging

from app.config import Config

logger = logging.getLogger("Jarvis")

# Session state: { thread_id: { "cwd": "/path" } }
_sessions = {}


def get_session(thread_id: str) -> dict:
    """Get or create session state for a thread."""
    if thread_id not in _sessions:
        _sessions[thread_id] = {
            "cwd": Config.DEFAULT_CWD,
        }
    return _sessions[thread_id]


def get_cwd(thread_id: str) -> str:
    """Get current working directory for a session."""
    return get_session(thread_id)["cwd"]


def set_cwd(thread_id: str, new_cwd: str) -> str:
    """
    Update session working directory.
    Validates the path is under ALLOWED_BASE_DIR.
    Creates directory if missing.
    Returns the resolved cwd or error string.
    """
    # Resolve absolute path
    session = get_session(thread_id)
    if not os.path.isabs(new_cwd):
        new_cwd = os.path.normpath(os.path.join(session["cwd"], new_cwd))
    else:
        new_cwd = os.path.normpath(new_cwd)

    # Validate under allowed base
    real_path = os.path.realpath(new_cwd)
    base = os.path.realpath(Config.ALLOWED_BASE_DIR)
    if not real_path.startswith(base):
        return f"ERROR: Path '{new_cwd}' is outside allowed base directory '{Config.ALLOWED_BASE_DIR}'."

    # Auto-create if missing
    os.makedirs(new_cwd, exist_ok=True)

    session["cwd"] = new_cwd
    logger.info(f"Session {thread_id}: cwd changed to {new_cwd}")
    return new_cwd


def handle_cd_command(thread_id: str, user_message: str) -> str | None:
    """
    Detect `cd <path>` in user message and update session cwd.
    Returns the new cwd if cd was detected, None otherwise.
    """
    msg = user_message.strip()

    # Match patterns: "cd /path", "cd path", "cd ..", "cd ~"
    if msg.startswith("cd ") or msg == "cd":
        parts = msg.split(None, 1)
        if len(parts) < 2:
            target = Config.DEFAULT_CWD
        else:
            target = parts[1].strip()
            if target == "~":
                target = os.path.expanduser("~")

        result = set_cwd(thread_id, target)
        return result

    return None


def get_all_sessions() -> dict:
    """Return all session states (for debugging)."""
    return dict(_sessions)
