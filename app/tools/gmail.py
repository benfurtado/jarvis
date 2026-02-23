"""
Jarvis Gmail Tools — send, fetch, classify emails via Gmail API.
"""
import os
import base64
import json
import logging
from datetime import datetime
from email.mime.text import MIMEText

from langchain_core.tools import tool
from app.config import Config
from app.llm import RotatingLLM
from app import db

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger("Jarvis")

# --- Gmail Service Singleton ---
_gmail_service = None


def get_gmail_service():
    """Get or create an authenticated Gmail API service."""
    global _gmail_service
    if _gmail_service:
        return _gmail_service

    scopes = Config.GMAIL_SCOPES
    logger.info("Initializing Gmail API service...")
    creds = None

    if os.path.exists("token.json"):
        try:
            creds = Credentials.from_authorized_user_file("token.json", scopes)
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
                creds = None

        if not creds:
            if not os.path.exists("credentials.json"):
                logger.error("credentials.json missing!")
                raise FileNotFoundError(
                    "credentials.json not found. Place your OAuth client file in the project root."
                )
            logger.info("Starting local OAuth server for authentication...")
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", scopes)
            creds = flow.run_local_server(port=0)

            with open("token.json", "w") as token:
                token.write(creds.to_json())
                logger.info("Saved new credentials to token.json")

    _gmail_service = build("gmail", "v1", credentials=creds)
    logger.info("Gmail API service connected successfully.")
    return _gmail_service


# --- Email Classification Prompt ---
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
        mime_msg = MIMEText(message)
        mime_msg["to"] = to
        mime_msg["subject"] = subject
        raw_bytes = base64.urlsafe_b64encode(mime_msg.as_bytes())
        raw_str = raw_bytes.decode()
        result = svc.users().messages().send(userId="me", body={"raw": raw_str}).execute()
        msg_id = result.get("id")
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
                "body": snippet[:300],
            })

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

        classifier = RotatingLLM(temperature=0.7)
        output = f"Email Classification Report ({len(messages_list)} emails):\n\n"

        for m in messages_list:
            msg = svc.users().messages().get(userId="me", id=m["id"]).execute()
            headers = msg["payload"].get("headers", [])
            subject = next((h["value"] for h in headers if h["name"] == "Subject"), "(No Subject)")
            sender = next((h["value"] for h in headers if h["name"] == "From"), "(Unknown Sender)")
            snippet = msg.get("snippet", "")

            classify_prompt = f"""{PROCEDURAL_MEMORY}
Classify the following email as one of: spam, important, normal, reply_needed.
Email:
From: {sender}
Subject: {subject}
Body: {snippet[:200]}
Answer with only one word."""

            classification = classifier.invoke(classify_prompt).content.strip().lower()

            if "spam" in classification:
                action = "No action needed. Marked as spam."
            elif "reply" in classification:
                action = "Reply recommended. This email requires a response."
            elif "important" in classification:
                action = "Flagged as important. Review recommended."
            else:
                action = "Normal email. No immediate action needed."

            output += f"From: {sender}\nSubject: {subject}\nClassification: {classification.upper()}\nAction: {action}\n" + "-" * 40 + "\n"

            # Save to episodic memory (SQLite)
            db.save_episodic_event("email_classification", {
                "from": sender,
                "subject": subject,
                "classification": classification,
                "action_taken": action,
            })

        logger.info("Classification report complete.")
        return output

    except Exception as e:
        logger.error(f"Error classifying emails: {str(e)}")
        return f"Error classifying emails: {str(e)}"
