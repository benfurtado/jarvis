"""
Web Search Intent Detection — helper for agent.py to force web tool execution.
"""
import re

def detect_web_intent(message: str) -> dict:
    """Detect if the user wants to search the web or look up real-time info."""
    msg_lower = message.lower()
    
    # Keywords that strongly imply web search intent
    search_keywords = [
        "search", "google", "lookup", "look up", "news", "latest", 
        "current", "today", "yesterday", "who is", "what is", "where is",
        "stock", "price", "weather", "match", "score", "versus", "vs",
        "find information", "browse", "website", "url"
    ]
    
    has_intent = any(kw in msg_lower for kw in search_keywords)
    
    # Check for direct URL
    url_found = re.search(r'https?://[^\s]+', message)
    
    return {
        "has_intent": has_intent or bool(url_found),
        "intent_type": "read" if url_found else "search",
        "url": url_found.group(0) if url_found else None
    }

def build_web_hint(intent: dict) -> str:
    """Build a system hint to force the LLM to use web tools."""
    if not intent["has_intent"]:
        return ""
    
    if intent["intent_type"] == "read":
        return f"\n\nHINT: The message contains a URL ({intent['url']}). Use read_website_content('{intent['url']}') to fetch the content directly. DO NOT respond with 'I can't browse the web'."
    
    return "\n\nHINT: This request requires real-time information. USE the `search_web` tool IMMEDIATELY. DO NOT explain that you are an AI or that you don't have current data. EXECUTE the search now."
