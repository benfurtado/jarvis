"""
Jarvis Tool Permission System — risk levels derived from TOOL_REGISTRY + approval workflow.
"""
import json
import logging

from app import db

logger = logging.getLogger("Jarvis")


def get_risk_level(tool_name: str) -> str:
    """Get risk level from TOOL_REGISTRY. Defaults to HIGH for unknown tools."""
    from app.tool_registry import get_risk_level as registry_risk
    return registry_risk(tool_name)


def requires_approval(tool_name: str) -> bool:
    """Check if a tool requires user approval before execution."""
    return get_risk_level(tool_name) == "HIGH"


def create_approval_request(user_id: str, tool_name: str, args: dict) -> dict:
    """
    Create a pending approval request for a HIGH-risk tool.
    Returns the approval info to send back to the frontend.
    """
    args_preview = _build_args_preview(tool_name, args)

    approval_id = db.create_approval(
        user_id=user_id,
        tool_name=tool_name,
        args=args,
        args_preview=args_preview,
    )

    logger.info(f"Approval request created: {approval_id} for tool '{tool_name}'")

    return {
        "status": "approval_required",
        "approval_id": approval_id,
        "tool": tool_name,
        "risk_level": "HIGH",
        "args_preview": args_preview,
        "message": f"Tool '{tool_name}' requires your approval before execution.",
    }


def process_approval(approval_id: str, action: str) -> dict:
    """
    Process an approval (approve/deny).
    Returns the approval record with updated status.
    """
    approval = db.get_approval(approval_id)
    if not approval:
        return {"error": "Approval not found"}

    if approval["status"] != "pending":
        return {"error": f"Approval already {approval['status']}"}

    if action not in ("approved", "denied"):
        return {"error": "Invalid action. Use 'approved' or 'denied'."}

    db.resolve_approval(approval_id, action)
    logger.info(f"Approval {approval_id} {action}")

    return {
        "approval_id": approval_id,
        "status": action,
        "tool": approval["tool_name"],
        "args": json.loads(approval["args_json"]) if approval["args_json"] else {},
    }


def _build_args_preview(tool_name: str, args: dict) -> str:
    """Build a human-readable preview of tool arguments."""
    previews = {
        "run_terminal_command": lambda a: f"Command: {a.get('command', 'N/A')}",
        "deploy_static_site": lambda a: f"Site: {a.get('name', '?')} port:{a.get('port', '?')}",
        "kill_process": lambda a: f"PID: {a.get('pid', a.get('name', 'N/A'))}",
        "delete_file": lambda a: f"Path: {a.get('path', 'N/A')} recursive:{a.get('recursive', False)}",
        "shutdown_system": lambda a: f"Delay: {a.get('delay_minutes', 0)} minutes",
        "restart_system": lambda a: f"Delay: {a.get('delay_minutes', 0)} minutes",
        "git_deploy": lambda a: f"Repo: {a.get('repo_url', 'N/A')} -> {a.get('directory', 'N/A')}",
        "docker_control": lambda a: f"Action: {a.get('action', 'N/A')} container:{a.get('container', 'N/A')}",
        "schedule_task": lambda a: f"Cmd: {a.get('command', 'N/A')} cron:{a.get('cron_expression', 'N/A')}",
        "ai_code_refactor": lambda a: f"File: {a.get('filepath', 'N/A')}",
    }
    fn = previews.get(tool_name)
    if fn:
        try:
            return fn(args)
        except Exception:
            pass
    return json.dumps(args)[:200]
