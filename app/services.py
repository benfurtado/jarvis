"""
Jarvis Process/Service Tracker — manages deployed sites and background processes.
"""
import os
import signal
import socket
import logging
import subprocess

logger = logging.getLogger("Jarvis")

# Active services registry
# { "name": { "port": int, "pid": int, "directory": str, "process": Popen } }
active_services = {}


def get_public_ip() -> str:
    """Detect public IP of the server."""
    try:
        result = subprocess.run(
            ["curl", "-s", "ifconfig.me"],
            capture_output=True, text=True, timeout=5,
        )
        ip = result.stdout.strip()
        if ip:
            return ip
    except Exception:
        pass

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def is_port_open(port: int) -> bool:
    """Check if a port is open/listening."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False


def start_service(name: str, directory: str, port: int, command: str = None) -> dict:
    """
    Start a background HTTP service.
    Args:
        name: Service name (e.g., "coffeesite")
        directory: Directory to serve from
        port: Port to run on
        command: Custom command (default: python3 -m http.server <port>)
    Returns dict with status, url, pid.
    """
    if name in active_services:
        info = active_services[name]
        if info["process"].poll() is None:
            return {
                "status": "already_running",
                "name": name,
                "port": info["port"],
                "pid": info["pid"],
                "url": f"http://{get_public_ip()}:{info['port']}",
            }

    if is_port_open(port):
        return {"status": "error", "message": f"Port {port} is already in use."}

    if not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)

    if command is None:
        command = f"python3 -m http.server {port}"

    try:
        import shlex
        parts = shlex.split(command)
        process = subprocess.Popen(
            parts,
            cwd=directory,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Give it a moment to start
        import time
        time.sleep(1)

        if process.poll() is not None:
            stderr = process.stderr.read().decode() if process.stderr else ""
            return {"status": "error", "message": f"Process exited immediately. stderr: {stderr}"}

        public_ip = get_public_ip()
        active_services[name] = {
            "port": port,
            "pid": process.pid,
            "directory": directory,
            "process": process,
        }

        logger.info(f"Service '{name}' started on port {port} (PID: {process.pid})")

        return {
            "status": "running",
            "name": name,
            "port": port,
            "pid": process.pid,
            "directory": directory,
            "url": f"http://{public_ip}:{port}",
        }

    except Exception as e:
        logger.error(f"Failed to start service '{name}': {e}")
        return {"status": "error", "message": str(e)}


def stop_service(name: str) -> dict:
    """Stop a running service by name."""
    if name not in active_services:
        return {"status": "error", "message": f"Service '{name}' not found."}

    info = active_services[name]
    process = info["process"]

    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)

        del active_services[name]
        logger.info(f"Service '{name}' stopped (was PID: {info['pid']})")
        return {"status": "stopped", "name": name}

    except Exception as e:
        logger.error(f"Failed to stop service '{name}': {e}")
        return {"status": "error", "message": str(e)}


def list_services() -> list:
    """List all active services with status."""
    result = []
    for name, info in list(active_services.items()):
        running = info["process"].poll() is None
        if not running:
            del active_services[name]
            continue
        result.append({
            "name": name,
            "port": info["port"],
            "pid": info["pid"],
            "directory": info["directory"],
            "url": f"http://{get_public_ip()}:{info['port']}",
        })
    return result


def cleanup_all():
    """Stop all services (called on shutdown)."""
    for name in list(active_services.keys()):
        stop_service(name)
