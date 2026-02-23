"""
Jarvis Security API — SSH keys, fail2ban, security audit, IP rules, login history.
"""
import os
import subprocess
import re
import json
import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from app.utils_os import is_windows, run_command

logger = logging.getLogger("Jarvis")
security_bp = Blueprint("security_api", __name__)


# ——— SSH Keys ———
@security_bp.route("/api/ssh/keys", methods=["GET"])
@jwt_required()
def list_ssh_keys():
    keys = []
    auth_file = os.path.expanduser("~/.ssh/authorized_keys")
    if os.path.exists(auth_file):
        with open(auth_file, "r") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split()
                    keys.append({
                        "id": i,
                        "type": parts[0] if len(parts) > 0 else "?",
                        "key_preview": parts[1][:20] + "..." if len(parts) > 1 else "?",
                        "comment": parts[2] if len(parts) > 2 else "",
                    })
    return jsonify({"keys": keys, "path": auth_file})


@security_bp.route("/api/ssh/keys", methods=["POST"])
@jwt_required()
def add_ssh_key():
    data = request.json or {}
    key = data.get("key", "").strip()
    if not key:
        return jsonify({"error": "Key required"}), 400
    auth_file = os.path.expanduser("~/.ssh/authorized_keys")
    os.makedirs(os.path.dirname(auth_file), exist_ok=True)
    with open(auth_file, "a") as f:
        f.write(key + "\n")
    return jsonify({"status": "added"})


@security_bp.route("/api/ssh/keys/<int:key_id>", methods=["DELETE"])
@jwt_required()
def remove_ssh_key(key_id):
    auth_file = os.path.expanduser("~/.ssh/authorized_keys")
    if not os.path.exists(auth_file):
        return jsonify({"error": "No keys file"}), 404
    with open(auth_file, "r") as f:
        lines = f.readlines()
    real_lines = [(i, l) for i, l in enumerate(lines) if l.strip() and not l.strip().startswith("#")]
    if key_id >= len(real_lines):
        return jsonify({"error": "Key not found"}), 404
    del lines[real_lines[key_id][0]]
    with open(auth_file, "w") as f:
        f.writelines(lines)
    return jsonify({"status": "removed"})


# ——— Fail2Ban ———
@security_bp.route("/api/fail2ban", methods=["GET"])
@jwt_required()
def fail2ban_status():
    if is_windows():
        return jsonify({"installed": False, "jails": [], "note": "Fail2Ban not supported on Windows"})
    try:
        out = run_command(["fail2ban-client", "status"], timeout=5)
# ... rest of fail2ban logic ...
        jails = []
        jail_match = re.search(r"Jail list:\s+(.+)", out)
        if jail_match:
            jail_names = [j.strip() for j in jail_match.group(1).split(",")]
            for jail in jail_names:
                try:
                    jout = subprocess.check_output(["fail2ban-client", "status", jail], text=True, timeout=5, stderr=subprocess.STDOUT)
                    banned = re.search(r"Currently banned:\s+(\d+)", jout)
                    total = re.search(r"Total banned:\s+(\d+)", jout)
                    banned_ips_match = re.search(r"Banned IP list:\s+(.*)", jout)
                    jails.append({
                        "name": jail,
                        "banned": int(banned.group(1)) if banned else 0,
                        "total_banned": int(total.group(1)) if total else 0,
                        "banned_ips": banned_ips_match.group(1).split() if banned_ips_match else [],
                    })
                except Exception:
                    jails.append({"name": jail, "banned": 0, "total_banned": 0, "banned_ips": []})
        return jsonify({"installed": True, "jails": jails})
    except FileNotFoundError:
        return jsonify({"installed": False, "jails": []})
    except Exception as e:
        return jsonify({"installed": False, "jails": [], "error": str(e)})


@security_bp.route("/api/fail2ban/unban", methods=["POST"])
@jwt_required()
def fail2ban_unban():
    data = request.json or {}
    ip = data.get("ip", "")
    jail = data.get("jail", "sshd")
    if not ip:
        return jsonify({"error": "IP required"}), 400
    try:
        subprocess.check_output(["fail2ban-client", "set", jail, "unbanip", ip], text=True, timeout=5, stderr=subprocess.STDOUT)
        return jsonify({"status": "unbanned", "ip": ip})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ——— Security Audit ———
