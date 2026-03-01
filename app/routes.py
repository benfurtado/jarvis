"""
Jarvis Routes — all API endpoints, health check, registry API.
"""
import os
import json
import logging

from flask import Blueprint, request, jsonify, render_template, send_from_directory
from flask_jwt_extended import jwt_required, get_jwt_identity

from app import db, limiter
from app.agent import build_agent, process_chat
from app.permissions import process_approval
from app.audit import log_tool_call, get_audit_logs
from app.session_manager import get_cwd, set_cwd, handle_cd_command
from app.services import list_services

logger = logging.getLogger("Jarvis")
main_bp = Blueprint("main", __name__)

# Build the LangGraph agent (singleton)
_agent_graph = None


def _get_agent():
    global _agent_graph
    if _agent_graph is None:
        _agent_graph = build_agent()
    return _agent_graph


# ====================
# Frontend
# ====================

@main_bp.route("/")
def index():
    return render_template("index.html")


# ====================
# Health Check
# ====================

@main_bp.route("/health")
def health():
    """Health check endpoint — no auth required."""
    import psutil
    from app.tool_registry import TOOL_REGISTRY
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return jsonify({
            "status": "healthy",
            "tools_registered": len(TOOL_REGISTRY),
            "cpu_percent": cpu,
            "ram_percent": mem.percent,
            "disk_percent": disk.percent,
            "db": "connected" if db.conn else "disconnected",
        })
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500


# ====================
# Tool Registry API
# ====================

@main_bp.route("/api/tools/registry")
@jwt_required()
def tool_registry():
    from app.tool_registry import get_registry_info
    return jsonify({"tools": get_registry_info()})


@main_bp.route("/api/tools/categories")
@jwt_required()
def tool_categories():
    from app.tool_registry import TOOL_REGISTRY
    cats = {}
    for name, entry in TOOL_REGISTRY.items():
        cat = entry["category"]
        if cat not in cats:
            cats[cat] = []
        cats[cat].append({"name": name, "risk_level": entry["risk_level"]})
    return jsonify({"categories": cats})


# ====================
# Chat API
# ====================

@main_bp.route("/api/chat", methods=["POST"])
@jwt_required()
@limiter.limit("30 per minute")
def chat():
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    user_message = data.get("message")
    thread_id = data.get("thread_id", "default_thread")
    frontend_cwd = data.get("cwd")

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    # Update session cwd if frontend sent one
    if frontend_cwd:
        set_cwd(thread_id, frontend_cwd)

    # Handle direct cd commands before sending to LLM
    cd_result = handle_cd_command(thread_id, user_message)
    if cd_result is not None:
        if cd_result.startswith("ERROR:"):
            return jsonify({"response": cd_result, "cwd": get_cwd(thread_id)})
        return jsonify({
            "response": f"Changed working directory to: {cd_result}",
            "cwd": cd_result,
        })

    cwd = get_cwd(thread_id)

    graph = _get_agent()
    result = process_chat(graph, user_message, thread_id, user_id, cwd=cwd)
    return jsonify(result)


# ====================
# Session CWD
# ====================

@main_bp.route("/api/session/cwd", methods=["GET"])
@jwt_required()
def get_session_cwd():
    thread_id = request.args.get("thread_id", "default_thread")
    return jsonify({"cwd": get_cwd(thread_id)})


@main_bp.route("/api/session/cwd", methods=["POST"])
@jwt_required()
def set_session_cwd():
    data = request.get_json(silent=True) or {}
    thread_id = data.get("thread_id", "default_thread")
    new_cwd = data.get("cwd")
    if not new_cwd:
        return jsonify({"error": "cwd required"}), 400
    result = set_cwd(thread_id, new_cwd)
    if result.startswith("ERROR:"):
        return jsonify({"error": result}), 400
    return jsonify({"cwd": result})


# ====================
# Services
# ====================

@main_bp.route("/api/services", methods=["GET"])
@jwt_required()
def get_services():
    services = list_services()
    return jsonify({"services": services})


# ====================
# Approvals
# ====================

@main_bp.route("/api/approvals/pending", methods=["GET"])
@jwt_required()
def get_pending_approvals():
    approvals = db.get_pending_approvals()
    return jsonify({"approvals": approvals})


@main_bp.route("/api/approvals/<approval_id>/approve", methods=["POST"])
@jwt_required()
def approve_tool(approval_id):
    user_id = get_jwt_identity()
    result = process_approval(approval_id, "approved")
    if "error" in result:
        return jsonify(result), 400
    log_tool_call(user_id=user_id, tool_name=result.get("tool", "unknown"),
                  args=result.get("args", {}), result_summary="Approved by user", status="approved")
    return jsonify({"status": "approved", **result})


@main_bp.route("/api/approvals/<approval_id>/deny", methods=["POST"])
@jwt_required()
def deny_tool(approval_id):
    user_id = get_jwt_identity()
    result = process_approval(approval_id, "denied")
    if "error" in result:
        return jsonify(result), 400
    log_tool_call(user_id=user_id, tool_name=result.get("tool", "unknown"),
                  args=result.get("args", {}), result_summary="Denied by user", status="denied")
    return jsonify({"status": "denied", **result})


# ====================
# Audit Logs
# ====================

@main_bp.route("/api/audit/logs", methods=["GET"])
@jwt_required()
def audit_logs():
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)
    logs = get_audit_logs(limit=min(limit, 200), offset=offset)
    return jsonify({"logs": logs, "limit": limit, "offset": offset})


# ====================
# Settings API
# ====================

