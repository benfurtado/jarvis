"""
Jarvis Authentication — JWT + bcrypt.
"""
import logging

import bcrypt
from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token,
    jwt_required,
    get_jwt_identity,
)

from app import db, limiter

logger = logging.getLogger("Jarvis")
auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["POST"])
@limiter.limit("5 per minute")
def login():
    """
    Username + Password login.
    Returns JWT immediately on success.
    """
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400

    user = db.get_user_by_username(username)
    if not user:
        return jsonify({"error": "Invalid credentials"}), 401

    if not bcrypt.checkpw(password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        logger.warning(f"Failed login attempt for user: {username}")
        return jsonify({"error": "Invalid credentials"}), 401

    if not user["is_active"]:
        return jsonify({"error": "Account disabled"}), 403

    # Issue full access token immediately
    access_token = create_access_token(identity=user["id"])
    logger.info(f"User '{username}' logged in.")
    return jsonify({
        "access_token": access_token,
        "username": username,
    }), 200


@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def get_current_user():
    """Return current authenticated user info."""
    user_id = get_jwt_identity()
    user = db.get_user_by_id(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify({
        "id": user["id"],
        "username": user["username"],
        "created_at": user["created_at"],
    }), 200
