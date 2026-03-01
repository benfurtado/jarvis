"""
Jarvis LLM Module — Handles LLM instantiation with automatic rotation and multi-provider failover.
Supports Gemini and Groq.
"""
import logging
import time
import threading
import json
from typing import Any, Dict, List

import requests
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import AIMessage
from app.config import Config

logger = logging.getLogger("Jarvis.LLM")


def _lc_messages_to_openai(messages) -> List[Dict[str, Any]]:
    """Convert LangChain messages to OpenAI-style messages."""
    out: List[Dict[str, Any]] = []
    for m in messages:
        role = None
        if getattr(m, "type", None) == "system":
            role = "system"
        elif getattr(m, "type", None) == "human":
            role = "user"
        elif getattr(m, "type", None) == "ai":
            role = "assistant"
        elif getattr(m, "type", None) == "tool":
            role = "tool"

        if role is None:
            role = "user"

        msg: Dict[str, Any] = {"role": role, "content": str(getattr(m, "content", ""))}

        # Tool result messages
        if role == "tool":
            msg["tool_call_id"] = getattr(m, "tool_call_id", "")

        # Assistant tool calls (if present)
        if role == "assistant" and getattr(m, "tool_calls", None):
            msg["tool_calls"] = []
            for tc in m.tool_calls:
                fn = tc.get("name")
                args = tc.get("args", {})
                msg["tool_calls"].append(
                    {
                        "id": tc.get("id"),
                        "type": "function",
                        "function": {"name": fn, "arguments": json.dumps(args)},
                    }
                )

        out.append(msg)
    return out


def _lc_tools_to_openai(tools) -> List[Dict[str, Any]]:
    """Convert LangChain tools to OpenAI tool schema."""
    out: List[Dict[str, Any]] = []
    for t in tools or []:
        # LangChain tools expose different attributes depending on type.
        name = getattr(t, "name", None)
        description = getattr(t, "description", "") or ""
        args_schema = getattr(t, "args_schema", None)
        parameters: Dict[str, Any] = {"type": "object", "properties": {}, "required": []}
        if args_schema is not None:
            try:
                schema = args_schema.model_json_schema()
                parameters = schema
            except Exception:
                pass

        if name:
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description,
                        "parameters": parameters,
                    },
                }
            )
    return out


