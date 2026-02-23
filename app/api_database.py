"""
Jarvis Database API — Browse and query databases.
"""
import sqlite3
import os
import logging
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

logger = logging.getLogger("Jarvis")
database_bp = Blueprint("database_api", __name__)

DATABASE_PATH = os.environ.get("DATABASE_PATH", "jarvis.db")

def _get_conn():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@database_bp.route("/api/database/tables", methods=["GET"])
@jwt_required()
def list_tables():
    """List all tables in the primary SQLite database."""
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row["name"] for row in cursor.fetchall()]
        conn.close()
        return jsonify({"tables": tables})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@database_bp.route("/api/database/query", methods=["POST"])
@jwt_required()
def run_query():
    """Run a custom SQL query (SELECT only for safety)."""
    data = request.get_json()
    query = data.get("query", "").strip()
    
    if not query.lower().startswith("select"):
        return jsonify({"error": "Only SELECT queries are allowed for safety."}), 403
        
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        
        result = [dict(row) for row in rows]
        conn.close()
        return jsonify({"rows": result, "count": len(result)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@database_bp.route("/api/database/stats", methods=["GET"])
@jwt_required()
def db_stats():
    """Get database size and row counts."""
    try:
        size = os.path.getsize(DATABASE_PATH)
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row["name"] for row in cursor.fetchall()]
        
        counts = {}
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) as count FROM {table}")
            counts[table] = cursor.fetchone()["count"]
            
        conn.close()
        return jsonify({
            "size_kb": round(size / 1024, 2),
            "tables": tables,
            "counts": counts
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
