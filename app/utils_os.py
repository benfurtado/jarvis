"""
Jarvis OS Utilities — Cross-platform command and system abstraction.
"""
import os
import platform
import subprocess
import logging

logger = logging.getLogger("Jarvis")

def is_windows():
    return platform.system() == "Windows"

def run_command(cmd, shell=None, timeout=10, **kwargs):
    """Run a command safely across platforms."""
    # Auto-detect shell mode if not specified
    if shell is None:
        shell = isinstance(cmd, str)
    try:
        return subprocess.check_output(cmd, shell=shell, text=True, timeout=timeout, stderr=subprocess.STDOUT, **kwargs)
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {cmd} | Error: {e.output}")
        raise e
    except Exception as e:
        logger.error(f"Command error: {cmd} | {str(e)}")
        raise e

def get_platform_info():
    """Unified system info."""
    return {
        "os": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "node": platform.node(),
    }

def get_firewall_rules():
    """Abstract firewall status/rules."""
    if is_windows():
        try:
            # Basic windows firewall check
            out = run_command("netsh advfirewall show allprofiles")
            return {"active": "ON" in out, "rules": [], "note": "Windows Firewall basic status"}
        except:
            return {"active": False, "rules": [], "note": "Failed to check firewall"}
    else:
        # Linux / UFW logic (could be moved here from api_network.py)
        # For now, let's keep it modular but providing a bridge
        return None

def get_installed_packages():
    """Abstract package list."""
    if is_windows():
        try:
            # winget is standard on newer windows, or use powershell
            out = run_command("powershell Get-Package | Select-Object Name, Version | ConvertTo-Json")
            import json
            data = json.loads(out)
            return [{"name": p["Name"], "version": p["Version"]} for p in data]
        except:
            return []
    else:
        # apt/dpkg logic bridge
        return None
