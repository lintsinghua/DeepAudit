"""
Tests for paginated repository listings in app.services.scanner (issue #166).

The GitHub, GitLab and Gitea list endpoints return one page at a time. A
repository with more branches or files than one page holds must still be
listed completely.
"""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from app.services.scanner import (
    ListingTruncatedError,
    fetch_all_pages,
    get_gitea_branches,
    get_github_branches,
    get_gitlab_branches,
    get_gitlab_files,
    scan_repo_task,
)


def make_paged_api(items, per_page_param, max_per_page):
    """Fake *_api function that serves `items` page by page, like the real APIs."""

    async def fake_api(url, token=None):
        query = parse_qs(urlparse(url).query)
        page = int(query.get("page", ["1"])[0])
        per_page = min(int(query[per_page_param][0]), max_per_page)
        start = (page - 1) * per_page
        return items[start : start + per_page]

    return fake_api


BRANCHES = [{"name": f"branch-{i}"} for i in range(150)]


class TestBranchPagination:
    async def test_github_branches_beyond_first_page(self):
        fake = make_paged_api(BRANCHES, "per_page", 100)
        with patch("app.services.scanner.github_api", fake):
            branches = await get_github_branches("https://github.com/owner/repo")
        assert branches == [b["name"] for b in BRANCHES]

    async def test_gitlab_branches_beyond_first_page(self):
        fake = make_paged_api(BRANCHES, "per_page", 100)
        with patch("app.services.scanner.gitlab_api", fake):
            branches = await get_gitlab_branches("https://gitlab.example.com/group/project")
        assert branches == [b["name"] for b in BRANCHES]

    async def test_gitea_branches_beyond_first_page(self):
        fake = make_paged_api(BRANCHES, "limit", 50)
        with patch("app.services.scanner.gitea_api", fake):
            branches = await get_gitea_branches("https://gitea.example.com/owner/repo")
        assert branches == [b["name"] for b in BRANCHES]

    async def test_single_page_repository(self):
        fake = make_paged_api(BRANCHES[:3], "per_page", 100)
        with patch("app.services.scanner.gitlab_api", fake):
            branches = await get_gitlab_branches("https://gitlab.example.com/group/project")
        assert branches == ["branch-0", "branch-1", "branch-2"]


class TestGitlabTreePagination:
    async def test_gitlab_files_beyond_first_page(self):
        tree = [{"type": "blob", "path": f"src/file_{i}.py"} for i in range(250)]
        fake = make_paged_api(tree, "per_page", 100)
        with patch("app.services.scanner.gitlab_api", fake):
            files = await get_gitlab_files("https://gitlab.example.com/group/project", "main")
        assert [f["path"] for f in files] == [t["path"] for t in tree]


class TestPaginationGuards:
    async def test_server_ignoring_page_param_does_not_repeat_items(self):
        first_page = BRANCHES[:100]

        async def ignores_page(url, token=None):
            return first_page

        with patch("app.services.scanner.gitlab_api", ignores_page):
            branches = await get_gitlab_branches("https://gitlab.example.com/group/project")
        assert branches == [b["name"] for b in first_page]

    async def test_listing_longer_than_page_cap_raises(self):
        # 3 pages of 10, but only 2 pages allowed: returning 20 items would
        # look like a complete listing, so the helper must refuse instead.
        items = [{"name": f"b-{i}"} for i in range(30)]
        fake = make_paged_api(items, "per_page", 10)
        with pytest.raises(Exception, match="max_pages=2"):
            await fetch_all_pages(fake, "https://h/x", per_page=10, max_pages=2)

    async def test_listing_ending_exactly_at_page_cap_is_complete(self):
        # 2 full pages and nothing after them: the cap is reached, but the
        # extra probe sees an empty page, so the listing is complete.
        items = [{"name": f"b-{i}"} for i in range(20)]
        fake = make_paged_api(items, "per_page", 10)
        result = await fetch_all_pages(fake, "https://h/x", per_page=10, max_pages=2)
        assert result == items

    async def test_truncated_gitlab_tree_fails_the_file_listing(self):
        tree = [{"type": "blob", "path": f"src/file_{i}.py"} for i in range(250)]
        fake = make_paged_api(tree, "per_page", 100)
        with patch("app.services.scanner.gitlab_api", fake), patch(
            "app.services.scanner.fetch_all_pages.__defaults__", ("per_page", 100, 2)
        ):
            with pytest.raises(Exception, match="max_pages"):
                await get_gitlab_files("https://gitlab.example.com/group/project", "main")


class _FakeSession:
    """Just enough of AsyncSession for scan_repo_task to reach the branch loop."""

    def __init__(self, task, project):
        self._rows = {"task": task, "project": project}

    async def get(self, model, key):
        return self._rows["task"] if key == "task-1" else self._rows["project"]

    async def commit(self):
        pass


def _session_factory(task, project):
    @asynccontextmanager
    async def factory():
        yield _FakeSession(task, project)

    return factory


class TestScanBranchFallback:
    """scan_repo_task tries default_branch, main and master when a branch fails."""

    def _run(self, fake_files):
        task = SimpleNamespace(
            project_id="project-1", branch_name="feature", exclude_patterns=None,
            status="pending", started_at=None, completed_at=None,
        )
        project = SimpleNamespace(
            source_type="repository", repository_url="https://gitlab.example.com/group/project",
            repository_type="gitlab", default_branch="develop",
        )
        calls = []

        async def get_gitlab_files(repo_url, branch, token=None, exclude_patterns=None):
            calls.append(branch)
            return await fake_files(branch)

        with patch("app.services.scanner.get_gitlab_files", get_gitlab_files), patch(
            "app.services.scanner.LLMService", MagicMock()
        ), patch("app.services.scanner.task_control", MagicMock()):
            asyncio.run(scan_repo_task("task-1", _session_factory(task, project)))
        return task, calls

    def test_truncated_listing_is_not_replaced_by_another_branch(self):
        # The requested branch exists but is too large to list. Falling back to
        # another branch would scan the wrong code, so the scan must stop here.
        async def fake_files(branch):
            if branch == "feature":
                raise ListingTruncatedError("列表超过 max_pages=500 页")
            return []

        task, calls = self._run(fake_files)
        assert calls == ["feature"]
        assert task.status == "failed"

    def test_other_errors_still_fall_back_to_other_branches(self):
        # Characterization: a missing branch keeps the existing fallback order.
        async def fake_files(branch):
            raise Exception("GitLab API 404: not found")

        task, calls = self._run(fake_files)
        assert calls == ["feature", "develop", "main", "master"]
        assert task.status == "failed"
