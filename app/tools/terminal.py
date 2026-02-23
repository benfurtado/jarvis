"""
Jarvis Terminal Tool — session-aware, cwd-persistent command execution.
Supports shell=True with cwd from session manager.
Allowlist + blocked patterns preserved.
"""
import re
import os
import subprocess
import logging
import threading

from langchain_core.tools import tool

from app.config import Config

logger = logging.getLogger("Jarvis")

BLOCKED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in Config.TERMINAL_BLOCKED_PATTERNS]
TIMEOUT = Config.TERMINAL_TIMEOUT

# Thread-local storage for session context
_thread_context = threading.local()


def set_terminal_context(thread_id: str, cwd: str):
    """Set the terminal context for the current request thread."""
    _thread_context.thread_id = thread_id
    _thread_context.cwd = cwd


def _get_cwd() -> str:
    """Get cwd from thread context, fallback to config default."""
    return getattr(_thread_context, "cwd", Config.DEFAULT_CWD)


def _get_thread_id() -> str:
    return getattr(_thread_context, "thread_id", "default")


def _validate_command(command: str) -> tuple[bool, str]:
    """
    Validate a command against blocked patterns.
    Returns (is_safe, reason).
    """
    for pattern in BLOCKED_PATTERNS:
        if pattern.search(command):
            return False, f"Blocked pattern detected: {pattern.pattern}"
    return True, "OK"


@tool
def run_terminal_command(command: str) -> str:
    """
    Executes a shell command in the current session working directory.
    The working directory persists across messages.
    Commands are validated against blocked patterns for safety.
    Args:
        command: The shell command to execute (e.g., 'ls -la', 'npm install', 'git status').
    """
    cwd = _get_cwd()
    logger.info(f"Terminal [{cwd}]: {command}")

    # Handle cd commands — update session
    stripped = command.strip()
    if stripped.startswith("cd ") or stripped == "cd":
        parts = stripped.split(None, 1)
        if len(parts) < 2:
            target = Config.DEFAULT_CWD
        else:
            target = parts[1].strip()
            if target == "~":
                target = os.path.expanduser("~")

        if not os.path.isabs(target):
            target = os.path.normpath(os.path.join(cwd, target))

        if os.path.isdir(target):
            from app.session_manager import set_cwd
            thread_id = _get_thread_id()
            result = set_cwd(thread_id, target)
            set_terminal_context(thread_id, target)
            return f"Changed directory to: {target}"
        else:
            os.makedirs(target, exist_ok=True)
            from app.session_manager import set_cwd
            thread_id = _get_thread_id()
            set_cwd(thread_id, target)
            set_terminal_context(thread_id, target)
            return f"Created and changed to directory: {target}"

    # Validate
    is_safe, reason = _validate_command(command)
    if not is_safe:
        logger.warning(f"Command BLOCKED: {command} — Reason: {reason}")
        return f"BLOCKED: {reason}"

    # Ensure cwd exists
    os.makedirs(cwd, exist_ok=True)

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if result.returncode != 0:
            logger.warning(f"Command exited with code {result.returncode}")
            output = f"[cwd: {cwd}]\nExit code: {result.returncode}\n"
            if stdout:
                output += f"Stdout:\n{stdout}\n"
            if stderr:
                output += f"Stderr:\n{stderr}"
            return output

        output = f"[cwd: {cwd}]\n"
        output += stdout if stdout else "Command completed successfully (no output)."
        return output

    except subprocess.TimeoutExpired:
        logger.error(f"Command timed out after {TIMEOUT}s: {command}")
        return f"ERROR: Command timed out after {TIMEOUT} seconds."
    except Exception as e:
        logger.error(f"Terminal error: {e}")
        return f"ERROR: {str(e)}"
