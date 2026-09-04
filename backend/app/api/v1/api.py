"""
模块说明：API 路由与依赖定义：api。
"""

from fastapi import APIRouter
from app.api.v1.endpoints import auth, users, projects, tasks, scan, members, config, database, prompts, rules, agent_tasks, embedding_config, ssh_keys

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(members.router, prefix="/projects", tags=["members"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(scan.router, prefix="/scan", tags=["scan"])
api_router.include_router(config.router, prefix="/config", tags=["config"])
api_router.include_router(database.router, prefix="/database", tags=["database"])
api_router.include_router(prompts.router, prefix="/prompts", tags=["prompts"])
api_router.include_router(rules.router, prefix="/rules", tags=["rules"])
api_router.include_router(agent_tasks.router, prefix="/agent-tasks", tags=["agent-tasks"])
api_router.include_router(embedding_config.router, prefix="/embedding", tags=["embedding"])
api_router.include_router(ssh_keys.router, prefix="/ssh-keys", tags=["ssh-keys"])
