"""
Jarvis Filesystem Tools — 12 tools for full file management.
All tools self-register into TOOL_REGISTRY.
"""
import os
import shutil
import hashlib
import base64
import zipfile
import json
import fnmatch
import logging
from datetime import datetime
from collections import defaultdict

import psutil
from langchain_core.tools import tool

from app.tool_registry import register_tool
from app.config import Config

logger = logging.getLogger("Jarvis")


def _resolve_path(path: str) -> str:
    """Resolve relative paths against DEFAULT_CWD."""
    if not os.path.isabs(path):
        path = os.path.join(Config.DEFAULT_CWD, path)
    return os.path.normpath(path)


# ===========================
# 1. BROWSE DIRECTORY
# ===========================

@tool
def browse_directory(path: str = ".", show_hidden: bool = False) -> str:
    """
    Lists directory contents with metadata (type, size, modified date).
    Args:
        path: Directory path to browse. Use '.' for current directory.
        show_hidden: Include hidden files (starting with .).
    """
    path = _resolve_path(path)
    if not os.path.isdir(path):
        return f"Not a directory: {path}"

    try:
        entries = []
        for item in sorted(os.listdir(path)):
            if not show_hidden and item.startswith("."):
                continue
            full = os.path.join(path, item)
            try:
                stat = os.stat(full)
                is_dir = os.path.isdir(full)
                size = stat.st_size if not is_dir else sum(
                    os.path.getsize(os.path.join(dp, f))
                    for dp, _, fs in os.walk(full) for f in fs
                ) if is_dir else 0
                mod = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                typ = "DIR " if is_dir else "FILE"
                size_str = _human_size(size)
                entries.append(f"  {typ}  {size_str:>8}  {mod}  {item}")
            except (PermissionError, OSError):
                entries.append(f"  ????  {'?':>8}  {'?':>16}  {item}")

        header = f"Directory: {path} ({len(entries)} items)\n\n"
        header += f"  {'TYPE':4}  {'SIZE':>8}  {'MODIFIED':>16}  NAME\n"
        header += "  " + "-" * 60 + "\n"
        return header + "\n".join(entries)
    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"Error browsing {path}: {e}"

register_tool("browse_directory", browse_directory, "LOW", "file")


# ===========================
# 2. SEARCH FILES
# ===========================

@tool
def search_files(directory: str = ".", pattern: str = "*", extension: str = "",
                 content: str = "", max_results: int = 50) -> str:
    """
    Search for files by name pattern, extension, or content.
    Args:
        directory: Root directory to search from.
        pattern: Glob pattern for filename (e.g., '*.py', 'config*').
        extension: File extension filter (e.g., 'py', 'txt').
        content: Search inside file contents for this string.
        max_results: Maximum number of results.
    """
    directory = _resolve_path(directory)
    if not os.path.isdir(directory):
        return f"Directory not found: {directory}"

    results = []
    count = 0

    try:
        for root, dirs, files in os.walk(directory):
            # Skip hidden dirs
            dirs[:] = [d for d in dirs if not d.startswith(".")]

            for fname in files:
                if count >= max_results:
                    break

                if extension and not fname.endswith(f".{extension}"):
                    continue
                if not fnmatch.fnmatch(fname, pattern):
                    continue

                full_path = os.path.join(root, fname)

                if content:
                    try:
                        with open(full_path, "r", errors="ignore") as f:
                            if content not in f.read():
                                continue
                    except (PermissionError, IsADirectoryError, OSError):
                        continue

                size = os.path.getsize(full_path)
                results.append(f"  {_human_size(size):>8}  {full_path}")
                count += 1

            if count >= max_results:
                break

        if not results:
            return f"No files matching criteria in {directory}"
        return f"Found {len(results)} files:\n\n" + "\n".join(results)
    except Exception as e:
        return f"Search error: {e}"

register_tool("search_files", search_files, "LOW", "file")


# ===========================
# 3. READ FILE
# ===========================

@tool
def read_file(path: str, start_line: int = 0, end_line: int = 0,
              encoding: str = "utf-8") -> str:
    """
    Reads file contents. Supports line range for large files.
    Args:
        path: File path.
        start_line: First line to read (0-indexed).
        end_line: Last line to read (inclusive). None = read all.
        encoding: File encoding. Default: utf-8.
    """
    path = _resolve_path(path)
    if not os.path.isfile(path):
        return f"File not found: {path}"

    try:
        size = os.path.getsize(path)
        if size > 5 * 1024 * 1024:  # 5MB
            return f"File too large ({_human_size(size)}). Use start_line/end_line for partial read."

        with open(path, "r", encoding=encoding, errors="replace") as f:
            lines = f.readlines()

        if end_line <= 0:
            end_line = len(lines)

        selected = lines[start_line:end_line]
        content = "".join(selected)

        return (f"File: {path} ({len(lines)} lines, {_human_size(size)})\n"
                f"Showing lines {start_line}-{min(end_line, len(lines))}:\n\n{content}")
    except Exception as e:
        return f"Error reading {path}: {e}"

