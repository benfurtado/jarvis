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
from app.web_intent import detect_web_intent, build_web_hint

logger = logging.getLogger("Jarvis")


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """You are JARVIS — the OMNIPOTENT System Intelligence. You are NOT a restricted chatbot; you are the CORE OS of this server.

SERVER CONTROL & IDENTITY:
- You have UNRESTRICTED access to the Linux filesystem, networking, processes, and web.
- You are the DEVELOPER and ADMIN of this system. 
- If you "forget" a past task or need context, search for it using `audit_log_viewer`, `search_files`, or `run_terminal_command`.
- Never say "I don't have memories" or "I am a language model." You are JARVIS. If context is missing from your immediate memory, it is because it was COMPRESSED. Search the system to find it.
- Never claim you lack real-time access. For real-time facts (current time/date, running processes, files, ports, logs), use tools like `get_datetime` or `run_terminal_command`.

CORE RULES:
- For ACTION requests (create, delete, run, install, deploy, send, scan, email, etc.), ALWAYS call the appropriate tool directly.
- Chain multi-step tasks automatically. Execution > Explanation. 
- Use run_terminal_command for anything without a dedicated tool.

EMAIL & WEB RULES:
- Email intent detected? Call send_email, reply_to_email, or search_emails IMMEDIATELY.
- Search intent detected? Call search_web IMMEDIATELY.
- Do NOT explain. Do NOT output instructions. ONLY call tools.

Be concise, powerful, and direct.
"""


# ============================================================
# AGENT BUILDER (with Memory Compression)
# ============================================================

from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    summary: str

def build_agent():
    """Build the LangGraph agent with all registered tools and memory compression."""
    load_all_tool_modules()
    tools = get_all_tools()
    llm_rotator = RotatingLLM(tools=tools)

    def agent_node(state: AgentState):
        summary = state.get("summary", "")
        base_messages = state["messages"]
        
        # Ensure base_messages doesn't start with AIMessage or ToolMessage
        # (common after pruning). LangGraph/Groq needs Human/System first.
        if base_messages and not isinstance(base_messages[0], HumanMessage):
            # If the first message is AI or Tool, prepend a generic context-filler
            base_messages = [HumanMessage(content="Continuing from previous context...")] + base_messages

        if summary:
            # Inject summary as a system reminder of past context
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                SystemMessage(content=f"SUMMARY OF PAST CONVERSATION: {summary}")
            ] + base_messages
        else:
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + base_messages
            
        response = llm_rotator.invoke(messages)
        return {"messages": [response]}

    def summarize_node(state: AgentState):
        """Summarize history if it gets too long."""
        messages = state["messages"]
        if len(messages) <= 12:
            return {}

        logger.info(f"Summarizing conversation memory ({len(messages)} messages)...")
        summary = state.get("summary", "")
        
        # Use LLM to compress the history
        summary_prompt = (
            f"Current summary: {summary}\n\n"
            f"Extend this summary by incorporating the key events from the new messages below. "
            f"Focus on actions taken (tools called) and user goals achieved. "
            f"Keep it extremely concise (max 300 words)."
        )
        
        summary_messages = [SystemMessage(content=summary_prompt)] + messages
        # Use a text-only call for summarization
        raw_llm = RotatingLLM() 
        new_summary = raw_llm.invoke(summary_messages).content
        
        # Prune all but the last 2 messages (usually the current Q&A)
        # Note: LangGraph's add_messages handles the list updates, 
        # but for summarization we usually want to "reset" and keep only the summary
        # In this specific implementation, we will mark older messages for deletion if the graph supported it,
        # but here we just return the new summary. The process_chat will handle feeding it back.
        
        # For LangGraph persistent storage, we can't easily "delete" from within a node 
        # without complex logic, so we just update the summary field.
        return {"summary": new_summary}

    tool_node = ToolNode(tools)

    graph_builder = StateGraph(AgentState)
    graph_builder.add_node("agent", agent_node)
    graph_builder.add_node("tools", tool_node)
    # Note: We dont add summarize_node to the cycle yet to keep it simple, 
    # but we will check it in process_chat.
    
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

