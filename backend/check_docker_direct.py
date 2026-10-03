"""
模块说明：后端模块：check_docker_direct。
"""


import sys
try:
    import docker
    print(f"Docker module: {docker.__file__}")
    client = docker.from_env()
    print("Client created")
    client.ping()
    print("Docker is available and ping successful")
    print(f"Docker version: {client.version()}")
except ImportError:
    print("Docker library not installed")
except Exception as e:
    print(f"Docker unavailable: {e}")
    import traceback
    traceback.print_exc()
