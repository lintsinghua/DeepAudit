from app.services.user_configuration import get_user_config_dict
from pathlib import Path
from app.services.audit_queue import enqueue
from app.services.zip_scan import process_zip_task, normalize_path
from app.services.archive import extract_zip, save_upload
from fastapi import APIRouter, UploadFile, File, Form, Depends, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Any, List, Optional
from pydantic import BaseModel
from datetime import datetime, timezone
import uuid
import shutil
import os
import json
from pathlib import Path
import zipfile
import asyncio

from app.api import deps
from app.db.session import get_db, AsyncSessionLocal
from app.models.audit import AuditTask, AuditIssue
from app.models.user import User
from app.models.project import Project
from app.models.analysis import InstantAnalysis
from app.models.user_config import UserConfig
from app.services.llm.service import LLMService
from app.services.scanner import (
    task_control,
    is_text_file,
    should_exclude,
    get_language_from_path,
    get_analysis_config,
)
from app.services.zip_storage import load_project_zip, save_project_zip, has_project_zip
from app.core.config import settings

router = APIRouter()


# 支持的文件扩展名
TEXT_EXTENSIONS = [
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".py",
    ".java",
    ".go",
    ".rs",
    ".cpp",
    ".c",
    ".h",
    ".cc",
    ".hh",
    ".cs",
    ".php",
    ".rb",
    ".kt",
    ".swift",
    ".sql",
    ".sh",
    ".json",
    ".yml",
    ".yaml",
]