@main_bp.route("/api/settings", methods=["GET"])
@jwt_required()
def get_settings():
    """Retrieve all global settings."""
    settings = db.get_all_config()
    return jsonify({"settings": settings})


@main_bp.route("/api/settings", methods=["POST"])
@jwt_required()
def update_settings():
    """Update global settings."""
    data = request.get_json(silent=True) or {}

    gmail_creds = data.get("gmail_credentials_json")
    if isinstance(gmail_creds, str) and gmail_creds.strip():
        project_dir = os.path.dirname(os.path.dirname(__file__))
        new_dir = os.path.join(project_dir, "credentials", "gmail")
        old_dir = os.path.join(project_dir, "gmail_data")
        data_dir = new_dir if (os.path.exists(os.path.join(new_dir, "credentials.json")) or os.path.exists(os.path.join(new_dir, "token.json"))) else old_dir
        if not (os.path.exists(os.path.join(old_dir, "credentials.json")) or os.path.exists(os.path.join(old_dir, "token.json"))):
            data_dir = new_dir
        os.makedirs(data_dir, exist_ok=True)
        creds_path = os.path.join(data_dir, "credentials.json")
        try:
            parsed = json.loads(gmail_creds)
            with open(creds_path, "w") as f:
                json.dump(parsed, f)
        except Exception:
            return jsonify({"error": "Invalid Gmail OAuth credentials JSON"}), 400

        if data.get("gmail_reset_token") is True:
            token_path = os.path.join(data_dir, "token.json")
            try:
                if os.path.exists(token_path):
                    os.remove(token_path)
            except OSError:
                pass

    if "gmail_reset_token" in data:
        data.pop("gmail_reset_token", None)

    for key, value in data.items():
        db.set_config(key, value)
    return jsonify({"status": "success", "updated": list(data.keys())})


# ====================
# System Monitor
# ====================

@main_bp.route("/api/system/status", methods=["GET"])
@jwt_required()
def system_status():
    try:
        from app.system_tools import system_snapshot as _snap
        result = _snap.invoke({})
        return jsonify({"status": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ====================
# File Manager
# ====================

@main_bp.route("/api/files/list", methods=["GET"])
@jwt_required()
def files_list():
    path = request.args.get("path", "/root/projects")
    from app.file_tools import browse_directory as _browse
    result = _browse.invoke({"path": path})
    return jsonify({"result": result})


@main_bp.route("/api/files/upload", methods=["POST"])
@jwt_required()
def files_upload():
    data = request.get_json(silent=True) or {}
    path = data.get("path")
    content_b64 = data.get("content_b64")
    if not path or not content_b64:
        return jsonify({"error": "path and content_b64 required"}), 400
    from app.file_tools import upload_file as _upload
    result = _upload.invoke({"path": path, "content_b64": content_b64})
    return jsonify({"result": result})


@main_bp.route("/api/files/download", methods=["GET"])
@jwt_required()
def files_download():
    path = request.args.get("path")
    if not path:
        return jsonify({"error": "path parameter required"}), 400
    from app.file_tools import download_file as _download
    result = _download.invoke({"path": path})
    return jsonify({"result": result})


# ====================
# Task Scheduler
# ====================

@main_bp.route("/api/scheduler/tasks", methods=["GET"])
@jwt_required()
def scheduler_list():
    tasks = db.get_scheduled_tasks(active_only=True)
    return jsonify({"tasks": tasks})


@main_bp.route("/api/scheduler/tasks", methods=["POST"])
@jwt_required()
def scheduler_create():
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    command = data.get("command")
    cron_expr = data.get("cron_expression")
    if not command or not cron_expr:
        return jsonify({"error": "command and cron_expression required"}), 400
    task_id = db.create_scheduled_task(user_id, command, cron_expr)
    log_tool_call(user_id=user_id, tool_name="schedule_task",
                  args={"command": command, "cron_expression": cron_expr},
                  result_summary=f"Task created: {task_id}", status="executed")
    return jsonify({"task_id": task_id, "status": "created"})


@main_bp.route("/api/scheduler/tasks/<task_id>", methods=["DELETE"])
@jwt_required()
def scheduler_cancel(task_id):
    user_id = get_jwt_identity()
    db.deactivate_scheduled_task(task_id)
    log_tool_call(user_id=user_id, tool_name="cancel_scheduled_task",
                  args={"task_id": task_id}, result_summary=f"Task cancelled: {task_id}",
                  status="executed")
    return jsonify({"status": "cancelled", "task_id": task_id})


# ====================
# Tool Self-Test
# ====================

@main_bp.route("/api/tools/selftest", methods=["POST"])
@jwt_required()
def tool_selftest():
    """Run a quick self-test on LOW risk tools."""
    from app.tool_registry import TOOL_REGISTRY
    results = {}
    test_tools = ["system_snapshot", "get_datetime", "list_processes",
                  "browse_directory", "list_active_services"]
    for name in test_tools:
        entry = TOOL_REGISTRY.get(name)
        if entry:
            try:
                output = entry["function"].invoke({})
                results[name] = {"status": "OK", "output_length": len(str(output))}
            except Exception as e:
                results[name] = {"status": "ERROR", "error": str(e)}
        else:
            results[name] = {"status": "NOT_FOUND"}
    return jsonify({"selftest": results})


# ====================
# Downloads
# ====================

@main_bp.route("/download/<path:filename>")
@jwt_required()
def serve_download(filename):
    try:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        directory = os.path.join(app_dir, "temp")
        return send_from_directory(directory, filename, as_attachment=True)
    except Exception as e:
        logger.error(f"Download serve error: {e}")
        return str(e), 404
