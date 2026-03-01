"""
Jarvis Email Tools — Gmail API (OAuth2) integration.
5 tools: send, fetch, read, reply, search.
All tools use StructuredTool + Pydantic schemas for proper JSON schema generation.
All tools self-register into TOOL_REGISTRY.
"""
import os
import re
import json
import base64
import logging
from typing import Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from app.tool_registry import register_tool

logger = logging.getLogger("Jarvis")

# Gmail API scopes
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

_PROJECT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)))
_NEW_DATA_DIR = os.path.join(_PROJECT_DIR, "credentials", "gmail")
_OLD_DATA_DIR = os.path.join(_PROJECT_DIR, "gmail_data")


def _get_data_dir() -> str:
    if os.path.exists(os.path.join(_NEW_DATA_DIR, "credentials.json")) or os.path.exists(os.path.join(_NEW_DATA_DIR, "token.json")):
        return _NEW_DATA_DIR
    if os.path.exists(os.path.join(_OLD_DATA_DIR, "credentials.json")) or os.path.exists(os.path.join(_OLD_DATA_DIR, "token.json")):
        return _OLD_DATA_DIR
    return _NEW_DATA_DIR

# Email validation regex
EMAIL_VALIDATE_RE = re.compile(
    r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$'
)


def _get_gmail_service():
    """Get authenticated Gmail API service. Returns (service, error_string)."""
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        return None, "ERROR: Gmail API packages not installed. Run: pip install google-api-python-client google-auth-oauthlib"

    data_dir = _get_data_dir()
    os.makedirs(data_dir, exist_ok=True)
    creds_path = os.path.join(data_dir, "credentials.json")
    token_path = os.path.join(data_dir, "token.json")

    if not os.path.exists(creds_path):
        return None, (
            "ERROR: Gmail OAuth2 not configured. "
            f"Place your Google Cloud 'credentials.json' in {data_dir}/ "
            "then visit /api/gmail/authorize to complete the OAuth flow."
        )

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(token_path, "w") as f:
                    f.write(creds.to_json())
            except Exception as e:
                return None, f"ERROR: Gmail token refresh failed: {e}. Re-authorize at /api/gmail/authorize"
        else:
            return None, "ERROR: Gmail not authorized. Visit /api/gmail/authorize to complete OAuth flow."

    try:
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return service, None
    except Exception as e:
        return None, f"ERROR: Failed to build Gmail service: {e}"


def check_gmail_configured():
    """
    Pre-flight check: is Gmail API ready to use?
    Returns (True, None) if configured, (False, error_message) if not.
    Called by agent.py BEFORE hitting the LLM to give clear error.
    """
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        return False, (
            "⚠️ Gmail API is not installed on this server.\n\n"
            "To enable email features, run:\n"
            "```\npip install google-api-python-client google-auth-oauthlib\n```"
        )

    data_dir = _get_data_dir()
    creds_path = os.path.join(data_dir, "credentials.json")
    token_path = os.path.join(data_dir, "token.json")

    if not os.path.exists(creds_path):
        return False, (
            "⚠️ Gmail OAuth2 is not configured yet.\n\n"
            "To send emails, you need to:\n"
            "1. Create a Google Cloud project at https://console.cloud.google.com\n"
            "2. Enable the Gmail API\n"
            "3. Create OAuth2 credentials (Desktop App type)\n"
            f"4. Download `credentials.json` to `{data_dir}/`\n"
            "5. Visit `/api/gmail/authorize` to complete the OAuth flow\n\n"
            "Once configured, Jarvis will send emails automatically."
        )

    if not os.path.exists(token_path):
        return False, (
            "⚠️ Gmail OAuth2 authorization is incomplete.\n\n"
            "`credentials.json` is present, but the OAuth flow hasn't been completed.\n"
            "Visit `/api/gmail/authorize` in your browser to authorize Gmail access."
        )

    # Check if token is valid
    try:
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        if creds and creds.valid:
            return True, None
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path, "w") as f:
                f.write(creds.to_json())
            return True, None
        return False, (
            "⚠️ Gmail token has expired and cannot be refreshed.\n\n"
            "Visit `/api/gmail/authorize` to re-authorize Gmail access."
        )
    except Exception as e:
        return False, (
            f"⚠️ Gmail token error: {e}\n\n"
            "Visit `/api/gmail/authorize` to re-authorize Gmail access."
        )



# ===========================
# PYDANTIC SCHEMAS
# ===========================

