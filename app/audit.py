"""
Jarvis Audit Logger — logs every tool call to SQLite via TOOL_REGISTRY risk lookup.
"""
import logging

from app import db
from app.tool_registry import get_risk_level

logger = logging.getLogger("Jarvis")


def log_tool_call(user_id: str, tool_name: str, args: dict,
                  result_summary: str, status: str) -> str:
    """
    Log a tool call to the audit table.

    Args:
        user_id: The authenticated user who triggered it.
        tool_name: Name of the tool.
        args: Arguments passed to the tool.
        result_summary: Brief summary of the result (truncated to 500 chars).
        status: 'executed', 'approved', 'denied', 'blocked', 'error'.

    Returns:
        The audit log entry ID.
    """
    risk_level = get_risk_level(tool_name)
    log_id = db.log_tool_call(
        user_id=user_id,
        tool_name=tool_name,
        risk_level=risk_level,
        args=args,
        result_summary=result_summary,
        status=status,
    )
    logger.info(
        f"AUDIT [{status.upper()}] tool={tool_name} risk={risk_level} user={user_id}"
    )
    return log_id


def get_audit_logs(limit: int = 50, offset: int = 0) -> list:
    """Retrieve paginated audit logs."""
    return db.get_audit_logs(limit=limit, offset=offset)
