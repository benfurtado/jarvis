"""
Jarvis Website Mirroring Tool.
"""
import os
import json
import uuid
import shutil
import subprocess
import logging

from langchain_core.tools import tool

logger = logging.getLogger("Jarvis")


@tool
def download_website(url: str) -> str:
    """
    Downloads and mirrors a website, then zips it for download.
    Args:
        url: The full URL (including http/https) of the website to download.
    """
    try:
        app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        base_tmp = os.path.join(app_dir, "temp")
        os.makedirs(base_tmp, exist_ok=True)

        folder_name = f"website_{uuid.uuid4().hex}"
        download_dir = os.path.join(base_tmp, folder_name)
        os.makedirs(download_dir, exist_ok=True)

        logger.info(f"DOWNLOAD_TOOL: Mirroring URL: {url} into {download_dir}")
        cmd = f"wget --mirror --convert-links --adjust-extension --page-requisites --no-parent --directory-prefix={download_dir} {url}"

        result = subprocess.run(cmd, shell=True, timeout=300, capture_output=True, text=True)
        logger.info(f"DOWNLOAD_TOOL: Wget exit code: {result.returncode}")

        downloaded_items = os.listdir(download_dir)
        if not downloaded_items:
            return json.dumps({"status": "error", "message": "Nothing was downloaded. Check if the URL is valid."})

        zip_path_base = os.path.join(base_tmp, folder_name)
        shutil.make_archive(zip_path_base, "zip", download_dir)
        shutil.rmtree(download_dir)

        zip_filename = f"{folder_name}.zip"
        full_zip_path = os.path.join(base_tmp, zip_filename)

        if os.path.exists(full_zip_path):
            logger.info(f"DOWNLOAD_TOOL: SUCCESS. File created at: {full_zip_path}")
            return json.dumps({
                "status": "success",
                "message": f"Website {url} successfully mirrored and zipped.",
                "download_url": f"/download/{zip_filename}",
                "filename": zip_filename,
            })
        else:
            return json.dumps({"status": "error", "message": "Failed to create zip file."})

    except Exception as e:
        logger.error(f"DOWNLOAD_TOOL: Exception occurred: {e}")
        return json.dumps({"status": "error", "message": str(e)})
