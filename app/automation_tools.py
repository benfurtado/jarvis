"""
Jarvis Automation & AI Tools — 11 tools for scheduling, monitoring, AI coding, browser, clipboard.
All tools self-register into TOOL_REGISTRY.
"""
import os
import subprocess
import shutil
import logging
import json
import time
from datetime import datetime

from langchain_core.tools import tool

from app.tool_registry import register_tool
from app.config import Config

logger = logging.getLogger("Jarvis")


# ===========================
# 1. SCHEDULE TASK
# ===========================

@tool
def schedule_task(command: str, cron_expression: str, description: str = "") -> str:
    """
    Schedule a cron-like recurring task.
    Args:
        command: Command or task to execute.
        cron_expression: Cron expression (e.g., '*/5 * * * *' for every 5 min).
        description: Optional description.
    """
    try:
        from app import db
        task_id = db.create_scheduled_task("system", command, cron_expression)
        return (f"Task scheduled:\n"
                f"  ID: {task_id}\n"
                f"  Command: {command}\n"
                f"  Schedule: {cron_expression}\n"
                f"  Description: {description or 'N/A'}")
    except Exception as e:
        return f"Schedule error: {e}"

register_tool("schedule_task", schedule_task, "HIGH", "automation")


# ===========================
# 2. CANCEL SCHEDULED TASK
# ===========================

@tool
def cancel_scheduled_task(task_id: str) -> str:
    """
    Cancel a scheduled task by ID.
    Args:
        task_id: Task UUID to cancel.
    """
    try:
        from app import db
        db.deactivate_scheduled_task(task_id)
        return f"Task {task_id} cancelled."
    except Exception as e:
        return f"Cancel error: {e}"

register_tool("cancel_scheduled_task", cancel_scheduled_task, "HIGH", "automation")


# ===========================
# 3. WATCHDOG MONITOR
# ===========================

_watchdog_rules = {}

@tool
def watchdog_monitor(action: str = "status", metric: str = "",
                     threshold: float = 0, alert_command: str = "",
                     rule_name: str = "") -> str:
    """
    Monitor system metrics and trigger alerts.
    Args:
        action: 'add', 'remove', 'status', 'list'.
        metric: 'cpu', 'memory', 'disk', 'process'. Required for 'add'.
        threshold: Threshold percentage. Required for 'add'.
        alert_command: Command to run when threshold breached.
        rule_name: Rule identifier.
    """
    global _watchdog_rules

    if action == "add":
        if not metric or threshold is None:
            return "Provide metric and threshold."
        name = rule_name or f"watchdog_{metric}_{int(time.time())}"
        _watchdog_rules[name] = {
            "metric": metric,
            "threshold": threshold,
            "alert_command": alert_command,
            "created": datetime.now().isoformat(),
            "triggered": False,
        }
        return f"Watchdog rule '{name}' added: {metric} > {threshold}%"

    elif action == "remove":
        if rule_name and rule_name in _watchdog_rules:
            del _watchdog_rules[rule_name]
            return f"Rule '{rule_name}' removed."
        return f"Rule '{rule_name}' not found."

    elif action == "list":
        if not _watchdog_rules:
            return "No watchdog rules configured."
        output = f"Watchdog Rules ({len(_watchdog_rules)}):\n"
        for name, rule in _watchdog_rules.items():
            output += (f"\n  {name}: {rule['metric']} > {rule['threshold']}%\n"
                      f"    Alert: {rule.get('alert_command', 'None')}\n"
                      f"    Last triggered: {'Yes' if rule['triggered'] else 'No'}\n")
        return output

    elif action == "status":
        import psutil
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/").percent

        output = (f"Watchdog Status:\n"
                  f"  CPU:  {cpu}%\n"
                  f"  RAM:  {mem}%\n"
                  f"  Disk: {disk}%\n")

        alerts = []
        for name, rule in _watchdog_rules.items():
            val = {"cpu": cpu, "memory": mem, "disk": disk}.get(rule["metric"], 0)
            if val > rule["threshold"]:
                alerts.append(f"  ⚠ {name}: {rule['metric']}={val}% > {rule['threshold']}%")
                rule["triggered"] = True
                if rule.get("alert_command"):
                    try:
                        subprocess.run(rule["alert_command"], shell=True, timeout=10)
                    except Exception:
                        pass

        if alerts:
            output += "\nALERTS:\n" + "\n".join(alerts)
        return output

    return "Invalid action. Use 'add', 'remove', 'list', or 'status'."