@security_bp.route("/api/security/audit", methods=["POST"])
@jwt_required()
def security_audit():
    results = []
    # Check open ports
    try:
        import socket as sock
        for port in [21, 23, 25, 3306, 5432, 6379, 27017]:
            s = sock.socket(sock.AF_INET, sock.SOCK_STREAM)
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                results.append({"name": f"Port {port} closed", "status": "FAIL", "detail": f"Service on port {port} is accessible"})
            else:
                results.append({"name": f"Port {port} closed", "status": "PASS", "detail": f"Port {port} is secured"})
            s.close()
    except Exception:
        pass

    # Check root SSH
    try:
        if os.path.exists("/etc/ssh/sshd_config"):
            with open("/etc/ssh/sshd_config", "r") as f:
                content = f.read()
                if re.search(r"^PermitRootLogin\s+yes", content, re.MULTILINE):
                    results.append({"name": "Root SSH Disabled", "status": "FAIL", "detail": "Root login via SSH is enabled"})
                else:
                    results.append({"name": "Root SSH Disabled", "status": "PASS", "detail": "Root login is restricted"})
                
                if re.search(r"^PasswordAuthentication\s+yes", content, re.MULTILINE):
                    results.append({"name": "Key-based Auth", "status": "FAIL", "detail": "Password authentication is enabled"})
                else:
                    results.append({"name": "Key-based Auth", "status": "PASS", "detail": "Only SSH keys allowed"})
    except Exception:
        pass

    # Check UFW status
    try:
        out = run_command(["ufw", "status"], timeout=5)
        if "inactive" in out.lower():
            results.append({"name": "Firewall Active", "status": "FAIL", "detail": "UFW firewall is inactive"})
        else:
            results.append({"name": "Firewall Active", "status": "PASS", "detail": "UFW firewall is active"})
    except Exception:
        results.append({"name": "Firewall Active", "status": "FAIL", "detail": "Firewall not configured"})

    # Check world-writable files
    try:
        out = run_command(["find", "/etc", "-maxdepth", "1", "-perm", "-o+w", "-type", "f"], timeout=5)
        files = [f for f in out.strip().split("\n") if f]
        if files:
            results.append({"name": "File Permissions", "status": "FAIL", "detail": f"{len(files)} writable files in /etc"})
        else:
            results.append({"name": "File Permissions", "status": "PASS", "detail": "No vulnerable files in /etc"})
    except Exception:
        pass

    passed = sum(1 for r in results if r["status"] == "PASS")
    score = int((passed / len(results) * 100)) if results else 0
    return jsonify({"checks": results, "score": score, "total": len(results)})


# ——— IP Whitelist/Blacklist ———
_ip_rules = {"whitelist": [], "blacklist": []}


@security_bp.route("/api/ip-rules", methods=["GET"])
@jwt_required()
def get_ip_rules():
    return jsonify(_ip_rules)


@security_bp.route("/api/ip-rules", methods=["POST"])
@jwt_required()
def update_ip_rules():
    data = request.json or {}
    list_type = data.get("type", "whitelist")
    ip = data.get("ip", "").strip()
    action = data.get("action", "add")
    if list_type not in ("whitelist", "blacklist") or not ip:
        return jsonify({"error": "Invalid params"}), 400
    if action == "add":
        if ip not in _ip_rules[list_type]:
            _ip_rules[list_type].append(ip)
    elif action == "remove":
        _ip_rules[list_type] = [x for x in _ip_rules[list_type] if x != ip]
    return jsonify(_ip_rules)


# ——— Login History ———
@security_bp.route("/api/security/logins", methods=["GET"])
@jwt_required()
def login_history():
    if is_windows():
        return jsonify({"logins": [], "note": "Login history via 'last' not available on Windows"})
    try:
        out = run_command(["last", "-n", "30", "-w"], timeout=5)
# ... rest of last logic ...
        logins = []
        for line in out.strip().split("\n"):
            if line.strip() and not line.startswith("wtmp") and not line.startswith("reboot"):
                parts = line.split()
                if len(parts) >= 3:
                    logins.append({"user": parts[0], "terminal": parts[1], "from": parts[2] if len(parts) > 2 else "", "raw": line.strip()})
        return jsonify({"logins": logins[:30]})
    except Exception as e:
        return jsonify({"logins": [], "error": str(e)})
