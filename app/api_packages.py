"""
Jarvis Packages API — installed packages, updates, crontab editor.
"""
import os
import subprocess
import re
import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from app.utils_os import is_windows, run_command

logger = logging.getLogger("Jarvis")
packages_bp = Blueprint("packages_api", __name__)


# ——— Installed Packages ———
@packages_bp.route("/api/packages", methods=["GET"])
@jwt_required()
def list_packages():
    search = request.args.get("search", "").lower()
    limit = int(request.args.get("limit", 100))
    if is_windows():
        try:
            # powershell Get-Package is very slow sometimes, use winget if possible
            # But winget is not always in path for SYSTEM/service account
            out = run_command(["powershell", "Get-Package | Select-Object Name, Version | ConvertTo-Json"], timeout=30)
            import json
            data = json.loads(out)
            pkgs = [{"name": p["Name"], "version": p["Version"], "size_kb": 0} for p in (data if isinstance(data, list) else [data])]
            if search: pkgs = [p for p in pkgs if search in p["name"].lower()]
            return jsonify({"packages": pkgs[:limit], "total": len(pkgs)})
        except Exception as e:
            return jsonify({"packages": [], "error": f"Windows package check failed: {e}"})

    try:
        out = run_command(["dpkg-query", "-W", "--showformat=${Package}\\t${Version}\\t${Status}\\t${Installed-Size}\\n"], timeout=10)
# ... rest of dpkg/rpm logic ...
        pkgs = []
        for line in out.strip().split("\n"):
            parts = line.split("\t")
            if len(parts) >= 4 and "installed" in parts[2].lower():
                if search and search not in parts[0].lower():
                    continue
                pkgs.append({"name": parts[0], "version": parts[1], "size_kb": int(parts[3]) if parts[3].isdigit() else 0})
        pkgs.sort(key=lambda x: x["name"])
        return jsonify({"packages": pkgs[:limit], "total": len(pkgs)})
    except FileNotFoundError:
        # Try rpm
        try:
            out = subprocess.check_output(["rpm", "-qa", "--queryformat", "%{NAME}\t%{VERSION}\t%{SIZE}\n"], text=True, timeout=10)
            pkgs = []
            for line in out.strip().split("\n"):
                parts = line.split("\t")
                if len(parts) >= 3:
                    if search and search not in parts[0].lower():
                        continue
                    pkgs.append({"name": parts[0], "version": parts[1], "size_kb": int(parts[2]) // 1024 if parts[2].isdigit() else 0})
            return jsonify({"packages": pkgs[:limit], "total": len(pkgs)})
        except Exception:
            return jsonify({"packages": [], "total": 0, "error": "No package manager found"})
    except Exception as e:
        return jsonify({"packages": [], "error": str(e)})


# ——— Available Updates ———
@packages_bp.route("/api/packages/updates", methods=["GET"])
@jwt_required()
def check_updates():
    if is_windows():
        return jsonify({"updates": [], "count": 0, "note": "Update check via apt not available on Windows"})
    try:
        run_command(["apt-get", "update", "-qq"], timeout=60)
        out = run_command(["apt", "list", "--upgradable"], timeout=15)
# ... rest of apt logic ...
        updates = []
        for line in out.strip().split("\n"):
            if "/" in line and "Listing" not in line:
                parts = line.split()
                name = parts[0].split("/")[0] if parts else ""
                version = parts[1] if len(parts) > 1 else ""
                if name:
                    updates.append({"name": name, "new_version": version})
        return jsonify({"updates": updates, "count": len(updates)})
    except Exception as e:
        return jsonify({"updates": [], "error": str(e)})


# ——— Pip Packages ———
@packages_bp.route("/api/packages/pip", methods=["GET"])
@jwt_required()
def pip_packages():
    search = request.args.get("search", "").lower()
    try:
        out = subprocess.check_output(["pip3", "list", "--format=json"], text=True, timeout=10, stderr=subprocess.DEVNULL)
        pkgs = []
        for p in __import__("json").loads(out):
            if search and search not in p.get("name", "").lower():
                continue
            pkgs.append({"name": p["name"], "version": p.get("version", "?")})
        return jsonify({"packages": pkgs[:200], "total": len(pkgs)})
    except Exception as e:
        return jsonify({"packages": [], "error": str(e)})


# ——— Crontab ———
@packages_bp.route("/api/crontab", methods=["GET"])
@jwt_required()
def get_crontab():
    if is_windows():
        return jsonify({"entries": [], "note": "Crontab not available on Windows. Use Task Scheduler."})
    try:
        out = run_command(["crontab", "-l"], timeout=5)
# ... rest of cron logic ...
        entries = []
        for line in out.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 5)
            if len(parts) >= 6:
                entries.append({
                    "schedule": " ".join(parts[:5]),
                    "command": parts[5],
                    "human": _cron_human(" ".join(parts[:5])),
                    "raw": line,
                })
        return jsonify({"entries": entries, "raw": out})
    except subprocess.CalledProcessError:
        return jsonify({"entries": [], "raw": "no crontab for user"})
    except Exception as e:
        return jsonify({"entries": [], "error": str(e)})


@packages_bp.route("/api/crontab", methods=["PUT"])
@jwt_required()
def set_crontab():
    data = request.json or {}
    content = data.get("content", "")
    try:
        proc = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True, timeout=5)
        proc.communicate(input=content)
        return jsonify({"status": "saved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _cron_human(expr):
    """Basic cron expression to human readable."""
    parts = expr.split()
    if len(parts) < 5:
        return expr
    m, h, dom, mon, dow = parts
    if expr == "* * * * *":
        return "Every minute"
    if m == "0" and h == "*":
        return "Every hour"
    if m == "0" and dom == "*" and mon == "*" and dow == "*":
        return f"Daily at {h}:00"
    if dow != "*" and dom == "*":
        days = {"0": "Sun", "1": "Mon", "2": "Tue", "3": "Wed", "4": "Thu", "5": "Fri", "6": "Sat"}
        return f"{days.get(dow, dow)} at {h}:{m.zfill(2)}"
    return expr


# ——— System Logs ———
@packages_bp.route("/api/system/logs", methods=["GET"])
@jwt_required()
def system_logs():
    lines = int(request.args.get("lines", 100))
    if is_windows():
        return jsonify({"logs": "Journalctl not available on Windows", "lines": 0})
    try:
        out = run_command(["journalctl", "--no-pager", "-n", str(lines), "--output=short"], timeout=10)
        return jsonify({"logs": out, "lines": lines})
# ... rest of log logic ...
    except FileNotFoundError:
        # Fallback to syslog
        try:
            out = subprocess.check_output(["tail", f"-n{lines}", "/var/log/syslog"], text=True, timeout=5)
            return jsonify({"logs": out, "lines": lines})
        except Exception:
            return jsonify({"logs": "No log source available", "lines": 0})
    except Exception as e:
        return jsonify({"logs": "", "error": str(e)})
