"""
Jarvis Communication Tools — Webhooks (Discord/Slack).
Email has been moved to email_tools.py (Gmail OAuth2).
"""
import logging
import requests
from langchain_core.tools import tool

from app.tool_registry import register_tool
from app import db

logger = logging.getLogger("Jarvis")


@tool
def send_webhook_message(message: str, webhook_url: str = "") -> str:
    """
    Send a message to a Discord or Slack webhook.
    Args:
        message: The message text to send.
        webhook_url: Optional override URL. Leave empty to use the one from Settings.
    """
    url = webhook_url if webhook_url else db.get_config("webhook_url")
    if not url:
        return "ERROR: Webhook URL not configured. Please set it in Settings or provide it as an argument."

    try:
        resp = requests.post(url, json={"content": message, "text": message}, timeout=10)
        if resp.ok:
            return "Message sent to webhook successfully."
        return f"Webhook failed: {resp.status_code} - {resp.text}"
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return f"Failed to send webhook: {str(e)}"

register_tool("send_webhook_message", send_webhook_message, "MEDIUM", "communication")
