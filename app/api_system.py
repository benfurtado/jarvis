"""
Jarvis System API — processes, network interfaces, connections, GPU, speedtest.
"""
import os
import json
import subprocess
import logging
import psutil
import time

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from app.utils_os import is_windows, get_platform_info, run_command

logger = logging.getLogger("Jarvis")
system_bp = Blueprint("system_api", __name__)

# ——— Resource History & Process Cache ———
_resource_history = []
_process_cache = []
_HISTORY_MAX = 360  # 30 min at 5s intervals


def _record_resources():
    """Snapshot CPU/RAM/Disk/Net and Top Processes."""
    global _process_cache
    net = psutil.net_io_counters()
    
    # 1. Update Resource History
    # Use interval=None to not block; psutil uses the delta since last call
    _resource_history.append({
        "ts": int(time.time()),
        "cpu": psutil.cpu_percent(interval=None),
        "ram": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage("/").percent,
        "swap": psutil.swap_memory().percent if hasattr(psutil, "swap_memory") else 0,
        "net_sent": net.bytes_sent,
        "net_recv": net.bytes_recv,
    })
    if len(_resource_history) > _HISTORY_MAX:
        _resource_history.pop(0)

    # 2. Update Process Cache
    # We iterate processes and get info. For CPU to be non-zero, it needs a delta.
    new_procs = []
    for p in psutil.process_iter(["pid", "name", "username", "cpu_percent", "memory_percent", "status"]):
        try:
            info = p.info
            new_procs.append({
                "pid": info["pid"],
                "name": info["name"] or "?",
                "user": info["username"] or "?",
                "cpu": round(info["cpu_percent"] or 0, 1),
                "ram": round(info["memory_percent"] or 0, 1),
                "status": info["status"],
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    _process_cache = sorted(new_procs, key=lambda x: x["cpu"], reverse=True)


# ——— Processes ———
@system_bp.route("/api/processes", methods=["GET"])
@jwt_required()
def get_processes():
    """Return top cached processes sorted by CPU or RAM."""
    sort_by = request.args.get("sort", "cpu")
    limit = int(request.args.get("limit", 50))
    search = request.args.get("search", "").lower()

    # Use cache if available, otherwise trigger one-time scan (might be 0s initially)
    procs = _process_cache if _process_cache else []
    if not procs: _record_resources() # Fallback for fresh boot
    
    filtered = procs
    if search:
        filtered = [p for p in procs if search in p["name"].lower() or search in str(p["pid"])]

    key = "cpu" if sort_by == "cpu" else "ram" if sort_by == "ram" else "pid"
    filtered.sort(key=lambda x: x.get(key, 0), reverse=(key != "pid"))
    
    return jsonify({"processes": filtered[:limit], "total": len(filtered), "cached": True})


@system_bp.route("/api/processes/<int:pid>/kill", methods=["POST"])
@jwt_required()
def kill_process(pid):
    """Kill a process by PID."""
    try:
        p = psutil.Process(pid)
        p.terminate()
        return jsonify({"status": "terminated", "pid": pid})
    except psutil.NoSuchProcess:
        return jsonify({"error": "Process not found"}), 404
    except psutil.AccessDenied:
        return jsonify({"error": "Access denied"}), 403


# ——— Network Interfaces ———
@system_bp.route("/api/network/interfaces", methods=["GET"])
@jwt_required()
def network_interfaces():
    """List all network interfaces with IPs and stats."""
    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    io = psutil.net_io_counters(pernic=True)
    result = []
    for name, addr_list in addrs.items():
        iface = {"name": name, "ips": [], "mac": "", "up": False, "speed": 0, "bytes_sent": 0, "bytes_recv": 0}
        for a in addr_list:
            if a.family.name == "AF_INET":
                iface["ips"].append(a.address)
            elif a.family.name == "AF_INET6":
                iface["ips"].append(a.address)
            elif a.family.name == "AF_PACKET":
                iface["mac"] = a.address
        if name in stats:
            iface["up"] = stats[name].isup
            iface["speed"] = stats[name].speed
        if name in io:
            iface["bytes_sent"] = io[name].bytes_sent
            iface["bytes_recv"] = io[name].bytes_recv
        result.append(iface)
    return jsonify({"interfaces": result})


# ——— Active Connections ———
@system_bp.route("/api/network/connections", methods=["GET"])
@jwt_required()
def network_connections():
    """List active network connections."""
    try:
        limit = int(request.args.get("limit", 100))
        conns = []
        # kind='inet' includes IPv4 and IPv6
        for c in psutil.net_connections(kind="inet"):
            try:
                # Local address
                laddr = f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else ""
                # Remote address
                raddr = f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else ""
                
                conns.append({
                    "proto": "TCP" if c.type == 1 else "UDP",
                    "laddr": laddr,
                    "raddr": raddr,
                    "status": c.status,
                    "pid": c.pid or "",
                })
            except Exception:
                continue
        return jsonify({"connections": conns[:limit], "total": len(conns)})
    except Exception as e:
        logger.error(f"Failed to get connections: {e}")
        return jsonify({"connections": [], "total": 0, "error": str(e)})


# ——— GPU Info ———
@system_bp.route("/api/gpu", methods=["GET"])
@jwt_required()
def gpu_info():
    """Get GPU info via nvidia-smi if available."""
    try:
        if is_windows():
            # Basic windows check - nvidia-smi usually in path if driver installed
            cmd = ["nvidia-smi", "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"]
        else:
            cmd = ["nvidia-smi", "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"]
        
        out = run_command(cmd, shell=False)
        gpus = []
        for line in out.strip().split("\n"):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                gpus.append({"name": parts[0], "temp": int(parts[1]), "util": int(parts[2]), "vram_used": int(parts[3]), "vram_total": int(parts[4])})
        return jsonify({"gpus": gpus})
    except FileNotFoundError:
        return jsonify({"gpus": [], "note": "nvidia-smi not found"})
    except Exception as e:
        return jsonify({"gpus": [], "error": str(e)})


# ——— Speed Test ———
@system_bp.route("/api/speedtest", methods=["POST"])
@jwt_required()
def speed_test():
    """Run a quick speed test using speedtest-cli."""
    try:
        out = subprocess.check_output(["speedtest-cli", "--json"], timeout=60, text=True)
        data = json.loads(out)
        return jsonify({
            "download_mbps": round(data.get("download", 0) / 1e6, 2),
            "upload_mbps": round(data.get("upload", 0) / 1e6, 2),
            "ping_ms": round(data.get("ping", 0), 1),
            "server": data.get("server", {}).get("sponsor", "Unknown"),
        })
    except FileNotFoundError:
        return jsonify({"error": "speedtest-cli not installed. Run: pip install speedtest-cli"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ——— Resource History ———
@system_bp.route("/api/system/history", methods=["GET"])
@jwt_required()
def resource_history():
    """Return resource usage history for charting."""
    _record_resources()
    points = int(request.args.get("points", 60))
    return jsonify({"history": _resource_history[-points:]})


# ——— System Overview (enhanced) ———
@system_bp.route("/api/system/overview", methods=["GET"])
@jwt_required()
def system_overview():
    """Full system overview with all key metrics."""
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()
    boot = psutil.boot_time()
    uptime_sec = int(time.time() - boot)
    
    # Enhanced Uptime Formatting
    days, rem = divmod(uptime_sec, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    uptime_str = f"{int(days)}d {int(hours)}h {int(mins)}m" if days > 0 else f"{int(hours)}h {int(mins)}m {int(secs)}s"

    # Public IP Retrieval (Quick check)
    public_ip = "Unknown"
    try:
        # Use a very fast timeout to avoid blocking the UI
        import urllib.request
        public_ip = urllib.request.urlopen('https://ident.me', timeout=1.0).read().decode('utf8')
    except: pass

    # Fallback for CPU reporting (avoid 0.0% on first call)
    cpu_now = psutil.cpu_percent(interval=None)
    if cpu_now == 0 and _resource_history:
        cpu_now = _resource_history[-1]["cpu"]

    info = get_platform_info()
    return jsonify({
        "cpu_percent": cpu_now,
        "cpu_count": psutil.cpu_count(),
        "ram_total_gb": round(vm.total / 1e9, 1),
        "ram_used_gb": round(vm.used / 1e9, 1),
        "ram_percent": vm.percent,
        "swap_percent": psutil.swap_memory().percent,
        "disk_total_gb": round(disk.total / 1e9, 1),
        "disk_used_gb": round(disk.used / 1e9, 1),
        "disk_percent": disk.percent,
        "net_sent_gb": round(net.bytes_sent / 1e9, 2),
        "net_recv_gb": round(net.bytes_recv / 1e9, 2),
        "uptime": uptime_str,
        "hostname": info["node"],
        "os": f"{info['os']} {info['release']}",
        "user": os.environ.get("USER", os.environ.get("USERNAME", "root")),
        "local_ip": info.get("ip", "Unknown"),
        "public_ip": public_ip,
        "load_avg": list(os.getloadavg()) if hasattr(os, "getloadavg") else [0,0,0],
    })
