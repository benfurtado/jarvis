"""
Jarvis System Monitor Tool — CPU, RAM, Disk, Processes.
"""
import json
import logging

import psutil
from langchain_core.tools import tool

logger = logging.getLogger("Jarvis")


@tool
def system_monitor() -> str:
    """
    Returns current system resource usage: CPU, RAM, Disk, and top processes.
    """
    logger.info("System monitor tool called.")
    try:
        # CPU
        cpu_percent_total = psutil.cpu_percent(interval=1)
        cpu_percent_per_core = psutil.cpu_percent(interval=0, percpu=True)
        cpu_count = psutil.cpu_count()

        # RAM
        mem = psutil.virtual_memory()
        ram_info = {
            "total_gb": round(mem.total / (1024 ** 3), 2),
            "available_gb": round(mem.available / (1024 ** 3), 2),
            "used_gb": round(mem.used / (1024 ** 3), 2),
            "percent": mem.percent,
        }

        # Disk
        disk_info = []
        for partition in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                disk_info.append({
                    "device": partition.device,
                    "mountpoint": partition.mountpoint,
                    "total_gb": round(usage.total / (1024 ** 3), 2),
                    "used_gb": round(usage.used / (1024 ** 3), 2),
                    "free_gb": round(usage.free / (1024 ** 3), 2),
                    "percent": usage.percent,
                })
            except PermissionError:
                continue

        # Top processes
        processes = []
        for proc in sorted(psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]),
                           key=lambda p: p.info.get("cpu_percent", 0) or 0, reverse=True)[:10]:
            processes.append({
                "pid": proc.info["pid"],
                "name": proc.info["name"],
                "cpu_percent": round(proc.info.get("cpu_percent", 0) or 0, 1),
                "memory_percent": round(proc.info.get("memory_percent", 0) or 0, 1),
            })

        result = {
            "cpu": {
                "total_percent": cpu_percent_total,
                "per_core": cpu_percent_per_core,
                "core_count": cpu_count,
            },
            "ram": ram_info,
            "disk": disk_info,
            "top_processes": processes,
        }

        # Format for readable output
        output = f"System Status:\n"
        output += f"  CPU: {cpu_percent_total}% ({cpu_count} cores)\n"
        output += f"  RAM: {ram_info['used_gb']}/{ram_info['total_gb']} GB ({ram_info['percent']}%)\n"
        for d in disk_info:
            output += f"  Disk [{d['mountpoint']}]: {d['used_gb']}/{d['total_gb']} GB ({d['percent']}%)\n"
        output += f"\nTop Processes:\n"
        for p in processes:
            output += f"  PID {p['pid']}: {p['name']} (CPU: {p['cpu_percent']}%, MEM: {p['memory_percent']}%)\n"

        return output

    except Exception as e:
        logger.error(f"System monitor error: {e}")
        return f"Error getting system status: {str(e)}"
