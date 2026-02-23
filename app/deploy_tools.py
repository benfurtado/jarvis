"""
Jarvis Deployment & Server Control Tools — 10 tools.
All tools self-register into TOOL_REGISTRY.
"""
import os
import socket
import subprocess
import json
import logging
import time

from langchain_core.tools import tool

from app.tool_registry import register_tool
from app.config import Config
from app.services import start_service, stop_service, list_services, get_public_ip

logger = logging.getLogger("Jarvis")


# ===========================
# 1. DEPLOY STATIC SITE
# ===========================

@tool
def deploy_static_site(name: str, directory: str, port: int, html: str) -> str:
    """
    Deploy a static website. Creates directory, writes index.html, starts HTTP server, returns public URL.
    Args:
        name: Site name identifier (e.g., 'coffeesite').
        directory: Absolute path for the site files.
        port: Port number to serve on (e.g., 3433).
        html: Full HTML content for index.html.
    """
    logger.info(f"Deploying static site '{name}' at {directory} on port {port}")
    try:
        os.makedirs(directory, exist_ok=True)
        index_path = os.path.join(directory, "index.html")
        with open(index_path, "w") as f:
            f.write(html)

        result = start_service(name, directory, port)

        if result["status"] == "running":
            return (f"Site '{name}' deployed!\n"
                    f"URL: {result['url']}\n"
                    f"Directory: {directory}\n"
                    f"Port: {port}\nPID: {result['pid']}\n"
                    f"index.html: {len(html)} bytes")
        elif result["status"] == "already_running":
            return (f"Site '{name}' already running at {result['url']}\n"
                    f"Updated index.html ({len(html)} bytes)")
        else:
            return f"Deploy failed: {result.get('message', 'Unknown error')}"
    except Exception as e:
        return f"Deploy error: {e}"

register_tool("deploy_static_site", deploy_static_site, "HIGH", "deploy")


# ===========================
# 2. STOP SERVICE
# ===========================

@tool
def stop_deployed_service(name: str) -> str:
    """
    Stops a deployed service/site by name.
    Args:
        name: Service name to stop.
    """
    result = stop_service(name)
    if result["status"] == "stopped":
        return f"Service '{name}' stopped."
    return f"Error: {result.get('message', 'Unknown error')}"

register_tool("stop_deployed_service", stop_deployed_service, "HIGH", "deploy")


# ===========================
# 3. LIST ACTIVE SERVICES
# ===========================

@tool
def list_active_services() -> str:
    """Lists all currently running deployed services with URLs, PIDs, and directories."""
    services = list_services()
    if not services:
        return "No active services running."
    output = f"Active Services ({len(services)}):\n\n"
    for s in services:
        output += (f"  {s['name']}\n"
                   f"    URL: {s['url']}\n"
                   f"    PID: {s['pid']}\n"
                   f"    Dir: {s['directory']}\n\n")
    return output

register_tool("list_active_services", list_active_services, "LOW", "deploy")


# ===========================
# 4. OPEN FIREWALL PORT
# ===========================

