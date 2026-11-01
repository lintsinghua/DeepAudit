"""
模块说明：API 路由与依赖定义：projects。
"""

from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from pydantic import BaseModel
from datetime import datetime, timezone
import shutil
import os
import uuid
import json

from app.api import deps
from app.db.session import get_db, AsyncSessionLocal
from app.models.project import Project
from app.models.user import User
from app.models.audit import AuditTask, AuditIssue
from app.models.agent_task import AgentTask, AgentTaskStatus, AgentFinding
from app.models.user_config import UserConfig
import zipfile
from app.services.scanner import scan_repo_task, get_github_files, get_gitlab_files, get_github_branches, get_gitlab_branches, get_gitea_branches, should_exclude, is_text_file
from app.services.zip_storage import (
    save_project_zip, load_project_zip, get_project_zip_meta,
    delete_project_zip, has_project_zip
)

router = APIRouter()

# Schemas
class ProjectCreate(BaseModel):
    """创建项目的请求模型。"""
    name: str
    source_type: Optional[str] = "repository"  # 'repository' 或 'zip'
    repository_url: Optional[str] = None
    repository_type: Optional[str] = "other"  # github, gitlab, other
    description: Optional[str] = None
    default_branch: Optional[str] = "main"
    programming_languages: Optional[List[str]] = None

class ProjectUpdate(BaseModel):
    """更新项目的请求模型。"""
    name: Optional[str] = None
    source_type: Optional[str] = None
    repository_url: Optional[str] = None
    repository_type: Optional[str] = None
    description: Optional[str] = None
    default_branch: Optional[str] = None
    programming_languages: Optional[List[str]] = None

class OwnerSchema(BaseModel):
    """项目所有者信息模型。"""
    id: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    role: Optional[str] = None

    class Config:
        from_attributes = True

class ProjectResponse(BaseModel):
    """项目响应模型。"""
    id: str
    name: str
    description: Optional[str] = None
    source_type: Optional[str] = "repository"  # 'repository' 或 'zip'
    repository_url: Optional[str] = None
    repository_type: Optional[str] = None  # github, gitlab, other
    default_branch: Optional[str] = None
    programming_languages: Optional[str] = None
    owner_id: str
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    owner: Optional[OwnerSchema] = None

    class Config:
        from_attributes = True

class StatsResponse(BaseModel):
    """项目统计响应模型。"""
    total_projects: int
    active_projects: int
    total_tasks: int
    completed_tasks: int
    total_issues: int
    resolved_issues: int
    avg_quality_score: float = 0.0

