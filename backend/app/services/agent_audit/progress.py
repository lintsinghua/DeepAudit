"""Publish live worker state for API replicas without sharing process memory."""

from sqlalchemy import update

from app.db.session import AsyncSessionLocal
from app.models.agent_task import AgentTask
from app.models.audit_job import AuditJob

from .runtime import _running_orchestrators


async def publish_progress(task_id):
    orchestrator = _running_orchestrators.get(task_id)
    if not orchestrator:
        return
    from app.services.agent.core import agent_registry

    tree = agent_registry.get_agent_tree()
    totals = {"iterations": 0, "tool_calls": 0, "tokens_used": 0}
    nodes = []
    for agent_id, node in tree.get("nodes", {}).items():
        instance = agent_registry.get_agent(agent_id)
        stats = instance.get_stats() if instance and hasattr(instance, "get_stats") else {}
        for key in totals:
            totals[key] += stats.get(key, 0)
        result = node.get("result") or {}
        nodes.append(
            dict(
                id=agent_id,
                agent_id=agent_id,
                agent_name=node.get("name", "Unknown"),
                agent_type=node.get("type", "unknown"),
                parent_agent_id=node.get("parent_id"),
                task_description=node.get("task"),
                knowledge_modules=node.get("knowledge_modules") or [],
                status=node.get("status", "unknown"),
                findings_count=len(result.get("findings", [])),
                iterations=stats.get("iterations", 0),
                tool_calls=stats.get("tool_calls", 0),
                tokens_used=stats.get("tokens_used", 0),
                children=[],
            )
        )
    async with AsyncSessionLocal() as db:
        job = await db.get(AuditJob, task_id, with_for_update=True)
        if not job:
            return
        task = await db.get(AgentTask, task_id)
        snapshot = dict(
            task_id=task_id,
            root_agent_id=tree.get("root_agent_id"),
            nodes=nodes,
            total_agents=len(nodes),
            total_findings=task.findings_count or 0,
            running_agents=sum(n["status"] == "running" for n in nodes),
            completed_agents=sum(n["status"] == "completed" for n in nodes),
            failed_agents=sum(n["status"] == "failed" for n in nodes),
        )
        job.checkpoint = {**(job.checkpoint or {}), "live_tree": snapshot}
        await db.execute(
            update(AgentTask)
            .where(AgentTask.id == task_id)
            .values(
                total_iterations=totals["iterations"],
                tool_calls_count=totals["tool_calls"],
                tokens_used=totals["tokens_used"],
            )
        )
        await db.commit()