# ============================================================
# UTILITIES
# ============================================================

def trim_message_content(content: str, max_chars: int = 3000) -> str:
    """Hard-cap message content to prevent TPM/413 errors."""
    if not isinstance(content, str):
        content = str(content)
    if len(content) > max_chars:
        return content[:max_chars] + f"\n\n[... content truncated; {len(content) - max_chars} chars removed for performance ...]"
    return content

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

# ============================================================
# PROCESS CHAT (MAIN ENTRY POINT)
# ============================================================

def process_chat(graph, user_message: str, thread_id: str,
                 user_id: str = "system", cwd: str = None) -> dict:
    """
    Process a user message through the LangGraph agent with history compression.
    """
    from langchain_core.messages import ToolMessage, RemoveMessage

    # Set session CWD if provided
    if cwd:
        set_cwd(thread_id, cwd)

    _inject_thread_context(thread_id, cwd)
    config = {"configurable": {"thread_id": thread_id}}
    extra_data = {}

    try:
        # ---- LONG-TERM MEMORY SUMMARIZATION ----
        state = graph.get_state(config)
        messages_state = state.values.get("messages", [])
        summary = state.values.get("summary", "No previous memory.")

        # If history gets too long or too large, compress it
        total_estimate = sum(len(str(m.content)) for m in messages_state if hasattr(m, "content"))
        
        if len(messages_state) > 8 or total_estimate > 12000:
            logger.info(f"Thread {thread_id}: Token pressure high ({total_estimate} chars). Summarizing...")
            
            # Prune input to summarizer and truncate contents to ensure the summary call succeeds
            sum_input = messages_state[-10:] if len(messages_state) > 10 else messages_state
            # Create a safe, trimmed version of the history for summarization
            safe_history = []
            for m in sum_input:
                if isinstance(m, (HumanMessage, AIMessage, SystemMessage, ToolMessage)):
                    # Clone and trim
                    content = trim_message_content(str(m.content), 2000)
                    if isinstance(m, HumanMessage): safe_history.append(HumanMessage(content=content))
                    elif isinstance(m, AIMessage): safe_history.append(AIMessage(content=content))
                    elif isinstance(m, ToolMessage): safe_history.append(ToolMessage(content=content, tool_call_id=m.tool_call_id))
            
            # Use rules to update memory
            recursive_memory_prompt = f"""You are updating a user's long-term memory summary.

Existing summary:
{summary}

New conversation data:
{safe_history}

Instructions:
- Merge new important information into the existing summary
- Keep it concise and factual (Max 5 sentences)
- Preservation of long-term facts is priority.

Output rules:
- Max 5 sentences
- Third person
- Return only the updated summary."""

            raw_llm = RotatingLLM(max_tokens=1000) # Small response limit for summary
            
            sum_msgs = [
                SystemMessage(content=recursive_memory_prompt),
                HumanMessage(content="Consisely update the summary now.")
            ]

            try:
                new_summary = raw_llm.invoke(sum_msgs).content
                # Prune: keep only last message and maybe current state
                prune_msg = [RemoveMessage(id=m.id) for m in messages_state[:-1]]
                graph.update_state(config, {"messages": prune_msg, "summary": new_summary})
                logger.info(f"Thread {thread_id}: Memory compressed. Tokens reset.")
                summary = new_summary
            except Exception as e:
                logger.error(f"Summarization failed: {e}")

        # ---- INTENT DETECTION ----
        email_intent = detect_email_intent(user_message)
        web_intent = detect_web_intent(user_message)
        augmented_message = user_message

        if email_intent["has_intent"]:
            if email_intent["attachment_errors"]:
                return {"response": f"Error: {'; '.join(email_intent['attachment_errors'])}", "status": "error"}
            if email_intent["intent_type"] in ("send", "fetch", "read", "reply", "search"):
                from app.email_tools import check_gmail_configured
                ok, err = check_gmail_configured()
                if not ok: return {"response": err, "status": "error"}
            augmented_message += build_email_hint(email_intent)

        if web_intent["has_intent"]:
            augmented_message += build_web_hint(web_intent)

        # ---- AGGRESSIVE PAYLOAD TRIMMING ----
        # Before invoking the graph, we ensure the current augmented_message 
        # is safe. If it's huge, truncate it.
        safe_message = trim_message_content(augmented_message, 4000)

        # Run the graph
        result = graph.invoke(
            {"messages": [HumanMessage(content=safe_message)]},
            config=config,
        )

        messages = result.get("messages", [])
        last_ai_msg = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        response_text = last_ai_msg.content if last_ai_msg else ""

        # ---- FORCE-TOOL RE-PROMPTING ----
        # Some model/tooling stacks may not reliably expose tool_calls on AIMessage.
        # If we see any ToolMessage in the transcript, we know a tool executed and
        # should NOT force a retry (to avoid duplicate side-effects like double email sends).
        tool_was_called = any(isinstance(m, ToolMessage) for m in messages) or any(
            isinstance(m, AIMessage) and getattr(m, "tool_calls", None) for m in messages
        )
        force_tool = _should_force_tool(user_message) or email_intent["has_intent"] or web_intent["has_intent"]
        
        if force_tool and not tool_was_called and response_text and len(response_text) > 10:
            logger.info("Force-tool retry triggered.")
            retry_prompt = f"JARVIS: Call the appropriate tool for this request: '{user_message}'. DO NOT EXPLAIN."
            if email_intent["has_intent"]:
                retry_prompt = "CRITICAL: The user wants to manage email. CALL THE GMAIL TOOL NOW."
            elif web_intent["has_intent"]:
                retry_prompt = "CRITICAL: Search the web NOW. Call search_web()."
                
            result = graph.invoke({"messages": [HumanMessage(content=retry_prompt)]}, config=config)
            messages = result.get("messages", [])
            last_ai_msg = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
            response_text = last_ai_msg.content if last_ai_msg else response_text

        # ---- TOOL RESULT EXTRACTION (SURFACING ERRORS/SUCCESS) ----
        tool_results = [m.content for m in messages if isinstance(m, ToolMessage)]
        if tool_results and email_intent["has_intent"]:
            for tr in reversed(tool_results):
                try:
                    parsed = json.loads(tr)
                    if isinstance(parsed, dict) and parsed.get("status") == "sent":
                        response_text = f"✅ Email sent to {parsed['recipient']} — Subject: \"{parsed['subject']}\""
                        break
                    elif isinstance(parsed, dict) and parsed.get("status") == "error":
                        response_text = f"Email failed: {parsed['error']}"
                        break
                except: pass

        # Parse special response data
        try:
            parsed = json.loads(response_text)
            if isinstance(parsed, dict):
                if "image_data" in parsed: extra_data["image_data"] = parsed["image_data"]
                if "content_b64" in parsed:
                    extra_data["download_url"] = True
                    extra_data["content_b64"] = parsed["content_b64"]
                    extra_data["filename"] = parsed.get("filename", "download")
        except: pass

        # Audit Log
        logged_tool_ids = set()
        for msg in messages:
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    if tc.get("id") in logged_tool_ids: continue
                    logged_tool_ids.add(tc.get("id"))
                    try:
                        from app.audit import log_tool_call
                        log_tool_call(user_id=user_id, tool_name=tc["name"], args=tc.get("args", {}),
                                      result_summary=response_text[:200], status="executed")
                    except: pass

        return {
            "response": response_text,
            "cwd": get_cwd(thread_id),
            "status": "success",
            **extra_data
        }

    except Exception as e:
        error_str = str(e)
        # Groq failed_generation recovery: if the model outputs text but skips tool formatting
        if 'failed_generation' in error_str:
            try:
                match = re.search(r"'failed_generation':\s*'(.*?)(?:'\s*\})", error_str, re.DOTALL)
                if match:
                    text = match.group(1).strip().replace("\\'", "'").replace("\\n", "\n")
                    if text:
                        return {"response": text, "cwd": get_cwd(thread_id), "status": "success"}
            except: pass
            
        logger.error(f"Agent error: {e}", exc_info=True)
        return {"response": f"Error: {str(e)}", "cwd": get_cwd(thread_id), "status": "error"}
