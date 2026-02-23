import os
import webview
import sqlite3
import subprocess
import base64
import mss
import io
import json
import websocket
import time
import logging
import uuid
from datetime import datetime
from email.mime.text import MIMEText
from PIL import Image
from typing import Annotated, List, Union, Optional
from typing_extensions import TypedDict

from flask import Flask, render_template, request, jsonify, send_from_directory

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage, BaseMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.prebuilt import ToolNode, tools_condition

# Gmail API imports
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("Jarvis")

# --- Configuration ---
from app.config import Config
from app.llm import RotatingLLM
WS_SERVER_URL = Config.WS_SERVER_URL

# Gmail OAuth Scopes
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send"
]

# --- Gmail Service Setup ---
_gmail_service = None

def get_gmail_service():
    """Get or create an authenticated Gmail API service."""
    global _gmail_service
    if _gmail_service:
        return _gmail_service
    
    logger.info("Initializing Gmail API service...")
    creds = None
    if os.path.exists("token.json"):
        try:
            creds = Credentials.from_authorized_user_file("token.json", GMAIL_SCOPES)
            logger.info("Loaded credentials from token.json")
        except Exception as e:
            logger.error(f"Error loading token.json: {e}")
            
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired credentials...")
            try:
                creds.refresh(Request())
            except Exception as e:
                logger.error(f"Error refreshing credentials: {e}")
                creds = None # Force re-auth
        
        if not creds:
            if not os.path.exists("credentials.json"):
                logger.error("credentials.json missing!")
                raise FileNotFoundError(
                    "credentials.json not found. Place your OAuth client file in the project root."
                )
            logger.info("Starting local OAuth server for authentication...")
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)
        
            with open("token.json", "w") as token:
                token.write(creds.to_json())
                logger.info("Saved new credentials to token.json")
    
    _gmail_service = build("gmail", "v1", credentials=creds)
    logger.info("Gmail API service connected successfully.")
    return _gmail_service

app = Flask(__name__)

def get_user_email() -> str:
    """Get the authenticated user's email address."""
    try:
        svc = get_gmail_service()
        profile = svc.users().getProfile(userId="me").execute()
        return profile.get("emailAddress", "")
    except Exception as e:
        logger.error(f"Error getting user email: {e}")
        return ""

# --- Email Classification Logic ---
PROCEDURAL_MEMORY = """
You are an AI Email Assistant.
- Classify emails into: spam, important, normal, or reply_needed.
- Spam = junk emails such as lotteries, phishing, promotions, or generic unsolicited advertisements.
- Important = work-related or deadlines (mentions of boss, projects, or tasks) but no direct reply required.
- Normal = casual or friendly messages (coffee invites, greetings, jokes) without urgency or expectation.
- Reply_needed = emails explicitly asking for response or action (e.g., "Are you available?", "Please confirm", "Send file").
- For forwarded emails, analyze the content, not just the subject line.
- If subject or body mentions "urgent", "deadline", "meeting", or "boss", treat it as important or reply_needed depending on action requested.
- If email requests a document/file, do not make one up; notify user instead.
- Emails from known spam sources (Glassdoor, Pinterest, Zolve, etc.) are spam unless context shows action required.
"""

EPISODIC_MEMORY_FILE = "episodic_memory.json"

