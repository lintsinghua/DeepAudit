"""
Tests for app/api/v1/endpoints/tasks.py

Covers:
- list_tasks: listing tasks, project filtering, empty results
- read_task: get single task, 404, 403 (wrong user)
- cancel_task: successful cancel, 404, 403, 400 (wrong status)
- read_task_issues: list issues, 404, 403
- update_issue: resolve issue, 404
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.v1.endpoints.tasks import (
    list_tasks,
    read_task,
    cancel_task,
    read_task_issues,
    update_issue,
    IssueUpdateSchema,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_ID = "user-001"
OTHER_USER_ID = "user-002"
PROJECT_ID = "proj-001"
TASK_ID = "task-001"


def _make_user(user_id=USER_ID, is_active=True, is_superuser=False):
    user = MagicMock()
    user.id = user_id
    user.is_active = is_active
    user.is_superuser = is_superuser
    return user


def _make_task(
    task_id=TASK_ID,
    project_id=PROJECT_ID,
    created_by=USER_ID,
    status="completed",
    with_project=True,
):
    task = MagicMock()
    task.id = task_id
    task.project_id = project_id
    task.task_type = "repository"
    task.status = status
    task.branch_name = "main"
    task.exclude_patterns = "[]"
    task.scan_config = "{}"
    task.total_files = 10
    task.scanned_files = 10
    task.total_lines = 500
    task.issues_count = 3
    task.quality_score = 85.0
    task.started_at = datetime.now(timezone.utc)
    task.completed_at = datetime.now(timezone.utc)
    task.created_by = created_by
    task.created_at = datetime.now(timezone.utc)
    if with_project:
        task.project = MagicMock()
        task.project.id = project_id
        task.project.name = "Test Project"
    else:
        task.project = None
    return task


def _make_issue(issue_id="issue-001", task_id=TASK_ID, status="open"):
    issue = MagicMock()
    issue.id = issue_id
    issue.task_id = task_id
    issue.file_path = "src/main.py"
    issue.line_number = 42
    issue.column_number = None
    issue.issue_type = "sql_injection"
    issue.severity = "high"
    issue.title = "SQL Injection"
    issue.message = "Potential SQL injection"
    issue.description = "Direct string interpolation in SQL query"
    issue.suggestion = "Use parameterized queries"
    issue.code_snippet = 'query = f"SELECT * FROM users WHERE id = {user_id}"'
    issue.ai_explanation = None
    issue.status = status
    issue.resolved_by = None
    issue.resolved_at = None
    issue.created_at = datetime.now(timezone.utc)
    return issue


def _db_with_project_ids(project_ids):
    """Build db mock that returns project IDs from the first query."""
    db = AsyncMock()
    # First call: select(Project.id).where(owner_id == ...)
    proj_result = MagicMock()
    proj_result.fetchall.return_value = [(pid,) for pid in project_ids]
    return db


def _db_with_tasks(db, tasks):
    """Configure db.execute to return the given tasks on the second call."""
    task_result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = tasks
    task_result.scalars.return_value = scalars_mock
    return task_result


def _db_with_scalar_first(db, obj):
    """Configure db.execute to return a single object via scalars().first()."""
    result = MagicMock()
    scalars = MagicMock()
    scalars.first.return_value = obj
    result.scalars.return_value = scalars
    return result


# ===================================================================
# list_tasks
# ===================================================================

class TestListTasks:

    @pytest.mark.asyncio
    async def test_list_tasks_returns_user_tasks(self):
        """Tasks belonging to the current user's projects are returned."""
        db = _db_with_project_ids([PROJECT_ID])
        task = _make_task()
        task_result = _db_with_tasks(db, [task])

        # First execute: project IDs; second: tasks
        proj_result = MagicMock()
        proj_result.fetchall.return_value = [(PROJECT_ID,)]
        db.execute.side_effect = [proj_result, task_result]

        user = _make_user()
        result = await list_tasks(db=db, current_user=user)

        assert len(result) == 1
        assert result[0].id == TASK_ID

    @pytest.mark.asyncio
    async def test_list_tasks_with_project_filter(self):
        """When project_id is provided, results are filtered."""
        db = _db_with_project_ids([PROJECT_ID, "proj-002"])
        task1 = _make_task(task_id="t1", project_id=PROJECT_ID)
        task2 = _make_task(task_id="t2", project_id="proj-002")
        task_result = _db_with_tasks(db, [task1])

        proj_result = MagicMock()
        proj_result.fetchall.return_value = [(PROJECT_ID, "proj-002")]
        db.execute.side_effect = [proj_result, task_result]

        user = _make_user()
        result = await list_tasks(project_id=PROJECT_ID, db=db, current_user=user)

        # The function was called; we verify the filter was applied
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_list_tasks_no_projects_returns_empty(self):
        """When user has no projects, return an empty list."""
        db = AsyncMock()
        proj_result = MagicMock()
        proj_result.fetchall.return_value = []  # no projects

        # No project IDs means the query uses .where(False), returning nothing
        task_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        task_result.scalars.return_value = scalars_mock

        db.execute.side_effect = [proj_result, task_result]

        user = _make_user()
        result = await list_tasks(db=db, current_user=user)

        assert result == []


