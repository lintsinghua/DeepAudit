"""Cancelling one audit must never stop another audit's agents."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.agent.core import graph_controller
from app.services.agent.core.registry import AgentRegistry


@pytest.fixture
def task_trees(monkeypatch):
    registry = AgentRegistry()
    agents = {}
    for agent_id, parent in [
        ("a", None), ("a-child", "a"), ("a-grandchild", "a-child"),
        ("b", None), ("b-child", "b"),
    ]:
        agents[agent_id] = MagicMock()
        registry.register_agent(
            agent_id, agent_id, "analysis", "audit", parent_id=parent,
            agent_instance=agents[agent_id],
        )
    monkeypatch.setattr(graph_controller, "agent_registry", registry)
    return registry, agents


def test_only_selected_tree_is_stopped(task_trees):
    registry, agents = task_trees
    result = graph_controller.agent_graph_controller.stop_agent_tree("a")
    assert result["success"]
    assert set(result["stopped"]) == {"a", "a-child", "a-grandchild"}
    for agent_id in ("a", "a-child", "a-grandchild"):
        agents[agent_id].cancel.assert_called_once()
    for agent_id in ("b", "b-child"):
        agents[agent_id].cancel.assert_not_called()
        assert registry.get_agent_node(agent_id)["status"] == "running"


def test_unknown_root_never_falls_back_to_global_stop(task_trees):
    _, agents = task_trees
    result = graph_controller.agent_graph_controller.stop_agent_tree("missing")
    assert not result["success"]
    for agent in agents.values():
        agent.cancel.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("runner_present", [True, False])
async def test_cancel_endpoint_scopes_stop_to_task(task_trees, monkeypatch, runner_present):
    from app.api.v1.endpoints import agent_tasks

    _, agents = task_trees
    task = SimpleNamespace(
        id="task-a", project_id="project-a", status=agent_tasks.AgentTaskStatus.RUNNING,
    )
    db = AsyncMock()
    db.get.side_effect = [task, SimpleNamespace(owner_id="owner-a")]
    runner = SimpleNamespace(agent_id="a", cancel=MagicMock())
    monkeypatch.setattr(agent_tasks, "_running_tasks", {"task-a": runner} if runner_present else {})
    monkeypatch.setattr(agent_tasks, "_running_asyncio_tasks", {})
    monkeypatch.setattr(agent_tasks, "_cancelled_tasks", set())
    await agent_tasks.cancel_agent_task("task-a", db, SimpleNamespace(id="owner-a"))
    assert task.status == agent_tasks.AgentTaskStatus.CANCELLED
    assert "task-a" in agent_tasks._cancelled_tasks
    db.commit.assert_awaited_once()
    if runner_present:
        runner.cancel.assert_called_once()
        agents["a-grandchild"].cancel.assert_called_once()
    agents["b"].cancel.assert_not_called()
    agents["b-child"].cancel.assert_not_called()
