"""
Jarvis TOOL_REGISTRY — central registry for all tools.
Every tool module registers here. Agent loads tools from registry.
"""
import logging
from typing import Callable

logger = logging.getLogger("Jarvis")

# Central registry: { "tool_name": { "function": callable, "risk_level": str, "category": str } }
TOOL_REGISTRY = {}


def register_tool(name: str, func: Callable, risk_level: str = "LOW",
                  category: str = "system", description: str = ""):
    """Register a tool in the global registry."""
    TOOL_REGISTRY[name] = {
        "function": func,
        "risk_level": risk_level,
        "category": category,
        "description": description or (func.__doc__ or "").strip().split("\n")[0],
    }


def get_all_tools() -> list:
    """Return all tool functions for LangGraph binding."""
    return [entry["function"] for entry in TOOL_REGISTRY.values()]


def get_risk_level(tool_name: str) -> str:
    """Get risk level from registry. Defaults to HIGH for unknown tools."""
    entry = TOOL_REGISTRY.get(tool_name)
    return entry["risk_level"] if entry else "HIGH"


def requires_approval(tool_name: str) -> bool:
    """Check if a tool requires user approval before execution."""
    return get_risk_level(tool_name) == "HIGH"


def get_tools_by_category(category: str) -> list:
    """Get all tools in a specific category."""
    return [
        {"name": name, **{k: v for k, v in entry.items() if k != "function"}}
        for name, entry in TOOL_REGISTRY.items()
        if entry["category"] == category
    ]


def get_registry_info() -> list:
    """Get full registry info (without function refs) for API/display."""
    return [
        {
            "name": name,
            "risk_level": entry["risk_level"],
            "category": entry["category"],
            "description": entry["description"],
        }
        for name, entry in TOOL_REGISTRY.items()
    ]


def load_all_tool_modules():
    """Import all tool modules so they self-register."""
    from app import system_tools       # noqa: F401
    from app import file_tools         # noqa: F401
    from app import deploy_tools       # noqa: F401
    from app import automation_tools   # noqa: F401
    from app import security_tools     # noqa: F401
    from app import communication_tools# noqa: F401
    from app import wordpress_tools    # noqa: F401
    from app import email_tools        # noqa: F401
    from app import web_tools          # noqa: F401
    logger.info(f"TOOL_REGISTRY loaded: {len(TOOL_REGISTRY)} tools across "
                f"{len(set(e['category'] for e in TOOL_REGISTRY.values()))} categories")
    # Debug: print all registered tool names
    tool_names = sorted(TOOL_REGISTRY.keys())
    logger.info(f"Registered tools: {tool_names}")

