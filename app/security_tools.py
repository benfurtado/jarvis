"""
Jarvis Security Tools — audit, geoip tracking, rate limiting helpers.
All tools self-register into TOOL_REGISTRY.
"""
import json
import logging
from datetime import datetime

from langchain_core.tools import tool

from app.tool_registry import register_tool
from app.config import Config

logger = logging.getLogger("Jarvis")


# ===========================
# 1. AUDIT LOG VIEWER
# ===========================

@tool
def audit_log_viewer(limit: int = 50, tool_filter: str = "",
                     status_filter: str = "") -> str:
    """
    View tool execution audit logs.
    Args:
        limit: Number of entries to show. Default: 50.
        tool_filter: Filter by tool name.
        status_filter: Filter by status (executed, approved, denied, error).
    """
    try:
        from app import db
        logs = db.get_audit_logs(limit=min(limit, 200))

        if tool_filter:
            logs = [l for l in logs if tool_filter.lower() in l["tool_name"].lower()]
        if status_filter:
            logs = [l for l in logs if l["status"] == status_filter]

        if not logs:
            return "No audit logs found matching criteria."

        output = f"Audit Logs ({len(logs)} entries):\n\n"
        output += f"{'TIMESTAMP':>20}  {'STATUS':>8}  {'RISK':>6}  TOOL\n"
        output += "-" * 65 + "\n"
        for log in logs[:50]:
            ts = log.get("timestamp", "?")[:19]
            output += f"  {ts}  {log['status']:>8}  {log['risk_level']:>6}  {log['tool_name']}\n"
            if log.get("result_summary"):
                summary = log["result_summary"][:80]
                output += f"    └─ {summary}\n"
        return output
    except Exception as e:
        return f"Audit log error: {e}"

register_tool("audit_log_viewer", audit_log_viewer, "LOW", "security")


# ===========================
# 2. GEOIP LOGIN TRACKING
# ===========================

@tool
def geoip_login_tracking(action: str = "list", ip: str = "") -> str:
    """
    Track and lookup GeoIP data for login attempts.
    Args:
        action: 'lookup' for single IP or 'list' for recent logins.
        ip: IP address to lookup (for 'lookup').
    """
    try:
        if action == "lookup" and ip:
            import subprocess
            r = subprocess.run(
                ["curl", "-s", f"http://ip-api.com/json/{ip}?fields=status,message,country,regionName,city,isp,org,as"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                data = json.loads(r.stdout)
                if data.get("status") == "success":
                    return (f"GeoIP for {ip}:\n"
                            f"  Country: {data.get('country', '?')}\n"
                            f"  Region: {data.get('regionName', '?')}\n"
                            f"  City: {data.get('city', '?')}\n"
                            f"  ISP: {data.get('isp', '?')}\n"
                            f"  Org: {data.get('org', '?')}\n"
                            f"  AS: {data.get('as', '?')}")
                return f"GeoIP lookup failed: {data.get('message', 'unknown')}"
            return "GeoIP service unreachable."

        elif action == "list":
            return "Login tracking: Check audit logs for login events."

        return "Invalid action. Use 'lookup' or 'list'."
    except Exception as e:
        return f"GeoIP error: {e}"

register_tool("geoip_login_tracking", geoip_login_tracking, "LOW", "security")


# ===========================
# 3. TOOL RISK INFO
# ===========================

@tool
def tool_risk_info(tool_name: str = "") -> str:
    """
    Show risk information for tools in the registry.
    Args:
        tool_name: Specific tool to check. If None, shows all.
    """
    from app.tool_registry import TOOL_REGISTRY, get_registry_info

    if tool_name:
        entry = TOOL_REGISTRY.get(tool_name)
        if entry:
            return (f"Tool: {tool_name}\n"
                    f"  Risk: {entry['risk_level']}\n"
                    f"  Category: {entry['category']}\n"
                    f"  Approval: {'REQUIRED' if entry['risk_level'] == 'HIGH' else 'Not required'}\n"
                    f"  Description: {entry['description']}")
        return f"Tool '{tool_name}' not found in registry."

    info = get_registry_info()
    output = f"Tool Registry ({len(info)} tools):\n\n"

    by_cat = {}
    for t in info:
        cat = t["category"]
        if cat not in by_cat:
            by_cat[cat] = []
        by_cat[cat].append(t)

    for cat, tools in sorted(by_cat.items()):
        output += f"  [{cat.upper()}] ({len(tools)} tools)\n"
        for t in tools:
            risk_icon = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}.get(t["risk_level"], "⚪")
            output += f"    {risk_icon} {t['name']} ({t['risk_level']})\n"
        output += "\n"
    return output

register_tool("tool_risk_info", tool_risk_info, "LOW", "security")
