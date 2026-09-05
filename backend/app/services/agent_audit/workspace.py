"""Workspace services for agent audits."""

import asyncio
import logging
import os
import re
import zipfile
from typing import Any, Optional

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.audit_job import AuditJob
from app.models.project import Project
from app.services.audit_queue import load_checkpoint, save_checkpoint, workspace_for
from app.services.git_ssh_service import GitSSHOperations

logger = logging.getLogger(__name__)
from .runtime import is_task_cancelled


def validate_git_url(url: str) -> bool:
    """
    验证 Git URL 是否安全

    Args:
        url: Git URL

    Returns:
        bool: URL 是否安全
    """
    if not url:
        return False

    from urllib.parse import urlparse

    parsed = urlparse(url)

    # 只允许 http, https, git, ssh 协议
    allowed_schemes = {"http", "https", "git", "ssh", "git@"}
    if parsed.scheme and parsed.scheme not in allowed_schemes:
        return False

    # 检查是否包含可疑的命令注入字符
    dangerous_patterns = [";", "|", "&", "$(", "`", "\n", "\r", "\t"]
    for pattern in dangerous_patterns:
        if pattern in url:
            return False

    return True


def validate_branch_name(branch: str) -> bool:
    """
    验证 Git 分支名称是否安全

    Args:
        branch: 分支名称

    Returns:
        bool: 分支名称是否安全
    """
    if not branch:
        return False

    # Git 分支名称规则：只允许字母、数字、下划线、连字符、点、斜杠
    # 参考: https://git-scm.com/docs/git-check-ref-format
    pattern = r"^[a-zA-Z0-9_\-\.\/]+$"
    if not re.match(pattern, branch):
        return False

    # 防止路径遍历
    if ".." in branch or branch.startswith("/") or branch.endswith("/"):
        return False

    # 限制长度
    if len(branch) > 256:
        return False

    return True


def is_path_safe(base_path: str, target_path: str) -> bool:
    """
    检查目标路径是否在基础目录内（防止路径遍历）

    Args:
        base_path: 基础目录
        target_path: 目标路径

    Returns:
        bool: 路径是否安全
    """
    # 规范化路径
    abs_base = os.path.abspath(base_path)
    abs_target = os.path.abspath(os.path.join(base_path, target_path))

    # 检查目标路径是否在基础目录内
    return abs_target.startswith(abs_base + os.sep) or abs_target == abs_base


def safe_extract_zip(zip_ref: zipfile.ZipFile, extract_dir: str, task_id: str) -> None:
    """
    安全解压 ZIP 文件，防止 Zip Slip 攻击

    Args:
        zip_ref: ZipFile 对象
        extract_dir: 解压目标目录
        task_id: 任务 ID（用于取消检查）
    """
    from app.services.archive import extract_zip

    extract_zip(
        zip_ref, extract_dir, strip_root=True, cancel_check=lambda: is_task_cancelled(task_id)
    )


