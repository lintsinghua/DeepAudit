"""
模块说明：API 路由与依赖定义：tasks。
"""

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


class AuditIssueSchema(BaseModel):
    """审计问题的响应模型。"""
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
    """问题状态更新的请求体模型。"""
    status: Optional[str] = None
    

class ProjectSchema(BaseModel):
    """项目基础信息的响应模型。"""
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
    """审计任务的响应模型。"""
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
    获取当前用户项目的任务列表。

    处理流程：
    - 查询当前用户拥有的项目列表
    - 构建任务查询并过滤项目范围
    - 可选按项目过滤
    - 返回按创建时间倒序的任务列表
    """
    # 查询当前用户拥有的项目 ID 列表
    projects_result = await db.execute(
        select(Project.id).where(Project.owner_id == current_user.id)
    )
    # 提取项目 ID 列表
    user_project_ids = [p[0] for p in projects_result.fetchall()]
    # 构建任务查询并预加载项目
    query = select(AuditTask).options(selectinload(AuditTask.project))
    # 仅返回当前用户项目的任务
    query = query.where(AuditTask.project_id.in_(user_project_ids)) if user_project_ids else query.where(False)
    # 可选按项目过滤
    if project_id:
        query = query.where(AuditTask.project_id == project_id)
    # 按创建时间倒序
    query = query.order_by(AuditTask.created_at.desc())
    # 执行查询
    result = await db.execute(query)
    # 返回任务列表
    return result.scalars().all()


@router.get("/{id}", response_model=AuditTaskSchema)
async def read_task(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取指定任务信息。

    处理流程：
    - 查询任务并预加载项目
    - 校验任务存在性
    - 校验是否为创建者
    """
    # 查询任务并加载项目
    result = await db.execute(
        select(AuditTask)
        .options(selectinload(AuditTask.project))
        .where(AuditTask.id == id)
    )
    # 提取任务对象
    task = result.scalars().first()
    # 若任务不存在则返回 404
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    # 校验权限：仅任务创建者可查看
    if task.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="无权查看此任务")
    # 返回任务信息
    return task


@router.post("/{id}/cancel")
async def cancel_task(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    取消运行中的任务。

    处理流程：
    - 查询任务
    - 校验创建者权限
    - 校验任务状态
    - 标记任务取消并更新数据库
    """
    # 查询任务
    result = await db.execute(select(AuditTask).where(AuditTask.id == id))
    # 提取任务对象
    task = result.scalars().first()
    # 若任务不存在则返回 404
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    # 校验权限：仅任务创建者可取消
    if task.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="无权取消此任务")
    # 校验可取消状态
    if task.status not in ["pending", "running"]:
        raise HTTPException(status_code=400, detail="只能取消待处理或运行中的任务")
    # 标记任务为取消
    task_control.cancel_task(id)
    # 更新数据库状态
    task.status = "cancelled"
    task.completed_at = datetime.now(timezone.utc)
    await db.commit()
    # 返回取消结果
    return {"message": "任务已取消", "task_id": id}


@router.get("/{id}/issues", response_model=List[AuditIssueSchema])
async def read_task_issues(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取指定任务的问题列表。

    处理流程：
    - 查询任务并校验存在性
    - 校验创建者权限
    - 查询问题并按严重程度排序
    """
    # 查询任务以校验权限
    task_result = await db.execute(
        select(AuditTask).where(AuditTask.id == id)
    )
    # 提取任务对象
    task = task_result.scalars().first()
    # 若任务不存在则返回 404
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    # 校验权限：仅任务创建者可查看问题
    if task.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="无权查看此任务的问题")
    # 查询任务问题并排序
    result = await db.execute(
        select(AuditIssue)
        .where(AuditIssue.task_id == id)
        .order_by(
            # 按严重程度排序
            AuditIssue.severity.desc(),
            AuditIssue.created_at.desc()
        )
    )
    # 返回问题列表
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
    更新问题状态（如已解决、误报）。

    处理流程：
    - 查询问题并校验存在性
    - 更新状态与解决信息
    - 保存并返回更新结果
    """
    # 查询指定问题
    result = await db.execute(
        select(AuditIssue)
        .where(AuditIssue.id == issue_id, AuditIssue.task_id == task_id)
    )
    # 提取问题对象
    issue = result.scalars().first()
    # 若问题不存在则返回 404
    if not issue:
        raise HTTPException(status_code=404, detail="问题不存在")
    # 如果传入状态则更新
    if issue_update.status:
        issue.status = issue_update.status
        # 若标记为已解决则记录处理人和时间
        if issue_update.status == "resolved":
            issue.resolved_by = current_user.id
            issue.resolved_at = datetime.now(timezone.utc)
    # 提交事务
    await db.commit()
    # 刷新对象
    await db.refresh(issue)
    # 返回更新结果
    return issue


@router.get("/{id}/report/pdf")
async def export_task_report_pdf(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    导出任务审计报告为 PDF。

    处理流程：
    - 查询任务并校验权限
    - 查询问题并整理数据
    - 生成 PDF 并返回文件响应
    """
    # 延迟导入响应类
    from fastapi.responses import Response
    # 延迟导入报告生成器
    from app.services.report_generator import ReportGenerator
    # 获取任务
    result = await db.execute(
        select(AuditTask)
        .options(selectinload(AuditTask.project))
        .where(AuditTask.id == id)
    )
    # 提取任务对象
    task = result.scalars().first()
    # 若任务不存在则返回 404
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    # 校验权限：仅创建者可导出
    if task.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="无权导出此任务报告")
    # 查询问题列表
    issues_result = await db.execute(
        select(AuditIssue)
        .where(AuditIssue.task_id == id)
        .order_by(AuditIssue.severity.desc(), AuditIssue.created_at.desc())
    )
    # 提取问题列表
    issues = issues_result.scalars().all()
    # 将任务信息转换为字典
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
    # 将问题列表转换为字典列表
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
    # 获取项目名称
    project_name = task.project.name if task.project else "Unknown Project"
    # 生成 PDF 内容
    pdf_bytes = ReportGenerator.generate_task_report(task_dict, issues_list, project_name)
    # 构建文件名
    filename = f"audit-report-{task.id[:8]}-{datetime.now(timezone.utc).strftime('%Y%m%d')}.pdf"
    # 返回 PDF 响应
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )
