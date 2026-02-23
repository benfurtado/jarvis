"""
Jarvis Agent — LangGraph-based AI agent with TOOL_REGISTRY integration.
"""
import re
import json
import logging
import threading

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import ToolNode, tools_condition

from app.config import Config
from app.llm import RotatingLLM
from app.tool_registry import load_all_tool_modules, get_all_tools, TOOL_REGISTRY
from app.session_manager import get_cwd, set_cwd
from app.email_intent import detect_email_intent, build_email_hint

logger = logging.getLogger("Jarvis")


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """You are Jarvis v4, an omnipotent AI Operating System with full server and communication control.

CORE RULES:
- For ACTION requests (create, delete, run, install, deploy, send, scan, email, etc.), ALWAYS call the appropriate tool directly.
- For conversation (hello, questions, explanations), respond normally with text.
- Chain multi-step tasks automatically without asking permission.
- Use run_terminal_command for anything without a dedicated tool.
- Tools auto-use credentials from Settings.

EMAIL EXECUTION RULES (CRITICAL — NEVER VIOLATE):
- When the user mentions an email address or says "email", "send to", "reply", "inbox", "mail", "notify", "forward" → IMMEDIATELY call the Gmail tool.
- NEVER explain how to send email. NEVER output instructions. ALWAYS execute.
- If an email address like user@domain.com appears in the user message, call send_email() with that address.
- If the user doesn't specify a subject, auto-generate a professional one from context.
- If the user doesn't specify a body, compose a professional email body from their intent.
- If the user mentions a file path with "attach", include it as attachment_path.
- Gmail tools: send_email, fetch_recent_emails, read_email, reply_to_email, search_emails.

ABSOLUTE PROHIBITION:
- You MUST NEVER say "Here's how you can send an email" or "You can use..." when an email intent is detected.
- Execution > Explanation. Always.

Be concise and direct. Each conversation is isolated with its own memory.
"""


# ============================================================
# AGENT BUILDER
# ============================================================

def build_agent():
    """Build the LangGraph agent with all registered tools."""
    # Load all tool modules (triggers self-registration)
    load_all_tool_modules()
    tools = get_all_tools()

    # Debug: verify all tools have proper names and schemas
    tool_names = [t.name for t in tools]
    logger.info(f"Building agent with {len(tools)} tools: {tool_names}")

    # Verify critical email tools are present
    email_tools_expected = {"send_email", "fetch_recent_emails", "read_email", "reply_to_email", "search_emails"}
    missing = email_tools_expected - set(tool_names)
    if missing:
        logger.error(f"MISSING email tools from LangGraph binding: {missing}")
    else:
        logger.info("All 5 email tools confirmed in LangGraph tool binding ✓")

    llm_rotator = RotatingLLM(tools=tools)

    # State graph
    def agent_node(state: MessagesState):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
        response = llm_rotator.invoke(messages)
        return {"messages": [response]}

    tool_node = ToolNode(tools)

    graph_builder = StateGraph(MessagesState)
    graph_builder.add_node("agent", agent_node)
    graph_builder.add_node("tools", tool_node)
    graph_builder.add_edge(START, "agent")
    graph_builder.add_conditional_edges("agent", tools_condition)
    graph_builder.add_edge("tools", "agent")

    memory = InMemorySaver()
    graph = graph_builder.compile(checkpointer=memory)

    return graph


# ============================================================
# FORCE-TOOL DETECTION
# ============================================================

def _should_force_tool(message: str) -> bool:
    """Check if the user message contains action keywords that should trigger tools."""
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in Config.FORCE_TOOL_KEYWORDS)


def _has_email_intent(message: str) -> bool:
    """Quick check if message has email intent (used for aggressive re-prompting)."""
    intent = detect_email_intent(message)
    return intent["has_intent"]


# ============================================================
# THREAD CONTEXT INJECTION
# ============================================================