async def _get_project_root(
    project: Project,
    task_id: str,
    branch_name: Optional[str] = None,
    github_token: Optional[str] = None,
    gitlab_token: Optional[str] = None,
    gitea_token: Optional[str] = None,  # 🔥 新增
    ssh_private_key: Optional[str] = None,  # 🔥 新增：SSH私钥（用于SSH认证）
    event_emitter: Optional[Any] = None,  # 🔥 新增：用于发送实时日志
) -> str:
    """
    获取项目根目录

    支持两种项目类型：
    - ZIP 项目：解压 ZIP 文件到临时目录
    - 仓库项目：克隆仓库到临时目录

    Args:
        project: 项目对象
        task_id: 任务ID
        branch_name: 分支名称（仓库项目使用，优先于 project.default_branch）
        github_token: GitHub 访问令牌（用于私有仓库）
        gitlab_token: GitLab 访问令牌（用于私有仓库）
        gitea_token: Gitea 访问令牌（用于私有仓库）
        ssh_private_key: SSH私钥（用于SSH认证）
        event_emitter: 事件发送器（用于发送实时日志）

    Returns:
        项目根目录路径

    Raises:
        RuntimeError: 当项目文件获取失败时
    """
    import shutil
    import subprocess
    import zipfile
    from urllib.parse import urlparse, urlunparse

    # 辅助函数：发送事件
    async def emit(message: str, level: str = "info"):
        if event_emitter:
            if level == "info":
                await event_emitter.emit_info(message)
            elif level == "warning":
                await event_emitter.emit_warning(message)
            elif level == "error":
                await event_emitter.emit_error(message)

    # 🔥 辅助函数：检查取消状态
    def check_cancelled():
        if is_task_cancelled(task_id):
            raise asyncio.CancelledError("任务已取消")

    workspace = workspace_for(task_id)
    from app.services.audit_queue import project_snapshot

    project = await project_snapshot(task_id, project)
    checkpoint = await load_checkpoint(task_id)
    cached_root = checkpoint.get("project_root")
    if (
        cached_root
        and os.path.isdir(cached_root)
        and os.path.commonpath([str(workspace), os.path.realpath(cached_root)]) == str(workspace)
    ):
        await emit("♻️ 恢复已准备的项目快照")
        return cached_root
    base_path = str(workspace / "source")

    # 确保目录存在且为空
    if os.path.exists(base_path):
        shutil.rmtree(base_path)
    os.makedirs(base_path, exist_ok=True)

    # 🔥 在开始任何操作前检查取消
    check_cancelled()

    # 根据项目类型处理
    if project.source_type == "zip":
        # 🔥 ZIP 项目：解压 ZIP 文件
        check_cancelled()  # 🔥 解压前检查
        await emit(f"📦 正在解压项目文件...")
        from app.services.zip_storage import load_project_zip

        async with AsyncSessionLocal() as snapshot_db:
            job = await snapshot_db.get(AuditJob, task_id)
            zip_path = (job.payload or {}).get("source_zip") if job else None
        zip_path = zip_path or await load_project_zip(project.id)

        if zip_path and os.path.exists(zip_path):
            try:
                check_cancelled()  # 🔥 解压前再次检查
                with zipfile.ZipFile(zip_path, "r") as zip_ref:
                    # 🔥 逐个文件解压，支持取消检查
                    # 🔥 Security Fix: 使用 safe_extract_zip 替代 extract，防止 Zip Slip 和软链接攻击
                    await asyncio.to_thread(safe_extract_zip, zip_ref, base_path, task_id)
                logger.info(f"✅ Extracted ZIP project {project.id} to {base_path}")
                await emit(f"✅ ZIP 文件解压完成")
            except Exception as e:
                logger.error(f"Failed to extract ZIP {zip_path}: {e}")
                await emit(f"❌ 解压失败: {e}", "error")
                raise RuntimeError(f"无法解压项目文件: {e}")
        else:
            logger.warning(f"⚠️ ZIP file not found for project {project.id}")
            await emit(f"❌ ZIP 文件不存在", "error")
            raise RuntimeError(f"项目 ZIP 文件不存在: {project.id}")

    elif project.source_type == "repository" and project.repository_url:
        # 🔥 仓库项目：优先使用 ZIP 下载（更快更稳定），git clone 作为回退
        repo_url = project.repository_url
        repo_type = project.repository_type or "other"

        # 🔥 安全验证：检查 Git URL 是否安全
        if not validate_git_url(repo_url):
            logger.error(f"❌ 无效的 Git URL: {repo_url}")
            await emit(f"❌ 无效的仓库 URL", "error")
            raise RuntimeError(f"无效的仓库 URL: {repo_url}")

        await emit(f"🔄 正在获取仓库: {repo_url}")

        # 检测是否为SSH URL（SSH链接不支持ZIP下载）
        is_ssh_url = GitSSHOperations.is_ssh_url(repo_url)

        # 解析仓库 URL 获取 owner/repo
        parsed = urlparse(repo_url)
        path_parts = parsed.path.strip("/").replace(".git", "").split("/")
        if len(path_parts) >= 2:
            owner, repo = path_parts[0], path_parts[1]
        else:
            owner, repo = None, None

        # 构建分支尝试顺序
        branches_to_try = []
        if branch_name:
            # 🔥 安全验证：检查分支名称是否安全
            if not validate_branch_name(branch_name):
                logger.error(f"❌ 无效的分支名称: {branch_name}")
                await emit(f"❌ 无效的分支名称", "error")
                raise RuntimeError(f"无效的分支名称: {branch_name}")
            branches_to_try.append(branch_name)
        if not branch_name:
            if project.default_branch and project.default_branch not in branches_to_try:
                # 🔥 安全验证：检查默认分支名称是否安全
                if validate_branch_name(project.default_branch):
                    branches_to_try.append(project.default_branch)
            for common_branch in ["main", "master"]:
                if common_branch not in branches_to_try:
                    branches_to_try.append(common_branch)

        download_success = False
        last_error = ""

        # ============ 方案1: 优先使用 ZIP 下载（更快更稳定）============
        # SSH链接直接跳过ZIP下载，使用git clone
        if is_ssh_url:
            logger.info(f"检测到SSH URL，跳过ZIP下载，直接使用Git克隆")
            await emit(f"🔑 检测到SSH认证，使用Git克隆...")

        if owner and repo and not is_ssh_url:
            import httpx

            for branch in branches_to_try:
                check_cancelled()

                # 清理目录
                if os.path.exists(base_path) and os.listdir(base_path):
                    shutil.rmtree(base_path)
                os.makedirs(base_path, exist_ok=True)

                # 构建 ZIP 下载 URL
                if repo_type == "github" or "github.com" in repo_url:
                    # GitHub ZIP 下载 URL
                    zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
                    headers = {}
                    if github_token:
                        headers["Authorization"] = f"token {github_token}"
                elif repo_type == "gitlab" or "gitlab" in repo_url:
                    # GitLab ZIP 下载 URL（需要对 owner/repo 进行 URL 编码）
                    import urllib.parse

                    project_path = urllib.parse.quote(f"{owner}/{repo}", safe="")
                    gitlab_host = parsed.netloc
                    zip_url = f"https://{gitlab_host}/api/v4/projects/{project_path}/repository/archive.zip?sha={branch}"
                    headers = {}
                    if gitlab_token:
                        headers["PRIVATE-TOKEN"] = gitlab_token
                else:
                    # 其他平台，跳过 ZIP 下载
                    break

                logger.info(f"📦 尝试下载 ZIP 归档 (分支: {branch})...")
                await emit(f"📦 尝试下载 ZIP 归档 (分支: {branch})")

                try:
                    zip_temp_path = str(workspace / "download.zip")

                    async def download_zip():
                        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                            async with client.stream("GET", zip_url, headers=headers) as resp:
                                if resp.status_code != 200:
                                    return False, f"HTTP {resp.status_code}"
                                import aiofiles

                                total = 0
                                async with aiofiles.open(zip_temp_path, "wb") as output:
                                    async for chunk in resp.aiter_bytes(64 * 1024):
                                        check_cancelled()
                                        total += len(chunk)
                                        if total > settings.ZIP_MAX_UPLOAD_BYTES:
                                            raise ValueError(
                                                "Repository ZIP exceeds the upload quota"
                                            )
                                        await output.write(chunk)
                                return True, None

                    # 使用取消检查循环
                    download_task = asyncio.create_task(download_zip())
                    while not download_task.done():
                        check_cancelled()
                        try:
                            success, error = await asyncio.wait_for(
                                asyncio.shield(download_task), timeout=1.0
                            )
                            break
                        except asyncio.TimeoutError:
                            continue

                    if download_task.done():
                        success, error = download_task.result()

                    if success and os.path.exists(zip_temp_path):
                        # 解压 ZIP
                        check_cancelled()
                        with zipfile.ZipFile(zip_temp_path, "r") as zip_ref:
                            # 🔥 使用安全解压函数，防止 Zip Slip 攻击
                            await asyncio.to_thread(safe_extract_zip, zip_ref, base_path, task_id)

                        # 清理临时文件
                        os.remove(zip_temp_path)
                        logger.info(f"✅ ZIP 下载成功 (分支: {branch})")
                        await emit(f"✅ 仓库获取成功 (ZIP下载, 分支: {branch})")
                        download_success = True
                        break
                    else:
                        last_error = error or "下载失败"
                        logger.warning(f"ZIP 下载失败 (分支 {branch}): {last_error}")
                        await emit(f"⚠️ ZIP 下载失败，尝试其他分支...", "warning")
                        # 清理临时文件
                        if os.path.exists(zip_temp_path):
                            os.remove(zip_temp_path)

                except asyncio.CancelledError:
                    logger.info(f"[Cancel] ZIP download cancelled for task {task_id}")
                    raise
                except Exception as e:
                    last_error = str(e)
                    logger.warning(f"ZIP 下载异常 (分支 {branch}): {e}")
                    await emit(f"⚠️ ZIP 下载异常: {str(e)[:50]}...", "warning")

        # ============ 方案2: 回退到 git clone ============
        if not download_success:
            if is_ssh_url:
                # SSH链接直接使用git clone，不是"失败"
                pass  # 已在上面输出提示
            else:
                await emit(f"🔄 ZIP 下载失败，回退到 Git 克隆...")
                logger.info("ZIP download failed, falling back to git clone")

            # 检查 git 是否可用
            try:
                git_check = subprocess.run(
                    ["git", "--version"], capture_output=True, text=True, timeout=10
                )
                if git_check.returncode != 0:
                    await emit(f"❌ Git 未安装", "error")
                    raise RuntimeError("Git 未安装，无法克隆仓库。")
            except FileNotFoundError:
                await emit(f"❌ Git 未安装", "error")
                raise RuntimeError("Git 未安装，无法克隆仓库。")
            except subprocess.TimeoutExpired:
                await emit(f"❌ Git 检测超时", "error")
                raise RuntimeError("Git 检测超时")

            # 构建带认证的 URL
            auth_url = repo_url
            if repo_type == "github" and github_token:
                auth_url = urlunparse(
                    (
                        parsed.scheme,
                        f"{github_token}@{parsed.netloc}",
                        parsed.path,
                        parsed.params,
                        parsed.query,
                        parsed.fragment,
                    )
                )
                await emit(f"🔐 使用 GitHub Token 认证")
            elif repo_type == "gitlab" and gitlab_token:
                auth_url = urlunparse(
                    (
                        parsed.scheme,
                        f"oauth2:{gitlab_token}@{parsed.netloc}",
                        parsed.path,
                        parsed.params,
                        parsed.query,
                        parsed.fragment,
                    )
                )
                await emit(f"🔐 使用 GitLab Token 认证")
            elif repo_type == "gitea" and gitea_token:
                auth_url = urlunparse(
                    (
                        parsed.scheme,
                        f"{gitea_token}@{parsed.netloc}",
                        parsed.path,
                        parsed.params,
                        parsed.query,
                        parsed.fragment,
                    )
                )
                await emit(f"🔐 使用 Gitea Token 认证")
            elif is_ssh_url and ssh_private_key:
                await emit(f"🔐 使用 SSH Key 认证")

            for branch in branches_to_try:
                check_cancelled()

                if os.path.exists(base_path) and os.listdir(base_path):
                    shutil.rmtree(base_path)
                    os.makedirs(base_path, exist_ok=True)

                logger.info(f"🔄 尝试克隆分支: {branch}")
                await emit(f"🔄 尝试克隆分支: {branch}")

                try:
                    # SSH URL使用GitSSHOperations（支持SSH密钥认证）
                    if is_ssh_url and ssh_private_key:

                        async def run_ssh_clone():
                            return await asyncio.to_thread(
                                GitSSHOperations.clone_repo_with_ssh,
                                repo_url,
                                ssh_private_key,
                                base_path,
                                branch,
                            )

                        clone_task = asyncio.create_task(run_ssh_clone())
                        while not clone_task.done():
                            check_cancelled()
                            try:
                                result = await asyncio.wait_for(
                                    asyncio.shield(clone_task), timeout=1.0
                                )
                                break
                            except asyncio.TimeoutError:
                                continue

                        if clone_task.done():
                            result = clone_task.result()

                        # GitSSHOperations返回字典格式
                        if result.get("success"):
                            logger.info(f"✅ Git 克隆成功 (SSH, 分支: {branch})")
                            await emit(f"✅ 仓库获取成功 (SSH克隆, 分支: {branch})")
                            download_success = True
                            break
                        else:
                            last_error = result.get("message", "未知错误")
                            logger.warning(f"SSH克隆失败 (分支 {branch}): {last_error[:200]}")
                            await emit(f"⚠️ 分支 {branch} SSH克隆失败...", "warning")
                    else:
                        # HTTPS URL使用标准git clone
                        async def run_clone():
                            return await asyncio.to_thread(
                                subprocess.run,
                                [
                                    "git",
                                    "clone",
                                    "--depth",
                                    "1",
                                    "--branch",
                                    branch,
                                    auth_url,
                                    base_path,
                                ],
                                capture_output=True,
                                text=True,
                                timeout=120,
                            )

                        clone_task = asyncio.create_task(run_clone())
                        while not clone_task.done():
                            check_cancelled()
                            try:
                                result = await asyncio.wait_for(
                                    asyncio.shield(clone_task), timeout=1.0
                                )
                                break
                            except asyncio.TimeoutError:
                                continue

                        if clone_task.done():
                            result = clone_task.result()

                        if result.returncode == 0:
                            logger.info(f"✅ Git 克隆成功 (分支: {branch})")
                            await emit(f"✅ 仓库获取成功 (Git克隆, 分支: {branch})")
                            download_success = True
                            break
                        else:
                            last_error = result.stderr
                            logger.warning(f"克隆失败 (分支 {branch}): {last_error[:200]}")
                            await emit(f"⚠️ 分支 {branch} 克隆失败...", "warning")
                except subprocess.TimeoutExpired:
                    last_error = f"克隆分支 {branch} 超时"
                    logger.warning(last_error)
                    await emit(f"⚠️ 分支 {branch} 克隆超时...", "warning")
                except asyncio.CancelledError:
                    logger.info(f"[Cancel] Git clone cancelled for task {task_id}")
                    raise

            # 尝试默认分支
            if not download_success:
                check_cancelled()
                await emit(f"🔄 尝试使用仓库默认分支...")

                if os.path.exists(base_path) and os.listdir(base_path):
                    shutil.rmtree(base_path)
                    os.makedirs(base_path, exist_ok=True)

                try:
                    # SSH URL使用GitSSHOperations（不指定分支）
                    if is_ssh_url and ssh_private_key:

                        async def run_default_ssh_clone():
                            return await asyncio.to_thread(
                                GitSSHOperations.clone_repo_with_ssh,
                                repo_url,
                                ssh_private_key,
                                base_path,
                                branch,
                            )

                        clone_task = asyncio.create_task(run_default_ssh_clone())
                        while not clone_task.done():
                            check_cancelled()
                            try:
                                result = await asyncio.wait_for(
                                    asyncio.shield(clone_task), timeout=1.0
                                )
                                break
                            except asyncio.TimeoutError:
                                continue

                        if clone_task.done():
                            result = clone_task.result()

                        if result.get("success"):
                            logger.info(f"✅ Git 克隆成功 (SSH, 默认分支)")
                            await emit(f"✅ 仓库获取成功 (SSH克隆, 默认分支)")
                            download_success = True
                        else:
                            last_error = result.get("message", "未知错误")
                    else:
                        # HTTPS URL使用标准git clone
                        async def run_default_clone():
                            return await asyncio.to_thread(
                                subprocess.run,
                                ["git", "clone", "--depth", "1", auth_url, base_path],
                                capture_output=True,
                                text=True,
                                timeout=120,
                            )

                        clone_task = asyncio.create_task(run_default_clone())
                        while not clone_task.done():
                            check_cancelled()
                            try:
                                result = await asyncio.wait_for(
                                    asyncio.shield(clone_task), timeout=1.0
                                )
                                break
                            except asyncio.TimeoutError:
                                continue

                        if clone_task.done():
                            result = clone_task.result()

                        if result.returncode == 0:
                            logger.info(f"✅ Git 克隆成功 (默认分支)")
                            await emit(f"✅ 仓库获取成功 (Git克隆, 默认分支)")
                            download_success = True
                        else:
                            last_error = result.stderr
                except subprocess.TimeoutExpired:
                    last_error = "克隆超时"
                except asyncio.CancelledError:
                    logger.info(f"[Cancel] Git clone cancelled for task {task_id}")
                    raise

        if not download_success:
            # 分析错误原因
            error_msg = "克隆仓库失败"
            if "Authentication failed" in last_error or "401" in last_error:
                error_msg = "认证失败，请检查 GitHub/GitLab Token 配置"
            elif "not found" in last_error.lower() or "404" in last_error:
                error_msg = "仓库不存在或无访问权限"
            elif "Could not resolve host" in last_error:
                error_msg = "无法解析主机名，请检查网络连接"
            elif "Permission denied" in last_error or "403" in last_error:
                error_msg = "无访问权限，请检查仓库权限或 Token"
            else:
                error_msg = f"克隆仓库失败: {last_error[:200]}"

            logger.error(f"❌ {error_msg}")
            await emit(f"❌ {error_msg}", "error")
            raise RuntimeError(error_msg)

    # 验证目录不为空
    if not os.listdir(base_path):
        await emit(f"❌ 项目目录为空", "error")
        raise RuntimeError(f"项目目录为空，可能是克隆/解压失败: {base_path}")

    # 🔥 智能检测：如果解压后只有一个子目录（常见于 ZIP 文件），
    # 则使用那个子目录作为真正的项目根目录
    # 例如：/tmp/deepaudit/UUID/PHP-Project/ -> 返回 /tmp/deepaudit/UUID/PHP-Project
    items = os.listdir(base_path)
    # 过滤掉 macOS 产生的 __MACOSX 目录和隐藏文件
    real_items = [item for item in items if not item.startswith("__") and not item.startswith(".")]

    if len(real_items) == 1:
        single_item_path = os.path.join(base_path, real_items[0])
        if os.path.isdir(single_item_path):
            logger.info(
                f"🔍 检测到单层嵌套目录，自动调整项目根目录: {base_path} -> {single_item_path}"
            )
            await emit(f"🔍 检测到嵌套目录，自动调整为: {real_items[0]}")
            base_path = single_item_path

    await emit(f"📁 项目准备完成: {base_path}")
    await save_checkpoint(task_id, project_root=base_path)
    return base_path
