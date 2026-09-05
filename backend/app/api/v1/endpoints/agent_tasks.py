"""
DeepAudit Agent 审计任务 API
基于 LangGraph 的 Agent 审计
"""

from fastapi import Response
from sqlalchemy import func, case
from app.services.audit_queue import enqueue, request_cancel

import logging
from typing import Any, List, Optional
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api import deps
from app.db.session import get_db
from app.models.agent_task import (
    AgentTask,
    AgentEvent,
    AgentFinding,
    AgentTaskStatus,
    AgentTaskPhase,
    AgentEventType,
    VulnerabilitySeverity,
    FindingStatus,
)
from app.models.project import Project
from app.models.user import User

logger = logging.getLogger(__name__)
from app.services.agent_audit.schemas import (
    AgentFindingResponse,
    AgentTaskCreate,
    AgentTaskResponse,
    TaskSummaryResponse,
)
from . import agent_events, agent_inspection, agent_reports

router = APIRouter()
router.include_router(agent_events.router)
router.include_router(agent_inspection.router)
router.include_router(agent_reports.router)
from app.services.agent_audit.runtime import (
    _running_tasks,
    _running_asyncio_tasks,
    _running_orchestrators,
    _cancelled_tasks,
)

@router.post("/", response_model=AgentTaskResponse)
async def create_agent_task(
    request: AgentTaskCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    创建并启动 Agent 审计任务
    """
    # 验证项目
    project = await db.get(Project, request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此项目")

    # 创建任务
    task = AgentTask(
        id=str(uuid4()),
        project_id=project.id,
        name=request.name or f"Agent Audit - {datetime.now().strftime('%Y%m%d_%H%M%S')}",
        description=request.description,
        status=AgentTaskStatus.PENDING,
        current_phase=AgentTaskPhase.PLANNING,
        target_vulnerabilities=request.target_vulnerabilities,
        verification_level=request.verification_level or "sandbox",
        branch_name=request.branch_name,  # 保存用户选择的分支
        exclude_patterns=request.exclude_patterns,
        target_files=request.target_files,
        max_iterations=request.max_iterations or 50,
        timeout_seconds=request.timeout_seconds or 1800,
        created_by=current_user.id,
    )

    db.add(task)
    source = None
    if project.source_type == "zip":
        from app.services.zip_storage import load_project_zip

        source = await load_project_zip(project.id)
        if not source:
            raise HTTPException(status_code=400, detail="请先上传项目 ZIP")
    await enqueue(db, task, "agent", zip_path=source)
    await db.commit()
    await db.refresh(task)

    logger.info(f"Created agent task {task.id} for project {project.name}")

    return task


@router.get("/", response_model=List[AgentTaskResponse])
async def list_agent_tasks(
    response: Response = None,
    search: str = Query("", max_length=200),
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取 Agent 任务列表
    """
    # 获取用户的项目
    projects_result = await db.execute(
        select(Project.id).where(Project.owner_id == current_user.id)
    )
    user_project_ids = [p[0] for p in projects_result.fetchall()]

    if not user_project_ids:
        return []

    # 构建查询
    query = select(AgentTask).where(AgentTask.project_id.in_(user_project_ids))

    if project_id:
        query = query.where(AgentTask.project_id == project_id)

    if status:
        query = query.where(AgentTask.status == status)
    if search:
        pattern = "%" + search.replace("%", r"\%").replace("_", r"\_") + "%"
        query = query.where(AgentTask.name.ilike(pattern) | AgentTask.task_type.ilike(pattern))
    if response is not None:
        response.headers["X-Total-Count"] = str(
            await db.scalar(select(func.count()).select_from(query.subquery()))
        )
    query = query.order_by(AgentTask.created_at.desc(), AgentTask.id.desc())
    query = query.offset(skip).limit(limit)

    result = await db.execute(query)
    tasks = result.scalars().all()

    return tasks


@router.get("/{task_id}", response_model=AgentTaskResponse)
async def get_agent_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取 Agent 任务详情
    """
    task = await db.get(AgentTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 检查权限
    project = await db.get(Project, task.project_id)
    if not project or project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此任务")

    # 构建响应，确保所有字段都包含
    try:
        # 计算进度百分比
        progress = 0.0
        if hasattr(task, "progress_percentage"):
            progress = task.progress_percentage
        elif task.status == AgentTaskStatus.COMPLETED:
            progress = 100.0
        elif task.status in [AgentTaskStatus.FAILED, AgentTaskStatus.CANCELLED]:
            progress = 0.0

        # 🔥 从运行中的 Orchestrator 获取实时统计
        total_iterations = task.total_iterations or 0
        tool_calls_count = task.tool_calls_count or 0
        tokens_used = task.tokens_used or 0

        orchestrator = _running_orchestrators.get(task_id)
        if orchestrator and task.status == AgentTaskStatus.RUNNING:
            # 从 Orchestrator 获取统计
            stats = orchestrator.get_stats()
            total_iterations = stats.get("iterations", 0)
            tool_calls_count = stats.get("tool_calls", 0)
            tokens_used = stats.get("tokens_used", 0)

            # 累加子 Agent 的统计
            if hasattr(orchestrator, "sub_agents"):
                for agent in orchestrator.sub_agents.values():
                    if hasattr(agent, "get_stats"):
                        sub_stats = agent.get_stats()
                        total_iterations += sub_stats.get("iterations", 0)
                        tool_calls_count += sub_stats.get("tool_calls", 0)
                        tokens_used += sub_stats.get("tokens_used", 0)

        # 手动构建响应数据
        response_data = {
            "id": task.id,
            "project_id": task.project_id,
            "name": task.name,
            "description": task.description,
            "task_type": task.task_type or "agent_audit",
            "status": task.status,
            "current_phase": task.current_phase,
            "current_step": task.current_step,
            "total_files": task.total_files or 0,
            "indexed_files": task.indexed_files or 0,
            "analyzed_files": task.analyzed_files or 0,
            "total_chunks": task.total_chunks or 0,
            "total_iterations": total_iterations,
            "tool_calls_count": tool_calls_count,
            "tokens_used": tokens_used,
            "findings_count": task.findings_count or 0,
            "total_findings": task.findings_count or 0,  # 兼容字段
            "verified_count": task.verified_count or 0,
            "verified_findings": task.verified_count or 0,  # 兼容字段
            "false_positive_count": task.false_positive_count or 0,
            "critical_count": task.critical_count or 0,
            "high_count": task.high_count or 0,
            "medium_count": task.medium_count or 0,
            "low_count": task.low_count or 0,
            "quality_score": float(task.quality_score or 0.0),
            "security_score": float(task.security_score)
            if task.security_score is not None
            else None,
            "progress_percentage": progress,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "error_message": task.error_message,
            "audit_scope": task.audit_scope,
            "target_vulnerabilities": task.target_vulnerabilities,
            "verification_level": task.verification_level,
            "exclude_patterns": task.exclude_patterns,
            "target_files": task.target_files,
        }

        return AgentTaskResponse(**response_data)
    except Exception as e:
        logger.error(f"Error serializing task {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"序列化任务数据失败: {str(e)}")


@router.post("/{task_id}/cancel")
async def cancel_agent_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    取消 Agent 任务
    """
    task = await db.get(AgentTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    project = await db.get(Project, task.project_id)
    if not project or project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作此任务")

    if task.status in [
        AgentTaskStatus.COMPLETED,
        AgentTaskStatus.FAILED,
        AgentTaskStatus.CANCELLED,
    ]:
        raise HTTPException(status_code=400, detail="任务已结束，无法取消")

    await request_cancel(db, task_id)

    # 🔥 0. 立即标记任务为已取消（用于前置操作的取消检查）
    _cancelled_tasks.add(task_id)
    logger.info(f"[Cancel] Added task {task_id} to cancelled set")

    # 🔥 1. 设置 Agent 的取消标志
    runner = _running_tasks.get(task_id)
    if runner:
        runner.cancel()
        logger.info(f"[Cancel] Set cancel flag for task {task_id}")

    # Stop only this task's dynamically registered descendants.
    from app.services.agent.core.graph_controller import agent_graph_controller

    try:
        if runner:
            stop_result = agent_graph_controller.stop_agent_tree(runner.agent_id)
            logger.info(f"[Cancel] Stopped task {task_id} agents: {stop_result}")
    except Exception as e:
        logger.warning(f"[Cancel] Failed to stop agents via registry: {e}")

    # 🔥 3. 强制取消 asyncio Task（立即中断 LLM 调用）
    asyncio_task = _running_asyncio_tasks.get(task_id)
    if asyncio_task and not asyncio_task.done():
        asyncio_task.cancel()
        logger.info(f"[Cancel] Cancelled asyncio task for {task_id}")

    # 更新状态
    task.status = AgentTaskStatus.CANCELLED
    task.completed_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info(f"[Cancel] Task {task_id} cancelled successfully")
    return {"message": "任务已取消", "task_id": task_id}


@router.get("/{task_id}/findings", response_model=List[AgentFindingResponse])
async def list_agent_findings(
    task_id: str,
    response: Response = None,
    severity: Optional[str] = None,
    verified_only: bool = False,
    is_verified: Optional[bool] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取 Agent 发现列表
    """
    task = await db.get(AgentTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    project = await db.get(Project, task.project_id)
    if not project or project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此任务")

    query = select(AgentFinding).where(AgentFinding.task_id == task_id)

    if severity:
        query = query.where(AgentFinding.severity == severity)

    if is_verified is not None:
        query = query.where(AgentFinding.is_verified == is_verified)
    elif verified_only:
        query = query.where(AgentFinding.is_verified == True)

    # 按严重程度排序
    severity_order = {
        VulnerabilitySeverity.CRITICAL: 0,
        VulnerabilitySeverity.HIGH: 1,
        VulnerabilitySeverity.MEDIUM: 2,
        VulnerabilitySeverity.LOW: 3,
        VulnerabilitySeverity.INFO: 4,
    }

    if response is not None:
        response.headers["X-Total-Count"] = str(
            await db.scalar(select(func.count()).select_from(query.subquery()))
        )
    query = query.order_by(
        case(severity_order, value=AgentFinding.severity, else_=5),
        AgentFinding.created_at.desc(),
        AgentFinding.id.desc(),
    )
    query = query.offset(skip).limit(limit)

    result = await db.execute(query)
    findings = result.scalars().all()

    return findings


@router.get("/{task_id}/summary", response_model=TaskSummaryResponse)
async def get_task_summary(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取任务摘要
    """
    task = await db.get(AgentTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    project = await db.get(Project, task.project_id)
    if not project or project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此任务")

    # 获取所有发现
    result = await db.execute(select(AgentFinding).where(AgentFinding.task_id == task_id))
    findings = result.scalars().all()

    # 统计
    severity_distribution = {}
    vulnerability_types = {}
    verified_count = 0

    for f in findings:
        # severity 和 vulnerability_type 已经是字符串
        sev = str(f.severity)
        vtype = str(f.vulnerability_type)

        severity_distribution[sev] = severity_distribution.get(sev, 0) + 1
        vulnerability_types[vtype] = vulnerability_types.get(vtype, 0) + 1

        if f.is_verified:
            verified_count += 1

    # 计算持续时间
    duration = None
    if task.started_at and task.completed_at:
        duration = int((task.completed_at - task.started_at).total_seconds())

    # 获取已完成的阶段
    phases_result = await db.execute(
        select(AgentEvent.phase)
        .where(AgentEvent.task_id == task_id)
        .where(AgentEvent.event_type == AgentEventType.PHASE_COMPLETE)
        .distinct()
    )
    phases = [str(p[0]) for p in phases_result.fetchall() if p[0]]

    return TaskSummaryResponse(
        task_id=task_id,
        status=str(task.status),  # status 已经是字符串
        security_score=task.security_score,
        total_findings=len(findings),
        verified_findings=verified_count,
        severity_distribution=severity_distribution,
        vulnerability_types=vulnerability_types,
        duration_seconds=duration,
        phases_completed=phases,
    )


@router.patch("/{task_id}/findings/{finding_id}")
async def update_finding_status(
    task_id: str,
    finding_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    更新发现状态
    """
    status = body.get("status")
    if not status:
        raise HTTPException(status_code=400, detail="缺少 status 字段")

    task = await db.get(AgentTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    project = await db.get(Project, task.project_id)
    if not project or project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作")

    finding = await db.get(AgentFinding, finding_id)
    if not finding or finding.task_id != task_id:
        raise HTTPException(status_code=404, detail="发现不存在")

    VALID_FINDING_STATUSES = {
        FindingStatus.NEW,
        FindingStatus.ANALYZING,
        FindingStatus.VERIFIED,
        FindingStatus.FALSE_POSITIVE,
        FindingStatus.NEEDS_REVIEW,
        FindingStatus.FIXED,
        FindingStatus.WONT_FIX,
        FindingStatus.DUPLICATE,
    }
    if status not in VALID_FINDING_STATUSES:
        raise HTTPException(status_code=400, detail=f"无效的状态: {status}")

    finding.status = status

    await db.commit()

    return {"message": "状态已更新", "finding_id": finding_id, "status": status}


# ============ Helper Functions ============


# ============ Agent Tree API ============


# ============ Checkpoint API ============


# ============ Report Generation API ============
