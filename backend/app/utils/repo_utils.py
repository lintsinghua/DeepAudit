from urllib.parse import urlparse
from typing import Dict

from app.core.config import settings


def trusted_repository_origin(url: str, repo_type: str) -> str:
    """将 HTTP 仓库及其凭据限定到部署者为该平台指定的来源。"""
    configured = {
        "github": "https://github.com",
        "gitlab": settings.GITLAB_ORIGIN,
        "gitea": settings.GITEA_ORIGIN,
    }.get(repo_type)
    if not configured:
        raise ValueError(f"未配置 {repo_type} 受信任的仓库来源")
    if "\\" in url or any(ord(char) < 32 or ord(char) == 127 for char in url):
        raise ValueError("仓库 URL 格式错误")

    trusted = urlparse(configured)
    if (trusted.scheme not in ("https", "http") or not trusted.hostname or
            trusted.username is not None or trusted.path not in ("", "/") or
            trusted.params or trusted.query or trusted.fragment):
        raise ValueError(f"{repo_type} 来源配置必须仅包含协议、主机及可选端口")
    parsed = urlparse(url)
    def origin(parts):
        port = parts.port if parts.port is not None else {"https": 443, "http": 80}.get(parts.scheme)
        return parts.scheme, parts.hostname, port

    if origin(parsed) != origin(trusted):
        raise ValueError(f"仓库 URL 与配置的 {repo_type} 来源不匹配")
    return f"{trusted.scheme}://{trusted.netloc}"


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

    base = trusted_repository_origin(repo_url, repo_type)

    if repo_type == "github":
        owner, repo = path_parts[-2], path_parts[-1]
        api_base = "https://api.github.com"

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