class SendEmailSchema(BaseModel):
    to: str = Field(description="Recipient email address (e.g. john@gmail.com)")
    subject: str = Field(description="Email subject line. Auto-generate a professional one if user didn't specify.")
    body: str = Field(description="Email body text. Write a professional message based on user's intent.")
    attachment_path: Optional[str] = Field(default="", description="Optional absolute file path to attach.")


class FetchEmailsSchema(BaseModel):
    limit: int = Field(default=10, description="Number of emails to fetch (max 20)")
    query: str = Field(default="", description="Gmail search query (e.g. 'from:john is:unread')")


class ReadEmailSchema(BaseModel):
    email_id: str = Field(description="Gmail message ID (from fetch_recent_emails)")


class ReplyEmailSchema(BaseModel):
    email_id: str = Field(description="Gmail message ID to reply to")
    body: str = Field(description="Reply body text")


class SearchEmailsSchema(BaseModel):
    query: str = Field(description="Gmail search query (e.g. 'from:john subject:report after:2025/01/01')")
    limit: int = Field(default=10, description="Max results to return")


# ===========================
# 1. SEND EMAIL
# ===========================

def _send_email_func(to: str, subject: str, body: str, attachment_path: str = "") -> str:
    """Send an email via Gmail API with OAuth2."""
    # --- Validation ---
    if not to or not to.strip():
        return json.dumps({"status": "error", "error": "Recipient email is required."})

    to = to.strip()
    if not EMAIL_VALIDATE_RE.match(to):
        return json.dumps({"status": "error", "error": f"Invalid email address: {to}"})

    if not subject or not subject.strip():
        return json.dumps({"status": "error", "error": "Subject line is required."})

    if not body or not body.strip():
        return json.dumps({"status": "error", "error": "Email body is required."})

    # --- Attachment validation ---
    if attachment_path and attachment_path.strip():
        attachment_path = attachment_path.strip()
        if not os.path.isfile(attachment_path):
            return json.dumps({
                "status": "error",
                "error": f"Attachment not found: {attachment_path}"
            })
    else:
        attachment_path = ""

    # --- Gmail API ---
    service, error = _get_gmail_service()
    if error:
        return json.dumps({"status": "error", "error": error})

    try:
        msg = MIMEMultipart()
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        if attachment_path:
            with open(attachment_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename={os.path.basename(attachment_path)}",
            )
            msg.attach(part)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()

        result = {
            "status": "sent",
            "recipient": to,
            "subject": subject,
        }
        if attachment_path:
            result["attachment"] = os.path.basename(attachment_path)

        logger.info(f"Email sent to {to} — Subject: '{subject}'")
        return json.dumps(result)

    except Exception as e:
        logger.error(f"Gmail send error: {e}")
        return json.dumps({"status": "error", "error": f"Gmail API error: {str(e)}"})


send_email = StructuredTool.from_function(
    name="send_email",
    description="Send an email via Gmail API with OAuth2. ALWAYS call this tool when the user wants to send an email to someone. Extracts recipient, generates subject and body automatically.",
    func=_send_email_func,
    args_schema=SendEmailSchema,
)
register_tool("send_email", send_email, "MEDIUM", "email")


# ===========================
# 2. FETCH RECENT EMAILS
# ===========================