@router.post("/", response_model=ProjectResponse)
async def create_project(
    *,
    db: AsyncSession = Depends(get_db),
    project_in: ProjectCreate,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    创建新项目。

    处理流程：
    - 根据 source_type 计算默认值
    - 构建项目对象并保存
    - 返回创建结果
    """
    import json
    # 根据 source_type 设置默认值
    source_type = project_in.source_type or "repository"
    
    # 构建项目对象
    project = Project(
        name=project_in.name,
        source_type=source_type,
        repository_url=project_in.repository_url if source_type == "repository" else None,
        repository_type=project_in.repository_type or "other" if source_type == "repository" else "other",
        description=project_in.description,
        default_branch=project_in.default_branch or "main",
        programming_languages=json.dumps(project_in.programming_languages or []),
        owner_id=current_user.id
    )
    # 写入数据库
    db.add(project)
    await db.commit()
    await db.refresh(project)
    # 返回项目
    return project

@router.get("/", response_model=List[ProjectResponse])
async def read_projects(
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    include_deleted: bool = False,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取当前用户的项目列表。

    处理流程：
    - 构建查询并限制为当前用户
    - 可选过滤已删除项目
    - 分页排序后返回
    """
    # 构建查询并预加载 owner
    query = select(Project).options(selectinload(Project.owner))
    # 只返回当前用户的项目
    query = query.where(Project.owner_id == current_user.id)
    if not include_deleted:
        query = query.where(Project.is_active == True)
    # 排序与分页
    query = query.order_by(Project.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    # 返回项目列表
    return result.scalars().all()

@router.get("/deleted", response_model=List[ProjectResponse])
async def read_deleted_projects(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取当前用户已删除（软删除）的项目列表。

    处理流程：
    - 查询当前用户的非活跃项目
    - 按更新时间倒序返回
    """
    # 查询已删除项目
    result = await db.execute(
        select(Project)
        .options(selectinload(Project.owner))
        .where(Project.owner_id == current_user.id)
        .where(Project.is_active == False)
        .order_by(Project.updated_at.desc())
    )
    # 返回项目列表
    return result.scalars().all()

@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取当前用户的项目统计信息。

    处理流程：
    - 查询项目与任务
    - 合并旧任务与 Agent 任务统计
    - 计算平均质量分
    """
    # 只统计当前用户的项目
    projects_result = await db.execute(
        select(Project).where(Project.owner_id == current_user.id)
    )
    projects = projects_result.scalars().all()
    project_ids = [p.id for p in projects]

    # 统计旧的 AuditTask
    tasks_result = await db.execute(
        select(AuditTask).where(AuditTask.project_id.in_(project_ids)) if project_ids else select(AuditTask).where(False)
    )
    tasks = tasks_result.scalars().all()
    task_ids = [t.id for t in tasks]

    # 统计旧的 AuditIssue
    issues_result = await db.execute(
        select(AuditIssue).where(AuditIssue.task_id.in_(task_ids)) if task_ids else select(AuditIssue).where(False)
    )
    issues = issues_result.scalars().all()

    # 同时统计新的 AgentTask
    agent_tasks_result = await db.execute(
        select(AgentTask).where(AgentTask.project_id.in_(project_ids)) if project_ids else select(AgentTask).where(False)
    )
    agent_tasks = agent_tasks_result.scalars().all()
    agent_task_ids = [t.id for t in agent_tasks]

    # 统计 AgentFinding
    agent_findings_result = await db.execute(
        select(AgentFinding).where(AgentFinding.task_id.in_(agent_task_ids)) if agent_task_ids else select(AgentFinding).where(False)
    )
    agent_findings = agent_findings_result.scalars().all()

    # 合并统计（旧任务 + 新 Agent 任务）
    total_tasks = len(tasks) + len(agent_tasks)
    completed_tasks = (
        len([t for t in tasks if t.status == "completed"]) +
        len([t for t in agent_tasks if t.status == AgentTaskStatus.COMPLETED])
    )
    total_issues = len(issues) + len(agent_findings)
    resolved_issues = (
        len([i for i in issues if i.status == "resolved"]) +
        len([f for f in agent_findings if f.status in ("fixed", "wont_fix", "false_positive")])
    )

    # 计算平均质量分（只统计已完成且有质量分的任务）
    quality_scores = (
        [t.quality_score for t in tasks if t.status == "completed" and t.quality_score and t.quality_score > 0] +
        [t.quality_score for t in agent_tasks if t.status == AgentTaskStatus.COMPLETED and t.quality_score and t.quality_score > 0]
    )
    avg_quality_score = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0

    # 返回统计结果
    return {
        "total_projects": len(projects),
        "active_projects": len([p for p in projects if p.is_active]),
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "total_issues": total_issues,
        "resolved_issues": resolved_issues,
        "avg_quality_score": avg_quality_score,
    }

@router.get("/{id}", response_model=ProjectResponse)
async def read_project(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取项目详情。

    处理流程：
    - 查询项目并预加载 owner
    - 校验存在性与权限
    - 返回项目对象
    """
    # 查询项目
    result = await db.execute(
        select(Project)
        .options(selectinload(Project.owner))
        .where(Project.id == id)
    )
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 检查权限：只有项目所有者可以查看
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权查看此项目")
    
    # 返回项目
    return project

@router.put("/{id}", response_model=ProjectResponse)
async def update_project(
    id: str,
    *,
    db: AsyncSession = Depends(get_db),
    project_in: ProjectUpdate,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    更新项目信息。

    处理流程：
    - 查询项目并校验权限
    - 处理可选字段与序列化
    - 保存更新并返回
    """
    import json
    # 查询项目
    result = await db.execute(select(Project).where(Project.id == id))
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 检查权限：只有项目所有者可以更新
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权更新此项目")
    
    # 提取更新字段
    update_data = project_in.model_dump(exclude_unset=True)
    if "programming_languages" in update_data and update_data["programming_languages"] is not None:
        update_data["programming_languages"] = json.dumps(update_data["programming_languages"])
    
    # 应用更新
    for field, value in update_data.items():
        setattr(project, field, value)
    
    # 更新时间并提交
    project.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(project)
    # 返回更新后的项目
    return project

@router.delete("/{id}")
async def delete_project(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    软删除项目。

    处理流程：
    - 查询项目并校验权限
    - 标记为非活跃
    - 保存并返回结果
    """
    # 查询项目
    result = await db.execute(select(Project).where(Project.id == id))
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 检查权限：只有项目所有者可以删除
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权删除此项目")
    
    # 标记为非活跃
    project.is_active = False
    project.updated_at = datetime.now(timezone.utc)
    await db.commit()
    # 返回删除结果
    return {"message": "项目已删除"}

@router.post("/{id}/restore")
async def restore_project(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    恢复已软删除项目。

    处理流程：
    - 查询项目并校验权限
    - 标记为活跃
    - 保存并返回结果
    """
    # 查询项目
    result = await db.execute(select(Project).where(Project.id == id))
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 检查权限：只有项目所有者可以恢复
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权恢复此项目")
    
    # 标记为活跃
    project.is_active = True
    project.updated_at = datetime.now(timezone.utc)
    await db.commit()
    # 返回恢复结果
    return {"message": "项目已恢复"}

@router.delete("/{id}/permanent")
async def permanently_delete_project(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    永久删除项目。

    处理流程：
    - 查询项目并校验权限
    - 删除 ZIP 资源（如有）
    - 删除项目并提交
    """
    # 查询项目
    result = await db.execute(select(Project).where(Project.id == id))
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 检查权限：只有项目所有者可以永久删除
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权永久删除此项目")
    
    # 如果是 ZIP 类型项目，删除关联的 ZIP 文件和元数据
    if project.source_type == "zip":
        try:
            await delete_project_zip(id)
            print(f"[Project] 已删除项目 {id} 的ZIP文件")
        except Exception as e:
            print(f"[Warning] 删除ZIP文件失败: {e}")
    
    # 删除项目记录
    await db.delete(project)
    await db.commit()
    # 返回删除结果
    return {"message": "项目已永久删除"}


@router.get("/{id}/files")
async def get_project_files(
    id: str,
    branch: Optional[str] = None,
    exclude_patterns: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取项目文件列表。

    可选参数:
    - branch: 指定仓库分支（仅对仓库类型项目有效）
    - exclude_patterns: JSON 格式的排除模式数组，如 ["node_modules/**", "*.log"]

    处理流程：
    - 校验项目与权限
    - 解析排除模式
    - 根据来源类型返回文件列表
    """
    # 获取项目信息
    project = await db.get(Project, id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 检查权限
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权查看此项目")
    
    # 解析排除模式
    parsed_exclude_patterns = []
    if exclude_patterns:
        try:
            parsed_exclude_patterns = json.loads(exclude_patterns)
        except json.JSONDecodeError:
            pass
    
    # 准备返回的文件列表
    files = []
    
    if project.source_type == "zip":
        # 处理 ZIP 类型项目
        zip_path = await load_project_zip(id)
        print(f"📦 ZIP项目 {id} 文件路径: {zip_path}")
        if not zip_path or not os.path.exists(zip_path):
            print(f"⚠️ ZIP文件不存在: {zip_path}")
            return []
            
        try:
            # 遍历 ZIP 内文件
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                for file_info in zip_ref.infolist():
                    if not file_info.is_dir():
                        name = file_info.filename
                        # 使用统一的排除逻辑，支持用户自定义排除模式
                        if should_exclude(name, parsed_exclude_patterns):
                            continue
                        # 只显示支持的代码文件
                        if not is_text_file(name):
                            continue
                        files.append({"path": name, "size": file_info.file_size})
        except Exception as e:
            print(f"Error reading zip file: {e}")
            raise HTTPException(status_code=500, detail="无法读取项目文件")
            
    elif project.source_type == "repository":
        # 处理仓库类型项目
        if not project.repository_url:
            return []

        # 从用户配置中获取 Token
        from sqlalchemy.future import select
        from app.core.encryption import decrypt_sensitive_data
        from app.core.config import settings
        from app.services.git_ssh_service import GitSSHOperations

        SENSITIVE_OTHER_FIELDS = ['githubToken', 'gitlabToken', 'sshPrivateKey']

        # 查询用户配置
        result = await db.execute(
            select(UserConfig).where(UserConfig.user_id == current_user.id)
        )
        config = result.scalar_one_or_none()

        # 初始化 Token 与 SSH 私钥
        github_token = settings.GITHUB_TOKEN
        gitlab_token = settings.GITLAB_TOKEN
        ssh_private_key = None

        if config and config.other_config:
            # 解密用户配置
            other_config = json.loads(config.other_config)
            for field in SENSITIVE_OTHER_FIELDS:
                if field in other_config and other_config[field]:
                    decrypted_val = decrypt_sensitive_data(other_config[field])
                    if field == 'githubToken':
                        github_token = decrypted_val
                    elif field == 'gitlabToken':
                        gitlab_token = decrypted_val
                    elif field == 'sshPrivateKey':
                        ssh_private_key = decrypted_val

        # 检查是否为 SSH URL
        is_ssh_url = GitSSHOperations.is_ssh_url(project.repository_url)
        target_branch = branch or project.default_branch or "main"

        try:
            if is_ssh_url:
                # 使用 SSH 方式获取文件列表
                if not ssh_private_key:
                    raise HTTPException(
                        status_code=400,
                        detail="仓库使用SSH URL，但未配置SSH密钥。请先在设置中生成SSH密钥。"
                    )

                print(f"🔐 使用SSH方式获取文件列表: {project.repository_url}")
                files_with_content = GitSSHOperations.get_repo_files_via_ssh(
                    project.repository_url,
                    ssh_private_key,
                    target_branch,
                    parsed_exclude_patterns
                )
                # 将文件内容长度作为 size 返回
                files = [{"path": f["path"], "size": len(f.get("content", ""))} for f in files_with_content]
            else:
                # 使用 API 方式获取文件列表
                repo_type = project.repository_type or "other"

                if repo_type == "github":
                    # 传入用户自定义排除模式
                    repo_files = await get_github_files(project.repository_url, target_branch, github_token, parsed_exclude_patterns)
                    files = [{"path": f["path"], "size": 0} for f in repo_files]
                elif repo_type == "gitlab":
                    # 传入用户自定义排除模式
                    repo_files = await get_gitlab_files(project.repository_url, target_branch, gitlab_token, parsed_exclude_patterns)
                    files = [{"path": f["path"], "size": 0} for f in repo_files]
                else:
                    raise HTTPException(status_code=400, detail="不支持的仓库类型")
        except HTTPException:
            raise
        except Exception as e:
             print(f"Error fetching repo files: {e}")
             raise HTTPException(status_code=500, detail=f"无法获取仓库文件: {str(e)}")

    # 返回文件列表
    return files

class ScanRequest(BaseModel):
    """扫描任务请求模型。"""
    file_paths: Optional[List[str]] = None
    full_scan: bool = True
    exclude_patterns: Optional[List[str]] = None
    branch_name: Optional[str] = None


@router.post("/{id}/scan")
async def scan_project(
    id: str,
    background_tasks: BackgroundTasks,
    scan_request: Optional[ScanRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    启动项目扫描任务。

    处理流程：
    - 校验项目与权限
    - 创建任务记录
    - 解析用户配置并解密敏感字段
    - 触发后台扫描任务
    """
    # 查询项目
    project = await db.get(Project, id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 获取分支和排除模式
    branch_name = scan_request.branch_name if scan_request else None
    exclude_patterns = scan_request.exclude_patterns if scan_request else None

    # 创建任务记录
    task = AuditTask(
        project_id=project.id,
        created_by=current_user.id,
        task_type="repository",
        status="pending",
        branch_name=branch_name or project.default_branch or "main",
        exclude_patterns=json.dumps(exclude_patterns or []),
        scan_config=json.dumps(scan_request.dict()) if scan_request else "{}"
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # 获取用户配置（包含解密敏感字段）
    from app.core.encryption import decrypt_sensitive_data

    # 需要解密的敏感字段列表
    SENSITIVE_LLM_FIELDS = [
        'llmApiKey', 'geminiApiKey', 'openaiApiKey', 'claudeApiKey',
        'qwenApiKey', 'deepseekApiKey', 'zhipuApiKey', 'moonshotApiKey',
        'baiduApiKey', 'minimaxApiKey', 'doubaoApiKey'
    ]
    SENSITIVE_OTHER_FIELDS = ['githubToken', 'gitlabToken']

    def decrypt_config(config_dict: dict, sensitive_fields: list) -> dict:
        """解密配置中的敏感字段。"""
        # 拷贝配置避免原地修改
        decrypted = config_dict.copy()
        # 遍历敏感字段并解密
        for field in sensitive_fields:
            if field in decrypted and decrypted[field]:
                decrypted[field] = decrypt_sensitive_data(decrypted[field])
        # 返回解密结果
        return decrypted

    # 查询用户配置
    result = await db.execute(
        select(UserConfig).where(UserConfig.user_id == current_user.id)
    )
    config = result.scalar_one_or_none()
    user_config = {}
    if config:
        # 解析配置
        llm_config = json.loads(config.llm_config) if config.llm_config else {}
        other_config = json.loads(config.other_config) if config.other_config else {}
        # 解密敏感字段
        llm_config = decrypt_config(llm_config, SENSITIVE_LLM_FIELDS)
        other_config = decrypt_config(other_config, SENSITIVE_OTHER_FIELDS)
        user_config = {
            'llmConfig': llm_config,
            'otherConfig': other_config,
        }

    # 将扫描配置注入到 user_config 中，以便 scan_repo_task 使用
    if scan_request and scan_request.file_paths:
        user_config['scan_config'] = {'file_paths': scan_request.file_paths}

    # 触发后台任务
    background_tasks.add_task(scan_repo_task, task.id, AsyncSessionLocal, user_config)

    # 返回任务状态
    return {"task_id": task.id, "status": "started"}


# ============ ZIP文件管理端点 ============

class ZipFileMetaResponse(BaseModel):
    """ZIP 文件元数据响应模型。"""
    has_file: bool
    original_filename: Optional[str] = None
    file_size: Optional[int] = None
    uploaded_at: Optional[str] = None


@router.get("/{id}/zip", response_model=ZipFileMetaResponse)
async def get_project_zip_info(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取项目 ZIP 文件信息。

    处理流程：
    - 校验项目存在性
    - 查询 ZIP 元数据
    - 返回元数据信息
    """
    # 查询项目
    project = await db.get(Project, id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 检查是否有 ZIP 文件
    has_file = await has_project_zip(id)
    if not has_file:
        return {"has_file": False}
    
    # 获取元数据
    meta = await get_project_zip_meta(id)
    if meta:
        # 返回元数据
        return {
            "has_file": True,
            "original_filename": meta.get("original_filename"),
            "file_size": meta.get("file_size"),
            "uploaded_at": meta.get("uploaded_at")
        }
    
    # 仅标记存在文件
    return {"has_file": True}


@router.post("/{id}/zip")
async def upload_project_zip(
    id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    上传或更新项目 ZIP 文件。

    处理流程：
    - 校验项目、权限与类型
    - 校验文件与大小
    - 保存至持久化存储
    - 清理临时文件
    """
    # 查询项目
    project = await db.get(Project, id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 检查权限
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作此项目")
    
    # 检查项目类型
    if project.source_type != "zip":
        raise HTTPException(status_code=400, detail="仅ZIP类型项目可以上传ZIP文件")
    
    # 验证文件类型
    if not file.filename.lower().endswith('.zip'):
        raise HTTPException(status_code=400, detail="请上传ZIP格式文件")
    
    # 保存到临时文件
    temp_file_id = str(uuid.uuid4())
    temp_file_path = f"/tmp/{temp_file_id}.zip"
    
    try:
        # 写入临时文件
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # 检查文件大小
        file_size = os.path.getsize(temp_file_path)
        if file_size > 500 * 1024 * 1024:  # 500MB limit
            raise HTTPException(status_code=400, detail="文件大小不能超过500MB")
        
        # 保存到持久化存储
        meta = await save_project_zip(id, temp_file_path, file.filename)
        
        # 返回上传结果与元数据
        return {
            "message": "ZIP文件上传成功",
            "original_filename": meta["original_filename"],
            "file_size": meta["file_size"],
            "uploaded_at": meta["uploaded_at"]
        }
    finally:
        # 清理临时文件
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)


@router.delete("/{id}/zip")
async def delete_project_zip_file(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    删除项目 ZIP 文件。

    处理流程：
    - 校验项目与权限
    - 删除 ZIP 文件
    - 返回结果
    """
    # 查询项目
    project = await db.get(Project, id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 检查权限
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作此项目")
    
    # 执行删除
    deleted = await delete_project_zip(id)
    
    if deleted:
        # 返回删除成功
        return {"message": "ZIP文件已删除"}
    else:
        # 返回未找到文件
        return {"message": "没有找到ZIP文件"}


# ============ 分支管理端点 ============

@router.get("/{id}/branches")
async def get_project_branches(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取项目仓库的分支列表。

    处理流程：
    - 校验项目类型与仓库地址
    - 解密用户 Token
    - 按仓库类型获取分支列表
    """
    # 查询项目
    project = await db.get(Project, id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 检查是否为仓库类型项目
    if project.source_type != "repository":
        raise HTTPException(status_code=400, detail="仅仓库类型项目支持获取分支")
    
    if not project.repository_url:
        raise HTTPException(status_code=400, detail="项目未配置仓库地址")
    
    # 获取用户配置的 Token
    from app.core.config import settings
    from app.core.encryption import decrypt_sensitive_data
    
    config = await db.execute(
        select(UserConfig).where(UserConfig.user_id == current_user.id)
    )
    config = config.scalar_one_or_none()
    
    # 初始化 Token
    github_token = settings.GITHUB_TOKEN
    gitea_token = settings.GITEA_TOKEN
    gitlab_token = settings.GITLAB_TOKEN

    SENSITIVE_OTHER_FIELDS = ['githubToken', 'gitlabToken', 'giteaToken']
    
    if config and config.other_config:
        import json
        # 解密用户 Token
        other_config = json.loads(config.other_config)
        for field in SENSITIVE_OTHER_FIELDS:
            if field in other_config and other_config[field]:
                decrypted_val = decrypt_sensitive_data(other_config[field])
                if field == 'githubToken':
                    github_token = decrypted_val
                elif field == 'gitlabToken':
                    gitlab_token = decrypted_val
                elif field == 'giteaToken':
                    gitea_token = decrypted_val
    
    repo_type = project.repository_type or "other"
    
    # 详细日志
    print(f"[Branch] 项目: {project.name}, 类型: {repo_type}, URL: {project.repository_url}")
    
    try:
        if repo_type == "github":
            if not github_token:
                print("[Branch] 警告: GitHub Token 未配置，可能会遇到 API 限制")
            branches = await get_github_branches(project.repository_url, github_token)
        elif repo_type == "gitlab":
            if not gitlab_token:
                print("[Branch] 警告: GitLab Token 未配置，可能无法访问私有仓库")
            branches = await get_gitlab_branches(project.repository_url, gitlab_token)
        elif repo_type == "gitea":
            if not gitea_token:
                print("[Branch] 警告: Gitea Token 未配置，可能无法访问私有仓库")
            branches = await get_gitea_branches(project.repository_url, gitea_token)
        else:
            # 对于其他类型，返回默认分支
            print(f"[Branch] 仓库类型 '{repo_type}' 不支持获取分支，返回默认分支")
            branches = [project.default_branch or "main"]
        
        print(f"[Branch] 成功获取 {len(branches)} 个分支")
        
        # 将默认分支放在第一位
        default_branch = project.default_branch or "main"
        if default_branch in branches:
            branches.remove(default_branch)
            branches.insert(0, default_branch)
        
        # 返回分支信息
        return {"branches": branches, "default_branch": default_branch}
    
    except Exception as e:
        error_msg = str(e)
        print(f"[Branch] 获取分支列表失败: {error_msg}")
        # 返回默认分支作为后备
        return {
            "branches": [project.default_branch or "main"],
            "default_branch": project.default_branch or "main",
            "error": str(e)
        }
