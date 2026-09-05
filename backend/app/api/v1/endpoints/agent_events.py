"""Agent Events HTTP endpoints."""

import logging
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api import deps
from app.db.session import get_db
from app.models.agent_task import (
    AgentEvent,
    AgentTask,
)
from app.models.project import Project
from app.models.user import User
from app.services.agent_audit.events import stream_events

logger = logging.getLogger(__name__)
from app.services.agent_audit.schemas import AgentEventResponse

router = APIRouter()


async def authorize_task(task_id, db, current_user):
    task = await db.get(AgentTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    project = await db.get(Project, task.project_id)
    if not project or project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此任务")


@router.get("/{task_id}/events")
@router.get("/{task_id}/stream")
async def stream_agent_events(
    task_id: str,
    request: Request,
    after_sequence: int = Query(0, ge=0),
    include_thinking: bool = True,
    include_tool_calls: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    await authorize_task(task_id, db, current_user)
    # Release the authorization transaction before a potentially long-lived stream.
    await db.rollback()
    previous = request.headers.get("last-event-id", "")
    if previous.isdigit():
        after_sequence = max(after_sequence, int(previous))
    return StreamingResponse(
        stream_events(
            task_id,
            request,
            after_sequence,
            include_thinking=include_thinking,
            include_tool_calls=include_tool_calls,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{task_id}/events/list", response_model=List[AgentEventResponse])
async def list_agent_events(
    task_id: str,
    after_sequence: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取 Agent 事件列表
    """
    task = await db.get(AgentTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    project = await db.get(Project, task.project_id)
    if not project or project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此任务")

    result = await db.execute(
        select(AgentEvent)
        .where(AgentEvent.task_id == task_id)
        .where(AgentEvent.sequence > after_sequence)
        .order_by(AgentEvent.sequence)
        .limit(limit)
    )
    events = result.scalars().all()

    # 🔥 Debug logging
    logger.debug(
        f"[EventsList] Task {task_id}: returning {len(events)} events (after_sequence={after_sequence})"
    )
    if events:
        logger.debug(
            f"[EventsList] First event: type={events[0].event_type}, seq={events[0].sequence}"
        )
        if len(events) > 1:
            logger.debug(
                f"[EventsList] Last event: type={events[-1].event_type}, seq={events[-1].sequence}"
            )

    return events
