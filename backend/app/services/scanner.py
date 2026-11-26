"""
仓库扫描服务 - 支持GitHub, GitLab 和 Gitea 仓库扫描
"""

import asyncio
import json
import math
from collections.abc import Awaitable, Callable
import httpx
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from urllib.parse import urlparse, quote
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.repo_utils import parse_repository_url, trusted_repository_origin
from app.utils.async_utils import prepare_in_thread
from app.models.audit import AuditTask, AuditIssue, source_position
from app.models.project import Project
from app.services.llm.service import LLMService, OutputLimitError
from app.core.config import settings


def get_analysis_config(user_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    获取分析配置参数（优先使用用户配置，然后使用系统配置）

    Returns:
        包含以下字段的字典:
        - max_analyze_files: 最大分析文件数
        - llm_concurrency: LLM 并发数
        - llm_gap_ms: LLM 请求间隔（毫秒）
    """
    other_config = {k: v for k, v in (user_config or {}).get('otherConfig', {}).items() if v is not None}

    return {
        'max_analyze_files': other_config.get('maxAnalyzeFiles', settings.MAX_ANALYZE_FILES),
        'llm_concurrency': other_config.get('llmConcurrency') or settings.LLM_CONCURRENCY,
        'llm_gap_ms': other_config.get('llmGapMs', settings.LLM_GAP_MS),
    }


# 支持的文本文件扩展名
TEXT_EXTENSIONS = [
    ".js", ".ts", ".tsx", ".jsx", ".py", ".java", ".go", ".rs", 
    ".cpp", ".c", ".h", ".cc", ".hh", ".cs", ".php", ".rb", 
    ".kt", ".swift", ".sql", ".sh", ".json", ".yml", ".yaml"
]

# 排除的目录和文件模式
EXCLUDE_PATTERNS = [
    "node_modules/", "vendor/", "dist/", "build/", ".git/",
    "__pycache__/", ".pytest_cache/", "coverage/", ".nyc_output/",
    ".vscode/", ".idea/", ".vs/", "target/", "out/",
    "__MACOSX/", ".DS_Store", "package-lock.json", "yarn.lock",
    "pnpm-lock.yaml", ".min.js", ".min.css", ".map"
]


def is_text_file(path: str) -> bool:
    """检查是否为文本文件"""
    return any(path.lower().endswith(ext) for ext in TEXT_EXTENSIONS)


def should_exclude(path: str, exclude_patterns: List[str] = None) -> bool:
    """检查是否应该排除该文件"""
    all_patterns = EXCLUDE_PATTERNS + (exclude_patterns or [])
    return any(pattern in path for pattern in all_patterns)


def get_language_from_path(path: str) -> str:
    """从文件路径获取语言类型"""
    ext = path.split('.')[-1].lower() if '.' in path else ''
    language_map = {
        'js': 'javascript', 'jsx': 'javascript',
        'ts': 'typescript', 'tsx': 'typescript',
        'py': 'python', 'java': 'java', 'go': 'go',
        'rs': 'rust', 'cpp': 'cpp', 'c': 'cpp',
        'cc': 'cpp', 'h': 'cpp', 'hh': 'cpp',
        'cs': 'csharp', 'php': 'php', 'rb': 'ruby',
        'kt': 'kotlin', 'swift': 'swift'
    }
    return language_map.get(ext, 'text')


class TaskControlManager:
    """任务控制管理器 - 用于取消运行中的任务"""
    
    def __init__(self):
        self._cancelled_tasks: set = set()
        self._active_tasks: set = set()

    def start_task(self, task_id: str):
        self._active_tasks.add(task_id)

    def is_active(self, task_id: str) -> bool:
        return task_id in self._active_tasks
    
    def cancel_task(self, task_id: str):
        """取消任务"""
        self._cancelled_tasks.add(task_id)
        print(f"🛑 任务 {task_id} 已标记为取消")
    
    def is_cancelled(self, task_id: str) -> bool:
        """检查任务是否被取消"""
        return task_id in self._cancelled_tasks
    
    def cleanup_task(self, task_id: str):
        """清理已完成任务的控制状态"""
        self._cancelled_tasks.discard(task_id)
        self._active_tasks.discard(task_id)


# 全局任务控制器
task_control = TaskControlManager()


async def github_api(url: str, token: str = None) -> Any:
    """调用GitHub API"""
    headers = {"Accept": "application/vnd.github+json"}
    t = token or settings.GITHUB_TOKEN
    if t:
        headers["Authorization"] = f"Bearer {t}"
    
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, headers=headers)
        if response.status_code == 403:
            raise Exception("GitHub API 403：请配置 GITHUB_TOKEN 或确认仓库权限/频率限制")
        if response.status_code == 404:
            raise FileNotFoundError("GitHub API 404")
        if response.status_code != 200:
            raise Exception(f"GitHub API {response.status_code}: {url}")
        return response.json()



async def gitea_api(url: str, token: str = None) -> Any:
    """调用Gitea API"""
    trusted_repository_origin(url, "gitea")
    headers = {"Content-Type": "application/json"}
    t = token or settings.GITEA_TOKEN
    if t:
        headers["Authorization"] = f"token {t}"
    
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, headers=headers)
        if response.status_code == 401:
            raise Exception("Gitea API 401：请配置 GITEA_TOKEN 或确认仓库权限")
        if response.status_code == 403:
            raise Exception("Gitea API 403：请确认仓库权限/频率限制")
        if response.status_code == 404:
            raise FileNotFoundError("Gitea API 404")
        if response.status_code != 200:
            raise Exception(f"Gitea API {response.status_code}: {url}")
        return response.json()


async def gitlab_api(url: str, token: str = None) -> Any:
    """调用GitLab API"""
    trusted_repository_origin(url, "gitlab")
    headers = {"Content-Type": "application/json"}
    t = token or settings.GITLAB_TOKEN
    if t:
        headers["PRIVATE-TOKEN"] = t
    
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, headers=headers)
        if response.status_code == 401:
            raise Exception("GitLab API 401：请配置 GITLAB_TOKEN 或确认仓库权限")
        if response.status_code == 403:
            raise Exception("GitLab API 403：请确认仓库权限/频率限制")
        if response.status_code == 404:
            raise FileNotFoundError("GitLab API 404")
        if response.status_code != 200:
            raise Exception(f"GitLab API {response.status_code}: {url}")
        return response.json()


class ScanInputError(ValueError):
    """Actionable scanner error suitable for the task owner."""


class ListingTruncatedError(ScanInputError):
    """列表超过页数上限、结果不完整。

    单独的类型让扫描能区分它和"分支不存在"：后者可以降级到其他分支，
    而前者说明分支存在只是太大，换分支会扫描错误的代码。
    """


async def fetch_all_pages(
    api_func: Callable[..., Awaitable[Any]],
    url: str,
    token: str | None = None,
    per_page_param: str = "per_page",
    per_page: int = 100,
    max_pages: int = 500,
) -> list[Any]:
    """逐页请求列表接口，直到返回空页（GitHub/GitLab/Gitea 列表接口每次只返回一页）

    达到 max_pages 后仍有数据时抛出异常，而不是返回不完整的列表。
    """
    items: list[Any] = []
    sep = "&" if "?" in url else "?"
    previous = None

    for page in range(1, max_pages + 2):
        try:
            data = await api_func(f"{url}{sep}{per_page_param}={per_page}&page={page}", token)
        except FileNotFoundError as exc:
            if page == 1:
                raise
            raise ListingTruncatedError("无法取得后续分页，列表不完整") from exc
        if not isinstance(data, list) or data == previous:
            raise ListingTruncatedError("分页响应无效，无法取得完整列表")
        if not data:
            return items
        if page > max_pages:
            break
        items.extend(data)
        previous = data

    raise ListingTruncatedError(
        f"列表超过 {max_pages} 页（每页 {per_page} 条），结果不完整"
    )


async def fetch_file_content(url: str, headers: Dict[str, str] = None) -> Optional[str]:
    """获取文件内容"""
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(url, headers=headers or {})
            if response.status_code == 200:
                return response.text
        except Exception as e:
            print(f"获取文件内容失败: {url}, 错误: {e}")
    return None


async def get_github_branches(repo_url: str, token: str = None) -> List[str]:
    """获取GitHub仓库分支列表"""
    repo_info = parse_repository_url(repo_url, "github")
    owner, repo = repo_info['owner'], repo_info['repo']
    
    branches_url = f"https://api.github.com/repos/{owner}/{repo}/branches"
    branches_data = await fetch_all_pages(github_api, branches_url, token)
    
    return [b["name"] for b in branches_data]





async def get_gitea_branches(repo_url: str, token: str = None) -> List[str]:
    """获取Gitea仓库分支列表"""
    repo_info = parse_repository_url(repo_url, "gitea")
    base_url = repo_info['base_url'] # This is {base}/api/v1
    owner, repo = repo_info['owner'], repo_info['repo']
    
    branches_url = f"{base_url}/repos/{owner}/{repo}/branches"
    branches_data = await fetch_all_pages(gitea_api, branches_url, token, per_page_param="limit", per_page=50)
    
    return [b["name"] for b in branches_data]


async def get_gitlab_branches(repo_url: str, token: str = None) -> List[str]:
    """获取GitLab仓库分支列表"""
    parsed = urlparse(repo_url)
    
    extracted_token = token
    if parsed.username:
        if parsed.username == 'oauth2' and parsed.password:
            extracted_token = parsed.password
        elif parsed.username and not parsed.password:
            extracted_token = parsed.username
    
    repo_info = parse_repository_url(repo_url, "gitlab")
    base_url = repo_info['base_url']
    project_path = quote(repo_info['project_path'], safe='')
    
    branches_url = f"{base_url}/projects/{project_path}/repository/branches"
    branches_data = await fetch_all_pages(gitlab_api, branches_url, extracted_token)
    
    return [b["name"] for b in branches_data]


async def get_github_files(repo_url: str, branch: str, token: str = None, exclude_patterns: List[str] = None) -> List[Dict[str, str]]:
    """获取GitHub仓库文件列表"""
    # 解析仓库URL
    repo_info = parse_repository_url(repo_url, "github")
    owner, repo = repo_info['owner'], repo_info['repo']
    
    # 获取仓库文件树
    tree_base = f"https://api.github.com/repos/{owner}/{repo}/git/trees"
    tree_data = await github_api(f"{tree_base}/{quote(branch, safe='')}?recursive=1", token)
    entries = tree_data["tree"]
    if tree_data.get("truncated"):
        entries = []
        pending = [("", tree_data["sha"])]
        while pending:
            prefix, sha = pending.pop()
            try:
                subtree = await github_api(f"{tree_base}/{quote(sha, safe='')}", token)
            except FileNotFoundError as exc:
                raise ListingTruncatedError("无法取得完整的文件树") from exc
            if subtree.get("truncated"):
                raise ListingTruncatedError(f"GitHub 目录列表不完整: {prefix or '/'}")
            for entry in subtree["tree"]:
                path = prefix + entry["path"]
                if entry["type"] == "tree":
                    if not should_exclude(path + "/", exclude_patterns):
                        pending.append((path + "/", entry["sha"]))
                else:
                    entries.append({**entry, "path": path})
    
    files = []
    for item in entries:
        if item.get("type") == "blob" and is_text_file(item["path"]) and not should_exclude(item["path"], exclude_patterns):
            size = item.get("size", 0)
            if size <= settings.MAX_FILE_SIZE_BYTES:
                files.append({
                    "path": item["path"],
                    "url": f"https://raw.githubusercontent.com/{owner}/{repo}/{quote(branch, safe='')}/{quote(item['path'])}"
                })
    
    return files


async def get_gitlab_files(repo_url: str, branch: str, token: str = None, exclude_patterns: List[str] = None) -> List[Dict[str, str]]:
    """获取GitLab仓库文件列表"""
    parsed = urlparse(repo_url)
    
    # 从URL中提取token（如果存在）
    extracted_token = token
    if parsed.username:
        if parsed.username == 'oauth2' and parsed.password:
            extracted_token = parsed.password
        elif parsed.username and not parsed.password:
            extracted_token = parsed.username
    
    # 解析项目路径
    repo_info = parse_repository_url(repo_url, "gitlab")
    base_url = repo_info['base_url'] # {base}/api/v4
    project_path = quote(repo_info['project_path'], safe='')
    
    # 获取仓库文件树
    tree_url = f"{base_url}/projects/{project_path}/repository/tree?ref={quote(branch)}&recursive=true"
    tree_data = await fetch_all_pages(gitlab_api, tree_url, extracted_token)
    
    files = []
    for item in tree_data:
        if item.get("type") == "blob" and is_text_file(item["path"]) and not should_exclude(item["path"], exclude_patterns):
            files.append({
                "path": item["path"],
                "url": f"{base_url}/projects/{project_path}/repository/files/{quote(item['path'], safe='')}/raw?ref={quote(branch)}",
                "token": extracted_token
            })
    
    return files



async def get_gitea_files(repo_url: str, branch: str, token: str = None, exclude_patterns: List[str] = None) -> List[Dict[str, str]]:
    """获取Gitea仓库文件列表"""
    repo_info = parse_repository_url(repo_url, "gitea")
    base_url = repo_info['base_url']
    owner, repo = repo_info['owner'], repo_info['repo']
    
    # Gitea tree API: GET /repos/{owner}/{repo}/git/trees/{sha}?recursive=1
    # 可以直接使用分支名作为sha
    tree_base = f"{base_url}/repos/{owner}/{repo}/git/trees"
    tree_data = await gitea_api(f"{tree_base}/{quote(branch, safe='')}?recursive=1", token)
    entries = list(tree_data["tree"] or [])
    if tree_data.get("truncated"):
        tree_url = f"{tree_base}/{quote(tree_data['sha'], safe='')}?recursive=1"
        expected = tree_data["total_count"]
        page = 1
        while tree_data.get("truncated"):
            page += 1
            try:
                tree_data = await gitea_api(f"{tree_url}&page={page}", token)
            except FileNotFoundError as exc:
                raise ListingTruncatedError("无法取得完整的文件树") from exc
            batch = tree_data["tree"]
            if not batch or tree_data.get("page") != page or len(entries) >= expected:
                raise ListingTruncatedError("Gitea 文件树分页不完整")
            entries.extend(batch)
        if len(entries) != expected:
            raise ListingTruncatedError("Gitea 文件树条目数量不一致")
    
    files = []
    for item in entries:
         # Gitea API returns 'type': 'blob' for files
        if item.get("type") == "blob" and is_text_file(item["path"]) and not should_exclude(item["path"], exclude_patterns):
            # 使用API raw endpoint: GET /repos/{owner}/{repo}/raw/{filepath}?ref={branch}
             files.append({
                "path": item["path"],
                "url": f"{base_url}/repos/{owner}/{repo}/raw/{quote(item['path'])}?ref={quote(branch)}",
                "token": token # 传递token以便fetch_file_content使用
            })
    
    return files
def record_scan_failure(task, reason):
    try:
        config = json.loads(task.scan_config or "{}")
    except (ValueError, TypeError):
        config = {}
    config = config if isinstance(config, dict) else {}
    task.scan_config = json.dumps({**config, "failure": reason}, ensure_ascii=False)


def scan_quality(result):
    score = result.get("quality_score")
    if score is None:
        return None
    score = float(score)
    if not math.isfinite(score) or not 0 <= score <= 100:
        raise ValueError("无效质量评分")
    return score


async def analyze_scan_file(service, content, language, scan_config, db):
    async def analyze(text):
        if scan_config.get("rule_set_id") or scan_config.get("prompt_template_id"):
            return await service.analyze_code_with_rules(
                text, language, rule_set_id=scan_config.get("rule_set_id"),
                prompt_template_id=scan_config.get("prompt_template_id"), db_session=db,
            )
        return await service.analyze_code(text, language)

    try:
        return await analyze(content)
    except OutputLimitError:
        lines = content.split("\n")
        midpoint = len(lines) // 2
        if not midpoint:
            raise
        # Retry each half once within the user's existing token limit.
        first = await analyze("\n".join(lines[:midpoint]))
        second = await analyze("\n".join(lines[midpoint:]))
        for issue in first["issues"]:
            issue["line"] = source_position(issue.get("line"), midpoint)
        for issue in second["issues"]:
            line = source_position(issue.get("line"), len(lines) - midpoint)
            issue["line"] = line + midpoint if line else None
        scores = [score for part in (first, second) if (score := scan_quality(part)) is not None]
        merged = {"issues": first["issues"] + second["issues"]}
        if scores:
            merged["quality_score"] = sum(scores) / len(scores)
        return merged


async def scan_repo_task(task_id: str, db_session_factory, user_config: dict = None):
    """
    后台仓库扫描任务
    
    Args:
        task_id: 任务ID
        db_session_factory: 数据库会话工厂
        user_config: 用户配置字典（包含llmConfig和otherConfig）
    """
    async with db_session_factory() as db:
        task = await db.get(AuditTask, task_id, with_for_update=True)
        if not task or task.status != "pending":
            return

        task_control.start_task(task_id)
        try:
            # 1. 更新状态为运行中
            task.status = "running"
            task.started_at = datetime.now(timezone.utc)
            await db.commit()
            
            # 创建使用用户配置的LLM服务实例
            llm_service = LLMService(user_config=user_config or {})

            # 2. 获取项目信息
            project = await db.get(Project, task.project_id)
            if not project:
                raise Exception("项目不存在")
            
            # 检查项目类型 - 仅支持仓库类型项目
            source_type = getattr(project, 'source_type', 'repository')
            if source_type == 'zip':
                raise Exception("ZIP类型项目请使用ZIP上传扫描接口")
            
            if not project.repository_url:
                raise Exception("仓库地址不存在")

            repo_url = project.repository_url
            branch = task.branch_name or project.default_branch or "main"
            repo_type = project.repository_type or "other"
            
            # 解析任务的排除模式
            import json as json_module
            task_exclude_patterns = []
            if task.exclude_patterns:
                try:
                    task_exclude_patterns = json_module.loads(task.exclude_patterns)
                except:
                    pass

            print(f"🚀 开始扫描仓库: {repo_url}, 分支: {branch}, 类型: {repo_type}, 来源: {source_type}")
            if task_exclude_patterns:
                print(f"📋 排除模式: {task_exclude_patterns}")

            # 3. 获取文件列表
            # 从用户配置中读取 GitHub/GitLab Token（优先使用用户配置，然后使用系统配置）
            user_other_config = (user_config or {}).get('otherConfig', {})
            github_token = user_other_config.get('githubToken') or settings.GITHUB_TOKEN
            gitlab_token = user_other_config.get('gitlabToken') or settings.GITLAB_TOKEN
            gitea_token = user_other_config.get('giteaToken') or settings.GITEA_TOKEN

            

            # 获取SSH私钥（如果配置了）
            ssh_private_key = None
            if 'sshPrivateKey' in user_other_config:
                from app.core.encryption import decrypt_sensitive_data
                ssh_private_key = decrypt_sensitive_data(user_other_config['sshPrivateKey'])

            files: List[Dict[str, str]] = []

            # 检查是否为SSH URL
            from app.services.git_ssh_service import GitSSHOperations
            is_ssh_url = GitSSHOperations.is_ssh_url(repo_url)

            if is_ssh_url:
                # 使用SSH方式获取文件
                if not ssh_private_key:
                    raise Exception("仓库使用SSH URL，但未配置SSH密钥。请先生成并配置SSH密钥。")

                print(f"🔐 使用SSH方式访问仓库: {repo_url}")
                try:
                    files_with_content = await prepare_in_thread(
                        GitSSHOperations.get_repo_files_via_ssh, repo_url, ssh_private_key, branch, task_exclude_patterns,
                        cancel_check=lambda: task_control.is_cancelled(task_id),
                    )
                    # 转换为统一格式
                    files = [{'path': f['path'], 'content': f['content']} for f in files_with_content]
                    actual_branch = branch
                    print(f"✅ 通过SSH成功获取 {len(files)} 个文件")
                except Exception as e:
                    raise Exception(f"SSH方式获取仓库文件失败: {str(e)}")
            else:
                # 使用API方式获取文件（原有逻辑）
                # 构建分支尝试顺序（分支降级机制）
                branches_to_try = [branch]
                requested_branch = json.loads(task.scan_config or "{}").get("branch_name")
                if not requested_branch:
                    for candidate in (project.default_branch, "main", "master"):
                        if candidate and candidate not in branches_to_try:
                            branches_to_try.append(candidate)

                actual_branch = branch  # 实际使用的分支
                last_error = None

                for try_branch in branches_to_try:
                    try:
                        print(f"🔄 尝试获取分支 {try_branch} 的文件列表...")
                        if repo_type == "github":
                            files = await get_github_files(repo_url, try_branch, github_token, task_exclude_patterns)
                        elif repo_type == "gitlab":
                            files = await get_gitlab_files(repo_url, try_branch, gitlab_token, task_exclude_patterns)
                        elif repo_type == "gitea":
                            files = await get_gitea_files(repo_url, try_branch, gitea_token, task_exclude_patterns)
                        else:
                            raise Exception("不支持的仓库类型，仅支持 GitHub, GitLab 和 Gitea 仓库")

                        if not files:
                            raise ScanInputError(f"分支 {try_branch} 中没有符合扫描条件的文件")
                        actual_branch = try_branch
                        break
                    except ScanInputError:
                        # 分支存在但文件列表不完整：不降级到其他分支，直接让扫描失败
                        raise
                    except Exception as e:
                        last_error = str(e)
                        print(f"⚠️ 获取分支 {try_branch} 失败: {last_error[:100]}")
                        if not isinstance(e, FileNotFoundError):
                            break

                if not files:
                    error_msg = f"无法获取仓库文件，所有分支尝试均失败"
                    if last_error:
                        if "404" in last_error or "Not Found" in last_error:
                            error_msg = f"仓库或分支不存在: {branch}"
                        elif "401" in last_error or "403" in last_error:
                            error_msg = "无访问权限，请检查 Token 配置"
                        else:
                            error_msg = f"获取文件失败: {last_error[:100]}"
                    raise ScanInputError(error_msg if "获取文件失败:" not in error_msg else "无法读取仓库，请检查仓库类型、受信任来源与访问权限")

            task.branch_name = actual_branch
            print(f"✅ 成功获取分支 {actual_branch} 的文件列表")

            # 获取分析配置（优先使用用户配置）
            analysis_config = get_analysis_config(user_config)
            max_analyze_files = analysis_config['max_analyze_files']
            llm_gap_ms = analysis_config['llm_gap_ms']

            # 限制文件数量
            # 如果指定了特定文件，则只分析这些文件
            target_files = (user_config or {}).get('scan_config', {}).get('file_paths', [])
            if target_files:
                print(f"🎯 指定分析 {len(target_files)} 个文件")
                files = [f for f in files if f['path'] in target_files]
                if not files:
                    raise ScanInputError("分支中未找到选定的文件")
            elif max_analyze_files > 0:
                files = files[:max_analyze_files]

            task.total_files = len(files)
            await db.commit()

            print(f"📊 获取到 {len(files)} 个文件，开始分析 (最大文件数: {max_analyze_files}, 请求间隔: {llm_gap_ms}ms)")

            # 4. 分析文件
            total_issues = 0
            total_lines = 0
            quality_scores = []
            scanned_files = 0
            failed_files = 0
            last_file_error = ""
            skipped_files = 0  # 跳过的文件（空文件、太大等）
            consecutive_failures = 0
            MAX_CONSECUTIVE_FAILURES = 5

            for file_info in files:
                await db.refresh(task, attribute_names=["status"])
                if task.status == "cancelled":
                    return
                # 检查是否取消
                if task_control.is_cancelled(task_id):
                    print(f"🛑 任务 {task_id} 已被用户取消")
                    return

                # 检查连续失败次数
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    print(f"❌ 任务 {task_id}: 连续失败 {consecutive_failures} 次，停止分析")
                    raise ScanInputError(f"连续 {consecutive_failures} 个文件分析失败，最近一次错误为 {last_file_error}")

                try:
                    # 获取文件内容

                    if is_ssh_url:
                        # SSH方式已经包含了文件内容
                        content = file_info.get('content', '')
                        print(f"📥 正在处理SSH文件: {file_info['path']}")
                    else:
                        headers = {}
                        # 使用提取的 token 或用户配置的 token
                        
                        if repo_type == "gitlab":
                            token_to_use = file_info.get('token') or gitlab_token
                            if token_to_use:
                                headers["PRIVATE-TOKEN"] = token_to_use
                        elif repo_type == "gitea":
                            token_to_use = file_info.get('token') or gitea_token
                            if token_to_use:
                                headers["Authorization"] = f"token {token_to_use}"
                        elif repo_type == "github":
                            # GitHub raw URL 也是直接下载，通常public不需要token，private需要
                            # GitHub raw user content url: raw.githubusercontent.com
                            if github_token:
                                headers["Authorization"] = f"Bearer {github_token}"
                        
                        print(f"📥 正在获取文件: {file_info['path']}")
                        content = await fetch_file_content(file_info["url"], headers)

                    if content is None:
                        raise ValueError("无法下载文件")
                    if not content.strip():
                        print(f"⚠️ 文件内容为空，跳过: {file_info['path']}")
                        skipped_files += 1
                        continue
                    
                    if len(content) > settings.MAX_FILE_SIZE_BYTES:
                        print(f"⚠️ 文件太大，跳过: {file_info['path']}")
                        skipped_files += 1
                        continue
                    
                    file_lines = content.split('\n')
                    file_line_count = len(file_lines)
                    language = get_language_from_path(file_info["path"])
                    
                    print(f"🤖 正在调用 LLM 分析: {file_info['path']} ({language}, {len(content)} bytes)")
                    # LLM分析 - 支持规则集和提示词模板
                    scan_config = (user_config or {}).get('scan_config', {})
                    analysis = await analyze_scan_file(llm_service, content, language, scan_config, db)
                    print(f"✅ LLM 分析完成: {file_info['path']}")
                    
                    # 再次检查是否取消（LLM分析后）
                    if task_control.is_cancelled(task_id):
                        print(f"🛑 任务 {task_id} 在LLM分析后被取消")
                        return
                    
                    await db.refresh(task, attribute_names=["status"], with_for_update=True)
                    if task.status == "cancelled":
                        return
                    # 保存问题
                    issues = analysis.get("issues", [])
                    for issue in issues:
                        line_num = source_position(issue.get("line"), file_line_count)
                        
                        # 健壮的代码片段提取逻辑
                        # 优先使用 LLM 返回的片段，如果为空则从源码提取
                        code_snippet = issue.get("code_snippet")
                        if not code_snippet or len(code_snippet.strip()) < 5:
                            # 从源码提取上下文 (前后2行)
                            try:
                                # line_num 是 1-based
                                idx = max(0, int(line_num) - 1)
                                start = max(0, idx - 2)
                                end = min(len(file_lines), idx + 3)
                                code_snippet = '\n'.join(file_lines[start:end])
                            except Exception:
                                code_snippet = ""

                        audit_issue = AuditIssue(
                            task_id=task.id,
                            file_path=file_info["path"],
                            line_number=line_num,
                            column_number=source_position(issue.get("column")),
                            issue_type=issue.get("type", "maintainability"),
                            severity=issue.get("severity", "low"),
                            title=issue.get("title", "Issue"),
                            message=issue.get("description") or issue.get("title", "Issue"),
                            suggestion=issue.get("suggestion"),
                            code_snippet=code_snippet,
                            ai_explanation=issue.get("ai_explanation"),
                            status="open"
                        )
                        db.add(audit_issue)
                    score = scan_quality(analysis)
                    task.scanned_files = scanned_files + 1
                    task.total_lines = total_lines + file_line_count
                    task.issues_count = total_issues + len(issues)
                    await db.commit()
                    scanned_files += 1
                    total_lines += file_line_count
                    total_issues += len(issues)
                    if score is not None:
                        quality_scores.append(score)
                    consecutive_failures = 0
                    
                    print(f"📈 任务 {task_id}: 进度 {scanned_files}/{len(files)} ({int(scanned_files/len(files)*100)}%)")
                    
                    # 请求间隔
                    await asyncio.sleep(llm_gap_ms / 1000)
                    
                except Exception as file_error:
                    await db.rollback()
                    await db.refresh(task)
                    if task.status == "cancelled":
                        return
                    failed_files += 1
                    last_file_error = str(file_error) if isinstance(file_error, OutputLimitError) else type(file_error).__name__
                    consecutive_failures = 0 if isinstance(file_error, OutputLimitError) else consecutive_failures + 1
                    # 打印详细错误信息
                    import traceback
                    print(f"❌ 分析文件失败 ({file_info['path']}): {file_error}")
                    print(f"   错误类型: {type(file_error).__name__}")
                    print(f"   详细信息: {traceback.format_exc()}")
                    await asyncio.sleep(llm_gap_ms / 1000)

            # 5. 完成任务
            await db.refresh(task, with_for_update=True)
            if task.status == "cancelled" or task_control.is_cancelled(task_id):
                task_control.cleanup_task(task_id)
                return
            if failed_files:
                record_scan_failure(task, f"{failed_files} 个文件分析失败，最近一次错误为 {last_file_error}")
            avg_quality_score = sum(quality_scores) / len(quality_scores) if quality_scores else 100.0
            
            # 判断任务状态
            # 如果所有文件都被跳过（空文件等），标记为完成但给出提示
            if len(files) > 0 and scanned_files == 0 and skipped_files == len(files):
                task.status = "completed"
                task.completed_at = datetime.now(timezone.utc)
                task.scanned_files = 0
                task.total_lines = 0
                task.issues_count = 0
                task.quality_score = 100.0
                await db.commit()
                print(f"⚠️ 任务 {task_id} 完成: 所有 {len(files)} 个文件均为空或被跳过，无需分析")
            # 如果有文件需要分析但全部失败（LLM调用失败），标记为失败
            elif len(files) > 0 and scanned_files == 0 and failed_files > 0:
                task.status = "failed"
                task.completed_at = datetime.now(timezone.utc)
                task.scanned_files = 0
                task.total_lines = total_lines
                task.issues_count = 0
                task.quality_score = 0
                await db.commit()
                print(f"❌ 任务 {task_id} 失败: {failed_files} 个文件分析失败，请检查 LLM API 配置")
            else:
                task.status = "failed" if failed_files else "completed"
                task.completed_at = datetime.now(timezone.utc)
                task.scanned_files = scanned_files
                task.total_lines = total_lines
                task.issues_count = total_issues
                task.quality_score = avg_quality_score
                await db.commit()
                print(f"✅ 任务 {task_id} 完成: 扫描 {scanned_files} 个文件, 发现 {total_issues} 个问题, 质量分 {avg_quality_score:.1f}")

        except asyncio.CancelledError:
            if not task_control.is_cancelled(task_id):
                raise
        except Exception as e:
            print(f"❌ 扫描失败: {e}")
            await db.rollback()
            await db.refresh(task, with_for_update=True)
            if task.status == "cancelled":
                return
            record_scan_failure(task, str(e) if isinstance(e, ScanInputError) else f"扫描中止（{type(e).__name__}）")
            task.status = "failed"
            task.completed_at = datetime.now(timezone.utc)
            await db.commit()
        finally:
            task_control.cleanup_task(task_id)
