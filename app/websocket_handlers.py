"""
Jarvis WebSocket Handlers — live logs, command streaming, approval events.
"""
import logging
import subprocess
import threading
import os
try:
    import pty
    import termios
    import fcntl
    HAS_PTY = True
except ImportError:
    HAS_PTY = False
import select
import shlex
import struct

from flask import request
from flask_socketio import SocketIO, emit, disconnect
from flask_jwt_extended import decode_token

logger = logging.getLogger("Jarvis")

# --- Terminal PTY State ---
_terminal_sessions = {}  # user_id -> { "fd": int, "pid": int }


def set_winsize(fd, row, col):
    """Set the window size for a terminal file descriptor."""
    if not HAS_PTY: return
    s = struct.pack("HHHH", row, col, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, s)


def register_handlers(socketio: SocketIO):
    """Register all WebSocket event handlers."""

    @socketio.on("connect")
    def handle_connect(auth=None):
        """Authenticate WebSocket connections via JWT token."""
        token = None
        if auth and isinstance(auth, dict):
            token = auth.get("token")

        if not token:
            logger.warning("WebSocket connection rejected: no token")
            disconnect()
            return

        try:
            decoded = decode_token(token)
            user_id = decoded.get("sub")
            logger.info(f"WebSocket connected: user={user_id}")
            emit("connected", {"status": "ok", "user_id": user_id})
        except Exception as e:
            logger.warning(f"WebSocket auth failed: {e}")
            disconnect()

    @socketio.on("disconnect")
    def handle_disconnect():
        logger.info("WebSocket client disconnected")

    @socketio.on("ping")
    def handle_ping(data=None):
        emit("pong", {"status": "alive"})

    @socketio.on("subscribe_logs")
    def handle_subscribe_logs(data=None):
        """Subscribe to live tool execution logs."""
        emit("log_subscribed", {"status": "ok"})

    @socketio.on("subscribe_approvals")
    def handle_subscribe_approvals(data=None):
        """Subscribe to approval request events."""
        emit("approval_subscribed", {"status": "ok"})

    @socketio.on("stream_command")
    def handle_stream_command(data):
        """
        Execute a command and stream output line-by-line via WebSocket.
        Data: { "command": str, "cwd": str }
        """
        command = data.get("command", "")
        cwd = data.get("cwd", "/root/projects")

        if not command:
            emit("command_output", {"type": "error", "data": "No command provided"})
            return

        def _stream():
            try:
                proc = subprocess.Popen(
                    command, shell=True, cwd=cwd,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1,
                )
                for line in iter(proc.stdout.readline, ""):
                    socketio.emit("command_output", {
                        "type": "stdout",
                        "data": line.rstrip("\n"),
                    })
                proc.wait()
                socketio.emit("command_output", {
                    "type": "exit",
                    "data": f"Process exited with code {proc.returncode}",
                    "exit_code": proc.returncode,
                })
            except Exception as e:
                socketio.emit("command_output", {
                    "type": "error",
                    "data": str(e),
                })

        thread = threading.Thread(target=_stream, daemon=True)
        thread.start()
        emit("command_output", {"type": "started", "data": f"Streaming: {command}"})

    @socketio.on("terminal_start")
    def handle_terminal_start(data=None):
        """Start a real PTY terminal session for the user."""
        try:
            sid = request.sid
            token = (request.args.get("token") or data.get("token")) if data else None
            user_id = "unknown"
            if token:
                try:
                    decoded = decode_token(token)
                    user_id = decoded.get("sub", "unknown")
                except: pass

            # We use sid as the key to support multiple tabs/users correctly
            if sid in _terminal_sessions:
                try:
                    sess = _terminal_sessions[sid]
                    if sess.get("type") == "pty":
                        os.close(sess["fd"])
                    else:
                        sess["proc"].terminate()
                except: pass

            if HAS_PTY:
                (child_pid, fd) = pty.fork()
                if child_pid == 0:
                    # Child process
                    os.environ["TERM"] = "xterm-256color"
                    shell = os.environ.get("SHELL", "/bin/bash")
                    os.execv(shell, [shell])
                else:
                    # Parent process
                    _terminal_sessions[sid] = {"fd": fd, "pid": child_pid, "type": "pty", "user_id": user_id}
                    set_winsize(fd, 24, 80)

                    def _read_pty():
                        while True:
                            try:
                                r, _, _ = select.select([fd], [], [], 0.1)
                                if fd in r:
                                    output = os.read(fd, 1024).decode("utf-8", "replace")
                                    if output:
                                        socketio.emit("terminal_output", {"data": output}, room=sid)
                                    else: break
                            except: break
                        if sid in _terminal_sessions: del _terminal_sessions[sid]
                    threading.Thread(target=_read_pty, daemon=True).start()
            else:
                # Windows / No-PTY Fallback
                shell = "cmd.exe" if os.name == "nt" else "/bin/sh"
                proc = subprocess.Popen(
                    shell, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=0, env=os.environ
                )
                _terminal_sessions[sid] = {"proc": proc, "type": "fallback", "user_id": user_id}
                
                def _read_fallback():
                    while True:
                        try:
                            line = proc.stdout.read(1)
                            if not line: break
                            socketio.emit("terminal_output", {"data": line}, room=sid)
                        except: break
                threading.Thread(target=_read_fallback, daemon=True).start()

            emit("terminal_ready", {"status": "ok"})
        except Exception as e:
            logger.error(f"Failed to start terminal: {e}")
            emit("terminal_error", {"error": str(e)})

    @socketio.on("terminal_input")
    def handle_terminal_input(data):
        """Send keystrokes to the PTY."""
        input_data = data.get("data", "")
        sid = request.sid
        if sid in _terminal_sessions:
            session = _terminal_sessions[sid]
            try:
                if session["type"] == "pty":
                    os.write(session["fd"], input_data.encode())
                else:
                    session["proc"].stdin.write(input_data)
                    session["proc"].stdin.flush()
            except: pass

    @socketio.on("terminal_resize")
    def handle_terminal_resize(data):
        """Handle terminal window resize."""
        rows = data.get("rows", 24)
        cols = data.get("cols", 80)
        sid = request.sid
        if sid in _terminal_sessions:
            session = _terminal_sessions[sid]
            try:
                if session["type"] == "pty":
                    set_winsize(session["fd"], rows, cols)
            except: pass

    # Background service: System Stats Broadcasting
    def _broadcast_stats():
        from app.api_system import _record_resources
        import time
        while True:
            try:
                # 1. Update the process cache and history
                _record_resources()
                
                # 2. Emit heart beat
                socketio.emit("system_heartbeat", {"ts": int(time.time()), "status": "ok"})
            except: pass
            time.sleep(5)

    threading.Thread(target=_broadcast_stats, daemon=True).start()


def emit_log(socketio: SocketIO, log_entry: dict):
    """Emit a log entry to all connected clients."""
    socketio.emit("tool_log", log_entry)


def emit_approval_request(socketio: SocketIO, approval_data: dict):
    """Emit an approval request to all connected clients."""
    socketio.emit("approval_required", approval_data)


def emit_command_output(socketio: SocketIO, data: dict):
    """Emit live command output."""
    socketio.emit("command_output", data)