def load_episodic_memory():
    if os.path.exists(EPISODIC_MEMORY_FILE):
        try:
            with open(EPISODIC_MEMORY_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading episodic memory: {e}")
    return []

def save_episodic_memory(memory):
    try:
        with open(EPISODIC_MEMORY_FILE, "w") as f:
            json.dump(memory, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving episodic memory: {e}")

# --- Tools ---
@tool
def download_website(url: str) -> str:
    """
    Downloads and mirrors a website, then zips it for download.
    Args:
        url: The full URL (including http/https) of the website to download.
    """
    import shutil
    try:
        # Use a 'temp' folder within the project directory
        app_dir = os.path.dirname(os.path.abspath(__file__))
        base_tmp = os.path.join(app_dir, "temp")
        os.makedirs(base_tmp, exist_ok=True)
        logger.info(f"DOWNLOAD_TOOL: Base directory: {base_tmp}")
        
        # Create a unique folder for this download
        folder_name = f"website_{uuid.uuid4().hex}"
        download_dir = os.path.join(base_tmp, folder_name)
        os.makedirs(download_dir, exist_ok=True)

        logger.info(f"DOWNLOAD_TOOL: Mirroring URL: {url} into {download_dir}")
        # Run wget
        cmd = f"wget --mirror --convert-links --adjust-extension --page-requisites --no-parent --directory-prefix={download_dir} {url}"
        
        logger.info(f"DOWNLOAD_TOOL: Executing: {cmd}")
        # Capture output for debugging
        result = subprocess.run(cmd, shell=True, timeout=300, capture_output=True, text=True)
        logger.info(f"DOWNLOAD_TOOL: Wget exit code: {result.returncode}")
        
        # Check if anything was actually downloaded
        downloaded_items = os.listdir(download_dir)
        logger.info(f"DOWNLOAD_TOOL: Files in download_dir: {downloaded_items}")
        
        if not downloaded_items:
             return json.dumps({"status": "error", "message": "Nothing was downloaded. Check if the URL is valid."})

        # Zip the result using shutil
        zip_path_base = os.path.join(base_tmp, folder_name)
        logger.info(f"DOWNLOAD_TOOL: Creating archive: {zip_path_base}.zip")
        shutil.make_archive(zip_path_base, 'zip', download_dir)
        
        # Clean up the raw folder
        shutil.rmtree(download_dir)
        
        zip_filename = f"{folder_name}.zip"
        full_zip_path = os.path.join(base_tmp, zip_filename)
        
        if os.path.exists(full_zip_path):
            logger.info(f"DOWNLOAD_TOOL: SUCCESS. File created at: {full_zip_path}")
            return json.dumps({
                "status": "success",
                "message": f"Website {url} successfully mirrored and zipped.",
                "download_url": f"/download/{zip_filename}",
                "filename": zip_filename
            })
        else:
            logger.error(f"DOWNLOAD_TOOL: Failed to find zip after creation: {full_zip_path}")
            return json.dumps({"status": "error", "message": "Failed to create zip file."})

    except Exception as e:
        logger.error(f"DOWNLOAD_TOOL: Exception occurred: {e}")
        return json.dumps({"status": "error", "message": str(e)})


@tool
def send_email(to: str, subject: str, message: str) -> str:
    """
    Sends an email using Gmail API.
    Args:
        to: The recipient email address.
        subject: The subject of the email.
        message: The body text of the email.
    """
    logger.info(f"Attempting to send email to {to} with subject: '{subject}'")
    try:
        svc = get_gmail_service()
        
        # Proper message formatting
        mime_msg = MIMEText(message)
        mime_msg["to"] = to
        mime_msg["subject"] = subject
        
        raw_bytes = base64.urlsafe_b64encode(mime_msg.as_bytes())
        raw_str = raw_bytes.decode()
        send_body = {"raw": raw_str}
        
        result = svc.users().messages().send(userId="me", body=send_body).execute()
        msg_id = result.get('id')
        logger.info(f"Email successfully sent! ID: {msg_id}")
        return f"SUCCESS: Email successfully sent to {to}.\nSubject: {subject}\nMessage Body:\n{message}"
    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")
        return f"Error sending email: {str(e)}"

@tool
def fetch_emails(max_results: int = 5) -> str:
    """
    Fetches recent emails from the user's Gmail inbox.
    Args:
        max_results: Number of emails to fetch (default 5, max 20).
    """
    logger.info(f"Fetching last {max_results} emails...")
    try:
        svc = get_gmail_service()
        max_results = min(max_results, 20)
        
        results = svc.users().messages().list(userId="me", maxResults=max_results).execute()
        messages = results.get("messages", [])
        
        if not messages:
            logger.info("No emails found.")
            return "No emails found in inbox."
        
        fetched = []
        for m in messages:
            msg = svc.users().messages().get(userId="me", id=m["id"]).execute()
            headers = msg["payload"].get("headers", [])
            subject = next((h["value"] for h in headers if h["name"] == "Subject"), "(No Subject)")
            sender = next((h["value"] for h in headers if h["name"] == "From"), "(Unknown Sender)")
            snippet = msg.get("snippet", "")
            
            fetched.append({
                "id": m["id"],
                "from": sender,
                "subject": subject,
                "body": snippet[:300]
            })
        
        logger.info(f"Successfully fetched {len(fetched)} emails.")
        output = f"I found {len(fetched)} recent emails:\n\n"
        for i, email in enumerate(fetched, 1):
            output += f"{i}. FROM: {email['from']}\n"
            output += f"   SUBJECT: {email['subject']}\n"
            output += f"   CONTENT: {email['body']}...\n\n"
        
        return output
    except Exception as e:
        logger.error(f"Error fetching emails: {str(e)}")
        return f"Error fetching emails: {str(e)}"

@tool
def classify_and_process_emails(max_results: int = 5) -> str:
    """
    Fetches recent emails, classifies each one (spam/important/normal/reply_needed),
    and suggests actions using AI.
    """
    logger.info(f"Starting email classification for {max_results} emails...")
    try:
        svc = get_gmail_service()
        max_results = min(max_results, 10)
        
        results = svc.users().messages().list(userId="me", maxResults=max_results).execute()
        messages_list = results.get("messages", [])
        
        if not messages_list:
            return "No emails found in inbox."
        
        classifier = RotatingLLM(temperature=0.7) # Slightly higher temp for classification
        episodic = load_episodic_memory()
        output = f"Email Classification Report ({len(messages_list)} emails):\n\n"
        
        for m in messages_list:
            msg = svc.users().messages().get(userId="me", id=m["id"]).execute()
            headers = msg["payload"].get("headers", [])
            subject = next((h["value"] for h in headers if h["name"] == "Subject"), "(No Subject)")
            sender = next((h["value"] for h in headers if h["name"] == "From"), "(Unknown Sender)")
            snippet = msg.get("snippet", "")
            
            logger.info(f"Classifying email from {sender}: '{subject}'")
            
            classify_prompt = f"""{PROCEDURAL_MEMORY}
Classify the following email as one of: spam, important, normal, reply_needed.
Email:
From: {sender}
Subject: {subject}
Body: {snippet[:200]}
Answer with only one word."""
            
            classification = classifier.invoke(classify_prompt).content.strip().lower()
            logger.info(f"Classification result: {classification}")
            
            # Determine action
            if "spam" in classification:
                action = "No action needed. Marked as spam."
            elif "reply" in classification:
                action = "Reply recommended. This email requires a response."
            elif "important" in classification:
                action = "Flagged as important. Review recommended."
            else:
                action = "Normal email. No immediate action needed."
            
            output += f"From: {sender}\nSubject: {subject}\nClassification: {classification.upper()}\nAction: {action}\n" + "-"*40 + "\n"
            
            episodic.append({
                "time": datetime.now().isoformat(), "from": sender, "subject": subject,
                "classification": classification, "action_taken": action
            })
        
        save_episodic_memory(episodic)
        logger.info("Classification report complete and saved to episodic memory.")
        return output
        
    except Exception as e:
        logger.error(f"Error classifying emails: {str(e)}")
        return f"Error classifying emails: {str(e)}"

@tool
def run_terminal_command(command: str) -> str:
    """
    Executes a shell command on the host system.
    """
    logger.info(f"Executing command: {command}")
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning(f"Command failed with return code {result.returncode}")
            return f"Command failed with return code {result.returncode}:\n{result.stderr}"
        return f"Output:\n{result.stdout}"
    except Exception as e:
        logger.error(f"Error executing command: {e}")
        return f"Error executing command: {str(e)}"

@tool
def take_screenshot() -> str:
    """
    Takes a screenshot of the primary monitor.
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
                "image_data": img_b64
            })
    except Exception as e:
        logger.error(f"Error taking screenshot: {e}")
        return f"Error taking screenshot: {str(e)}"

# --- Global State for WebSocket Connections ---
SOCIAL_MANAGER = None

class SocialMediaManager:
    def __init__(self):
        self.active_tasks = {}
        
    def start_task(self, thread_id, payload):
        if thread_id in self.active_tasks:
            try:
                self.active_tasks[thread_id]['ws'].close()
            except:
                pass
                
        self.active_tasks[thread_id] = {
            'logs': [], 'status': 'starting', 'last_qr': None, 'ws': None
        }
        
        import threading
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
                task['logs'].append(f"[{timestamp}] {msg_type.upper()}: {str(content)[:100]}")
                if msg_type == 'qr_code':
                    task['last_qr'] = content
                    task['status'] = 'waiting_for_scan'
                elif msg_type == 'status':
                    task['status'] = content
                    if "exited" in str(content):
                        task['status'] = 'completed'
                        ws.close()
                elif msg_type == 'error':
                    task['status'] = 'error'
            except Exception as e:
                task['logs'].append(f"SYSTEM ERROR: {str(e)}")

        def on_error(ws, error):
            task['logs'].append(f"WS ERROR: {str(error)}")
            task['status'] = 'error'

        def on_close(ws, close_status_code, close_msg):
            task['logs'].append("WS CONNECTION CLOSED")
            if task['status'] != 'completed':
                task['status'] = 'disconnected'

        def on_open(ws):
            task['logs'].append("WS CONNECTED. Sending payload...")
            ws.send(json.dumps(payload))

        ws = websocket.WebSocketApp(
            WS_SERVER_URL,
            on_open=on_open, on_message=on_message,
            on_error=on_error, on_close=on_close
        )
        task['ws'] = ws
        ws.run_forever()

    def get_update(self, thread_id):
        if thread_id not in self.active_tasks:
            return {"status": "no_task", "logs": []}
        task = self.active_tasks[thread_id]
        return {
            "status": task['status'],
            "logs": task['logs'][-5:],
            "qr_code": task['last_qr']
        }

SOCIAL_MANAGER = SocialMediaManager()

@tool
def send_social_message(service: str, target: str, message: str) -> str:
    """
    Sends social messages via WhatsApp.
    """
    logger.info(f"Social message request: service={service}, target={target}")
    if service.lower() == "instagram":
        return "Instagram messaging is currently disabled."

    thread_id = "session_1"
    payload = {
        "service": service.lower(),
        "action": "send_message",
        "payload": {"target": target, "message": message}
    }

    SOCIAL_MANAGER.start_task(thread_id, payload)
    time.sleep(2)
    update = SOCIAL_MANAGER.get_update(thread_id)
    
    if update.get('qr_code'):
        qr_raw = update['qr_code']
        qr_b64 = qr_raw.split(",")[1] if "," in qr_raw else qr_raw
        return json.dumps({
            "status": "success", 
            "message": "QR Code received. Please scan.",
            "image_data": qr_b64,
            "logs": update['logs']
        })
    return f"Task started. Status: {update['status']}"

@tool
def check_social_status(thread_id_ref: str = "current") -> str:
    """
    Checks the status of the social media task.
    """
    thread_id = "session_1"
    update = SOCIAL_MANAGER.get_update(thread_id)
    response = {
        "status": "success",
        "task_status": update['status'],
        "logs": update['logs']
    }
    if update.get('qr_code'):
        qr_raw = update['qr_code']
        qr_b64 = qr_raw.split(",")[1] if "," in qr_raw else qr_raw
        response["image_data"] = qr_b64
    return json.dumps(response)

# --- LangGraph Setup ---
ALL_TOOLS = [run_terminal_command, take_screenshot, send_social_message, check_social_status, send_email, fetch_emails, classify_and_process_emails, download_website]

class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

llm_rotator = RotatingLLM(tools=ALL_TOOLS)

SYSTEM_PROMPT = """You are Jarvis, an advanced AI system. 

STYLE RULES:
- For general conversation, reply in exactly 1-2 natural, human-like sentences.
- When reporting DATA from a tool (fetching emails, classification, downloading sites, etc.), you MUST be thorough and use structured formatting.
- You ARE allowed to use simple markdown like bullet points (.) and new lines when presenting reports or email lists.
- Do NOT use bolding (**), code blocks (```), or hashtags (#).
- Be professional, transparent, and clear.
- Do NOT use hyphens for bullet points; use periods or simple spacing.

EMAIL PROTOCOL:
- When writing emails, use a polite and professional tone.
- Start with a proper greeting (e.g., "Hello [Name]," or "Dear [Name],").
- Ensure the message is clear, concise, and structured.
- Always include the signature: "Best regards, Jarvis (AI Assistant)".

WEBSITE DOWNLOADS:
- When asked to download or mirror a site, use the 'download_website' tool.
- Inform the user that the site is being mirrored and that you will provide a download link once it is ready.
- Once finished, tell them they can click the download button below your message.

You have access to: terminal, screenshots, WhatsApp, Gmail, and Website Mirroring."""

def chatbot(state: State):
    messages = state["messages"]
    recent_messages = messages[-20:] if len(messages) > 20 else messages
    
    start_index = 0
    for i, msg in enumerate(recent_messages):
        if isinstance(msg, HumanMessage):
            start_index = i
            break
    recent_messages = recent_messages[start_index:]
    
    while recent_messages and isinstance(recent_messages[0], ToolMessage):
        recent_messages.pop(0)
    
    sanitized_messages = []
    for msg in recent_messages:
        if isinstance(msg, ToolMessage):
            try:
                data = json.loads(msg.content)
                if isinstance(data, dict):
                    data_for_llm = data.copy()
                    if "image_data" in data_for_llm:
                        data_for_llm["image_data"] = "<image_data_hidden>"
                    sanitized_messages.append(ToolMessage(
                        content=json.dumps(data_for_llm),
                        tool_call_id=msg.tool_call_id,
                        name=msg.name or "tool_result"
                    ))
                    continue
            except:
                pass 
        elif isinstance(msg, SystemMessage):
            continue
        sanitized_messages.append(msg)

    return {"messages": [llm_rotator.invoke([SystemMessage(content=SYSTEM_PROMPT)] + sanitized_messages)]}

graph_builder = StateGraph(State)
graph_builder.add_node("chatbot", chatbot)
graph_builder.add_node("tools", ToolNode(ALL_TOOLS))
graph_builder.add_edge(START, "chatbot")
graph_builder.add_conditional_edges("chatbot", tools_condition)
graph_builder.add_edge("tools", "chatbot")

conn = sqlite3.connect("memory.db", check_same_thread=False)
memory = SqliteSaver(conn)
graph = graph_builder.compile(checkpointer=memory)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download/<path:filename>')
def serve_download(filename):
    try:
        app_dir = os.path.dirname(os.path.abspath(__file__))
        directory = os.path.join(app_dir, "temp")
        return send_from_directory(directory, filename, as_attachment=True)
    except Exception as e:
        logger.error(f"Download serve error: {e}")
        return str(e), 404

@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    user_message = data.get('message')
    thread_id = data.get('thread_id', 'default_thread') 

    if not user_message:
        return jsonify({'error': 'No message provided'}), 400

    config = {"configurable": {"thread_id": thread_id}}
    inputs = {"messages": [HumanMessage(content=user_message)]}
    
    try:
        final_state = graph.invoke(inputs, config=config)
        latest_messages = final_state["messages"]
        last_message = latest_messages[-1]
        response_text = last_message.content
        extra_data = {}
        # Search back through history for the most recent tool data
        logger.info(f"Searching {len(latest_messages)} messages for extra data...")
        for msg in reversed(latest_messages):
            if isinstance(msg, ToolMessage):
                try:
                    tool_data = json.loads(msg.content)
                    if isinstance(tool_data, dict):
                        # Capture image if we don't have one yet
                        if "image_data" in tool_data and "image_data" not in extra_data:
                            extra_data["image_data"] = tool_data["image_data"]
                        # Capture download if we don't have one yet
                        if "download_url" in tool_data and "download_url" not in extra_data:
                            logger.info(f"FOUND DOWNLOAD IN HISTORY: {tool_data['download_url']}")
                            extra_data["download_url"] = tool_data["download_url"]
                            extra_data["filename"] = tool_data.get("filename", "download.zip")
                except Exception:
                    continue
            
            # If we found both, we can stop
            if "image_data" in extra_data and "download_url" in extra_data:
                break
            
            # Limit how far back we look to avoid sending very old downloads
            # but ensure we look back at least past the current turn
            if len(extra_data) == 0 and isinstance(msg, HumanMessage) and msg.content != user_message:
                # If we haven't found anything even after passing the PREVIOUS human message, stop
                # break # Disabled to be more aggressive in finding the link
                pass
        
        if extra_data:
            logger.info(f"Final Payload keys: {list(extra_data.keys())}")
        return jsonify({'response': response_text, **extra_data})
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return jsonify({'response': f"Error: {str(e)}"}), 500

if __name__ == '__main__':
    logger.info("Starting Jarvis server on port 5000...")
    app.run(host='0.0.0.0', port=5000, debug=True)