register_tool("read_file", read_file, "LOW", "file")


# ===========================
# 4. WRITE FILE
# ===========================

@tool
def write_file(path: str, content: str, append: bool = False) -> str:
    """
    Writes content to a file. Auto-creates parent directories.
    Args:
        path: File path.
        content: Content to write.
        append: If True, append instead of overwrite.
    """
    path = _resolve_path(path)
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        mode = "a" if append else "w"
        with open(path, mode) as f:
            f.write(content)
        return f"Written to {path} ({'appended' if append else 'created'}, {len(content)} bytes)"
    except Exception as e:
        return f"Error writing {path}: {e}"

register_tool("write_file", write_file, "MEDIUM", "file")


# ===========================
# 5. DELETE FILE
# ===========================

@tool
def delete_file(path: str, recursive: bool = False) -> str:
    """
    Deletes a file or directory.
    Args:
        path: Path to delete.
        recursive: If True and path is a directory, delete recursively.
    """
    path = _resolve_path(path)
    if not os.path.exists(path):
        return f"Path not found: {path}"

    try:
        if os.path.isfile(path):
            os.remove(path)
            return f"Deleted file: {path}"
        elif os.path.isdir(path):
            if recursive:
                shutil.rmtree(path)
                return f"Deleted directory (recursive): {path}"
            else:
                os.rmdir(path)
                return f"Deleted empty directory: {path}"
    except Exception as e:
        return f"Delete error: {e}"

register_tool("delete_file", delete_file, "HIGH", "file")


# ===========================
# 6. MOVE FILE
# ===========================

@tool
def move_file(source: str, destination: str) -> str:
    """
    Moves/renames a file or directory.
    Args:
        source: Source path.
        destination: Destination path.
    """
    source = _resolve_path(source)
    destination = _resolve_path(destination)

    if not os.path.exists(source):
        return f"Source not found: {source}"

    try:
        os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
        shutil.move(source, destination)
        return f"Moved: {source} -> {destination}"
    except Exception as e:
        return f"Move error: {e}"

register_tool("move_file", move_file, "MEDIUM", "file")


# ===========================
# 7. ZIP DIRECTORY
# ===========================

@tool
def zip_directory(source_dir: str, output_path: str = "") -> str:
    """
    Compresses a directory into a .zip archive.
    Args:
        source_dir: Directory to compress.
        output_path: Output .zip path. Default: <source_dir>.zip
    """
    source_dir = _resolve_path(source_dir)
    if not os.path.isdir(source_dir):
        return f"Directory not found: {source_dir}"

    if not output_path:
        output_path = source_dir.rstrip("/") + ".zip"
    else:
        output_path = _resolve_path(output_path)

    try:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        file_count = 0
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(source_dir):
                for f in files:
                    full = os.path.join(root, f)
                    arcname = os.path.relpath(full, source_dir)
                    zf.write(full, arcname)
                    file_count += 1

        size = os.path.getsize(output_path)
        return f"Created {output_path} ({file_count} files, {_human_size(size)})"
    except Exception as e:
        return f"Zip error: {e}"

register_tool("zip_directory", zip_directory, "MEDIUM", "file")


# ===========================
# 8. UNZIP ARCHIVE
# ===========================

@tool
def unzip_archive(archive_path: str, output_dir: str = "") -> str:
    """
    Extracts a .zip archive.
    Args:
        archive_path: Path to .zip file.
        output_dir: Extraction directory. Default: same directory as archive.
    """
    archive_path = _resolve_path(archive_path)
    if not os.path.isfile(archive_path):
        return f"Archive not found: {archive_path}"

    if not output_dir:
        output_dir = os.path.dirname(archive_path)
    else:
        output_dir = _resolve_path(output_dir)

    try:
        os.makedirs(output_dir, exist_ok=True)
        with zipfile.ZipFile(archive_path, "r") as zf:
            names = zf.namelist()
            zf.extractall(output_dir)
        return f"Extracted {len(names)} files to {output_dir}"
    except Exception as e:
        return f"Unzip error: {e}"

register_tool("unzip_archive", unzip_archive, "MEDIUM", "file")


# ===========================
# 9. DISK USAGE REPORT
# ===========================