@router.post("/upload-zip")
async def scan_zip(
    background_tasks: BackgroundTasks,
    project_id: str = Form(...),
    file: UploadFile = File(...),
    scan_config: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Upload and scan a ZIP file.
    上传ZIP文件并启动扫描，同时将ZIP文件保存到持久化存储
    """
    # Verify project exists
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 检查权限：只有项目所有者可以上传
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作此项目")

    # Validate file
    if not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="请上传ZIP格式文件")

    # Save Uploaded File to temp
    file_id = str(uuid.uuid4())
    file_path = f"/tmp/{file_id}.zip"
    await save_upload(file, file_path)

    try:
        # 保存ZIP文件到持久化存储
        await save_project_zip(project_id, file_path, file.filename)

        if scan_config:
            try:
                parsed_scan_config = json.loads(scan_config)
                if not isinstance(parsed_scan_config, dict):
                    raise ValueError("scan_config must be an object")
            except (ValueError, TypeError) as exc:
                raise HTTPException(status_code=400, detail="扫描配置必须是有效 JSON 对象") from exc

        # Create Task
        task = AuditTask(
            project_id=project_id,
            created_by=current_user.id,
            task_type="zip_upload",
            status="pending",
            scan_config=scan_config if scan_config else "{}",
        )
        db.add(task)
        stored_zip_path = await load_project_zip(project_id)
        await enqueue(db, task, "zip", zip_path=file_path)
        await db.commit()
        await db.refresh(task)
    finally:
        Path(file_path).unlink(missing_ok=True)

    return {"task_id": task.id, "status": "queued"}


class ScanRequest(BaseModel):
    file_paths: Optional[List[str]] = None
    full_scan: bool = True
    exclude_patterns: Optional[List[str]] = None
    rule_set_id: Optional[str] = None
    prompt_template_id: Optional[str] = None


@router.post("/scan-stored-zip")
async def scan_stored_zip(
    project_id: str,
    background_tasks: BackgroundTasks,
    scan_request: Optional[ScanRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    使用已存储的ZIP文件启动扫描（无需重新上传）
    """
    # Verify project exists
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 检查权限：只有项目所有者可以扫描
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作此项目")

    # 检查是否有存储的ZIP文件
    stored_zip_path = await load_project_zip(project_id)
    if not stored_zip_path:
        raise HTTPException(status_code=400, detail="项目没有已存储的ZIP文件，请先上传")

    # Create Task
    task = AuditTask(
        project_id=project_id,
        created_by=current_user.id,
        task_type="zip_upload",
        status="pending",
        scan_config=json.dumps(scan_request.dict()) if scan_request else "{}",
    )
    db.add(task)
    await enqueue(db, task, "zip", zip_path=stored_zip_path)
    await db.commit()
    await db.refresh(task)

    return {"task_id": task.id, "status": "queued"}


class InstantAnalysisRequest(BaseModel):
    code: str
    language: str
    prompt_template_id: Optional[str] = None


class InstantAnalysisResponse(BaseModel):
    id: str
    user_id: str
    language: str
    issues_count: int
    quality_score: float
    analysis_time: float
    analysis_result: str  # JSON字符串，包含完整的分析结果
    created_at: datetime

    class Config:
        from_attributes = True


@router.post("/instant")
async def instant_analysis(
    req: InstantAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Perform instant code analysis.
    """
    # 获取用户配置
    user_config = await get_user_config_dict(db, current_user.id)

    # 创建使用用户配置的LLM服务实例
    llm_service = LLMService(user_config=user_config)

    start_time = datetime.now(timezone.utc)

    try:
        # 如果指定了提示词模板，使用自定义分析
        # 统一使用 analyze_code_with_rules，会自动使用默认模板
        result = await llm_service.analyze_code_with_rules(
            req.code,
            req.language,
            prompt_template_id=req.prompt_template_id,
            db_session=db,
            use_default_template=True,  # 没有指定模板时使用数据库中的默认模板
        )
    except Exception as e:
        # 分析失败，返回错误信息
        error_msg = str(e)
        print(f"❌ 即时分析失败: {error_msg}")
        raise HTTPException(status_code=500, detail=f"代码分析失败: {error_msg}")

    end_time = datetime.now(timezone.utc)
    duration = (end_time - start_time).total_seconds()

    # Save record
    analysis = InstantAnalysis(
        user_id=current_user.id,
        language=req.language,
        code_content="",  # Do not persist code for privacy
        analysis_result=json.dumps(result),
        issues_count=len(result.get("issues", [])),
        quality_score=result.get("quality_score", 0),
        analysis_time=duration,
    )
    db.add(analysis)
    await db.commit()
    await db.refresh(analysis)

    # Return result with analysis ID for export functionality
    return {**result, "analysis_id": analysis.id, "analysis_time": duration}


@router.get("/instant/history", response_model=List[InstantAnalysisResponse])
async def get_instant_analysis_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
    limit: int = 20,
) -> Any:
    """
    Get user's instant analysis history.
    """
    result = await db.execute(
        select(InstantAnalysis)
        .where(InstantAnalysis.user_id == current_user.id)
        .order_by(InstantAnalysis.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.delete("/instant/history/{analysis_id}")
async def delete_instant_analysis(
    analysis_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Delete a specific instant analysis record.
    """
    result = await db.execute(
        select(InstantAnalysis)
        .where(InstantAnalysis.id == analysis_id)
        .where(InstantAnalysis.user_id == current_user.id)
    )
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(status_code=404, detail="分析记录不存在")

    await db.delete(analysis)
    await db.commit()

    return {"message": "删除成功"}


@router.delete("/instant/history")
async def delete_all_instant_analyses(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Delete all instant analysis records for current user.
    """
    from sqlalchemy import delete

    await db.execute(delete(InstantAnalysis).where(InstantAnalysis.user_id == current_user.id))
    await db.commit()

    return {"message": "已清空所有历史记录"}


@router.get("/instant/history/{analysis_id}/report/pdf")
async def export_instant_report_pdf(
    analysis_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Export instant analysis report as PDF by analysis ID.
    """
    from fastapi.responses import Response
    from app.services.report_generator import ReportGenerator

    # 获取即时分析记录
    result = await db.execute(
        select(InstantAnalysis)
        .where(InstantAnalysis.id == analysis_id)
        .where(InstantAnalysis.user_id == current_user.id)
    )
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(status_code=404, detail="分析记录不存在")

    # 解析分析结果
    try:
        analysis_result = json.loads(analysis.analysis_result) if analysis.analysis_result else {}
    except json.JSONDecodeError:
        analysis_result = {}

    # 生成 PDF
    pdf_bytes = ReportGenerator.generate_instant_report(
        analysis_result, analysis.language, analysis.analysis_time
    )

    # 返回 PDF 文件
    filename = f"instant-analysis-{analysis.language}-{analysis.id[:8]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
