"""
Jarvis Enhanced Files API — tree, read, write, permissions, bulk, upload.
"""
import os
import stat
import shutil
import logging
import zipfile
import mimetypes

from flask import Blueprint, jsonify, request, send_file
from flask_jwt_extended import jwt_required

from app.utils_os import is_windows

logger = logging.getLogger("Jarvis")
files_bp = Blueprint("files_api", __name__)


def _file_info(path):
    try:
        st = os.stat(path)
        return {
            "name": os.path.basename(path),
            "path": path,
            "is_dir": os.path.isdir(path),
            "size": st.st_size,
            "modified": int(st.st_mtime),
            "permissions": stat.filemode(st.st_mode),
            "owner_uid": st.st_uid,
        }
    except Exception:
        return {"name": os.path.basename(path), "path": path, "is_dir": False, "size": 0, "error": "inaccessible"}


@files_bp.route("/api/files/tree", methods=["GET"])
@jwt_required()
def file_tree():
    """Get directory tree (1 level deep by default)."""
    path = request.args.get("path", "C:\\" if is_windows() else "/root")
    depth = int(request.args.get("depth", 1))
    if not os.path.exists(path):
        return jsonify({"error": "Path not found"}), 404
    if not os.path.isdir(path):
        return jsonify({"error": "Not a directory"}), 400

    def _build(p, d):
        children = []
        if d <= 0:
            return children
        try:
            entries = sorted(os.listdir(p))
        except PermissionError:
            return children
        dirs = [e for e in entries if os.path.isdir(os.path.join(p, e)) and not e.startswith(".")]
        files = [e for e in entries if not os.path.isdir(os.path.join(p, e)) and not e.startswith(".")]
        for name in dirs:
            fp = os.path.join(p, name)
            info = _file_info(fp)
            info["children"] = _build(fp, d - 1) if d > 1 else []
            info["has_children"] = True
            children.append(info)
        for name in files:
            fp = os.path.join(p, name)
            children.append(_file_info(fp))
        return children

    return jsonify({"path": path, "children": _build(path, depth)})


@files_bp.route("/api/files/read", methods=["GET"])
@jwt_required()
def read_file():
    path = request.args.get("path", "")
    if not path or not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404
    if os.path.isdir(path):
        return jsonify({"error": "Is a directory"}), 400
    size = os.path.getsize(path)
    if size > 2 * 1024 * 1024:
        return jsonify({"error": "File too large (>2MB)", "size": size}), 400
    mime = mimetypes.guess_type(path)[0] or "text/plain"
    is_text = mime.startswith("text") or mime in ("application/json", "application/xml", "application/javascript", "application/x-yaml")
    if is_text:
        try:
            with open(path, "r", errors="replace") as f:
                content = f.read()
            ext = os.path.splitext(path)[1].lstrip(".")
            return jsonify({"content": content, "path": path, "size": size, "mime": mime, "ext": ext})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        return jsonify({"binary": True, "path": path, "size": size, "mime": mime, "ext": os.path.splitext(path)[1]})


@files_bp.route("/api/files/write", methods=["POST"])
@jwt_required()
def write_file():
    data = request.json or {}
    path = data.get("path", "")
    content = data.get("content", "")
    if not path:
        return jsonify({"error": "Path required"}), 400
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return jsonify({"status": "saved", "path": path, "size": len(content)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@files_bp.route("/api/files/permissions", methods=["GET"])
@jwt_required()
def get_permissions():
    path = request.args.get("path", "")
    if not path or not os.path.exists(path):
        return jsonify({"error": "Not found"}), 404
    st = os.stat(path)
    return jsonify({
        "path": path,
        "permissions": stat.filemode(st.st_mode),
        "octal": oct(st.st_mode)[-3:],
        "uid": st.st_uid,
        "gid": st.st_gid,
    })


@files_bp.route("/api/files/permissions", methods=["POST"])
@jwt_required()
def set_permissions():
    data = request.json or {}
    path = data.get("path", "")
    mode = data.get("mode", "")
    if not path or not mode:
        return jsonify({"error": "Path and mode required"}), 400
    try:
        os.chmod(path, int(mode, 8))
        return jsonify({"status": "ok", "path": path, "mode": mode})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@files_bp.route("/api/files/bulk", methods=["POST"])
@jwt_required()
def bulk_operation():
    data = request.json or {}
    action = data.get("action", "")
    paths = data.get("paths", [])
    dest = data.get("destination", "")
    if action not in ("delete", "move", "zip"):
        return jsonify({"error": "Invalid action"}), 400
    results = []
    if action == "delete":
        for p in paths:
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p)
                else:
                    os.remove(p)
                results.append({"path": p, "status": "deleted"})
            except Exception as e:
                results.append({"path": p, "status": "error", "error": str(e)})
    elif action == "move":
        for p in paths:
            try:
                shutil.move(p, dest)
                results.append({"path": p, "status": "moved"})
            except Exception as e:
                results.append({"path": p, "status": "error", "error": str(e)})
    elif action == "zip":
        zip_path = dest or (os.path.join(os.environ.get("TEMP", "/tmp"), "bulk_download.zip") if is_windows() else "/tmp/bulk_download.zip")
        try:
            with zipfile.ZipFile(zip_path, "w") as zf:
                for p in paths:
                    if os.path.isdir(p):
                        for root, dirs, files in os.walk(p):
                            for f in files:
                                fp = os.path.join(root, f)
                                zf.write(fp, os.path.relpath(fp, os.path.dirname(p)))
                    else:
                        zf.write(p, os.path.basename(p))
            results.append({"zip": zip_path, "status": "created"})
        except Exception as e:
            results.append({"zip": zip_path, "status": "error", "error": str(e)})
    return jsonify({"action": action, "results": results})


@files_bp.route("/api/files/upload", methods=["POST"])
@jwt_required()
def upload_file():
    dest_dir = request.form.get("path", os.environ.get("TEMP", "/tmp") if is_windows() else "/tmp")
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f = request.files["file"]
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f.filename)
    f.save(dest)
    return jsonify({"status": "uploaded", "path": dest, "size": os.path.getsize(dest)})


@files_bp.route("/api/files/download", methods=["GET"])
@jwt_required()
def download_file():
    path = request.args.get("path", "")
    if not path or not os.path.exists(path):
        return jsonify({"error": "Not found"}), 404
    return send_file(path, as_attachment=True)