@tool
def disk_usage_report(path: str = "/") -> str:
    """
    Detailed disk usage report for all partitions.
    Args:
        path: Specific path for du analysis. Default: /.
    """
    try:
        output = "Disk Usage Report:\n\n"

        # Partition info
        partitions = psutil.disk_partitions()
        for p in partitions:
            try:
                usage = psutil.disk_usage(p.mountpoint)
                output += (f"  {p.device} -> {p.mountpoint} ({p.fstype})\n"
                          f"    Total: {_human_size(usage.total)}, "
                          f"Used: {_human_size(usage.used)} ({usage.percent}%), "
                          f"Free: {_human_size(usage.free)}\n\n")
            except (PermissionError, OSError):
                continue

        # Top directories by size
        if path != "/":
            output += f"\nLargest items in {path}:\n"
            try:
                items = []
                for item in os.listdir(path):
                    full = os.path.join(path, item)
                    try:
                        if os.path.isdir(full):
                            size = sum(os.path.getsize(os.path.join(dp, f))
                                      for dp, _, fs in os.walk(full) for f in fs)
                        else:
                            size = os.path.getsize(full)
                        items.append((size, item))
                    except (PermissionError, OSError):
                        continue
                items.sort(reverse=True)
                for size, name in items[:15]:
                    output += f"  {_human_size(size):>10}  {name}\n"
            except Exception:
                pass

        return output
    except Exception as e:
        return f"Disk report error: {e}"

register_tool("disk_usage_report", disk_usage_report, "LOW", "file")


# ===========================
# 10. DUPLICATE FILE FINDER
# ===========================

@tool
def duplicate_file_finder(directory: str, min_size: int = 1024) -> str:
    """
    Finds duplicate files using MD5 hashing.
    Args:
        directory: Directory to scan.
        min_size: Minimum file size in bytes to consider. Default: 1024.
    """
    directory = _resolve_path(directory)
    if not os.path.isdir(directory):
        return f"Directory not found: {directory}"

    try:
        hash_map = defaultdict(list)
        scanned = 0

        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fname in files:
                full = os.path.join(root, fname)
                try:
                    size = os.path.getsize(full)
                    if size < min_size:
                        continue
                    scanned += 1
                    h = hashlib.md5()
                    with open(full, "rb") as f:
                        for chunk in iter(lambda: f.read(8192), b""):
                            h.update(chunk)
                    hash_map[h.hexdigest()].append(full)
                except (PermissionError, OSError):
                    continue

        dupes = {h: paths for h, paths in hash_map.items() if len(paths) > 1}

        if not dupes:
            return f"No duplicates found in {directory} ({scanned} files scanned)."

        output = f"Found {len(dupes)} duplicate groups ({scanned} files scanned):\n\n"
        for h, paths in list(dupes.items())[:20]:
            size = os.path.getsize(paths[0])
            output += f"  [{_human_size(size)}] MD5: {h[:12]}...\n"
            for p in paths:
                output += f"    {p}\n"
            output += "\n"
        return output
    except Exception as e:
        return f"Duplicate finder error: {e}"

register_tool("duplicate_file_finder", duplicate_file_finder, "LOW", "file")


# ===========================
# 11. UPLOAD FILE (base64)
# ===========================

@tool
def upload_file(path: str, content_b64: str) -> str:
    """
    Uploads a file from base64-encoded content.
    Args:
        path: Destination file path.
        content_b64: Base64-encoded file content.
    """
    path = _resolve_path(path)
    try:
        data = base64.b64decode(content_b64)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return f"Uploaded {path} ({_human_size(len(data))})"
    except Exception as e:
        return f"Upload error: {e}"

register_tool("upload_file", upload_file, "MEDIUM", "file")


# ===========================
# 12. DOWNLOAD FILE (base64)
# ===========================

@tool
def download_file(path: str) -> str:
    """
    Downloads a file by returning its base64-encoded content.
    Args:
        path: File path to download.
    """
    path = _resolve_path(path)
    if not os.path.isfile(path):
        return f"File not found: {path}"

    try:
        size = os.path.getsize(path)
        if size > 50 * 1024 * 1024:
            return f"File too large for download ({_human_size(size)}). Max: 50MB."

        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()

        return json.dumps({
            "content_b64": b64,
            "filename": os.path.basename(path),
            "size": size,
            "path": path,
        })
    except Exception as e:
        return f"Download error: {e}"

register_tool("download_file", download_file, "MEDIUM", "file")


# ===========================
# HELPER
# ===========================

def _human_size(size: int) -> str:
    """Convert bytes to human-readable size."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size) < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}PB"
