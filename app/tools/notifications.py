"""
Jarvis Notifications — Telegram push notifications.
"""
import logging

import requests
from langchain_core.tools import tool

from app.config import Config

logger = logging.getLogger("Jarvis")


def _send_telegram(message: str) -> bool:
    """Internal function to send a Telegram message."""
    token = Config.TELEGRAM_BOT_TOKEN
    chat_id = Config.TELEGRAM_CHAT_ID

    if not token or not chat_id:
        logger.warning("Telegram not configured (missing bot token or chat ID).")
        return False

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
        }, timeout=10)
        if resp.status_code == 200:
            logger.info("Telegram notification sent.")
            return True
        else:
            logger.error(f"Telegram API error: {resp.status_code} — {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False


@tool
def send_telegram_notification(message: str) -> str:
    """
    Sends a push notification via Telegram bot.
    Args:
        message: The message text to send.
    """
    if not Config.TELEGRAM_BOT_TOKEN or not Config.TELEGRAM_CHAT_ID:
        return "Telegram notifications are not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env."

    success = _send_telegram(message)
    if success:
        return f"Telegram notification sent successfully: {message[:100]}"
    else:
        return "Failed to send Telegram notification. Check logs for details."


def notify_approval_required(tool_name: str, args_preview: str):
    """Send a Telegram notification when a HIGH-risk tool needs approval."""
    _send_telegram(
        f"🔐 <b>Jarvis Approval Required</b>\n\n"
        f"Tool: <code>{tool_name}</code>\n"
        f"Details: {args_preview}\n\n"
        f"Open Jarvis to approve or deny."
    )


def notify_task_completed(task_id: str, command: str, output: str):
    """Send a Telegram notification when a scheduled task completes."""
    _send_telegram(
        f"✅ <b>Scheduled Task Completed</b>\n\n"
        f"Task ID: <code>{task_id}</code>\n"
        f"Command: <code>{command}</code>\n"
        f"Output: {output[:200]}"
    )
