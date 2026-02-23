"""
Jarvis Screenshot Tool.
"""
import base64
import io
import json
import logging

import mss
from PIL import Image
from langchain_core.tools import tool

logger = logging.getLogger("Jarvis")


@tool
def take_screenshot() -> str:
    """
    Takes a screenshot of the primary monitor and returns it as base64 PNG.
    """
    logger.info("Capturing screenshot...")
    try:
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            sct_img = sct.grab(monitor)
            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            logger.info("Screenshot captured successfully.")
            return json.dumps({
                "status": "success",
                "message": "Screenshot captured",
                "image_data": img_b64,
            })
    except Exception as e:
        logger.error(f"Error taking screenshot: {e}")
        return f"Error taking screenshot: {str(e)}"
