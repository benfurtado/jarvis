"""
Jarvis Social Media Tools — WhatsApp messaging via WebSocket.
"""
import json
import time
import logging
import threading

import websocket
from langchain_core.tools import tool

from app.config import Config

logger = logging.getLogger("Jarvis")


class SocialMediaManager:
    """Manages WebSocket connections to the WhatsApp bridge."""

    def __init__(self):
        self.active_tasks = {}

    def start_task(self, thread_id, payload):
        if thread_id in self.active_tasks:
            try:
                self.active_tasks[thread_id]["ws"].close()
            except Exception:
                pass

        self.active_tasks[thread_id] = {
            "logs": [],
            "status": "starting",
            "last_qr": None,
            "ws": None,
        }

        t = threading.Thread(target=self._run_ws, args=(thread_id, payload))
        t.daemon = True
        t.start()
        return "Task started."

    def _run_ws(self, thread_id, payload):
        task = self.active_tasks[thread_id]

        def on_message(ws, message):
            try:
                data = json.loads(message)
                msg_type = data.get("type")
                content = data.get("data")
                timestamp = time.strftime("%H:%M:%S")
                task["logs"].append(f"[{timestamp}] {msg_type.upper()}: {str(content)[:100]}")
                if msg_type == "qr_code":
                    task["last_qr"] = content
                    task["status"] = "waiting_for_scan"
                elif msg_type == "status":
                    task["status"] = content
                    if "exited" in str(content):
                        task["status"] = "completed"
                        ws.close()
                elif msg_type == "error":
                    task["status"] = "error"
            except Exception as e:
                task["logs"].append(f"SYSTEM ERROR: {str(e)}")

        def on_error(ws, error):
            task["logs"].append(f"WS ERROR: {str(error)}")
            task["status"] = "error"

        def on_close(ws, close_status_code, close_msg):
            task["logs"].append("WS CONNECTION CLOSED")
            if task["status"] != "completed":
                task["status"] = "disconnected"

        def on_open(ws):
            task["logs"].append("WS CONNECTED. Sending payload...")
            ws.send(json.dumps(payload))

        ws = websocket.WebSocketApp(
            Config.WS_SERVER_URL,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        task["ws"] = ws
        ws.run_forever()

    def get_update(self, thread_id):
        if thread_id not in self.active_tasks:
            return {"status": "no_task", "logs": []}
        task = self.active_tasks[thread_id]
        return {
            "status": task["status"],
            "logs": task["logs"][-5:],
            "qr_code": task["last_qr"],
        }


# Singleton
SOCIAL_MANAGER = SocialMediaManager()


@tool
def send_social_message(service: str, target: str, message: str) -> str:
    """
    Sends social messages via WhatsApp.
    Args:
        service: The service to use (currently only 'whatsapp').
        target: Target phone number or contact name.
        message: Message to send.
    """
    logger.info(f"Social message request: service={service}, target={target}")
    if service.lower() == "instagram":
        return "Instagram messaging is currently disabled."

    thread_id = "session_1"
    payload = {
        "service": service.lower(),
        "action": "send_message",
        "payload": {"target": target, "message": message},
    }

    SOCIAL_MANAGER.start_task(thread_id, payload)
    time.sleep(2)
    update = SOCIAL_MANAGER.get_update(thread_id)

    if update.get("qr_code"):
        qr_raw = update["qr_code"]
        qr_b64 = qr_raw.split(",")[1] if "," in qr_raw else qr_raw
        return json.dumps({
            "status": "success",
            "message": "QR Code received. Please scan.",
            "image_data": qr_b64,
            "logs": update["logs"],
        })
    return f"Task started. Status: {update['status']}"


@tool
def check_social_status(thread_id_ref: str = "current") -> str:
    """
    Checks the status of the social media task.
    Args:
        thread_id_ref: Reference to the thread (default 'current').
    """
    thread_id = "session_1"
    update = SOCIAL_MANAGER.get_update(thread_id)
    response = {
        "status": "success",
        "task_status": update["status"],
        "logs": update["logs"],
    }
    if update.get("qr_code"):
        qr_raw = update["qr_code"]
        qr_b64 = qr_raw.split(",")[1] if "," in qr_raw else qr_raw
        response["image_data"] = qr_b64
    return json.dumps(response)
