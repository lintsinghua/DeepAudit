"""Replayable event stream shared by every API replica."""

import asyncio
import json
import time

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.agent_task import AgentEvent, AgentTask


def event_payload(event):
    return {
        "id": event.id,
        "type": event.event_type,
        "event_type": event.event_type,
        "phase": event.phase,
        "message": event.message,
        "sequence": event.sequence,
        "timestamp": event.created_at.isoformat() if event.created_at else None,
        "tool_name": event.tool_name,
        "tool_input": event.tool_input,
        "tool_output": event.tool_output,
        "tool_duration_ms": event.tool_duration_ms,
        "finding_id": event.finding_id,
        "tokens_used": event.tokens_used,
        "metadata": event.event_metadata,
        "tool": {
            "name": event.tool_name,
            "input": event.tool_input,
            "output": event.tool_output,
            "duration_ms": event.tool_duration_ms,
        }
        if event.tool_name
        else None,
    }


def encode_sse(payload):
    sequence = payload.get("sequence")
    event_id = f"id: {sequence}\n" if sequence is not None else ""
    return (
        f"{event_id}event: {payload['type']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
    )


async def stream_events(
    task_id, request, after_sequence=0, *, include_thinking=True, include_tool_calls=True
):
    cursor = after_sequence
    last_heartbeat = time.monotonic()
    while not await request.is_disconnected():
        async with async_session_factory() as db:
            events = list(
                await db.scalars(
                    select(AgentEvent)
                    .where(
                        AgentEvent.task_id == task_id,
                        AgentEvent.sequence > cursor,
                    )
                    .order_by(AgentEvent.sequence)
                    .limit(200)
                )
            )
            task = await db.get(AgentTask, task_id)
            status = task.status if task else "deleted"
        for event in events:
            cursor = event.sequence
            if not include_thinking and str(event.event_type).startswith("thinking"):
                continue
            if not include_tool_calls and str(event.event_type).startswith("tool"):
                continue
            yield encode_sse(event_payload(event))
        if not events and status in {"completed", "failed", "cancelled", "deleted"}:
            yield encode_sse({"type": "task_end", "status": status, "sequence": cursor})
            return
        if time.monotonic() - last_heartbeat >= 15:
            yield encode_sse({"type": "heartbeat"})
            last_heartbeat = time.monotonic()
        if len(events) < 200:
            await asyncio.sleep(0.25)
