from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from pydantic import BaseModel
from datetime import datetime, timezone

from app.api import deps
from app.db.session import get_db
from app.models.audit import AuditTask, AuditIssue
from app.models.project import Project
from app.models.user import User
from app.services.scanner import task_control

router = APIRouter()


# Schemas
class AuditIssueSchema(BaseModel):
    id: str
    task_id: str
    file_path: str
    line_number: Optional[int] = None
    column_number: Optional[int] = None
    issue_type: str
    severity: str
    title: Optional[str] = None
    message: Optional[str] = None
    description: Optional[str] = None
    suggestion: Optional[str] = None
    code_snippet: Optional[str] = None
    ai_explanation: Optional[str] = None
    status: str
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class IssueUpdateSchema(BaseModel):
    status: Optional[str] = None
    

class ProjectSchema(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    source_type: Optional[str] = None
    repository_url: Optional[str] = None
    repository_type: Optional[str] = None
    default_branch: Optional[str] = None
    programming_languages: Optional[str] = None
    owner_id: str
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AuditTaskSchema(BaseModel):
    id: str
    project_id: str
    task_type: str
    status: str
    branch_name: Optional[str] = None
    exclude_patterns: Optional[str] = None
    scan_config: Optional[str] = None
    total_files: int = 0
    scanned_files: int = 0
    total_lines: int = 0
    issues_count: int = 0
    quality_score: float = 0.0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_by: str
    created_at: datetime
    project: Optional[ProjectSchema] = None
    
    class Config:
        from_attributes = True


@router.get("/", response_model=List[AuditTaskSchema])
async def list_tasks(
    project_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    List tasks for current user's projects.
    """
    # 先获取当前用户的项目ID列表
    projects_result = await db.execute(
        select(Project.id).where(Project.owner_id == current_user.id)
    )
    user_project_ids = [p[0] for p in projects_result.fetchall()]
    
    query = select(AuditTask).options(selectinload(AuditTask.project))
    # 只返回当前用户项目的任务
    query = query.where(AuditTask.project_id.in_(user_project_ids)) if user_project_ids else query.where(False)
    if project_id:
        query = query.where(AuditTask.project_id == project_id)
    query = query.order_by(AuditTask.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{id}", response_model=AuditTaskSchema)
async def read_task(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Get task status by ID.
    """
    result = await db.execute(
        select(AuditTask)
        .options(selectinload(AuditTask.project))
        .where(AuditTask.id == id)
    )
    task = result.scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    # 检查权限：只有任务创建者可以查看
    if task.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="无权查看此任务")
    
    return task


@router.post("/{id}/cancel")
async def cancel_task(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Cancel a running task.
    """
    result = await db.execute(select(AuditTask).where(AuditTask.id == id))
    task = result.scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    # 检查权限：只有任务创建者可以取消
    if task.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="无权取消此任务")
    
    if task.status not in ["pending", "running"]:
        raise HTTPException(status_code=400, detail="只能取消待处理或运行中的任务")
    
    # 标记任务为取消
    task_control.cancel_task(id)
    
    # 更新数据库状态
    task.status = "cancelled"
    task.completed_at = datetime.now(timezone.utc)
    await db.commit()
    
    return {"message": "任务已取消", "task_id": id}


@router.get("/{id}/issues", response_model=List[AuditIssueSchema])
async def read_task_issues(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Get issues for a specific task.
    """
    # 先检查任务是否存在且属于当前用户
    task_result = await db.execute(
        select(AuditTask).where(AuditTask.id == id)
    )
    task = task_result.scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    # 检查权限：只有任务创建者可以查看问题
    if task.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="无权查看此任务的问题")
    
    result = await db.execute(
        select(AuditIssue)
        .where(AuditIssue.task_id == id)
        .order_by(
            # 按严重程度排序
            AuditIssue.severity.desc(),
            AuditIssue.created_at.desc()
        )
    )
    return result.scalars().all()


@router.patch("/{task_id}/issues/{issue_id}", response_model=AuditIssueSchema)
async def update_issue(
    task_id: str,
    issue_id: str,
    issue_update: IssueUpdateSchema,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Update issue status (e.g., resolve, mark as false positive).
    """
    result = await db.execute(
        select(AuditIssue)
        .where(AuditIssue.id == issue_id, AuditIssue.task_id == task_id)
    )
    issue = result.scalars().first()
    if not issue:
        raise HTTPException(status_code=404, detail="问题不存在")
    
    if issue_update.status:
        issue.status = issue_update.status
        if issue_update.status == "resolved":
            issue.resolved_by = current_user.id
            issue.resolved_at = datetime.now(timezone.utc)
    
    await db.commit()
    await db.refresh(issue)
    return issue


@router.get("/{id}/report")
async def export_task_report(
    id: str,
    format: str = "pdf",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Export task audit report in multiple formats (pdf/markdown/html/json).
    Keeps the legacy `/report/pdf` route as an alias.
    """
    from fastapi.responses import Response
    from app.services.report_generator import ReportGenerator

    # 获取任务
    result = await db.execute(
        select(AuditTask)
        .options(selectinload(AuditTask.project))
        .where(AuditTask.id == id)
    )
    task = result.scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 检查权限
    if task.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="无权导出此任务报告")

    # 获取问题列表
    issues_result = await db.execute(
        select(AuditIssue)
        .where(AuditIssue.task_id == id)
        .order_by(AuditIssue.severity.desc(), AuditIssue.created_at.desc())
    )
    issues = issues_result.scalars().all()

    task_dict = {
        'id': task.id,
        'status': task.status,
        'branch_name': task.branch_name,
        'total_files': task.total_files,
        'scanned_files': task.scanned_files,
        'total_lines': task.total_lines,
        'issues_count': task.issues_count,
        'quality_score': task.quality_score,
        'created_at': task.created_at.isoformat() if task.created_at else None,
        'completed_at': task.completed_at.isoformat() if task.completed_at else None,
    }

    issues_list = [
        {
            'title': issue.title,
            'description': issue.description,
            'severity': issue.severity,
            'issue_type': issue.issue_type,
            'file_path': issue.file_path,
            'line_number': issue.line_number,
            'column_number': issue.column_number,
            'code_snippet': issue.code_snippet,
            'suggestion': issue.suggestion,
        }
        for issue in issues
    ]

    project_name = task.project.name if task.project else "Unknown Project"

    # 规整格式，非法格式抛出 400
    try:
        fmt = ReportGenerator._normalize_format(format)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    data = ReportGenerator.generate_task_report(task_dict, issues_list, project_name, fmt)

    media_types = {
        'pdf': 'application/pdf',
        'markdown': 'text/markdown; charset=utf-8',
        'html': 'text/html; charset=utf-8',
        'json': 'application/json; charset=utf-8',
    }
    extensions = {'pdf': 'pdf', 'markdown': 'md', 'html': 'html', 'json': 'json'}

    filename = f"audit-report-{task.id[:8]}-{datetime.now(timezone.utc).strftime('%Y%m%d')}.{extensions[fmt]}"
    return Response(
        content=data,
        media_type=media_types[fmt],
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


@router.get("/{id}/report/pdf")
async def export_task_report_pdf(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Export task audit report as PDF (legacy alias for compatibility).
    """
    return await export_task_report(id=id, format="pdf", db=db, current_user=current_user)