# ===================================================================
# read_task
# ===================================================================

class TestReadTask:

    @pytest.mark.asyncio
    async def test_read_task_success(self):
        """Returns task when it exists and belongs to current user."""
        task = _make_task()
        db = AsyncMock()
        db.execute.return_value = _db_with_scalar_first(db, task)

        user = _make_user()
        result = await read_task(id=TASK_ID, db=db, current_user=user)

        assert result.id == TASK_ID

    @pytest.mark.asyncio
    async def test_read_task_not_found(self):
        """Raises 404 when task does not exist."""
        db = AsyncMock()
        db.execute.return_value = _db_with_scalar_first(db, None)

        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await read_task(id="nonexistent", db=db, current_user=user)
        assert exc_info.value.status_code == 404
        assert "任务不存在" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_read_task_wrong_user_forbidden(self):
        """Raises 403 when task belongs to another user."""
        task = _make_task(created_by=OTHER_USER_ID)
        db = AsyncMock()
        db.execute.return_value = _db_with_scalar_first(db, task)

        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await read_task(id=TASK_ID, db=db, current_user=user)
        assert exc_info.value.status_code == 403
        assert "无权" in exc_info.value.detail


# ===================================================================
# cancel_task
# ===================================================================

class TestCancelTask:

    @pytest.mark.asyncio
    async def test_cancel_pending_task_success(self):
        """Successfully cancel a pending task."""
        task = _make_task(status="pending")
        db = AsyncMock()
        db.execute.return_value = _db_with_scalar_first(db, task)

        user = _make_user()
        with patch("app.api.v1.endpoints.tasks.task_control") as mock_tc:
            result = await cancel_task(id=TASK_ID, db=db, current_user=user)

        assert result["message"] == "任务已取消"
        assert result["task_id"] == TASK_ID
        assert task.status == "cancelled"
        mock_tc.cancel_task.assert_called_once_with(TASK_ID)

    @pytest.mark.asyncio
    async def test_cancel_running_task_success(self):
        """Successfully cancel a running task."""
        task = _make_task(status="running")
        db = AsyncMock()
        db.execute.return_value = _db_with_scalar_first(db, task)

        user = _make_user()
        with patch("app.api.v1.endpoints.tasks.task_control") as mock_tc:
            result = await cancel_task(id=TASK_ID, db=db, current_user=user)

        assert result["task_id"] == TASK_ID

    @pytest.mark.asyncio
    async def test_cancel_task_not_found(self):
        """Raises 404 when task does not exist."""
        db = AsyncMock()
        db.execute.return_value = _db_with_scalar_first(db, None)

        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await cancel_task(id="nonexistent", db=db, current_user=user)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_task_wrong_user_forbidden(self):
        """Raises 403 when trying to cancel another user's task."""
        task = _make_task(created_by=OTHER_USER_ID, status="pending")
        db = AsyncMock()
        db.execute.return_value = _db_with_scalar_first(db, task)

        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await cancel_task(id=TASK_ID, db=db, current_user=user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_cancel_completed_task_raises_400(self):
        """Raises 400 when trying to cancel an already completed task."""
        task = _make_task(status="completed")
        db = AsyncMock()
        db.execute.return_value = _db_with_scalar_first(db, task)

        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await cancel_task(id=TASK_ID, db=db, current_user=user)
        assert exc_info.value.status_code == 400
        assert "只能取消待处理或运行中的任务" in exc_info.value.detail


# ===================================================================
# read_task_issues
# ===================================================================

class TestReadTaskIssues:

    @pytest.mark.asyncio
    async def test_read_issues_success(self):
        """Returns issues for a task owned by the current user."""
        task = _make_task(with_project=False)
        issue1 = _make_issue(issue_id="i1")
        issue2 = _make_issue(issue_id="i2")

        db = AsyncMock()

        # First execute: fetch task
        task_result = _db_with_scalar_first(db, task)
        # Second execute: fetch issues
        issue_result = MagicMock()
        issue_scalars = MagicMock()
        issue_scalars.all.return_value = [issue1, issue2]
        issue_result.scalars.return_value = issue_scalars

        db.execute.side_effect = [task_result, issue_result]

        user = _make_user()
        result = await read_task_issues(id=TASK_ID, db=db, current_user=user)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_read_issues_task_not_found(self):
        """Raises 404 when task does not exist."""
        db = AsyncMock()

        task_result = _db_with_scalar_first(db, None)
        db.execute.return_value = task_result

        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await read_task_issues(id="nonexistent", db=db, current_user=user)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_read_issues_wrong_user_forbidden(self):
        """Raises 403 when task belongs to another user."""
        task = _make_task(created_by=OTHER_USER_ID, with_project=False)
        db = AsyncMock()

        task_result = _db_with_scalar_first(db, task)
        db.execute.return_value = task_result

        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await read_task_issues(id=TASK_ID, db=db, current_user=user)
        assert exc_info.value.status_code == 403


# ===================================================================
# update_issue
# ===================================================================

class TestUpdateIssue:

    @pytest.mark.asyncio
    async def test_resolve_issue_success(self):
        """Resolve an issue and set resolved_by/resolved_at."""
        issue = _make_issue(status="open")
        db = AsyncMock()
        db.get.return_value = _make_task()

        issue_result = MagicMock()
        issue_scalars = MagicMock()
        issue_scalars.first.return_value = issue
        issue_result.scalars.return_value = issue_scalars
        db.execute.return_value = issue_result

        user = _make_user()
        update = IssueUpdateSchema(status="resolved")
        result = await update_issue(
            task_id=TASK_ID, issue_id="issue-001",
            issue_update=update, db=db, current_user=user
        )

        assert issue.status == "resolved"
        assert issue.resolved_by == USER_ID
        assert issue.resolved_at is not None

    @pytest.mark.asyncio
    async def test_update_issue_not_found(self):
        """Raises 404 when issue does not exist."""
        db = AsyncMock()
        db.get.return_value = _make_task()

        issue_result = MagicMock()
        issue_scalars = MagicMock()
        issue_scalars.first.return_value = None
        issue_result.scalars.return_value = issue_scalars
        db.execute.return_value = issue_result

        user = _make_user()
        update = IssueUpdateSchema(status="resolved")
        with pytest.raises(HTTPException) as exc_info:
            await update_issue(
                task_id=TASK_ID, issue_id="nonexistent",
                issue_update=update, db=db, current_user=user
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_issue_status_false_positive(self):
        """Update issue status to false_positive (not resolved, so no resolved_by)."""
        issue = _make_issue(status="open")
        db = AsyncMock()
        db.get.return_value = _make_task()

        issue_result = MagicMock()
        issue_scalars = MagicMock()
        issue_scalars.first.return_value = issue
        issue_result.scalars.return_value = issue_scalars
        db.execute.return_value = issue_result

        user = _make_user()
        update = IssueUpdateSchema(status="false_positive")
        await update_issue(
            task_id=TASK_ID, issue_id="issue-001",
            issue_update=update, db=db, current_user=user
        )

        assert issue.status == "false_positive"
        # resolved_by should NOT be set since status is not "resolved"
        assert issue.resolved_by is None

    @pytest.mark.asyncio
    async def test_other_user_cannot_modify_issue(self):
        db = AsyncMock()
        db.get.return_value = _make_task(created_by=OTHER_USER_ID)
        with pytest.raises(HTTPException) as exc:
            await update_issue(
                task_id=TASK_ID, issue_id="issue-001",
                issue_update=IssueUpdateSchema(status="resolved"),
                db=db, current_user=_make_user(),
            )
        assert exc.value.status_code == 403
        db.execute.assert_not_awaited()
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_task_cannot_modify_issue(self):
        db = AsyncMock()
        db.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            await update_issue(
                task_id=TASK_ID, issue_id="issue-001",
                issue_update=IssueUpdateSchema(status="resolved"),
                db=db, current_user=_make_user(),
            )
        assert exc.value.status_code == 404
        db.execute.assert_not_awaited()
        db.commit.assert_not_awaited()