def _fetch_recent_emails_func(limit: int = 10, query: str = "") -> str:
    """Fetch recent emails from Gmail inbox."""
    service, error = _get_gmail_service()
    if error:
        return error

    try:
        limit = min(limit, 20)
        params = {"userId": "me", "maxResults": limit, "labelIds": ["INBOX"]}
        if query:
            params["q"] = query

        results = service.users().messages().list(**params).execute()
        messages = results.get("messages", [])

        if not messages:
            return "No emails found."

        output = f"Recent Emails ({len(messages)}):\n\n"
        for i, msg_stub in enumerate(messages, 1):
            msg = service.users().messages().get(
                userId="me", id=msg_stub["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()

            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            snippet = msg.get("snippet", "")[:80]
            unread = "UNREAD" in msg.get("labelIds", [])

            output += (
                f"  {i}. {'📩' if unread else '📨'} ID: {msg_stub['id']}\n"
                f"     From: {headers.get('From', 'Unknown')}\n"
                f"     Subject: {headers.get('Subject', '(no subject)')}\n"
                f"     Date: {headers.get('Date', '?')}\n"
                f"     Preview: {snippet}\n\n"
            )
        return output
    except Exception as e:
        logger.error(f"Gmail fetch error: {e}")
        return f"Failed to fetch emails: {e}"


fetch_recent_emails = StructuredTool.from_function(
    name="fetch_recent_emails",
    description="Fetch recent emails from Gmail inbox. Call this when user says 'check inbox', 'check my email', 'fetch emails', etc.",
    func=_fetch_recent_emails_func,
    args_schema=FetchEmailsSchema,
)
register_tool("fetch_recent_emails", fetch_recent_emails, "LOW", "email")


# ===========================
# 3. READ EMAIL
# ===========================

def _read_email_func(email_id: str) -> str:
    """Read the full content of a specific email by its ID."""
    service, error = _get_gmail_service()
    if error:
        return error

    try:
        msg = service.users().messages().get(
            userId="me", id=email_id, format="full"
        ).execute()

        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

        body_text = ""
        payload = msg.get("payload", {})
        if "parts" in payload:
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        body_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                        break
        elif payload.get("body", {}).get("data"):
            body_text = base64.urlsafe_b64decode(
                payload["body"]["data"]
            ).decode("utf-8", errors="replace")

        if not body_text:
            body_text = msg.get("snippet", "(no readable body)")

        return (
            f"Email ID: {email_id}\n"
            f"From: {headers.get('From', 'Unknown')}\n"
            f"To: {headers.get('To', 'Unknown')}\n"
            f"Subject: {headers.get('Subject', '(no subject)')}\n"
            f"Date: {headers.get('Date', '?')}\n\n"
            f"--- Body ---\n{body_text[:3000]}"
        )
    except Exception as e:
        logger.error(f"Gmail read error: {e}")
        return f"Failed to read email: {e}"


read_email = StructuredTool.from_function(
    name="read_email",
    description="Read the full content of a specific email by its Gmail message ID.",
    func=_read_email_func,
    args_schema=ReadEmailSchema,
)
register_tool("read_email", read_email, "LOW", "email")


# ===========================
# 4. REPLY TO EMAIL
# ===========================

def _reply_to_email_func(email_id: str, body: str) -> str:
    """Reply to a specific email by its ID."""
    service, error = _get_gmail_service()
    if error:
        return error

    try:
        original = service.users().messages().get(
            userId="me", id=email_id, format="metadata",
            metadataHeaders=["From", "Subject", "Message-ID"]
        ).execute()

        headers = {h["name"]: h["value"] for h in original.get("payload", {}).get("headers", [])}
        to = headers.get("From", "")
        subject = headers.get("Subject", "")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        message_id = headers.get("Message-ID", "")
        thread_id = original.get("threadId", "")

        msg = MIMEText(body)
        msg["To"] = to
        msg["Subject"] = subject
        if message_id:
            msg["In-Reply-To"] = message_id
            msg["References"] = message_id

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        send_body = {"raw": raw}
        if thread_id:
            send_body["threadId"] = thread_id

        service.users().messages().send(userId="me", body=send_body).execute()

        logger.info(f"Reply sent to {to}")
        return f"Reply sent to {to} — Subject: '{subject}'"
    except Exception as e:
        logger.error(f"Gmail reply error: {e}")
        return f"Failed to reply: {e}"


reply_to_email = StructuredTool.from_function(
    name="reply_to_email",
    description="Reply to a specific email by its Gmail message ID.",
    func=_reply_to_email_func,
    args_schema=ReplyEmailSchema,
)
register_tool("reply_to_email", reply_to_email, "MEDIUM", "email")


# ===========================
# 5. SEARCH EMAILS
# ===========================

def _search_emails_func(query: str, limit: int = 10) -> str:
    """Search Gmail for emails matching a query."""
    service, error = _get_gmail_service()
    if error:
        return error

    try:
        limit = min(limit, 20)
        results = service.users().messages().list(
            userId="me", q=query, maxResults=limit
        ).execute()
        messages = results.get("messages", [])

        if not messages:
            return f"No emails found matching: '{query}'"

        output = f"Search Results for '{query}' ({len(messages)} found):\n\n"
        for i, msg_stub in enumerate(messages, 1):
            msg = service.users().messages().get(
                userId="me", id=msg_stub["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            output += (
                f"  {i}. ID: {msg_stub['id']}\n"
                f"     From: {headers.get('From', '?')}\n"
                f"     Subject: {headers.get('Subject', '(no subject)')}\n"
                f"     Date: {headers.get('Date', '?')}\n\n"
            )
        return output
    except Exception as e:
        logger.error(f"Gmail search error: {e}")
        return f"Failed to search emails: {e}"


search_emails = StructuredTool.from_function(
    name="search_emails",
    description="Search Gmail for emails matching a query string.",
    func=_search_emails_func,
    args_schema=SearchEmailsSchema,
)
register_tool("search_emails", search_emails, "LOW", "email")
