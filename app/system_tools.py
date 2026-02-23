"""
Jarvis System Intelligence Tools — 13 tools for system awareness and control.
All tools self-register into TOOL_REGISTRY.
"""
import os
import platform
import subprocess
import socket
import base64
import logging
from datetime import datetime

import psutil
from langchain_core.tools import tool

from app.tool_registry import register_tool
from app.config import Config

logger = logging.getLogger("Jarvis")


# ===========================
# 1. SYSTEM SNAPSHOT
# ===========================

@tool
def system_snapshot() -> str:
    """
    Returns comprehensive system information: OS, hostname, uptime, CPU, RAM, disk, IPs, user.
    """
    try:
        uname = platform.uname()
        boot = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot

        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        # IPs
        local_ip = "unknown"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            pass

        public_ip = "unknown"
        try:
            r = subprocess.run(["curl", "-s", "ifconfig.me"], capture_output=True, text=True, timeout=5)
            public_ip = r.stdout.strip()
        except Exception:
            pass

        user = os.getenv("USER", os.getenv("USERNAME", "unknown"))

        # Enhanced Uptime
        days = uptime.days
        hours, rem = divmod(uptime.seconds, 3600)
        mins = rem // 60

        return (
            f"System Snapshot:\n"
            f"  OS: {uname.system} {uname.release}\n"
            f"  Hostname: {uname.node}\n"
            f"  Uptime: {days}d {hours}h {mins}m\n"
            f"  CPU: {cpu_percent:.1f}% ({cpu_count} cores)\n"
            f"  RAM: {mem.used / (1024**3):.1f}/{mem.total / (1024**3):.1f} GB ({mem.percent}%)\n"
            f"  Disk [/]: {disk.used / (1024**3):.1f}/{disk.total / (1024**3):.1f} GB ({disk.percent}%)\n"
            f"  Local IP: {local_ip}\n"
            f"  Public IP: {public_ip}\n"
            f"  User: {user}"
        )
    except Exception as e:
        return f"Error getting system snapshot: {e}"

register_tool("system_snapshot", system_snapshot, "LOW", "system")


# ===========================
# 2. GET DATETIME
# ===========================

@tool
def get_datetime() -> str:
    """Returns current date, time, and timezone."""
    now = datetime.now()
    import time
    tz = time.tzname[0]
    return f"Date: {now.strftime('%Y-%m-%d')}\nTime: {now.strftime('%H:%M:%S')}\nTimezone: {tz}"

register_tool("get_datetime", get_datetime, "LOW", "system")


# ===========================
# 3. TAKE SCREENSHOT
# ===========================

