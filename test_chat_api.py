import os
import sys
import logging

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.agent import build_agent, process_chat

# Configure logging to see what's happening
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("API-Test")

def test_chat():
    logger.info("Building agent graph...")
    graph = build_agent()
    
    test_message = "Hello JARVIS, this is an automated API health check. Are you online?"
    thread_id = "test-session-999"
    
    logger.info(f"Sending test message: {test_message}")
    try:
        # We don't need the full Flask app context for process_chat usually, 
        # but create_app ensures Config is loaded and TOOL_REGISTRY is ready.
        app = create_app()
        with app.app_context():
            result = process_chat(graph, test_message, thread_id)
            logger.info("--- API RESPONSE ---")
            logger.info(result)
            logger.info("--------------------")
            
            if result.get("status") == "success":
                print("\n✅ API IS WORKING!")
            else:
                print(f"\n❌ API FAILED: {result.get('response')}")
                
    except Exception as e:
        logger.error(f"FATAL ERROR during test: {e}", exc_info=True)

if __name__ == "__main__":
    test_chat()
