"""
Jarvis File Manager Tools — list, download, upload, search files.
All operations are sandboxed to ALLOWED_DIRS from config.
"""
import os
import base64
import glob
import json
import logging
from datetime import datetime

from langchain_core.tools import tool

from app.config import Config

logger = logging.getLogger("Jarvis")

MAX_DOWNLOAD_SIZE = 10 * 1024 * 1024  # 10 MB


def _is_path_allowed(path: str) -> bool:
    """Check if a path falls within allowed directories."""
    real_path = os.path.realpath(path)
    for allowed in Config.ALLOWED_DIRS:
        if real_path.startswith(os.path.realpath(allowed)):
            return True
    return False


@tool
def list_directory(path: str) -> str:
    """
    Lists files and directories at the given path.
    Args:
        path: Absolute path to the directory to list.
    """
    logger.info(f"File manager: listing {path}")
    if not _is_path_allowed(path):
        return f"ACCESS DENIED: Path '{path}' is outside allowed directories."

    if not os.path.isdir(path):
        return f"Error: '{path}' is not a directory or does not exist."

    try:
        items = []
        for entry in sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower())):
            stat = entry.stat(follow_symlinks=False)
            items.append({
                "name": entry.name,
                "type": "directory" if entry.is_dir() else "file",
                "size": stat.st_size if entry.is_file() else None,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            })

        if not items:
            return f"Directory '{path}' is empty."

        output = f"Contents of {path} ({len(items)} items):\n\n"
        for item in items:
            icon = "📁" if item["type"] == "directory" else "📄"
            size_str = f" ({_format_size(item['size'])})" if item["size"] is not None else ""
            output += f"  {icon} {item['name']}{size_str} — {item['modified']}\n"
        return output

    except PermissionError:
        return f"Permission denied for '{path}'."
    except Exception as e:
        return f"Error listing directory: {str(e)}"


@tool
def download_file(path: str) -> str:
    """
    Returns a file's content as base64 for download.
    Limited to files under 10 MB within allowed directories.
    Args:
        path: Absolute path to the file.
    """
    logger.info(f"File manager: downloading {path}")
    if not _is_path_allowed(path):
        return f"ACCESS DENIED: Path '{path}' is outside allowed directories."

    if not os.path.isfile(path):
        return f"Error: '{path}' is not a file or does not exist."

    size = os.path.getsize(path)
    if size > MAX_DOWNLOAD_SIZE:
        return f"Error: File is too large ({_format_size(size)}). Maximum is {_format_size(MAX_DOWNLOAD_SIZE)}."

    try:
        with open(path, "rb") as f:
            content = f.read()
        return json.dumps({
            "status": "success",
            "filename": os.path.basename(path),
            "size": size,
            "content_b64": base64.b64encode(content).decode("utf-8"),
        })
    except Exception as e:
        return f"Error reading file: {str(e)}"


@tool
def upload_file(path: str, content_b64: str) -> str:
    """
    Writes a file from base64 content.
    Args:
        path: Absolute path where the file should be created.
        content_b64: Base64-encoded file content.
    """
    logger.info(f"File manager: uploading to {path}")
    if not _is_path_allowed(path):
        return f"ACCESS DENIED: Path '{path}' is outside allowed directories."

    try:
        content = base64.b64decode(content_b64)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        return f"SUCCESS: File written to {path} ({_format_size(len(content))})"
    except Exception as e:
        return f"Error writing file: {str(e)}"


@tool
def search_files(pattern: str, directory: str = "/root/projects") -> str:
    """
    Recursively searches for files matching a glob pattern.
    Args:
        pattern: Glob pattern (e.g., '*.py', '**/*.json').
        directory: Base directory to search in.
    """
    logger.info(f"File manager: searching '{pattern}' in {directory}")
    if not _is_path_allowed(directory):
        return f"ACCESS DENIED: Directory '{directory}' is outside allowed directories."

    try:
        search_path = os.path.join(directory, pattern)
        matches = glob.glob(search_path, recursive=True)
        matches = [m for m in matches if _is_path_allowed(m)]  # Double-check

        if not matches:
            return f"No files matching '{pattern}' found in {directory}."

        # Limit results
        total = len(matches)
        matches = matches[:50]

        output = f"Found {total} file(s) matching '{pattern}':\n\n"
        for m in matches:
            size = os.path.getsize(m) if os.path.isfile(m) else 0
            output += f"  {m} ({_format_size(size)})\n"

        if total > 50:
            output += f"\n  ... and {total - 50} more."
        return output

    except Exception as e:
        return f"Error searching files: {str(e)}"


def _format_size(size: int) -> str:
    """Format bytes to human-readable string."""
    if size is None:
        return "N/A"
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
