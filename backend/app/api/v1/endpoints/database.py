"""
数据库管理API端点
提供数据导出、导入、清空等功能
"""

from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from pydantic import BaseModel
import json
from datetime import datetime, timezone

from app.api import deps
from app.db.session import get_db
from app.models.user import User
from app.models.project import Project, ProjectMember
from app.models.audit import AuditTask, AuditIssue
from app.models.analysis import InstantAnalysis
from app.models.user_config import UserConfig

router = APIRouter()


class DatabaseExportResponse(BaseModel):
    """数据库导出响应模型。"""
    export_date: str
    user_id: str
    data: Dict[str, Any]
    
    class Config:
        from_attributes = True


@router.get("/export", response_model=DatabaseExportResponse)
async def export_database(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    导出当前用户的所有数据。

    处理流程：
    - 查询项目、任务、问题、即时分析与配置
    - 构建标准化导出结构
    - 返回导出响应
    """
    try:
        # 1. 获取用户的所有项目
        projects_result = await db.execute(
            select(Project)
            .where(Project.owner_id == current_user.id)
            .options(selectinload(Project.tasks))
        )
        projects = projects_result.scalars().all()
        
        # 2. 获取用户的所有任务
        tasks_result = await db.execute(
            select(AuditTask)
            .where(AuditTask.created_by == current_user.id)
            .options(selectinload(AuditTask.issues))
        )
        tasks = tasks_result.scalars().all()
        
        # 3. 获取用户的所有问题（通过任务关联）
        task_ids = [task.id for task in tasks]
        issues = []
        if task_ids:
            issues_result = await db.execute(
                select(AuditIssue)
                .where(AuditIssue.task_id.in_(task_ids))
            )
            issues = issues_result.scalars().all()
        
        # 4. 获取用户的即时分析记录
        analyses_result = await db.execute(
            select(InstantAnalysis)
            .where(InstantAnalysis.user_id == current_user.id)
        )
        analyses = analyses_result.scalars().all()
        
        # 5. 获取用户的配置
        config_result = await db.execute(
            select(UserConfig)
            .where(UserConfig.user_id == current_user.id)
        )
        config = config_result.scalar_one_or_none()
        
        # 6. 获取用户参与的项目（作为成员）
        members_result = await db.execute(
            select(ProjectMember)
            .where(ProjectMember.user_id == current_user.id)
            .options(selectinload(ProjectMember.project))
        )
        members = members_result.scalars().all()
        
        # 7. 构建导出数据
        export_data = {
            "version": "1.0.0",
            "export_date": datetime.now(timezone.utc).isoformat(),
            "user": {
                "id": current_user.id,
                "email": current_user.email,
                "full_name": current_user.full_name,
            },
            "projects": [
                {
                    "id": p.id,
                    "name": p.name,
                    "description": p.description,
                    "source_type": p.source_type,
                    "repository_url": p.repository_url,
                    "repository_type": p.repository_type,
                    "default_branch": p.default_branch,
                    "programming_languages": json.loads(p.programming_languages) if p.programming_languages else [],
                    "is_active": p.is_active,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                    "updated_at": p.updated_at.isoformat() if p.updated_at else None,
                }
                for p in projects
            ],
            "tasks": [
                {
                    "id": t.id,
                    "project_id": t.project_id,
                    "task_type": t.task_type,
                    "status": t.status,
                    "branch_name": t.branch_name,
                    "exclude_patterns": json.loads(t.exclude_patterns) if t.exclude_patterns else [],
                    "total_files": t.total_files,
                    "scanned_files": t.scanned_files,
                    "total_lines": t.total_lines,
                    "issues_count": t.issues_count,
                    "quality_score": t.quality_score,
                    "started_at": t.started_at.isoformat() if t.started_at else None,
                    "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in tasks
            ],
            "issues": [
                {
                    "id": i.id,
                    "task_id": i.task_id,
                    "file_path": i.file_path,
                    "line_number": i.line_number,
                    "column_number": i.column_number,
                    "issue_type": i.issue_type,
                    "severity": i.severity,
                    "title": i.title,
                    "message": i.message,
                    "description": i.description,
                    "suggestion": i.suggestion,
                    "code_snippet": i.code_snippet,
                    "ai_explanation": i.ai_explanation,
                    "status": i.status,
                    "created_at": i.created_at.isoformat() if i.created_at else None,
                }
                for i in issues
            ],
            "instant_analyses": [
                {
                    "id": a.id,
                    "language": a.language,
                    "issues_count": a.issues_count,
                    "quality_score": a.quality_score,
                    "analysis_time": a.analysis_time,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in analyses
            ],
            "user_config": {
                "llm_config": json.loads(config.llm_config) if config and config.llm_config else {},
                "other_config": json.loads(config.other_config) if config and config.other_config else {},
            } if config else {},
            "project_members": [
                {
                    "id": m.id,
                    "project_id": m.project_id,
                    "role": m.role,
                    "permissions": json.loads(m.permissions) if m.permissions else {},
                    "joined_at": m.joined_at.isoformat() if m.joined_at else None,
                }
                for m in members
            ],
        }
        
        # 返回导出结果
        return DatabaseExportResponse(
            export_date=export_data["export_date"],
            user_id=current_user.id,
            data=export_data
        )
        
    except Exception as e:
        # 记录错误并返回异常
        print(f"导出数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"导出数据失败: {str(e)}")


class DatabaseImportRequest(BaseModel):
    """数据库导入请求模型。"""
    data: Dict[str, Any]


@router.post("/import")
async def import_database(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    从 JSON 文件导入数据。

    处理流程：
    - 读取并解析 JSON
    - 校验用户身份
    - 逐类导入并合并数据
    """
    try:
        # 读取文件内容
        content = await file.read()
        import_data = json.loads(content.decode('utf-8'))
        
        if not isinstance(import_data, dict) or "data" not in import_data:
            raise HTTPException(status_code=400, detail="无效的导入文件格式")
        
        # 提取数据载荷
        data = import_data["data"]
        
        # 验证用户 ID（只能导入自己的数据）
        if data.get("user", {}).get("id") != current_user.id:
            raise HTTPException(status_code=403, detail="只能导入自己的数据")
        
        # 初始化导入计数
        imported_count = {
            "projects": 0,
            "tasks": 0,
            "issues": 0,
            "analyses": 0,
            "config": 0,
        }
        
        # 1. 导入项目（跳过已存在的）
        if "projects" in data:
            for p_data in data["projects"]:
                existing = await db.get(Project, p_data.get("id"))
                if not existing:
                    # 构建项目对象
                    project = Project(
                        id=p_data.get("id"),
                        name=p_data.get("name"),
                        description=p_data.get("description"),
                        source_type=p_data.get("source_type", "repository"),
                        repository_url=p_data.get("repository_url"),
                        repository_type=p_data.get("repository_type"),
                        default_branch=p_data.get("default_branch"),
                        programming_languages=json.dumps(p_data.get("programming_languages", [])),
                        owner_id=current_user.id,
                        is_active=p_data.get("is_active", True) if "is_active" in p_data else (p_data.get("status") != "inactive" if "status" in p_data else True),
                    )
                    db.add(project)
                    imported_count["projects"] += 1
        
        # 提交项目导入
        await db.commit()
        
        # 2. 导入任务（需要先有项目）
        if "tasks" in data:
            for t_data in data["tasks"]:
                existing = await db.get(AuditTask, t_data.get("id"))
                if not existing:
                    # 检查项目是否存在
                    project = await db.get(Project, t_data.get("project_id"))
                    if project:
                        # 构建任务对象
                        task = AuditTask(
                            id=t_data.get("id"),
                            project_id=t_data.get("project_id"),
                            created_by=current_user.id,
                            task_type=t_data.get("task_type"),
                            status=t_data.get("status", "pending"),
                            branch_name=t_data.get("branch_name"),
                            exclude_patterns=json.dumps(t_data.get("exclude_patterns", [])),
                            scan_config=json.dumps(t_data.get("scan_config", {})),
                            total_files=t_data.get("total_files", 0),
                            scanned_files=t_data.get("scanned_files", 0),
                            total_lines=t_data.get("total_lines", 0),
                            issues_count=t_data.get("issues_count", 0),
                            quality_score=t_data.get("quality_score", 0.0),
                        )
                        db.add(task)
                        imported_count["tasks"] += 1
        
        # 提交任务导入
        await db.commit()
        
        # 3. 导入问题（需要先有任务）
        if "issues" in data:
            for i_data in data["issues"]:
                existing = await db.get(AuditIssue, i_data.get("id"))
                if not existing:
                    # 检查任务是否存在
                    task = await db.get(AuditTask, i_data.get("task_id"))
                    if task:
                        # 构建问题对象
                        issue = AuditIssue(
                            id=i_data.get("id"),
                            task_id=i_data.get("task_id"),
                            file_path=i_data.get("file_path"),
                            line_number=i_data.get("line_number"),
                            column_number=i_data.get("column_number"),
                            issue_type=i_data.get("issue_type"),
                            severity=i_data.get("severity"),
                            title=i_data.get("title"),
                            message=i_data.get("message"),
                            description=i_data.get("description"),
                            suggestion=i_data.get("suggestion"),
                            code_snippet=i_data.get("code_snippet"),
                            ai_explanation=i_data.get("ai_explanation"),
                            status=i_data.get("status", "open"),
                        )
                        db.add(issue)
                        imported_count["issues"] += 1
        
        # 提交问题导入
        await db.commit()
        
        # 4. 导入即时分析
        if "instant_analyses" in data:
            for a_data in data["instant_analyses"]:
                existing = await db.get(InstantAnalysis, a_data.get("id"))
                if not existing:
                    # 构建分析记录
                    analysis = InstantAnalysis(
                        id=a_data.get("id"),
                        user_id=current_user.id,
                        language=a_data.get("language"),
                        code_content="",
                        analysis_result=json.dumps(a_data.get("analysis_result", {})),
                        issues_count=a_data.get("issues_count", 0),
                        quality_score=a_data.get("quality_score", 0.0),
                        analysis_time=a_data.get("analysis_time", 0.0),
                    )
                    db.add(analysis)
                    imported_count["analyses"] += 1
        
        # 提交分析导入
        await db.commit()
        
        # 5. 导入用户配置（合并）
        if "user_config" in data and data["user_config"]:
            config_result = await db.execute(
                select(UserConfig)
                .where(UserConfig.user_id == current_user.id)
            )
            config = config_result.scalar_one_or_none()
            
            if not config:
                # 创建配置记录
                config = UserConfig(
                    user_id=current_user.id,
                    llm_config=json.dumps(data["user_config"].get("llm_config", {})),
                    other_config=json.dumps(data["user_config"].get("other_config", {})),
                )
                db.add(config)
            else:
                # 合并配置
                existing_llm = json.loads(config.llm_config) if config.llm_config else {}
                existing_other = json.loads(config.other_config) if config.other_config else {}
                existing_llm.update(data["user_config"].get("llm_config", {}))
                existing_other.update(data["user_config"].get("other_config", {}))
                config.llm_config = json.dumps(existing_llm)
                config.other_config = json.dumps(existing_other)
            
            imported_count["config"] = 1
        
        # 提交配置导入
        await db.commit()
        
        # 返回导入统计
        return {
            "message": "数据导入成功",
            "imported": imported_count
        }
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="无效的 JSON 文件格式")
    except Exception as e:
        # 记录错误并回滚
        print(f"导入数据失败: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"导入数据失败: {str(e)}")


@router.delete("/clear")
async def clear_database(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    清空当前用户的所有数据。

    处理流程：
    - 删除问题、任务、项目、分析与配置
    - 统计删除数量
    - 提交事务并返回结果
    """
    try:
        # 初始化删除计数
        deleted_count = {
            "projects": 0,
            "tasks": 0,
            "issues": 0,
            "analyses": 0,
            "config": 0,
        }
        
        # 1. 删除用户的所有问题（通过任务）
        tasks_result = await db.execute(
            select(AuditTask)
            .where(AuditTask.created_by == current_user.id)
        )
        tasks = tasks_result.scalars().all()
        task_ids = [task.id for task in tasks]
        
        if task_ids:
            issues_result = await db.execute(
                select(AuditIssue)
                .where(AuditIssue.task_id.in_(task_ids))
            )
            issues = issues_result.scalars().all()
            for issue in issues:
                await db.delete(issue)
            deleted_count["issues"] = len(issues)
        
        # 2. 删除用户的所有任务
        for task in tasks:
            await db.delete(task)
        deleted_count["tasks"] = len(tasks)
        
        # 3. 删除用户的所有项目
        projects_result = await db.execute(
            select(Project)
            .where(Project.owner_id == current_user.id)
        )
        projects = projects_result.scalars().all()
        for project in projects:
            await db.delete(project)
        deleted_count["projects"] = len(projects)
        
        # 4. 删除用户的即时分析
        analyses_result = await db.execute(
            select(InstantAnalysis)
            .where(InstantAnalysis.user_id == current_user.id)
        )
        analyses = analyses_result.scalars().all()
        for analysis in analyses:
            await db.delete(analysis)
        deleted_count["analyses"] = len(analyses)
        
        # 5. 删除用户配置
        config_result = await db.execute(
            select(UserConfig)
            .where(UserConfig.user_id == current_user.id)
        )
        config = config_result.scalar_one_or_none()
        if config:
            await db.delete(config)
            deleted_count["config"] = 1
        
        # 6. 删除用户的项目成员关系（作为成员）
        members_result = await db.execute(
            select(ProjectMember)
            .where(ProjectMember.user_id == current_user.id)
        )
        members = members_result.scalars().all()
        for member in members:
            await db.delete(member)
        
        # 提交删除
        await db.commit()
        
        # 返回删除结果
        return {
            "message": "数据已清空",
            "deleted": deleted_count
        }
        
    except Exception as e:
        # 记录错误并回滚
        print(f"清空数据失败: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"清空数据失败: {str(e)}")


class DatabaseStatsResponse(BaseModel):
    """数据库统计信息响应模型。"""
    total_projects: int
    active_projects: int
    total_tasks: int
    completed_tasks: int
    pending_tasks: int
    running_tasks: int
    failed_tasks: int
    total_issues: int
    open_issues: int
    resolved_issues: int
    critical_issues: int
    high_issues: int
    medium_issues: int
    low_issues: int
    total_analyses: int
    total_members: int
    has_config: bool


@router.get("/stats", response_model=DatabaseStatsResponse)
async def get_database_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取当前用户的数据库统计信息。

    处理流程：
    - 统计项目、任务与问题
    - 统计即时分析与成员
    - 汇总并返回
    """
    try:
        # 1. 项目统计
        projects_result = await db.execute(
            select(Project)
            .where(Project.owner_id == current_user.id)
        )
        projects = projects_result.scalars().all()
        total_projects = len(projects)
        active_projects = len([p for p in projects if p.is_active])
        
        # 2. 任务统计
        tasks_result = await db.execute(
            select(AuditTask)
            .where(AuditTask.created_by == current_user.id)
        )
        tasks = tasks_result.scalars().all()
        total_tasks = len(tasks)
        completed_tasks = len([t for t in tasks if t.status == "completed"])
        pending_tasks = len([t for t in tasks if t.status == "pending"])
        running_tasks = len([t for t in tasks if t.status == "running"])
        failed_tasks = len([t for t in tasks if t.status == "failed"])
        
        # 3. 问题统计
        task_ids = [task.id for task in tasks]
        total_issues = 0
        open_issues = 0
        resolved_issues = 0
        critical_issues = 0
        high_issues = 0
        medium_issues = 0
        low_issues = 0
        
        if task_ids:
            issues_result = await db.execute(
                select(AuditIssue)
                .where(AuditIssue.task_id.in_(task_ids))
            )
            issues = issues_result.scalars().all()
            total_issues = len(issues)
            open_issues = len([i for i in issues if i.status == "open"])
            resolved_issues = len([i for i in issues if i.status == "resolved"])
            critical_issues = len([i for i in issues if i.severity == "critical"])
            high_issues = len([i for i in issues if i.severity == "high"])
            medium_issues = len([i for i in issues if i.severity == "medium"])
            low_issues = len([i for i in issues if i.severity == "low"])
        
        # 4. 即时分析统计
        analyses_result = await db.execute(
            select(InstantAnalysis)
            .where(InstantAnalysis.user_id == current_user.id)
        )
        analyses = analyses_result.scalars().all()
        total_analyses = len(analyses)
        
        # 5. 项目成员统计
        members_result = await db.execute(
            select(ProjectMember)
            .where(ProjectMember.user_id == current_user.id)
        )
        members = members_result.scalars().all()
        total_members = len(members)
        
        # 6. 配置检查
        config_result = await db.execute(
            select(UserConfig)
            .where(UserConfig.user_id == current_user.id)
        )
        has_config = config_result.scalar_one_or_none() is not None
        
        # 返回统计结果
        return DatabaseStatsResponse(
            total_projects=total_projects,
            active_projects=active_projects,
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            pending_tasks=pending_tasks,
            running_tasks=running_tasks,
            failed_tasks=failed_tasks,
            total_issues=total_issues,
            open_issues=open_issues,
            resolved_issues=resolved_issues,
            critical_issues=critical_issues,
            high_issues=high_issues,
            medium_issues=medium_issues,
            low_issues=low_issues,
            total_analyses=total_analyses,
            total_members=total_members,
            has_config=has_config,
        )
        
    except Exception as e:
        # 记录错误并返回异常
        print(f"获取统计信息失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")


class DatabaseHealthResponse(BaseModel):
    """数据库健康检查响应模型。"""
    status: str  # healthy, warning, error
    database_connected: bool
    total_records: int
    last_backup_date: str | None
    issues: List[str]
    warnings: List[str]


@router.get("/health", response_model=DatabaseHealthResponse)
async def check_database_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    检查数据库健康状态。

    处理流程：
    - 校验数据库连接
    - 统计记录数量
    - 检查数据完整性
    - 返回健康状态
    """
    try:
        # 初始化状态与指标
        issues = []
        warnings = []
        database_connected = True
        total_records = 0
        last_backup_date = None
        
        # 1. 检查数据库连接
        try:
            await db.execute(select(1))
        except Exception as e:
            database_connected = False
            issues.append(f"数据库连接失败: {str(e)}")
        
        if database_connected:
            # 2. 统计总记录数
            try:
                projects_count = len((await db.execute(
                    select(Project).where(Project.owner_id == current_user.id)
                )).scalars().all())
                
                tasks_count = len((await db.execute(
                    select(AuditTask).where(AuditTask.created_by == current_user.id)
                )).scalars().all())
                
                analyses_count = len((await db.execute(
                    select(InstantAnalysis).where(InstantAnalysis.user_id == current_user.id)
                )).scalars().all())
                
                total_records = projects_count + tasks_count + analyses_count
            except Exception as e:
                warnings.append(f"统计记录数时出错: {str(e)}")
            
            # 3. 检查数据完整性
            try:
                # 检查孤立的任务（项目不存在）
                tasks_result = await db.execute(
                    select(AuditTask).where(AuditTask.created_by == current_user.id)
                )
                tasks = tasks_result.scalars().all()
                orphan_tasks = 0
                for task in tasks:
                    project = await db.get(Project, task.project_id)
                    if not project:
                        orphan_tasks += 1
                
                if orphan_tasks > 0:
                    warnings.append(f"发现 {orphan_tasks} 个孤立任务（关联的项目不存在）")
                
                # 检查孤立的问题（任务不存在）
                if tasks:
                    task_ids = [task.id for task in tasks]
                    issues_result = await db.execute(
                        select(AuditIssue).where(AuditIssue.task_id.in_(task_ids))
                    )
                    issues_list = issues_result.scalars().all()
                    orphan_issues = 0
                    for issue in issues_list:
                        task = await db.get(AuditTask, issue.task_id)
                        if not task:
                            orphan_issues += 1
                    
                    if orphan_issues > 0:
                        warnings.append(f"发现 {orphan_issues} 个孤立问题（关联的任务不存在）")
            except Exception as e:
                warnings.append(f"数据完整性检查时出错: {str(e)}")
        
        # 4. 确定健康状态
        if not database_connected or issues:
            status = "error"
        elif warnings:
            status = "warning"
        else:
            status = "healthy"
        
        # 返回健康检查结果
        return DatabaseHealthResponse(
            status=status,
            database_connected=database_connected,
            total_records=total_records,
            last_backup_date=last_backup_date,
            issues=issues,
            warnings=warnings,
        )
        
    except Exception as e:
        # 记录错误并返回异常
        print(f"健康检查失败: {e}")
        raise HTTPException(status_code=500, detail=f"健康检查失败: {str(e)}")
