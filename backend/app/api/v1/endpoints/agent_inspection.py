"""Agent Inspection HTTP endpoints."""

import json
import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api import deps
from app.db.session import get_db
from app.models.agent_task import (
    AgentTask,
)
from app.models.project import Project
from app.models.user import User

logger = logging.getLogger(__name__)
from app.services.agent_audit.schemas import (
    AgentTreeNodeResponse,
    AgentTreeResponse,
    CheckpointResponse,
)

router = APIRouter()


@router.get("/{task_id}/agent-tree", response_model=AgentTreeResponse)
async def get_agent_tree(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取任务的 Agent 树结构

    返回动态 Agent 树的完整结构，包括：
    - 所有 Agent 节点
    - 父子关系
    - 执行状态
    - 发现统计
    """
    task = await db.get(AgentTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    project = await db.get(Project, task.project_id)
    if not project or project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此任务")

    from app.models.audit_job import AuditJob

    job = await db.get(AuditJob, task_id)
    if task.status not in {"completed", "failed", "cancelled"} and job:
        snapshot = (job.checkpoint or {}).get("live_tree")
        if snapshot:
            return AgentTreeResponse(**snapshot)

    # 从数据库获取（已完成的任务）
    from app.models.agent_task import AgentTreeNode

    result = await db.execute(
        select(AgentTreeNode)
        .where(AgentTreeNode.task_id == task_id)
        .order_by(AgentTreeNode.depth, AgentTreeNode.created_at)
    )
    db_nodes = result.scalars().all()

    if not db_nodes:
        return AgentTreeResponse(
            task_id=task_id,
            nodes=[],
        )

    # 构建响应
    nodes = []
    root_id = None
    running = 0
    completed = 0
    failed = 0

    for node in db_nodes:
        if node.parent_agent_id is None:
            root_id = node.agent_id

        if node.status == "running":
            running += 1
        elif node.status == "completed":
            completed += 1
        elif node.status == "failed":
            failed += 1

        # 🔥 FIX: 对于 Orchestrator (root agent)，使用 task 的 findings_count
        # 这确保了正确显示聚合的 findings 总数
        if node.parent_agent_id is None:
            # Root agent uses task's total findings
            node_findings_count = task.findings_count or 0
        else:
            node_findings_count = node.findings_count or 0

        nodes.append(
            AgentTreeNodeResponse(
                id=node.id,
                agent_id=node.agent_id,
                agent_name=node.agent_name,
                agent_type=node.agent_type,
                parent_agent_id=node.parent_agent_id,
                depth=node.depth,
                task_description=node.task_description,
                knowledge_modules=node.knowledge_modules,
                status=node.status,
                result_summary=node.result_summary,
                findings_count=node_findings_count,
                iterations=node.iterations or 0,
                tokens_used=node.tokens_used or 0,
                tool_calls=node.tool_calls or 0,
                duration_ms=node.duration_ms,
                children=[],
            )
        )

    # 🔥 使用 task.findings_count 作为 total_findings，确保一致性
    return AgentTreeResponse(
        task_id=task_id,
        root_agent_id=root_id,
        total_agents=len(nodes),
        running_agents=running,
        completed_agents=completed,
        failed_agents=failed,
        total_findings=task.findings_count or 0,
        nodes=nodes,
    )


@router.get("/{task_id}/checkpoints", response_model=List[CheckpointResponse])
async def list_checkpoints(
    task_id: str,
    agent_id: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取任务的检查点列表

    用于：
    - 查看执行历史
    - 状态恢复
    - 调试分析
    """
    task = await db.get(AgentTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    project = await db.get(Project, task.project_id)
    if not project or project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此任务")

    from app.models.agent_task import AgentCheckpoint

    query = select(AgentCheckpoint).where(AgentCheckpoint.task_id == task_id)

    if agent_id:
        query = query.where(AgentCheckpoint.agent_id == agent_id)

    query = query.order_by(AgentCheckpoint.created_at.desc()).limit(limit)

    result = await db.execute(query)
    checkpoints = result.scalars().all()

    return [
        CheckpointResponse(
            id=cp.id,
            agent_id=cp.agent_id,
            agent_name=cp.agent_name,
            agent_type=cp.agent_type,
            iteration=cp.iteration,
            status=cp.status,
            total_tokens=cp.total_tokens or 0,
            tool_calls=cp.tool_calls or 0,
            findings_count=cp.findings_count or 0,
            checkpoint_type=cp.checkpoint_type or "auto",
            checkpoint_name=cp.checkpoint_name,
            created_at=cp.created_at.isoformat() if cp.created_at else None,
        )
        for cp in checkpoints
    ]


@router.get("/{task_id}/checkpoints/{checkpoint_id}")
async def get_checkpoint_detail(
    task_id: str,
    checkpoint_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取检查点详情

    返回完整的 Agent 状态数据
    """
    task = await db.get(AgentTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    project = await db.get(Project, task.project_id)
    if not project or project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此任务")

    from app.models.agent_task import AgentCheckpoint

    checkpoint = await db.get(AgentCheckpoint, checkpoint_id)
    if not checkpoint or checkpoint.task_id != task_id:
        raise HTTPException(status_code=404, detail="检查点不存在")

    # 解析状态数据
    state_data = {}
    if checkpoint.state_data:
        try:
            state_data = json.loads(checkpoint.state_data)
        except json.JSONDecodeError:
            pass

    return {
        "id": checkpoint.id,
        "task_id": checkpoint.task_id,
        "agent_id": checkpoint.agent_id,
        "agent_name": checkpoint.agent_name,
        "agent_type": checkpoint.agent_type,
        "parent_agent_id": checkpoint.parent_agent_id,
        "iteration": checkpoint.iteration,
        "status": checkpoint.status,
        "total_tokens": checkpoint.total_tokens,
        "tool_calls": checkpoint.tool_calls,
        "findings_count": checkpoint.findings_count,
        "checkpoint_type": checkpoint.checkpoint_type,
        "checkpoint_name": checkpoint.checkpoint_name,
        "state_data": state_data,
        "metadata": checkpoint.checkpoint_metadata,
        "created_at": checkpoint.created_at.isoformat() if checkpoint.created_at else None,
    }
