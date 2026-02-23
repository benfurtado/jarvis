"""
Jarvis WordPress Tools — WP-CLI Wrapper.
Allows full management of WordPress sites via server-local WP-CLI.
"""
import os
import subprocess
import logging
from langchain_core.tools import tool

from app.tool_registry import register_tool
from app.utils_os import run_command
from app import db

logger = logging.getLogger("Jarvis")

def _check_wp_cli():
    """Verify if wp-cli is installed, return path or None."""
    try:
        r = subprocess.run(["which", "wp"], capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout.strip()
    except:
        pass
    return None

def _install_wp_cli():
    """Attempt to download and install wp-cli if missing."""
    target = "/usr/local/bin/wp"
    logger.info("WordPress: Attempting to install wp-cli...")
    try:
        # Download phar
        subprocess.run(["curl", "-O", "https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar"], check=True)
        subprocess.run(["chmod", "+x", "wp-cli.phar"], check=True)
        # Move to bin (requires sudo usually, but we are root or in a container)
        subprocess.run(["mv", "wp-cli.phar", target], check=True)
        return target
    except Exception as e:
        logger.error(f"wp-cli install failed: {e}")
        return None

@tool
def wp_command(command: str, path: str = "") -> str:
    """
    Execute a WP-CLI command on a WordPress installation.
    Args:
        command: The WP-CLI command (e.g., 'plugin list', 'user create', 'core update').
        path: Path to the WordPress root. Defaults to the one in Settings.
    """
    wp_bin = _check_wp_cli()
    if not wp_bin:
        wp_bin = _install_wp_cli()
        if not wp_bin:
            return "ERROR: wp-cli is not installed and could not be auto-installed. Please install it manually."

    target_path = path or db.get_config("wp_path")
    if not target_path:
        return "ERROR: WordPress path not configured. Set 'wp_path' in Settings or provide it as an argument."
    
    if not os.path.isdir(target_path):
        return f"ERROR: Path '{target_path}' is not a directory."

    full_cmd = f"{wp_bin} {command} --path={target_path} --allow-root"
    
    try:
        # We use run_command from utils_os for consistent behavior
        result = run_command(full_cmd, shell=True, timeout=60)
        return f"WP-CLI Output (@ {target_path}):\n{result}"
    except Exception as e:
        logger.error(f"WP-CLI execution error: {e}")
        return f"Failed to execute WP-CLI command: {str(e)}"

register_tool("wp_command", wp_command, "HIGH", "wordpress")

@tool
def wp_site_info() -> str:
    """Get basic info about the configured WordPress site."""
    return wp_command.invoke({"command": "core version && wp option get siteurl && wp plugin list --status=active"})

register_tool("wp_site_info", wp_site_info, "LOW", "wordpress")
