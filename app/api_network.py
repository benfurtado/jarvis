"""
Jarvis Network & Firewall API — UFW rules, port scan, DNS, SSL certs.
"""
import os
import re
import subprocess
import json
import ssl
import socket
import logging
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from app.utils_os import is_windows, run_command

logger = logging.getLogger("Jarvis")
network_bp = Blueprint("network_api", __name__)

# ——— Firewall (UFW) ———
@network_bp.route("/api/firewall/rules", methods=["GET"])
@jwt_required()
def firewall_rules():
    if is_windows():
        return jsonify({"active": False, "rules": [], "note": "UFW not supported on Windows. Use Windows Firewall."})
    try:
        out = run_command(["ufw", "status", "numbered"], timeout=5)
        lines = out.strip().split("\n")
        status_line = lines[0] if lines else "inactive"
        active = "active" in status_line.lower()
        rules = []
        for line in lines:
            m = re.match(r"\[\s*(\d+)\]\s+(.+?)\s+(ALLOW|DENY|REJECT|LIMIT)\s+(IN|OUT)?\s*(.*)", line)
            if m:
                rules.append({"num": int(m.group(1)), "to": m.group(2).strip(), "action": m.group(3), "direction": m.group(4) or "IN", "from": m.group(5).strip()})
        return jsonify({"active": active, "rules": rules, "raw": out})
    except FileNotFoundError:
        return jsonify({"active": False, "rules": [], "note": "UFW not installed"})
    except Exception as e:
        return jsonify({"active": False, "rules": [], "error": str(e)})

@network_bp.route("/api/firewall/rules", methods=["POST"])
@jwt_required()
def add_firewall_rule():
    if is_windows(): return jsonify({"error": "UFW not available on Windows"}), 400
    data = request.json or {}
    port = data.get("port", "")
    action = data.get("action", "allow")
    proto = data.get("proto", "tcp")
    if not port: return jsonify({"error": "Port required"}), 400
    try:
        cmd = ["ufw", action, f"{port}/{proto}"]
        out = run_command(cmd, timeout=10, input="y\n")
        return jsonify({"status": "ok", "output": out.strip()})
    except Exception as e: return jsonify({"error": str(e)}), 500

@network_bp.route("/api/firewall/rules/<int:rule_num>", methods=["DELETE"])
@jwt_required()
def delete_firewall_rule(rule_num):
    if is_windows(): return jsonify({"error": "UFW not available on Windows"}), 400
    try:
        out = run_command(["ufw", "--force", "delete", str(rule_num)], timeout=10)
        return jsonify({"status": "ok", "output": out.strip()})
    except Exception as e: return jsonify({"error": str(e)}), 500

# ——— Port Scanning ———
@network_bp.route("/api/ports/scan", methods=["POST"])
@jwt_required()
def scan_ports():
    data = request.json or {}
    host = data.get("host", "127.0.0.1")
    port_range = data.get("range", "1-1024")
    common_only = data.get("common_only", True)
    common_ports = [21, 22, 25, 53, 80, 443, 3306, 5432, 6379, 8080, 8443, 9090, 27017, 5000, 3000, 8000]
    results = []
    if common_only:
        for port in common_ports:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.5)
                r = s.connect_ex((host, port))
                if r == 0:
                    results.append({"port": port, "state": "open", "service": _port_service(port)})
                s.close()
            except Exception:
                continue
    else:
        try:
            start, end = map(int, port_range.split("-"))
            for port in range(start, min(end + 1, 65536)):
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(0.3)
                    if s.connect_ex((host, port)) == 0:
                        results.append({"port": port, "state": "open", "service": _port_service(port)})
                    s.close()
                except Exception:
                    continue
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    return jsonify({"host": host, "ports": results})


def _port_service(port):
    services = {21: "FTP", 22: "SSH", 25: "SMTP", 53: "DNS", 80: "HTTP", 443: "HTTPS", 3306: "MySQL", 5432: "PostgreSQL",
                6379: "Redis", 8080: "HTTP-Alt", 8443: "HTTPS-Alt", 9090: "Proxy", 27017: "MongoDB", 5000: "Flask", 3000: "Node", 8000: "Django"}
    return services.get(port, "unknown")


# ——— DNS / Hosts ———
@network_bp.route("/api/dns", methods=["GET"])
@jwt_required()
def dns_config():
    hosts_path = r"C:\Windows\System32\drivers\etc\hosts" if is_windows() else "/etc/hosts"
    hosts = ""
    resolv = ""
    try:
        if os.path.exists(hosts_path):
            with open(hosts_path, "r") as f: hosts = f.read()
    except: pass
    if not is_windows():
        try:
            if os.path.exists("/etc/resolv.conf"):
                with open("/etc/resolv.conf", "r") as f: resolv = f.read()
        except: pass
    return jsonify({"hosts": hosts, "resolv": resolv})


@network_bp.route("/api/dns/hosts", methods=["PUT"])
@jwt_required()
def update_hosts():
    data = request.json or {}
    content = data.get("content", "")
    hosts_path = r"C:\Windows\System32\drivers\etc\hosts" if is_windows() else "/etc/hosts"
    try:
        with open(hosts_path, "w") as f:
            f.write(content)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ——— SSL Certificate Monitor ———
@network_bp.route("/api/ssl/certs", methods=["GET"])
@jwt_required()
def ssl_certs():
    if is_windows():
        return jsonify({"certs": [], "note": "LetsEncrypt SSL monitoring not supported on Windows"})
    certs = []
    le_path = "/etc/letsencrypt/live"
    if os.path.exists(le_path):
# ... rest of cert logic ...
        for domain in os.listdir(le_path):
            cert_file = os.path.join(le_path, domain, "cert.pem")
            if os.path.exists(cert_file):
                try:
                    out = subprocess.check_output(["openssl", "x509", "-enddate", "-noout", "-in", cert_file], text=True, timeout=5)
                    expiry_str = out.strip().replace("notAfter=", "")
                    certs.append({"domain": domain, "expiry": expiry_str, "path": cert_file})
                except Exception:
                    certs.append({"domain": domain, "expiry": "unknown", "path": cert_file})
    return jsonify({"certs": certs})