register_tool("watchdog_monitor", watchdog_monitor, "MEDIUM", "automation")


# ===========================
# 4. LOG ANALYZER
# ===========================

@tool
def log_analyzer(log_path: str, tail_lines: int = 100, query: str = "") -> str:
    """
    Read and analyze log files. Returns tail and summary.
    Args:
        log_path: Path to log file.
        tail_lines: Number of lines from end. Default: 100.
        query: Filter lines containing this string.
    """
    if not os.path.isfile(log_path):
        return f"Log file not found: {log_path}"

    try:
        with open(log_path, "r", errors="replace") as f:
            lines = f.readlines()

        recent = lines[-tail_lines:]

        if query:
            recent = [l for l in recent if query.lower() in l.lower()]

        error_count = sum(1 for l in recent if "error" in l.lower())
        warn_count = sum(1 for l in recent if "warn" in l.lower())

        output = (f"Log: {log_path} ({len(lines)} total lines)\n"
                  f"Showing last {len(recent)} lines"
                  f"{f' matching \"{query}\"' if query else ''}:\n"
                  f"  Errors: {error_count}, Warnings: {warn_count}\n\n")
        output += "".join(recent[-50:])  # Limit output
        return output
    except Exception as e:
        return f"Log analyzer error: {e}"

register_tool("log_analyzer", log_analyzer, "LOW", "automation")


# ===========================
# 5. AI CODE WRITER
# ===========================

@tool
def ai_code_writer(filepath: str, description: str, language: str = "python") -> str:
    """
    Generates code based on description and writes it to a file. Uses the LLM.
    Args:
        filepath: Output file path.
        description: What the code should do.
        language: Programming language. Default: python.
    """
    try:
        from app.llm import RotatingLLM
        from app.config import Config

        llm = RotatingLLM(temperature=0.3)

        prompt = (f"Write production-quality {language} code.\n"
                  f"Description: {description}\n"
                  f"Output ONLY the code, no explanations, no markdown fences.")

        response = llm.invoke(prompt)
        code = response.content.strip()

        # Remove markdown code fences if present
        if code.startswith("```"):
            lines = code.split("\n")
            code = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

        abs_path = filepath
        if not os.path.isabs(filepath):
            abs_path = os.path.join(Config.DEFAULT_CWD, filepath)

        os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
        with open(abs_path, "w") as f:
            f.write(code)

        return f"Code written to {abs_path} ({len(code)} bytes, {len(code.split(chr(10)))} lines)"
    except Exception as e:
        return f"AI code writer error: {e}"

register_tool("ai_code_writer", ai_code_writer, "MEDIUM", "automation")


# ===========================
# 6. AI CODE REFACTOR
# ===========================

@tool
def ai_code_refactor(filepath: str, instructions: str = "Improve code quality") -> str:
    """
    Reads a file, sends to LLM for refactoring, writes improved version back.
    Args:
        filepath: File to refactor.
        instructions: Refactoring instructions.
    """
    if not os.path.isabs(filepath):
        filepath = os.path.join(Config.DEFAULT_CWD, filepath)

    if not os.path.isfile(filepath):
        return f"File not found: {filepath}"

    try:
        with open(filepath, "r") as f:
            original = f.read()

        from app.llm import RotatingLLM
        llm = RotatingLLM(temperature=0.2)

        prompt = (f"Refactor the following code.\n"
                  f"Instructions: {instructions}\n"
                  f"Output ONLY the improved code, no explanations, no markdown fences.\n\n"
                  f"--- CODE ---\n{original}\n--- END ---")

        response = llm.invoke(prompt)
        new_code = response.content.strip()

        if new_code.startswith("```"):
            lines = new_code.split("\n")
            new_code = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

        # Backup original
        backup_path = filepath + ".bak"
        shutil.copy2(filepath, backup_path)

        with open(filepath, "w") as f:
            f.write(new_code)

        return (f"Refactored {filepath}\n"
                f"  Original: {len(original)} bytes\n"
                f"  New: {len(new_code)} bytes\n"
                f"  Backup: {backup_path}")
    except Exception as e:
        return f"Refactor error: {e}"

