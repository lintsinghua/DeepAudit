"""
模块说明：应用模块：repo_utils。
"""

from urllib.parse import urlparse, urlunparse
from typing import Dict, Optional

def parse_repository_url(repo_url: str, repo_type: str) -> Dict[str, str]:
    """
    Parses a repository URL and returns its components.

    Args:
        repo_url: The repository URL.
        repo_type: The type of repository ('github', 'gitlab', 'gitea').

    Returns:
        A dictionary containing parsed components:
        - base_url: The API base URL (for self-hosted instances) or default API URL.
        - owner: The owner/namespace of the repository.
        - repo: The repository name.
        - server_url: The base URL of the server (scheme + netloc).

    Raises:
        ValueError: If the URL is invalid or schema/domain check fails.
    """
    if not repo_url:
        raise ValueError(f"{repo_type} 仓库 URL 不能为空")

    # Basic sanitization
    repo_url = repo_url.strip()

    # Check scheme to prevent SSRF (only allow http and https)
    parsed = urlparse(repo_url)
    if parsed.scheme not in ('http', 'https'):
         raise ValueError(f"{repo_type} 仓库 URL 必须使用 http 或 https 协议")

    # Remove .git suffix if present
    path = parsed.path.strip('/')
    if path.endswith('.git'):
        path = path[:-4]

    path_parts = path.split('/')
    if len(path_parts) < 2:
        raise ValueError(f"{repo_type} 仓库 URL 格式错误")

    base = f"{parsed.scheme}://{parsed.netloc}"

    if repo_type == "github":
        # Handle github.com specifically if needed, or assume path_parts are owner/repo
        # Case: https://github.com/owner/repo
        if 'github.com' in parsed.netloc:
             owner, repo = path_parts[-2], path_parts[-1]
             api_base = "https://api.github.com"
        else:
             # Enterprise GitHub or similar?
             owner, repo = path_parts[-2], path_parts[-1]
             api_base = f"{base}/api/v3" # Assumption for GHE

    elif repo_type == "gitlab":
        # GitLab supports subgroups, so path could be group/subgroup/repo
        # But commonly we just need project path (URL encoded)
        # We'll treat the full path as the project path identifier
        repo = path_parts[-1]
        owner = "/".join(path_parts[:-1])
        api_base = f"{base}/api/v4"

    elif repo_type == "gitea":
        # Gitea: /owner/repo
        owner, repo = path_parts[0], path_parts[1]
        api_base = f"{base}/api/v1"

    else:
        raise ValueError(f"不支持的仓库类型: {repo_type}")

    return {
        "base_url": api_base,
        "owner": owner,
        "repo": repo,
        "project_path": path, # Useful for GitLab
        "server_url": base
    }
