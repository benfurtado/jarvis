"""
Jarvis LLM Module — Handles LLM instantiation with automatic rotation and multi-provider failover.
Supports Gemini and Groq.
"""
import logging
import time
import threading
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
from app.config import Config

logger = logging.getLogger("Jarvis.LLM")

class RotatingLLM:
    def __init__(self, tools=None, temperature=0.2, max_tokens=4096):
        self.tools = tools
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        # Provider State
        self.gemini_keys = Config.GEMINI_API_KEYS
        self.gemini_model = Config.GEMINI_MODEL
        self.groq_keys = Config.GROQ_API_KEYS
        self.groq_models = Config.LLM_MODELS
        
        self.current_gemini_key_idx = 0
        self.current_groq_key_idx = 0
        self.current_groq_model_idx = 0
        
        # Default priority
        self.active_provider = "groq" # Setting Groq as primary for stability

    def _get_llm(self, provider=None):
        target = provider or self.active_provider
        
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
        providers_to_try = ["groq", "gemini"] # Try Groq first for stability
        
        for provider in providers_to_try:
            if provider == "gemini" and not self.gemini_keys: continue
            if provider == "groq" and not self.groq_keys: continue
            
            # --- Try Provider ---
            if provider == "gemini":
                for _ in range(len(self.gemini_keys)):
                    try:
                        llm = self._get_llm("gemini")
                        # Gemini bind_tools is delicate, we bind here if tools present
                        if self.tools: llm = llm.bind_tools(self.tools)
                        return llm.invoke(messages, **kwargs)
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
                        llm = self._get_llm("groq")
                        if self.tools: llm = llm.bind_tools(self.tools)
                        return llm.invoke(messages, **kwargs)
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