register_tool("ai_code_refactor", ai_code_refactor, "HIGH", "automation")


# ===========================
# 7. AUTO BACKUP DIRECTORY
# ===========================

@tool
def auto_backup_directory(source_dir: str, backup_name: str = "") -> str:
    """
    Creates a timestamped .tar.gz backup of a directory.
    Args:
        source_dir: Directory to backup.
        backup_name: Optional name for the backup.
    """
    if not os.path.isabs(source_dir):
        source_dir = os.path.join(Config.DEFAULT_CWD, source_dir)

    if not os.path.isdir(source_dir):
        return f"Directory not found: {source_dir}"

    try:
        backup_dir = Config.BACKUP_DIR
        os.makedirs(backup_dir, exist_ok=True)

        name = backup_name or os.path.basename(source_dir.rstrip("/"))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = f"{name}_{timestamp}.tar.gz"
        archive_path = os.path.join(backup_dir, archive_name)

        r = subprocess.run(
            ["tar", "-czf", archive_path, "-C", os.path.dirname(source_dir),
             os.path.basename(source_dir)],
            capture_output=True, text=True, timeout=300,
        )

        if r.returncode == 0:
            size = os.path.getsize(archive_path)
            return (f"Backup created:\n"
                    f"  Archive: {archive_path}\n"
                    f"  Size: {_human_size(size)}\n"
                    f"  Source: {source_dir}")
        return f"Backup failed: {r.stderr}"
    except Exception as e:
        return f"Backup error: {e}"

register_tool("auto_backup_directory", auto_backup_directory, "MEDIUM", "automation")


# ===========================
# 8. BROWSER AUTOMATION
# ===========================

