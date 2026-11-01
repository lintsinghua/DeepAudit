"""
Tests for paginated repository listings in app.services.scanner (issue #166).

The GitHub, GitLab and Gitea list endpoints return one page at a time. A
repository with more branches or files than one page holds must still be
listed completely.
"""

from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from app.services.scanner import (
    get_gitea_branches,
    get_github_branches,
    get_gitlab_branches,
    get_gitlab_files,
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
