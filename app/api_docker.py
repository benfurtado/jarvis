"""
Jarvis Docker API — containers, images, volumes, compose, logs.
"""
import subprocess
import json
import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

logger = logging.getLogger("Jarvis")
docker_bp = Blueprint("docker_api", __name__)


def _docker_available():
    try:
        subprocess.check_output(["docker", "info"], timeout=5, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


# ——— Containers ———
@docker_bp.route("/api/docker/containers", methods=["GET"])
@jwt_required()
def list_containers():
    if not _docker_available():
        return jsonify({"containers": [], "docker_available": False})
    try:
        out = subprocess.check_output(
            ["docker", "ps", "-a", "--format", '{"id":"{{.ID}}","name":"{{.Names}}","image":"{{.Image}}","status":"{{.Status}}","ports":"{{.Ports}}","state":"{{.State}}","size":"{{.Size}}"}'],
            text=True, timeout=10
        )
        containers = []
        for line in out.strip().split("\n"):
            if line.strip():
                try:
                    containers.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        # Get CPU/MEM stats
        try:
            stats_out = subprocess.check_output(
                ["docker", "stats", "--no-stream", "--format", '{"id":"{{.ID}}","cpu":"{{.CPUPerc}}","mem":"{{.MemUsage}}"}'],
                text=True, timeout=10
            )
            stats_map = {}
            for line in stats_out.strip().split("\n"):
                if line.strip():
                    try:
                        s = json.loads(line)
                        stats_map[s["id"]] = s
                    except Exception:
                        continue
            for c in containers:
                st = stats_map.get(c["id"], {})
                c["cpu"] = st.get("cpu", "0%")
                c["mem"] = st.get("mem", "0B / 0B")
        except Exception:
            pass
        return jsonify({"containers": containers, "docker_available": True})
    except Exception as e:
        return jsonify({"containers": [], "error": str(e), "docker_available": True})


@docker_bp.route("/api/docker/containers/<container_id>/action", methods=["POST"])
@jwt_required()
def container_action(container_id):
    action = request.json.get("action", "")
    if action not in ("start", "stop", "restart", "remove"):
        return jsonify({"error": "Invalid action"}), 400
    try:
        cmd = ["docker", "rm", "-f", container_id] if action == "remove" else ["docker", action, container_id]
        subprocess.check_output(cmd, text=True, timeout=30, stderr=subprocess.STDOUT)
        return jsonify({"status": "ok", "action": action, "container": container_id})
    except subprocess.CalledProcessError as e:
        return jsonify({"error": e.output.strip()}), 500


@docker_bp.route("/api/docker/containers/<container_id>/logs", methods=["GET"])
@jwt_required()
def container_logs(container_id):
    lines = request.args.get("lines", "100")
    try:
        out = subprocess.check_output(["docker", "logs", "--tail", lines, container_id], text=True, timeout=10, stderr=subprocess.STDOUT)
        return jsonify({"logs": out, "container": container_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ——— Images ———
@docker_bp.route("/api/docker/images", methods=["GET"])
@jwt_required()
def list_images():
    if not _docker_available():
        return jsonify({"images": [], "docker_available": False})
    try:
        out = subprocess.check_output(
            ["docker", "images", "--format", '{"id":"{{.ID}}","repo":"{{.Repository}}","tag":"{{.Tag}}","size":"{{.Size}}","created":"{{.CreatedSince}}"}'],
            text=True, timeout=10
        )
        images = []
        for line in out.strip().split("\n"):
            if line.strip():
                try:
                    images.append(json.loads(line))
                except Exception:
                    continue
        return jsonify({"images": images, "docker_available": True})
    except Exception as e:
        return jsonify({"images": [], "error": str(e)})


@docker_bp.route("/api/docker/images/<image_id>/remove", methods=["DELETE"])
@jwt_required()
def remove_image(image_id):
    try:
        subprocess.check_output(["docker", "rmi", "-f", image_id], text=True, timeout=30, stderr=subprocess.STDOUT)
        return jsonify({"status": "removed", "image": image_id})
    except subprocess.CalledProcessError as e:
        return jsonify({"error": e.output.strip()}), 500


# ——— Volumes ———
@docker_bp.route("/api/docker/volumes", methods=["GET"])
@jwt_required()
def list_volumes():
    if not _docker_available():
        return jsonify({"volumes": [], "docker_available": False})
    try:
        out = subprocess.check_output(
            ["docker", "volume", "ls", "--format", '{"name":"{{.Name}}","driver":"{{.Driver}}","mountpoint":"{{.Mountpoint}}"}'],
            text=True, timeout=10
        )
        volumes = []
        for line in out.strip().split("\n"):
            if line.strip():
                try:
                    volumes.append(json.loads(line))
                except Exception:
                    continue
        return jsonify({"volumes": volumes, "docker_available": True})
    except Exception as e:
        return jsonify({"volumes": [], "error": str(e)})


@docker_bp.route("/api/docker/volumes/<volume_name>", methods=["DELETE"])
@jwt_required()
def remove_volume(volume_name):
    try:
        subprocess.check_output(["docker", "volume", "rm", volume_name], text=True, timeout=10, stderr=subprocess.STDOUT)
        return jsonify({"status": "removed", "volume": volume_name})
    except subprocess.CalledProcessError as e:
        return jsonify({"error": e.output.strip()}), 500


# ——— Docker Compose ———
@docker_bp.route("/api/docker/compose", methods=["POST"])
@jwt_required()
def compose_action():
    data = request.json or {}
    directory = data.get("directory", ".")
    action = data.get("action", "up")
    if action not in ("up", "down", "restart", "ps"):
        return jsonify({"error": "Invalid action"}), 400
    try:
        cmd = ["docker", "compose"]
        if action == "up":
            cmd += ["up", "-d"]
        elif action == "ps":
            cmd += ["ps"]
        else:
            cmd += [action]
        out = subprocess.check_output(cmd, text=True, timeout=60, cwd=directory, stderr=subprocess.STDOUT)
        return jsonify({"status": "ok", "output": out})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