@tool
def browser_automation(action: str, url: str = "", selector: str = "",
                       text: str = "", screenshot_path: str = "") -> str:
    """
    Browser automation: open URL, click elements, fill forms, take screenshots.
    Args:
        action: 'open', 'click', 'type', 'screenshot', 'get_text'.
        url: URL to open (for 'open').
        selector: CSS selector for element (for click/type/get_text).
        text: Text to type (for 'type' action).
        screenshot_path: Save path for screenshot.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By

        opts = Options()
        opts.add_argument("--headless")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")

        driver = webdriver.Chrome(options=opts)

        try:
            if action == "open":
                if not url:
                    return "URL required for 'open' action."
                driver.get(url)
                return f"Opened: {url}\nTitle: {driver.title}"

            elif action == "click" and selector:
                el = driver.find_element(By.CSS_SELECTOR, selector)
                el.click()
                return f"Clicked: {selector}"

            elif action == "type" and selector and text:
                el = driver.find_element(By.CSS_SELECTOR, selector)
                el.send_keys(text)
                return f"Typed into {selector}: {text[:50]}"

            elif action == "screenshot":
                if url:
                    driver.get(url)
                    time.sleep(2)
                path = screenshot_path or os.path.join(Config.TEMP_DIR, f"browser_{int(time.time())}.png")
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                driver.save_screenshot(path)
                return f"Screenshot saved: {path}"

            elif action == "get_text" and selector:
                el = driver.find_element(By.CSS_SELECTOR, selector)
                return f"Text: {el.text[:500]}"

            return "Invalid action or missing parameters."
        finally:
            driver.quit()

    except ImportError:
        return "Browser automation requires 'selenium' and chromedriver. Install: pip install selenium"
    except Exception as e:
        return f"Browser error: {e}"

register_tool("browser_automation", browser_automation, "MEDIUM", "automation")


# ===========================
# 9. KEYBOARD AUTOMATION
# ===========================

@tool
def keyboard_automation(action: str, keys: str = "", text: str = "") -> str:
    """
    Keyboard automation: type text, press key combos.
    Args:
        action: 'type' (type text string) or 'hotkey' (press key combination).
        keys: Key combination for hotkey (e.g., 'ctrl+c', 'alt+tab').
        text: Text to type for 'type' action.
    """
    try:
        import pyautogui
        pyautogui.FAILSAFE = True

        if action == "type" and text:
            pyautogui.typewrite(text, interval=0.02)
            return f"Typed: {text[:50]}..."
        elif action == "hotkey" and keys:
            key_list = [k.strip() for k in keys.split("+")]
            pyautogui.hotkey(*key_list)
            return f"Pressed: {keys}"
        return "Invalid action or missing args."
    except ImportError:
        return "Keyboard automation requires 'pyautogui'. Install: pip install pyautogui"
    except Exception as e:
        return f"Keyboard error: {e}"

register_tool("keyboard_automation", keyboard_automation, "HIGH", "automation")


# ===========================
# 10. CLIPBOARD READ
# ===========================

@tool
def clipboard_read() -> str:
    """Reads the current clipboard contents."""
    try:
        r = subprocess.run(["xclip", "-selection", "clipboard", "-o"],
                          capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return f"Clipboard contents:\n{r.stdout[:2000]}"
        # Fallback to xsel
        r = subprocess.run(["xsel", "--clipboard", "--output"],
                          capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return f"Clipboard contents:\n{r.stdout[:2000]}"
        return "Could not read clipboard. No display session or xclip/xsel not available."
    except FileNotFoundError:
        return "xclip/xsel not installed."
    except Exception as e:
        return f"Clipboard read error: {e}"

register_tool("clipboard_read", clipboard_read, "LOW", "automation")


# ===========================
# 11. CLIPBOARD WRITE
# ===========================

@tool
def clipboard_write(content: str) -> str:
    """
    Writes text to the system clipboard.
    Args:
        content: Text to copy to clipboard.
    """
    try:
        proc = subprocess.Popen(["xclip", "-selection", "clipboard"],
                               stdin=subprocess.PIPE, timeout=5)
        proc.communicate(input=content.encode())
        if proc.returncode == 0:
            return f"Copied to clipboard ({len(content)} chars)"
        # Fallback
        proc = subprocess.Popen(["xsel", "--clipboard", "--input"],
                               stdin=subprocess.PIPE, timeout=5)
        proc.communicate(input=content.encode())
        return f"Copied to clipboard ({len(content)} chars)"
    except FileNotFoundError:
        return "xclip/xsel not installed."
    except Exception as e:
        return f"Clipboard write error: {e}"

register_tool("clipboard_write", clipboard_write, "MEDIUM", "automation")


# ===========================
# 12. RUN TERMINAL COMMAND (upgraded)
# ===========================

@tool
def run_terminal_command(command: str) -> str:
    """
    Execute a terminal command in the current session working directory.
    Handles cd commands natively. Returns output and current working directory.
    Args:
        command: Shell command to execute.
    """
    import re
    from app.session_manager import get_cwd, set_cwd

    # Get current context
    import threading
    ctx = getattr(threading.current_thread(), "_jarvis_ctx", {})
    thread_id = ctx.get("thread_id", "default_thread")

    timeout = Config.TERMINAL_TIMEOUT

    # Security: check blocked patterns
    for pattern in Config.TERMINAL_BLOCKED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return f"BLOCKED: Command matched security pattern: {pattern}"

    # Handle cd commands natively
    cd_match = re.match(r'^cd\s+(.*)', command.strip())
    if cd_match:
        target = cd_match.group(1).strip().strip('"').strip("'")
        cwd = get_cwd(thread_id)

        if target == "~":
            target = os.path.expanduser("~")
        elif target == "-":
            target = os.getenv("OLDPWD", cwd)
        elif not os.path.isabs(target):
            target = os.path.normpath(os.path.join(cwd, target))

        if os.path.isdir(target):
            result = set_cwd(thread_id, target)
            if result.startswith("ERROR:"):
                return result
            return f"[CWD: {target}]\n(changed to {target})"
        else:
            return f"cd: no such directory: {target}"

    cwd = get_cwd(thread_id)
    os.makedirs(cwd, exist_ok=True)

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += ("\n--- STDERR ---\n" + result.stderr if output else result.stderr)

        if not output.strip():
            output = "(command completed with no output)"

        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"

        return f"[CWD: {cwd}]\n{output[:10000]}"
    except subprocess.TimeoutExpired:
        return f"[CWD: {cwd}]\nCommand timed out after {timeout}s"
    except Exception as e:
        return f"[CWD: {cwd}]\nExecution error: {e}"

register_tool("run_terminal_command", run_terminal_command, "HIGH", "automation")


# ===========================
# HELPER
# ===========================

def _human_size(size: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size) < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}PB"