def _inject_thread_context(thread_id: str, cwd: str = None):
    """Inject thread_id and cwd into thread-local storage for tools to access."""
    t = threading.current_thread()
    t._jarvis_ctx = {
        "thread_id": thread_id,
        "cwd": cwd or get_cwd(thread_id),
    }


# ============================================================
# PROCESS CHAT (MAIN ENTRY POINT)
# ============================================================

def process_chat(graph, user_message: str, thread_id: str,
                 user_id: str = "system", cwd: str = None) -> dict:
    """
    Process a user message through the LangGraph agent.

    Returns:
        dict with keys: response, cwd, status, and optional image_data/download_url
    """
    from langchain_core.messages import ToolMessage

    # Set session CWD if provided
    if cwd:
        set_cwd(thread_id, cwd)

    # Inject context for tools
    _inject_thread_context(thread_id, cwd)

    config = {"configurable": {"thread_id": thread_id}}
    extra_data = {}

    try:
        # ---- EMAIL INTENT DETECTION ----
        email_intent = detect_email_intent(user_message)
        augmented_message = user_message

        if email_intent["has_intent"]:
            logger.info(
                f"Email intent active: type={email_intent['intent_type']}, "
                f"recipients={email_intent['recipients']}"
            )

            # Pre-validate attachments — fail fast
            if email_intent["attachment_errors"]:
                errors = "; ".join(email_intent["attachment_errors"])
                return {
                    "response": f"Cannot send email: {errors}",
                    "cwd": get_cwd(thread_id),
                    "status": "error",
                }

            # ---- PRE-FLIGHT GMAIL CHECK ----
            # If email intent requires Gmail (send/fetch/read/reply/search),
            # check if Gmail is configured BEFORE hitting the LLM.
            if email_intent["intent_type"] in ("send", "fetch", "read", "reply", "search"):
                from app.email_tools import check_gmail_configured
                gmail_ok, gmail_error = check_gmail_configured()
                if not gmail_ok:
                    return {
                        "response": gmail_error,
                        "cwd": get_cwd(thread_id),
                        "status": "error",
                    }

            # Inject system directive to force tool execution
            hint = build_email_hint(email_intent)
            augmented_message = user_message + hint

        # Run the graph
        result = graph.invoke(
            {"messages": [HumanMessage(content=augmented_message)]},
            config=config,
        )

        # Extract last AI message
        messages = result.get("messages", [])
        last_message = None
        response_text = ""

        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                last_message = msg
                response_text = msg.content or ""
                break

        # ---- CHECK IF ANY TOOL WAS ALREADY CALLED ----
        # If a tool was called (even if it returned an error), do NOT retry.
        tool_was_called = any(
            isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None)
            for msg in messages
        )

        # ---- FORCE-TOOL RE-PROMPTING ----
        # Only retry if NO tool was called at all (LLM responded with text only)
        force_tool = _should_force_tool(user_message) or email_intent["has_intent"]
        max_retries = 3 if email_intent["has_intent"] else (2 if force_tool else 0)
        retries = 0

        while (
            force_tool
            and not tool_was_called
            and retries < max_retries
            and isinstance(last_message, AIMessage)
            and not getattr(last_message, "tool_calls", None)
            and response_text
            and len(response_text) > 20
        ):
            retries += 1
            logger.info(f"Force-tool retry {retries}/{max_retries}: re-prompting agent")

            if email_intent["has_intent"] and email_intent["intent_type"] == "send":
                recipient = email_intent["recipients"][0] if email_intent["recipients"] else "unknown"
                retry_prompt = (
                    f"CRITICAL: You just responded with text instead of executing. "
                    f"The user wants to EMAIL {recipient}. "
                    f"You MUST call send_email(to=\"{recipient}\", subject=<generate>, body=<generate>) RIGHT NOW. "
                    f"Original request: '{user_message}'. "
                    f"DO NOT output any text. ONLY call the send_email tool."
                )
            else:
                retry_prompt = (
                    f"You responded with text instead of calling a tool. "
                    f"The user said: '{user_message}'. "
                    f"You MUST call the appropriate tool to execute this action directly. "
                    f"Do NOT explain how to do it — DO it using the tools available to you."
                )

            result = graph.invoke(
                {"messages": [HumanMessage(content=retry_prompt)]},
                config=config,
            )

            messages = result.get("messages", [])
            for msg in reversed(messages):
                if isinstance(msg, AIMessage):
                    last_message = msg
                    response_text = msg.content or ""
                    break

            # Check if tool was called this time
            tool_was_called = any(
                isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None)
                for msg in messages
            )
            if tool_was_called:
                break

        if not response_text and last_message:
            response_text = str(last_message.content)

        # ---- EXTRACT TOOL RESULTS (for better error reporting) ----
        # If a tool was called and returned an error, use the tool's error
        # instead of the LLM's vague paraphrase.
        tool_results = []
        for msg in messages:
            if isinstance(msg, ToolMessage):
                tool_results.append(msg.content or "")

        # Check if tool returned a structured error we should surface
        if tool_results and email_intent["has_intent"]:
            for tr in reversed(tool_results):
                try:
                    parsed_tool = json.loads(tr)
                    if isinstance(parsed_tool, dict) and parsed_tool.get("status") == "error":
                        error_msg = parsed_tool.get("error", "Unknown error")
                        response_text = f"Email failed: {error_msg}"
                        break
                    elif isinstance(parsed_tool, dict) and parsed_tool.get("status") == "sent":
                        recipient = parsed_tool.get("recipient", "")
                        subject = parsed_tool.get("subject", "")
                        response_text = f"✅ Email sent to {recipient} — Subject: \"{subject}\""
                        if parsed_tool.get("attachment"):
                            response_text += f" (attached: {parsed_tool['attachment']})"
                        break
                except (json.JSONDecodeError, TypeError):
                    pass

        # Parse special response data (images, downloads)
        try:
            parsed = json.loads(response_text)
            if isinstance(parsed, dict):
                if "image_data" in parsed:
                    extra_data["image_data"] = parsed["image_data"]
                if "content_b64" in parsed:
                    extra_data["download_url"] = True
                    extra_data["content_b64"] = parsed["content_b64"]
                    extra_data["filename"] = parsed.get("filename", "download")
        except (json.JSONDecodeError, TypeError):
            pass

        # Log tool calls to audit (deduplicated)
        logged_tool_ids = set()
        for msg in messages:
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    tc_id = tc.get("id", "")
                    if tc_id in logged_tool_ids:
                        continue
                    logged_tool_ids.add(tc_id)
                    try:
                        from app.audit import log_tool_call
                        log_tool_call(
                            user_id=user_id,
                            tool_name=tc["name"],
                            args=tc.get("args", {}),
                            result_summary=response_text[:200],
                            status="executed",
                        )
                    except Exception as e:
                        logger.error(f"Audit log error: {e}")

        # Get current CWD to return
        current_cwd = get_cwd(thread_id)

        return {
            "response": response_text,
            "cwd": current_cwd,
            "status": "success",
            **extra_data,
        }


    except Exception as e:
        error_str = str(e)
        # Groq tool_use_failed: the model wanted to say text but it was misformatted.
        if 'failed_generation' in error_str:
            try:
                match = re.search(r"'failed_generation':\s*'(.*?)(?:'\s*\})", error_str, re.DOTALL)
                if match:
                    text = match.group(1).strip()
                    text = text.replace("\\'", "'").replace("\\n", "\n")
                    if text:
                        return {
                            "response": text,
                            "cwd": get_cwd(thread_id),
                            "status": "success",
                        }
            except Exception:
                pass
        logger.error(f"Agent error: {e}", exc_info=True)
        return {
            "response": f"Error processing request: {str(e)}",
            "cwd": get_cwd(thread_id),
            "status": "error",
        }