class AzureAIInferenceChat:
    """Minimal Azure AI Inference chat client that returns LangChain AIMessage."""

    def __init__(self, endpoint: str, api_key: str, api_version: str, model: str,
                 temperature: float, max_tokens: int, timeout: int = 30):
        self.endpoint = endpoint
        self.api_key = api_key
        self.api_version = api_version
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._tools = None

    def bind_tools(self, tools):
        self._tools = tools
        return self

    def invoke(self, messages, **kwargs):
        url = self.endpoint
        if "api-version=" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}api-version={self.api_version}"

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": _lc_messages_to_openai(messages),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        openai_tools = _lc_tools_to_openai(self._tools)
        if openai_tools:
            payload["tools"] = openai_tools
            payload["tool_choice"] = "auto"

        headers = {
            "Content-Type": "application/json",
            "api-key": self.api_key,
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("Azure AI Inference returned no choices")

        msg = choices[0].get("message") or {}
        content = msg.get("content") or ""

        tool_calls = []
        for tc in (msg.get("tool_calls") or []):
            fn = (tc.get("function") or {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            tool_calls.append({
                "id": tc.get("id"),
                "name": fn.get("name"),
                "args": args,
                "type": "tool_call",
            })

        return AIMessage(content=content, tool_calls=tool_calls)


class AzureOpenAIChat:
    """Azure OpenAI-compatible client via raw HTTP (base_url=/openai/v1).

    Note: some Azure gateways/models are strict or inconsistent about tool calling.
    To avoid hard failures (e.g., 424 validation errors), this client defaults to
    plain chat (no tools). Tool-capable providers (Groq) remain available in failover.
    """

    def __init__(self, base_url: str, api_key: str, model: str,
                 temperature: float, max_tokens: int, timeout: int = 30):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._tools = None

    def bind_tools(self, tools):
        self._tools = tools
        return self

    def invoke(self, messages, **kwargs):
        url = self.base_url.rstrip("/") + "/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": _lc_messages_to_openai(messages),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        # Intentionally do NOT send tools by default to this gateway.
        headers = {
            "Content-Type": "application/json",
            "api-key": self.api_key,
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        # Provide a helpful error body on failure
        if resp.status_code >= 400:
            try:
                err = resp.json()
            except Exception:
                err = {"error": resp.text[:500]}
            raise RuntimeError(f"Azure OpenAI HTTP {resp.status_code}: {err}")

        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("Azure OpenAI returned no choices")

        msg = choices[0].get("message") or {}
        content = msg.get("content") or ""

        tool_calls = []
        for tc in (msg.get("tool_calls") or []):
            fn = (tc.get("function") or {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            tool_calls.append({
                "id": tc.get("id"),
                "name": fn.get("name"),
                "args": args,
                "type": "tool_call",
            })

        return AIMessage(content=content, tool_calls=tool_calls)

class RotatingLLM:
    def __init__(self, tools=None, temperature=0.2, max_tokens=4096):
        self.tools = tools
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        # Provider State
        self.azure_openai_base_url = Config.AZURE_OPENAI_BASE_URL
        self.azure_openai_api_key = Config.AZURE_OPENAI_API_KEY
        self.azure_openai_model = Config.AZURE_OPENAI_MODEL

        self.azure_endpoint = Config.AZURE_AI_ENDPOINT
        self.azure_api_key = Config.AZURE_AI_API_KEY
        self.azure_api_version = Config.AZURE_AI_API_VERSION
        self.azure_model = Config.AZURE_AI_MODEL

        self.gemini_keys = Config.GEMINI_API_KEYS
        self.gemini_model = Config.GEMINI_MODEL
        self.enable_gemini = bool(Config.ENABLE_GEMINI)
        self.groq_keys = Config.GROQ_API_KEYS
        self.groq_models = Config.LLM_MODELS
        
        self.current_gemini_key_idx = 0
        self.current_groq_key_idx = 0
        self.current_groq_model_idx = 0
        
        # Default priority
        self.active_provider = "groq" # Setting Groq as primary for stability

    def _get_llm(self, provider=None):
        target = provider or self.active_provider

        if target == "azure_openai" and self.azure_openai_base_url and self.azure_openai_api_key:
            return AzureOpenAIChat(
                base_url=self.azure_openai_base_url,
                api_key=self.azure_openai_api_key,
                model=self.azure_openai_model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                timeout=30,
            )

        if target == "azure_ai" and self.azure_endpoint and self.azure_api_key:
            return AzureAIInferenceChat(
                endpoint=self.azure_endpoint,
                api_key=self.azure_api_key,
                api_version=self.azure_api_version,
                model=self.azure_model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                timeout=30,
            )
        
        if target == "gemini" and self.gemini_keys:
            key = self.gemini_keys[self.current_gemini_key_idx]
            model_name = self.gemini_model.replace("models/", "")
            return ChatGoogleGenerativeAI(
                google_api_key=key,
                model=model_name,
                temperature=self.temperature,
                max_output_tokens=self.max_tokens,
                max_retries=0, # Rotation handled by this class
                timeout=10, # 10s timeout to prevent UI hang
            )
        else:
            # Default to Groq
            key = self.groq_keys[self.current_groq_key_idx]
            model = self.groq_models[self.current_groq_model_idx]
            return ChatGroq(
                api_key=key,
                model=model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                max_retries=0,
                timeout=15,
            )

    def invoke(self, messages, **kwargs):
        """Invoke LLM with multi-provider failover logic."""
        providers_to_try = ["azure_openai", "azure_ai", "groq", "gemini"]
        
        for provider in providers_to_try:
            if provider == "azure_openai" and not (self.azure_openai_base_url and self.azure_openai_api_key):
                continue
            if provider == "azure_ai" and not (self.azure_endpoint and self.azure_api_key):
                continue
            if provider == "gemini" and (not self.enable_gemini or not self.gemini_keys):
                continue
            if provider == "groq" and not self.groq_keys: continue
            
            # --- Try Provider ---
            if provider == "azure_openai":
                logger.info("LLM provider selected: azure_openai")
                try:
                    llm = self._get_llm("azure_openai")
                    if self.tools:
                        llm = llm.bind_tools(self.tools)
                    result = llm.invoke(messages, **kwargs)
                    logger.info("LLM provider succeeded: azure_openai")
                    return result
                except Exception as e:
                    error_str = str(e).lower()
                    logger.warning(f"Azure OpenAI failed: {error_str[:200]}")
                    continue

            if provider == "azure_ai":
                logger.info("LLM provider selected: azure_ai")
                try:
                    llm = self._get_llm("azure_ai")
                    if self.tools:
                        llm = llm.bind_tools(self.tools)
                    result = llm.invoke(messages, **kwargs)
                    logger.info("LLM provider succeeded: azure_ai")
                    return result
                except Exception as e:
                    error_str = str(e).lower()
                    logger.warning(f"Azure AI Inference failed: {error_str[:200]}")
                    continue

            if provider == "gemini":
                for _ in range(len(self.gemini_keys)):
                    try:
                        logger.info("LLM provider selected: gemini")
                        llm = self._get_llm("gemini")
                        # Gemini bind_tools is delicate, we bind here if tools present
                        if self.tools: llm = llm.bind_tools(self.tools)
                        result = llm.invoke(messages, **kwargs)
                        logger.info("LLM provider succeeded: gemini")
                        return result
                    except Exception as e:
                        error_str = str(e).lower()
                        logger.warning(f"Gemini (Key {self.current_gemini_key_idx}) failed: {error_str[:150]}")
                        self.current_gemini_key_idx = (self.current_gemini_key_idx + 1) % len(self.gemini_keys)
                        if any(ind in error_str for ind in ["429", "quota", "exhausted", "not_found", "404"]):
                            continue
                        break # Fatal error, try next provider
            
            elif provider == "groq":
                max_rotations = min(10, len(self.groq_keys) * len(self.groq_models))
                for _ in range(max_rotations):
                    try:
                        logger.info("LLM provider selected: groq")
                        llm = self._get_llm("groq")
                        if self.tools: llm = llm.bind_tools(self.tools)
                        result = llm.invoke(messages, **kwargs)
                        logger.info("LLM provider succeeded: groq")
                        return result
                    except Exception as e:
                        error_str = str(e).lower()
                        rotate_indicators = [
                            "429", "rate_limit", "limit", "413", "large", 
                            "decommissioned", "not supported", "model_not_found"
                        ]
                        if any(ind in error_str for ind in rotate_indicators) or "tool calling" in error_str:
                            logger.warning(f"Groq rotating: {error_str[:100]}...")
                            self.current_groq_model_idx = (self.current_groq_model_idx + 1) % len(self.groq_models)
                            if self.current_groq_model_idx == 0:
                                self.current_groq_key_idx = (self.current_groq_key_idx + 1) % len(self.groq_keys)
                            continue
                        break # Fatal error, try next provider

        raise Exception("Multi-provider failover exhausted. All keys/providers failed.")

def get_rotating_llm(tools=None, temperature=0.2, max_tokens=4096):
    """Factory function to get a rotating LLM instance."""
    return RotatingLLM(tools=tools, temperature=temperature, max_tokens=max_tokens)