@tool
def take_screenshot() -> str:
    """
    Captures screenshot of primary monitor. Returns base64 preview and file path.
    """
    try:
        import mss
        temp_dir = Config.TEMP_DIR
        os.makedirs(temp_dir, exist_ok=True)
        filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        filepath = os.path.join(temp_dir, filename)

        with mss.mss() as sct:
            monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            img = sct.grab(monitor)
            from PIL import Image
            pil_img = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
            pil_img.save(filepath)

        with open(filepath, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()

        import json
        return json.dumps({"image_data": b64, "path": filepath, "size": os.path.getsize(filepath)})
    except ImportError:
        return "Screenshot requires 'mss' and 'Pillow' packages. Install with: pip install mss Pillow"
    except Exception as e:
        return f"Screenshot error: {e}"

register_tool("take_screenshot", take_screenshot, "MEDIUM", "system")


# ===========================
# 4. WEBCAM CAPTURE
# ===========================

@tool
def webcam_capture() -> str:
    """Captures a single frame from the webcam. Returns base64 image."""
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return "No webcam detected or webcam unavailable."
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return "Failed to capture webcam frame."

        temp_dir = Config.TEMP_DIR
        os.makedirs(temp_dir, exist_ok=True)
        filepath = os.path.join(temp_dir, f"webcam_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
        cv2.imwrite(filepath, frame)

        with open(filepath, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()

        import json
        return json.dumps({"image_data": b64, "path": filepath})
    except ImportError:
        return "Webcam capture requires 'opencv-python'. Install with: pip install opencv-python"
    except Exception as e:
        return f"Webcam error: {e}"

register_tool("webcam_capture", webcam_capture, "MEDIUM", "system")


# ===========================
# 5. LIST PROCESSES
# ===========================

@tool
def list_processes(sort_by: str = "cpu", limit: int = 20) -> str:
    """
    Lists running processes with PID, name, CPU%, and memory%.
    Args:
        sort_by: Sort by 'cpu' or 'memory'. Default: 'cpu'.
        limit: Max number of processes. Default: 20.
    """
    try:
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                info = p.info
                procs.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        key = "cpu_percent" if sort_by == "cpu" else "memory_percent"
        procs.sort(key=lambda x: x.get(key, 0) or 0, reverse=True)
        procs = procs[:limit]

        output = f"Top {len(procs)} Processes (by {sort_by}):\n\n"
        output += f"{'PID':>7}  {'CPU%':>6}  {'MEM%':>6}  NAME\n"
        output += "-" * 50 + "\n"
        for p in procs:
            output += f"{p['pid']:>7}  {(p['cpu_percent'] or 0):>5.1f}%  {(p['memory_percent'] or 0):>5.1f}%  {p['name']}\n"
        return output
    except Exception as e:
        return f"Error listing processes: {e}"

register_tool("list_processes", list_processes, "LOW", "system")


# ===========================
# 6. KILL PROCESS
# ===========================

@tool
def kill_process(pid: int = 0, name: str = "") -> str:
    """
    Stops a process by PID or name.
    Args:
        pid: Process ID to kill.
        name: Process name to kill (kills first match).
    """
    try:
        if pid:
            p = psutil.Process(pid)
            pname = p.name()
            p.terminate()
            try:
                p.wait(timeout=5)
            except psutil.TimeoutExpired:
                p.kill()
            return f"Process {pname} (PID {pid}) terminated."
        elif name:
            killed = []
            for p in psutil.process_iter(["pid", "name"]):
                if p.info["name"] and name.lower() in p.info["name"].lower():
                    try:
                        p.terminate()
                        killed.append(f"{p.info['name']} (PID {p.info['pid']})")
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            if killed:
                return f"Terminated: {', '.join(killed)}"
            return f"No process matching '{name}' found."
        else:
            return "Provide either pid or name."
    except psutil.NoSuchProcess:
        return f"Process {pid} not found."
    except psutil.AccessDenied:
        return f"Permission denied to kill process {pid or name}."
    except Exception as e:
        return f"Error killing process: {e}"

register_tool("kill_process", kill_process, "HIGH", "system")


# ===========================
# 7. VOLUME CONTROL
# ===========================

@tool
def system_volume_control(action: str = "get", level: int = 50) -> str:
    """
    Get or set system volume.
    Args:
        action: 'get' or 'set'.
        level: Volume level 0-100 (for 'set').
    """
    try:
        if action == "get":
            r = subprocess.run(["amixer", "get", "Master"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return f"Volume info:\n{r.stdout.strip()}"
            return "Could not read volume. amixer not available."
        elif action == "set":
            r = subprocess.run(["amixer", "set", "Master", f"{level}%"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return f"Volume set to {level}%"
            return f"Failed to set volume: {r.stderr}"
        return "Invalid action. Use 'get' or 'set'."
    except FileNotFoundError:
        return "Volume control not available (amixer not installed)."
    except Exception as e:
        return f"Volume control error: {e}"

register_tool("system_volume_control", system_volume_control, "MEDIUM", "system")


# ===========================
# 8. BRIGHTNESS CONTROL
# ===========================

@tool
def system_brightness_control(action: str = "get", level: int = 50) -> str:
    """
    Get or set system brightness.
    Args:
        action: 'get' or 'set'.
        level: Brightness 0-100 (for 'set').
    """
    try:
        bl_dir = "/sys/class/backlight"
        if not os.path.exists(bl_dir):
            return "Brightness control not available on this system (no backlight interface)."

        devices = os.listdir(bl_dir)
        if not devices:
            return "No backlight device found."

        device = os.path.join(bl_dir, devices[0])
        max_br = int(open(os.path.join(device, "max_brightness")).read().strip())
        cur_br = int(open(os.path.join(device, "brightness")).read().strip())

        if action == "get":
            pct = int((cur_br / max_br) * 100)
            return f"Brightness: {pct}% ({cur_br}/{max_br})"
        elif action == "set":
            new_br = int((level / 100) * max_br)
            with open(os.path.join(device, "brightness"), "w") as f:
                f.write(str(new_br))
            return f"Brightness set to {level}% ({new_br}/{max_br})"
        return "Invalid action. Use 'get' or 'set'."
    except Exception as e:
        return f"Brightness control error: {e}"

register_tool("system_brightness_control", system_brightness_control, "MEDIUM", "system")


# ===========================
# 9. LOCK SYSTEM
# ===========================

@tool
def lock_system() -> str:
    """Locks the system screen."""
    try:
        r = subprocess.run(["loginctl", "lock-session"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return "System locked."
        # Fallback
        r2 = subprocess.run(["xdg-screensaver", "lock"], capture_output=True, text=True, timeout=5)
        if r2.returncode == 0:
            return "System locked."
        return "Could not lock system. No display session found."
    except FileNotFoundError:
        return "Lock command not available on this system."
    except Exception as e:
        return f"Lock error: {e}"

register_tool("lock_system", lock_system, "HIGH", "system")


# ===========================
# 10. SHUTDOWN SYSTEM
# ===========================

@tool
def shutdown_system(delay_minutes: int = 0) -> str:
    """
    Shuts down the system. USE WITH EXTREME CAUTION.
    Args:
        delay_minutes: Delay in minutes (0 = immediate).
    """
    try:
        if delay_minutes > 0:
            r = subprocess.run(["shutdown", "-h", f"+{delay_minutes}"], capture_output=True, text=True, timeout=5)
        else:
            r = subprocess.run(["shutdown", "-h", "now"], capture_output=True, text=True, timeout=5)
        return f"Shutdown initiated. {r.stdout.strip()} {r.stderr.strip()}"
    except Exception as e:
        return f"Shutdown error: {e}"

register_tool("shutdown_system", shutdown_system, "HIGH", "system")


# ===========================
# 11. RESTART SYSTEM
# ===========================

@tool
def restart_system(delay_minutes: int = 0) -> str:
    """
    Restarts the system. USE WITH EXTREME CAUTION.
    Args:
        delay_minutes: Delay in minutes (0 = immediate).
    """
    try:
        if delay_minutes > 0:
            r = subprocess.run(["shutdown", "-r", f"+{delay_minutes}"], capture_output=True, text=True, timeout=5)
        else:
            r = subprocess.run(["shutdown", "-r", "now"], capture_output=True, text=True, timeout=5)
        return f"Restart initiated. {r.stdout.strip()} {r.stderr.strip()}"
    except Exception as e:
        return f"Restart error: {e}"

register_tool("restart_system", restart_system, "HIGH", "system")


# ===========================
# 12. GPU INFO
# ===========================

@tool
def get_gpu_info() -> str:
    """Returns GPU information using nvidia-smi or lspci."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
                           "--format=csv,noheader,nounits"],
                          capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            lines = r.stdout.strip().split("\n")
            output = "GPU Information:\n"
            for i, line in enumerate(lines):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 6:
                    output += (f"\n  GPU {i}: {parts[0]}\n"
                              f"    VRAM: {parts[2]} / {parts[1]} MB (free: {parts[3]} MB)\n"
                              f"    Utilization: {parts[4]}%\n"
                              f"    Temperature: {parts[5]}°C\n")
            return output
    except FileNotFoundError:
        pass

    try:
        r = subprocess.run(["lspci"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            gpus = [l for l in r.stdout.split("\n") if "VGA" in l or "3D" in l or "Display" in l]
            if gpus:
                return "GPU(s) detected:\n" + "\n".join(f"  {g.strip()}" for g in gpus)
    except FileNotFoundError:
        pass

    return "No GPU information available."

register_tool("get_gpu_info", get_gpu_info, "LOW", "system")


# ===========================
# 13. TEMPERATURE INFO
# ===========================

@tool
def get_temperature_info() -> str:
    """Returns CPU and system temperature readings."""
    try:
        temps = psutil.sensors_temperatures()
        if not temps:
            # Try lm-sensors fallback
            r = subprocess.run(["sensors"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return f"Temperature Readings:\n{r.stdout.strip()}"
            return "No temperature sensors available."

        output = "Temperature Readings:\n\n"
        for chip, entries in temps.items():
            output += f"  {chip}:\n"
            for entry in entries:
                label = entry.label or "Temp"
                output += f"    {label}: {entry.current}°C"
                if entry.high:
                    output += f" (high: {entry.high}°C)"
                if entry.critical:
                    output += f" (critical: {entry.critical}°C)"
                output += "\n"
        return output
    except Exception as e:
        return f"Temperature info error: {e}"

register_tool("get_temperature_info", get_temperature_info, "LOW", "system")
