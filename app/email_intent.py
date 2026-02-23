"""
Jarvis Email Intent Detection — regex + NLP-lite extraction.
Detects email addresses, intent phrases, attachment paths.
Used by agent.py to force email tool execution.
"""
import re
import os
import logging

logger = logging.getLogger("Jarvis")

# Email address regex (RFC 5322 simplified)
EMAIL_REGEX = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}',
    re.IGNORECASE
)

# Intent phrases that signal email action
EMAIL_INTENT_PHRASES = [
    r'\bemail\b', r'\bsend\s+(?:an?\s+)?(?:email|mail|message)\b',
    r'\bsend\s+to\b', r'\bmail\s+(?:him|her|them|it|this)\b',
    r'\breply\s+to\b', r'\bnotify\b', r'\bforward\b',
    r'\bmessage\s+(?:him|her|them)\b', r'\bwrite\s+(?:an?\s+)?email\b',
    r'\bshoot\s+(?:an?\s+)?email\b', r'\bdrop\s+(?:an?\s+)?email\b',
    r'\binbox\b', r'\bfetch\s+(?:my\s+)?(?:email|mail)\b',
    r'\bcheck\s+(?:my\s+)?(?:email|mail)\b', r'\bread\s+(?:my\s+)?(?:email|mail)\b',
    r'\bsearch\s+(?:my\s+)?(?:email|mail)\b',
]
EMAIL_INTENT_RE = re.compile('|'.join(EMAIL_INTENT_PHRASES), re.IGNORECASE)

# Attachment path regex — matches absolute/relative paths with extensions
ATTACHMENT_REGEX = re.compile(
    r'(?:attach(?:ment)?(?:\s+(?:the\s+)?file)?\s+)?((?:/[\w.\-]+)+(?:\.\w{1,10}))',
    re.IGNORECASE
)

# Alternative: explicit "attach /path/to/file" pattern
EXPLICIT_ATTACH_RE = re.compile(
    r'attach\s+((?:/[\w.\-]+)+)',
    re.IGNORECASE
)


def detect_email_intent(message: str) -> dict:
    """
    Analyze a user message for email intent.

    Returns:
        {
            "has_intent": bool,
            "intent_type": "send" | "fetch" | "read" | "reply" | "search" | None,
            "recipients": [str],
            "attachments": [str],
            "attachment_errors": [str],
            "raw_message": str,
        }
    """
    result = {
        "has_intent": False,
        "intent_type": None,
        "recipients": [],
        "attachments": [],
        "attachment_errors": [],
        "raw_message": message,
    }

    msg_lower = message.lower()

    # 1. Extract email addresses
    emails = EMAIL_REGEX.findall(message)
    if emails:
        result["recipients"] = list(set(emails))

    # 2. Check for intent phrases
    has_phrase = bool(EMAIL_INTENT_RE.search(message))

    # 3. Determine if there's email intent
    result["has_intent"] = bool(emails and has_phrase) or bool(emails and _has_send_context(msg_lower))

    if not result["has_intent"] and has_phrase:
        # Intent phrase without email address — might be fetch/read/search
        if any(re.search(p, msg_lower) for p in [r'\binbox\b', r'\bfetch\b', r'\bcheck\s+.*mail\b']):
            result["has_intent"] = True
            result["intent_type"] = "fetch"
        elif any(re.search(p, msg_lower) for p in [r'\bread\s+.*mail\b', r'\bread\s+.*email\b']):
            result["has_intent"] = True
            result["intent_type"] = "read"
        elif any(re.search(p, msg_lower) for p in [r'\bsearch\s+.*mail\b', r'\bsearch\s+.*email\b']):
            result["has_intent"] = True
            result["intent_type"] = "search"

    # 4. Classify intent type if we have recipients
    if result["has_intent"] and result["recipients"] and not result["intent_type"]:
        if re.search(r'\breply\b', msg_lower):
            result["intent_type"] = "reply"
        else:
            result["intent_type"] = "send"

    # 5. Extract attachment paths
    attach_matches = EXPLICIT_ATTACH_RE.findall(message)
    all_path_matches = ATTACHMENT_REGEX.findall(message)
    paths = list(set(attach_matches + all_path_matches))

    for path in paths:
        path = path.strip()
        if os.path.isfile(path):
            result["attachments"].append(path)
        elif path.startswith('/'):
            result["attachment_errors"].append(f"File not found: {path}")

    if result["has_intent"]:
        logger.info(
            f"Email intent detected: type={result['intent_type']}, "
            f"recipients={result['recipients']}, "
            f"attachments={result['attachments']}"
        )

    return result


def _has_send_context(msg_lower: str) -> bool:
    """Check if message has context suggesting sending (not just mentioning an email)."""
    send_words = [
        'email', 'mail', 'send', 'notify', 'tell', 'inform',
        'message', 'write to', 'reach out', 'contact', 'let.*know',
        'forward', 'shoot', 'drop', 'that', 'about',
    ]
    return any(re.search(w, msg_lower) for w in send_words)


def build_email_hint(intent: dict) -> str:
    """
    Build a system hint that forces the LLM to call the email tool.
    Injected into the message before sending to the agent.
    """
    if not intent["has_intent"]:
        return ""

    parts = []

    if intent["intent_type"] == "send" and intent["recipients"]:
        recipient = intent["recipients"][0]
        parts.append(
            f"\n\n[SYSTEM DIRECTIVE — MANDATORY]\n"
            f"The user wants to SEND an email to {recipient}. "
            f"You MUST call the send_email tool NOW with:\n"
            f"  to: \"{recipient}\"\n"
            f"  subject: Generate a professional subject from the user's message.\n"
            f"  body: Write a professional email body based on the user's intent.\n"
        )
        if intent["attachments"]:
            parts.append(f"  attachment_path: \"{intent['attachments'][0]}\"\n")
        if intent["attachment_errors"]:
            parts.append(f"NOTE: {'; '.join(intent['attachment_errors'])}\n")
        parts.append(
            "DO NOT explain. DO NOT ask questions. CALL send_email() NOW."
        )

    elif intent["intent_type"] == "fetch":
        parts.append(
            "\n\n[SYSTEM DIRECTIVE — MANDATORY]\n"
            "The user wants to check their inbox. "
            "You MUST call fetch_recent_emails tool NOW. DO NOT explain."
        )

    elif intent["intent_type"] == "search":
        parts.append(
            "\n\n[SYSTEM DIRECTIVE — MANDATORY]\n"
            "The user wants to search their emails. "
            "You MUST call search_emails tool NOW. DO NOT explain."
        )

    elif intent["intent_type"] == "read":
        parts.append(
            "\n\n[SYSTEM DIRECTIVE — MANDATORY]\n"
            "The user wants to read an email. "
            "You MUST call read_email tool NOW. DO NOT explain."
        )

    elif intent["intent_type"] == "reply" and intent["recipients"]:
        parts.append(
            "\n\n[SYSTEM DIRECTIVE — MANDATORY]\n"
            "The user wants to reply to an email. "
            "You MUST call reply_to_email tool NOW. DO NOT explain."
        )

    return "".join(parts)
