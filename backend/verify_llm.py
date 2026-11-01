"""
模块说明：后端模块：verify_llm。
"""

import asyncio
import logging
import sys
import os
sys.path.append(os.getcwd())

# Configure logging to stdout
logging.basicConfig(
    stream=sys.stdout, 
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

print("Starting verification script...", flush=True)

try:
    from app.services.llm.service import LLMService
    print("Imported LLMService", flush=True)
except Exception as e:
    print(f"Failed to import LLMService: {e}", flush=True)
    sys.exit(1)

async def test_llm():
    try:
        print("Initializing LLMService...", flush=True)
        service = LLMService()
        print(f"Config: Provider={service.config.provider}, Model={service.config.model}", flush=True)
        
        messages = [{"role": "user", "content": "Hello, are you working?"}]
        print("Sending request...", flush=True)
        
        accumulated = ""
        async for chunk in service.chat_completion_stream(messages):
            if chunk["type"] == "token":
                print(f"Token: {chunk['content']}", end="", flush=True)
                accumulated += chunk['content']
            elif chunk["type"] == "done":
                print(f"\nDone. Usage: {chunk.get('usage')}", flush=True)
                print(f"Finish reason: {chunk.get('finish_reason')}", flush=True)
            elif chunk["type"] == "error":
                print(f"\nError: {chunk.get('error')}", flush=True)

        print(f"\nFinal content: '{accumulated}'", flush=True)
    except Exception as e:
        print(f"\nException in test_llm: {e}", flush=True)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_llm())