@tool
def open_firewall_port(port: int, protocol: str = "tcp") -> str:
    """
    Opens a port in UFW firewall.
    Args:
        port: Port number to open.
        protocol: 'tcp' or 'udp'. Default: tcp.
    """
    try:
        r = subprocess.run(
            ["ufw", "allow", f"{port}/{protocol}"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            return f"Firewall port {port}/{protocol} opened.\n{r.stdout.strip()}"
        return f"Failed: {r.stderr.strip()}"
    except FileNotFoundError:
        return "UFW not installed."
    except Exception as e:
        return f"Firewall error: {e}"

register_tool("open_firewall_port", open_firewall_port, "HIGH", "deploy")


# ===========================
# 5. CLOSE FIREWALL PORT
# ===========================

@tool
def close_firewall_port(port: int, protocol: str = "tcp") -> str:
    """
    Closes a port in UFW firewall.
    Args:
        port: Port number to close.
        protocol: 'tcp' or 'udp'. Default: tcp.
    """
    try:
        r = subprocess.run(
            ["ufw", "delete", "allow", f"{port}/{protocol}"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            return f"Firewall port {port}/{protocol} closed.\n{r.stdout.strip()}"
        return f"Failed: {r.stderr.strip()}"
    except FileNotFoundError:
        return "UFW not installed."
    except Exception as e:
        return f"Firewall error: {e}"

register_tool("close_firewall_port", close_firewall_port, "HIGH", "deploy")


# ===========================
# 6. SCAN OPEN PORTS
# ===========================

@tool
def scan_open_ports(host: str = "127.0.0.1", port_range: str = "1-1024") -> str:
    """
    Scans for open ports on a host.
    Args:
        host: Host to scan. Default: localhost.
        port_range: Port range (e.g., '80-443' or '1-1024').
    """
    try:
        parts = port_range.split("-")
        start_port = int(parts[0])
        end_port = int(parts[1]) if len(parts) > 1 else start_port

        open_ports = []
        for port in range(start_port, min(end_port + 1, start_port + 500)):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.3)
                    if s.connect_ex((host, port)) == 0:
                        try:
                            service = socket.getservbyport(port)
                        except OSError:
                            service = "unknown"
                        open_ports.append(f"  {port:>5}  {service}")
            except Exception:
                continue

        if not open_ports:
            return f"No open ports found on {host} ({port_range})"
        return f"Open ports on {host}:\n\n  {'PORT':>5}  SERVICE\n" + "\n".join(open_ports)
    except Exception as e:
        return f"Port scan error: {e}"

register_tool("scan_open_ports", scan_open_ports, "MEDIUM", "deploy")


# ===========================
# 7. GIT DEPLOY
# ===========================

@tool
def git_deploy(repo_url: str, directory: str, branch: str = "main",
               install_cmd: str = "", start_cmd: str = "",
               port: int = 0, name: str = "") -> str:
    """
    Clone a git repo, install dependencies, and start the service.
    Args:
        repo_url: Git repository URL.
        directory: Target directory.
        branch: Branch to clone. Default: main.
        install_cmd: Dependency install command (e.g., 'npm install').
        start_cmd: Start command (e.g., 'npm start').
        port: Port the service runs on.
        name: Service name for tracking.
    """
    try:
        os.makedirs(os.path.dirname(directory) or ".", exist_ok=True)

        # Clone
        if os.path.isdir(directory) and os.path.isdir(os.path.join(directory, ".git")):
            r = subprocess.run(["git", "-C", directory, "pull", "origin", branch],
                              capture_output=True, text=True, timeout=120)
            clone_msg = f"Updated existing repo: {r.stdout.strip()}"
        else:
            r = subprocess.run(["git", "clone", "-b", branch, repo_url, directory],
                              capture_output=True, text=True, timeout=120)
            clone_msg = f"Cloned: {r.stdout.strip()}"

        if r.returncode != 0:
            return f"Git error: {r.stderr.strip()}"

        output = f"{clone_msg}\n"

        # Install
        if install_cmd:
            r = subprocess.run(install_cmd, shell=True, cwd=directory,
                              capture_output=True, text=True, timeout=300)
            output += f"Install: {'OK' if r.returncode == 0 else r.stderr[:200]}\n"

        # Start
        if start_cmd and port and name:
            import shlex
            proc = subprocess.Popen(shlex.split(start_cmd), cwd=directory,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(2)
            if proc.poll() is None:
                from app.services import active_services
                active_services[name] = {
                    "port": port, "pid": proc.pid,
                    "directory": directory, "process": proc,
                }
                ip = get_public_ip()
                output += f"Service '{name}' started (PID: {proc.pid})\nURL: http://{ip}:{port}"
            else:
                stderr = proc.stderr.read().decode()[:200]
                output += f"Service failed to start: {stderr}"
        elif start_cmd:
            output += "Provide port and name to auto-start the service."

        return output
    except Exception as e:
        return f"Git deploy error: {e}"

register_tool("git_deploy", git_deploy, "HIGH", "deploy")


# ===========================
# 8. DOCKER CONTROL
# ===========================

@tool
def docker_control(action: str, container: str = "", image: str = "",
                   ports: str = "", name: str = "") -> str:
    """
    Docker container management: list, start, stop, run, remove.
    Args:
        action: 'list', 'start', 'stop', 'run', 'remove', 'logs'.
        container: Container ID or name (for start/stop/remove/logs).
        image: Docker image (for run).
        ports: Port mapping (for run, e.g., '8080:80').
        name: Container name (for run).
    """
    try:
        if action == "list":
            r = subprocess.run(["docker", "ps", "-a", "--format",
                               "table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"],
                              capture_output=True, text=True, timeout=10)
        elif action == "start" and container:
            r = subprocess.run(["docker", "start", container],
                              capture_output=True, text=True, timeout=30)
        elif action == "stop" and container:
            r = subprocess.run(["docker", "stop", container],
                              capture_output=True, text=True, timeout=30)
        elif action == "remove" and container:
            r = subprocess.run(["docker", "rm", "-f", container],
                              capture_output=True, text=True, timeout=30)
        elif action == "logs" and container:
            r = subprocess.run(["docker", "logs", "--tail", "50", container],
                              capture_output=True, text=True, timeout=10)
        elif action == "run" and image:
            cmd = ["docker", "run", "-d"]
            if name:
                cmd += ["--name", name]
            if ports:
                cmd += ["-p", ports]
            cmd.append(image)
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        else:
            return "Invalid action or missing parameters."

        if r.returncode == 0:
            return r.stdout.strip() or f"Docker {action} completed."
        return f"Docker error: {r.stderr.strip()}"
    except FileNotFoundError:
        return "Docker not installed."
    except Exception as e:
        return f"Docker error: {e}"

register_tool("docker_control", docker_control, "HIGH", "deploy")


# ===========================
# 9. REVERSE PROXY GENERATOR
# ===========================

@tool
def reverse_proxy_generator(domain: str, upstream_port: int,
                            ssl: bool = True) -> str:
    """
    Generates Nginx reverse proxy config for a domain.
    Args:
        domain: Domain name (e.g., 'app.example.com').
        upstream_port: Backend port to proxy to.
        ssl: Include SSL config placeholders. Default: True.
    """
    config = f"""server {{
    listen 80;
    server_name {domain};
    {"return 301 https://$server_name$request_uri;" if ssl else ""}

    location / {{
        proxy_pass http://127.0.0.1:{upstream_port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }}
}}
"""
    if ssl:
        config += f"""
server {{
    listen 443 ssl http2;
    server_name {domain};

    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;

    location / {{
        proxy_pass http://127.0.0.1:{upstream_port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }}
}}
"""

    # Save to file
    conf_path = f"/etc/nginx/sites-available/{domain}"
    try:
        os.makedirs("/etc/nginx/sites-available", exist_ok=True)
        with open(conf_path, "w") as f:
            f.write(config)
        # Symlink
        link_path = f"/etc/nginx/sites-enabled/{domain}"
        if not os.path.exists(link_path):
            os.symlink(conf_path, link_path)
        return (f"Nginx config written to {conf_path}\n"
                f"Symlinked to {link_path}\n"
                f"Run: nginx -t && systemctl reload nginx\n"
                f"For SSL: certbot --nginx -d {domain}")
    except PermissionError:
        return f"Generated config (save manually to {conf_path}):\n\n{config}"
    except Exception as e:
        return f"Config generated but write failed: {e}\n\n{config}"

register_tool("reverse_proxy_generator", reverse_proxy_generator, "HIGH", "deploy")


# ===========================
# 10. SERVICE HEALTH CHECK
# ===========================

@tool
def service_health_check(url: str = "", port: int = 0,
                         host: str = "127.0.0.1") -> str:
    """
    Check if a service is healthy via HTTP request or port check.
    Args:
        url: Full URL to health check (e.g., 'http://localhost:3000/health').
        port: Port number to check connectivity.
        host: Host for port check. Default: 127.0.0.1.
    """
    results = []

    if url:
        try:
            import requests
            r = requests.get(url, timeout=5)
            results.append(f"HTTP {url}: {r.status_code} ({'OK' if r.ok else 'FAIL'})")
            if r.ok and len(r.text) < 500:
                results.append(f"  Response: {r.text[:200]}")
        except Exception as e:
            results.append(f"HTTP {url}: UNREACHABLE ({e})")

    if port:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(3)
                if s.connect_ex((host, port)) == 0:
                    results.append(f"Port {port} on {host}: OPEN")
                else:
                    results.append(f"Port {port} on {host}: CLOSED")
        except Exception as e:
            results.append(f"Port {port}: ERROR ({e})")

    return "\n".join(results) if results else "Provide url or port to check."

register_tool("service_health_check", service_health_check, "LOW", "deploy")
