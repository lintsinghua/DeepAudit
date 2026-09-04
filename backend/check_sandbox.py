"""
模块说明：后端模块：check_sandbox。
"""


import asyncio
import logging
import sys
import os

# Add backend to path
sys.path.append(os.getcwd())

# Configure logging
logging.basicConfig(level=logging.INFO)

from app.services.agent.tools.sandbox_tool import SandboxManager

async def main():
    print("Checking SandboxManager...")
    mgr = SandboxManager()
    await mgr.initialize()
    print(f"Is available: {mgr.is_available}")
    print(f"Diagnosis: {mgr.get_diagnosis()}")
    
    if mgr.is_available:
        print("Docker client created successfully.")
        try:
            ver = mgr._docker_client.version()
            print(f"Docker version: {ver}")
        except Exception as e:
            print(f"Error getting version: {e}")

if __name__ == "__main__":
    asyncio.run(main())
