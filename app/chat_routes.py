"""
Jarvis Chat Routes — Multi-chat system (ChatGPT-style).
Blueprint: chat_bp
"""
import logging

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app import db, limiter
from app.agent import build_agent, process_chat
from app.session_manager import get_cwd, set_cwd, handle_cd_command

logger = logging.getLogger("Jarvis")
chat_bp = Blueprint("chats", __name__)

# Singleton agent graph
_agent_graph = None


def _get_agent():
    global _agent_graph
    if _agent_graph is None:
        _agent_graph = build_agent()
    return _agent_graph


# ====================
# Create Chat
# ====================

@chat_bp.route("/api/chats", methods=["POST"])
@jwt_required()
def create_chat():
    """Create a new chat session."""
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    title = data.get("title", "New Chat")
    chat = db.create_chat(user_id=user_id, title=title)
    logger.info(f"Chat created: {chat['id']} for user {user_id}")
    return jsonify({"chat": chat}), 201


# ====================
# List Chats
# ====================

@chat_bp.route("/api/chats", methods=["GET"])
@jwt_required()
def list_chats():
    """List all chats for the current user, newest first."""
    user_id = get_jwt_identity()
    chats = db.get_chats(user_id)
    return jsonify({"chats": chats})


# ====================
# Get Single Chat + Messages
# ====================

@chat_bp.route("/api/chats/<chat_id>", methods=["GET"])
@jwt_required()
def get_chat(chat_id):
    """Get a specific chat with its full message history."""
    chat = db.get_chat(chat_id)
    if not chat:
        return jsonify({"error": "Chat not found"}), 404
    messages = db.get_messages(chat_id)
    return jsonify({"chat": chat, "messages": messages})


# ====================
# Delete Chat
# ====================

@chat_bp.route("/api/chats/<chat_id>", methods=["DELETE"])
@jwt_required()
def delete_chat(chat_id):
    """Delete a chat and all its messages."""
    chat = db.get_chat(chat_id)
    if not chat:
        return jsonify({"error": "Chat not found"}), 404
    db.delete_chat(chat_id)
    logger.info(f"Chat deleted: {chat_id}")
    return jsonify({"status": "deleted", "chat_id": chat_id})


# ====================
# Send Message to Chat
# ====================

@chat_bp.route("/api/chats/<chat_id>/message", methods=["POST"])
@jwt_required()
@limiter.limit("30 per minute")
def send_message(chat_id):
    """Send a message to a specific chat and get AI response."""
    user_id = get_jwt_identity()
    chat = db.get_chat(chat_id)
    if not chat:
        return jsonify({"error": "Chat not found"}), 404

    data = request.get_json(silent=True) or {}
    user_message = data.get("message")
    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    thread_id = chat["thread_id"]
    frontend_cwd = data.get("cwd")

    # Update session CWD if frontend sent one
    if frontend_cwd:
        set_cwd(thread_id, frontend_cwd)

    # Handle direct cd commands
    cd_result = handle_cd_command(thread_id, user_message)
    if cd_result is not None:
        # Save user message
        db.save_message(chat_id, "user", user_message)
        if cd_result.startswith("ERROR:"):
            db.save_message(chat_id, "assistant", cd_result)
            return jsonify({"response": cd_result, "cwd": get_cwd(thread_id)})
        response_text = f"Changed working directory to: {cd_result}"
        db.save_message(chat_id, "assistant", response_text)
        # Persist CWD to chat record
        db.update_chat_cwd(chat_id, cd_result)
        return jsonify({"response": response_text, "cwd": cd_result})

    cwd = get_cwd(thread_id)

    # Save user message to DB
    db.save_message(chat_id, "user", user_message)

    # Auto-generate title from first message
    messages_count = len(db.get_messages(chat_id))
    if messages_count <= 1:  # This is the first message
        title = user_message[:60].strip()
        if len(user_message) > 60:
            title += "..."
        db.update_chat_title(chat_id, title)

    # Process through LangGraph agent
    graph = _get_agent()
    result = process_chat(graph, user_message, thread_id, user_id, cwd=cwd)

    # Save AI response to DB
    response_text = result.get("response", "")
    db.save_message(chat_id, "assistant", response_text)

    # Touch chat to update timestamp
    db.touch_chat(chat_id)

    return jsonify(result)
