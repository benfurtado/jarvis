"""
Jarvis LLM Module — Handles LLM instantiation with automatic rotation and failover.
"""
import logging
from langchain_groq import ChatGroq
from app.config import Config

logger = logging.getLogger("Jarvis.LLM")

class RotatingLLM:
    def __init__(self, api_keys=None, models=None, tools=None, temperature=0.2, max_tokens=4096):
        self.api_keys = api_keys if api_keys else Config.GROQ_API_KEYS
        self.models = models if models else Config.LLM_MODELS
        self.tools = tools
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.current_key_idx = 0
        self.current_model_idx = 0
        
        if not self.api_keys:
            self.api_keys = [Config.GROQ_API_KEY]
        if not self.models:
            self.models = [Config.LLM_MODEL]
            
        if not self.api_keys or not self.api_keys[0]:
            logger.error("No GROQ_API_KEY found in config!")

    def _get_llm(self):
        key = self.api_keys[self.current_key_idx]
        model = self.models[self.current_model_idx]
        llm = ChatGroq(
            api_key=key,
            model=model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        if self.tools:
            return llm.bind_tools(self.tools)
        return llm

    def invoke(self, messages, **kwargs):
        first_key_idx = self.current_key_idx
        first_model_idx = self.current_model_idx
        import time
        
        while True:
            try:
                llm_instance = self._get_llm()
                return llm_instance.invoke(messages, **kwargs)
            except Exception as e:
                error_str = str(e)
                # Handle 429 (Rate Limit), 413 (Token Limit), and 400 (Incorrect model for tool calling)
                rate_limit_indicators = [
                    "429", "rate_limit", "tokens per minute", "requests per minute",
                    "RPM", "TPM", "TPD", "tokens per day", "request too large", "413"
                ]
                
                is_retryable = any(ind in error_str.lower() for ind in rate_limit_indicators) or \
                               ("400" in error_str and "tool calling" in error_str.lower())
                
                if is_retryable:
                    error_type = "Tool calling not supported" if "tool calling" in error_str.lower() else "Rate limit hit"
                    current_model = self.models[self.current_model_idx]
                    
                    logger.warning(
                        f"{error_type} for model {current_model}. Rotating..."
                    )
                    
                    # Try next model
                    self.current_model_idx = (self.current_model_idx + 1) % len(self.models)
                    
                    # If we cycled through all models, try next key
                    if self.current_model_idx == 0:
                        self.current_key_idx = (self.current_key_idx + 1) % len(self.api_keys)
                        
                    # If we are back to the original key and model, stop
                    if (self.current_key_idx == first_key_idx and 
                        self.current_model_idx == first_model_idx):
                        logger.error(f"Cycled through all {len(self.api_keys)} keys and {len(self.models)} models. FAILED.")
                        raise e
                    
                    # Small sleep before retry to give the provider/balancer a moment
                    time.sleep(2)
                else:
                    raise e

def get_rotating_llm(tools=None, temperature=0.2, max_tokens=4096):
    """Factory function to get a rotating LLM instance."""
    return RotatingLLM(tools=tools, temperature=temperature, max_tokens=max_tokens)
