"""
模块说明：API 路由与依赖定义：scan。
"""

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
from app.services.scanner import task_control, is_text_file, should_exclude, get_language_from_path, get_analysis_config
from app.services.zip_storage import load_project_zip, save_project_zip, has_project_zip
from app.core.config import settings

router = APIRouter()


def normalize_path(path: str) -> str:
    """
    统一路径分隔符为正斜杠，确保跨平台兼容性。

    处理流程：
    - 将反斜杠替换为正斜杠
    - 返回标准化路径
    """
    # 统一替换为正斜杠
    return path.replace("\\", "/")


# 支持的文件扩展名
TEXT_EXTENSIONS = [
    ".js", ".ts", ".tsx", ".jsx", ".py", ".java", ".go", ".rs",
    ".cpp", ".c", ".h", ".cc", ".hh", ".cs", ".php", ".rb",
    ".kt", ".swift", ".sql", ".sh", ".json", ".yml", ".yaml"
]


async def process_zip_task(task_id: str, file_path: str, db_session_factory, user_config: dict = None):
    """
    后台 ZIP 文件处理任务。

    处理流程：
    - 查询任务并标记运行
    - 解压 ZIP 并筛选可扫描文件
    - 按配置逐文件分析并写入问题
    - 汇总结果并更新任务状态
    """
    # 打开数据库会话
    async with db_session_factory() as db:
        # 查询任务
        task = await db.get(AuditTask, task_id)
        if not task:
            return

        try:
            # 更新任务为运行中
            task.status = "running"
            task.started_at = datetime.now(timezone.utc)
            await db.commit()
            
            # 创建使用用户配置的 LLM 服务实例
            llm_service = LLMService(user_config=user_config or {})

            # 准备解压目录
            extract_dir = Path(f"/tmp/{task_id}")
            extract_dir.mkdir(parents=True, exist_ok=True)
            
            # 解压 ZIP
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)

            # 获取用户自定义排除模式
            scan_config = (user_config or {}).get('scan_config', {})
            custom_exclude_patterns = scan_config.get('exclude_patterns', [])
            
            # 扫描可分析文件
            files_to_scan = []
            for root, dirs, files in os.walk(extract_dir):
                # 排除常见非代码目录
                dirs[:] = [d for d in dirs if d not in ['node_modules', '__pycache__', '.git', 'dist', 'build', 'vendor']]
                
                for file in files:
                    # 计算相对路径
                    full_path = Path(root) / file
                    # 统一使用正斜杠，确保跨平台兼容性
                    rel_path = normalize_path(str(full_path.relative_to(extract_dir)))
                    
                    # 检查文件类型和排除规则（包含用户自定义排除模式）
                    if is_text_file(rel_path) and not should_exclude(rel_path, custom_exclude_patterns):
                        try:
                            # 读取文本内容并检查大小
                            content = full_path.read_text(errors='ignore')
                            if len(content) <= settings.MAX_FILE_SIZE_BYTES:
                                files_to_scan.append({
                                    "path": rel_path,
                                    "content": content
                                })
                        except:
                            pass

            # 获取分析配置（优先使用用户配置）
            analysis_config = get_analysis_config(user_config)
            max_analyze_files = analysis_config['max_analyze_files']
            llm_gap_ms = analysis_config['llm_gap_ms']

            # 限制文件数量
            # 如果指定了特定文件，则只分析这些文件
            target_files = scan_config.get('file_paths', [])
            if target_files:
                # 统一目标文件路径的分隔符，确保匹配一致性
                normalized_targets = {normalize_path(p) for p in target_files}
                print(f"🎯 ZIP任务: 指定分析 {len(normalized_targets)} 个文件")
                # 仅保留目标文件
                files_to_scan = [f for f in files_to_scan if f['path'] in normalized_targets]
            elif max_analyze_files > 0:
                # 按最大文件数裁剪
                files_to_scan = files_to_scan[:max_analyze_files]

            # 更新任务统计信息
            task.total_files = len(files_to_scan)
            await db.commit()

            print(f"📊 ZIP任务 {task_id}: 找到 {len(files_to_scan)} 个文件 (最大文件数: {max_analyze_files}, 请求间隔: {llm_gap_ms}ms)")

            # 初始化统计变量
            total_issues = 0
            total_lines = 0
            quality_scores = []
            scanned_files = 0
            failed_files = 0

            for file_info in files_to_scan:
                # 检查是否取消
                if task_control.is_cancelled(task_id):
                    print(f"🛑 ZIP任务 {task_id} 已被取消")
                    task.status = "cancelled"
                    task.completed_at = datetime.now(timezone.utc)
                    await db.commit()
                    task_control.cleanup_task(task_id)
                    return

                try:
                    # 读取文件内容与语言
                    content = file_info['content']
                    total_lines += content.count('\n') + 1
                    language = get_language_from_path(file_info['path'])
                    
                    # 获取规则集和提示词模板 ID
                    scan_config = (user_config or {}).get('scan_config', {})
                    rule_set_id = scan_config.get('rule_set_id')
                    prompt_template_id = scan_config.get('prompt_template_id')
                    
                    # 使用规则集和提示词模板进行分析
                    if rule_set_id or prompt_template_id:
                        result = await llm_service.analyze_code_with_rules(
                            content, language, 
                            rule_set_id=rule_set_id,
                            prompt_template_id=prompt_template_id,
                            db_session=db
                        )
                    else:
                        # 使用默认规则分析
                        result = await llm_service.analyze_code(content, language)
                    
                    # 写入问题记录
                    issues = result.get("issues", [])
                    for i in issues:
                        issue = AuditIssue(
                            task_id=task.id,
                            file_path=file_info['path'],
                            line_number=i.get('line', 1),
                            column_number=i.get('column'),
                            issue_type=i.get('type', 'maintainability'),
                            severity=i.get('severity', 'low'),
                            title=i.get('title', 'Issue'),
                            message=i.get('title', 'Issue'),
                            description=i.get('description'),
                            suggestion=i.get('suggestion'),
                            code_snippet=i.get('code_snippet'),
                            ai_explanation=json.dumps(i.get('xai')) if i.get('xai') else None,
                            status="open"
                        )
                        db.add(issue)
                        total_issues += 1
                    
                    # 记录质量评分
                    if "quality_score" in result:
                        quality_scores.append(result["quality_score"])
                    
                    # 更新任务进度
                    scanned_files += 1
                    task.scanned_files = scanned_files
                    task.total_lines = total_lines
                    task.issues_count = total_issues
                    await db.commit()
                    
                    print(f"📈 ZIP任务 {task_id}: 进度 {scanned_files}/{len(files_to_scan)}")
                    
                    # 请求间隔
                    await asyncio.sleep(llm_gap_ms / 1000)

                except Exception as file_error:
                    # 记录单文件失败
                    failed_files += 1
                    print(f"❌ ZIP任务分析文件失败 ({file_info['path']}): {file_error}")
                    await asyncio.sleep(llm_gap_ms / 1000)

            # 完成任务
            avg_quality_score = sum(quality_scores) / len(quality_scores) if quality_scores else 100.0
            
            # 如果有文件需要分析但全部失败，标记为失败
            if len(files_to_scan) > 0 and scanned_files == 0:
                task.status = "failed"
                task.completed_at = datetime.now(timezone.utc)
                task.scanned_files = 0
                task.total_lines = total_lines
                task.issues_count = 0
                task.quality_score = 0
                await db.commit()
                print(f"❌ ZIP任务 {task_id} 失败: 所有 {len(files_to_scan)} 个文件分析均失败，请检查 LLM API 配置")
            else:
                # 标记完成并写入统计
                task.status = "completed"
                task.completed_at = datetime.now(timezone.utc)
                task.scanned_files = scanned_files
                task.total_lines = total_lines
                task.issues_count = total_issues
                task.quality_score = avg_quality_score
                await db.commit()
                print(f"✅ ZIP任务 {task_id} 完成: 扫描 {scanned_files} 个文件, 发现 {total_issues} 个问题")
            # 清理任务控制状态
            task_control.cleanup_task(task_id)
            
        except Exception as e:
            # 记录失败
            print(f"❌ ZIP扫描失败: {e}")
            task.status = "failed"
            task.completed_at = datetime.now(timezone.utc)
            await db.commit()
            # 清理任务控制状态
            task_control.cleanup_task(task_id)
        finally:
            # Cleanup - 只清理解压目录，不删除源 ZIP 文件（已持久化存储）
            if extract_dir.exists():
                shutil.rmtree(extract_dir)


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
    上传 ZIP 文件并启动扫描，同时将 ZIP 文件保存到持久化存储。

    处理流程：
    - 校验项目与权限
    - 校验 ZIP 文件与大小
    - 保存 ZIP 到持久化存储
    - 创建任务并触发后台处理
    """
    # 校验项目存在
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 检查权限：只有项目所有者可以上传
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作此项目")
    
    # 校验文件类型
    if not file.filename.lower().endswith('.zip'):
        raise HTTPException(status_code=400, detail="请上传ZIP格式文件")
        
    # 保存上传文件到临时路径
    file_id = str(uuid.uuid4())
    file_path = f"/tmp/{file_id}.zip"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # 校验文件大小
    file_size = os.path.getsize(file_path)
    if file_size > 500 * 1024 * 1024:  # 500MB limit
        os.remove(file_path)
        raise HTTPException(status_code=400, detail="文件大小不能超过500MB")
    
    # 保存 ZIP 文件到持久化存储
    await save_project_zip(project_id, file_path, file.filename)
    
    # 解析扫描配置
    parsed_scan_config = {}
    if scan_config:
        try:
            parsed_scan_config = json.loads(scan_config)
        except json.JSONDecodeError:
            pass

    # 创建扫描任务
    task = AuditTask(
        project_id=project_id,
        created_by=current_user.id,
        task_type="zip_upload",
        status="pending",
        scan_config=scan_config if scan_config else "{}"
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # 获取用户配置
    user_config = await get_user_config_dict(db, current_user.id)
    
    # 将扫描配置注入到 user_config 中（包括规则集、提示词模板和排除模式）
    if parsed_scan_config:
        user_config['scan_config'] = {
            'file_paths': parsed_scan_config.get('file_paths', []),
            'exclude_patterns': parsed_scan_config.get('exclude_patterns', []),
            'rule_set_id': parsed_scan_config.get('rule_set_id'),
            'prompt_template_id': parsed_scan_config.get('prompt_template_id'),
        }

    # 触发后台任务 - 使用持久化存储的文件路径
    stored_zip_path = await load_project_zip(project_id)
    background_tasks.add_task(process_zip_task, task.id, stored_zip_path or file_path, AsyncSessionLocal, user_config)

    # 返回任务状态
    return {"task_id": task.id, "status": "queued"}


class ScanRequest(BaseModel):
    """扫描配置请求模型。"""
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
    使用已存储的 ZIP 文件启动扫描（无需重新上传）。

    处理流程：
    - 校验项目与权限
    - 校验已存储 ZIP
    - 创建任务并触发后台处理
    """
    # 校验项目存在
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 检查权限：只有项目所有者可以扫描
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作此项目")
    
    # 检查是否有存储的 ZIP 文件
    stored_zip_path = await load_project_zip(project_id)
    if not stored_zip_path:
        raise HTTPException(status_code=400, detail="项目没有已存储的ZIP文件，请先上传")
    
    # 创建扫描任务
    task = AuditTask(
        project_id=project_id,
        created_by=current_user.id,
        task_type="zip_upload",
        status="pending",
        scan_config=json.dumps(scan_request.dict()) if scan_request else "{}"
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # 获取用户配置
    user_config = await get_user_config_dict(db, current_user.id)
    
    # 将扫描配置注入到 user_config 中（包括规则集、提示词模板和排除模式）
    if scan_request:
        user_config['scan_config'] = {
            'file_paths': scan_request.file_paths or [],
            'exclude_patterns': scan_request.exclude_patterns or [],
            'rule_set_id': scan_request.rule_set_id,
            'prompt_template_id': scan_request.prompt_template_id,
        }

    # 触发后台任务
    background_tasks.add_task(process_zip_task, task.id, stored_zip_path, AsyncSessionLocal, user_config)

    # 返回任务状态
    return {"task_id": task.id, "status": "queued"}


class InstantAnalysisRequest(BaseModel):
    """即时分析请求模型。"""
    code: str
    language: str
    prompt_template_id: Optional[str] = None


class InstantAnalysisResponse(BaseModel):
    """即时分析响应模型。"""
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


async def get_user_config_dict(db: AsyncSession, user_id: str) -> dict:
    """
    获取用户配置字典（包含解密敏感字段）。

    处理流程：
    - 查询用户配置
    - 解析并解密敏感字段
    - 返回统一配置字典
    """
    # 延迟导入解密函数
    from app.core.encryption import decrypt_sensitive_data
    
    # 需要解密的敏感字段列表（与 config.py 保持一致）
    SENSITIVE_LLM_FIELDS = [
        'llmApiKey', 'geminiApiKey', 'openaiApiKey', 'claudeApiKey',
        'qwenApiKey', 'deepseekApiKey', 'zhipuApiKey', 'moonshotApiKey',
        'baiduApiKey', 'minimaxApiKey', 'doubaoApiKey'
    ]
    SENSITIVE_OTHER_FIELDS = ['githubToken', 'gitlabToken']
    
    def decrypt_config(config: dict, sensitive_fields: list) -> dict:
        """
        解密配置中的敏感字段。

        处理流程：
        - 拷贝配置
        - 遍历敏感字段并解密
        - 返回解密结果
        """
        # 拷贝配置
        decrypted = config.copy()
        # 遍历敏感字段
        for field in sensitive_fields:
            # 有值时解密
            if field in decrypted and decrypted[field]:
                decrypted[field] = decrypt_sensitive_data(decrypted[field])
        # 返回解密后的配置
        return decrypted
    
    # 查询用户配置
    result = await db.execute(
        select(UserConfig).where(UserConfig.user_id == user_id)
    )
    # 获取配置对象
    config = result.scalar_one_or_none()
    if not config:
        return {}
    
    # 解析配置
    llm_config = json.loads(config.llm_config) if config.llm_config else {}
    other_config = json.loads(config.other_config) if config.other_config else {}
    
    # 解密敏感字段
    llm_config = decrypt_config(llm_config, SENSITIVE_LLM_FIELDS)
    other_config = decrypt_config(other_config, SENSITIVE_OTHER_FIELDS)
    
    # 返回组合后的配置
    return {
        'llmConfig': llm_config,
        'otherConfig': other_config,
    }


@router.post("/instant")
async def instant_analysis(
    req: InstantAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user), 
) -> Any:
    """
    执行即时代码分析。

    处理流程：
    - 获取用户配置
    - 调用 LLM 分析
    - 保存分析记录
    - 返回分析结果
    """
    # 获取用户配置
    user_config = await get_user_config_dict(db, current_user.id)
    
    # 创建使用用户配置的 LLM 服务实例
    llm_service = LLMService(user_config=user_config)
    
    # 记录开始时间
    start_time = datetime.now(timezone.utc)
    
    try:
        # 如果指定了提示词模板，使用自定义分析
        # 统一使用 analyze_code_with_rules，会自动使用默认模板
        result = await llm_service.analyze_code_with_rules(
            req.code, req.language,
            prompt_template_id=req.prompt_template_id,
            db_session=db,
            use_default_template=True  # 没有指定模板时使用数据库中的默认模板
        )
    except Exception as e:
        # 分析失败，返回错误信息
        error_msg = str(e)
        print(f"❌ 即时分析失败: {error_msg}")
        raise HTTPException(
            status_code=500, 
            detail=f"代码分析失败: {error_msg}"
        )
    
    # 计算分析耗时
    end_time = datetime.now(timezone.utc)
    duration = (end_time - start_time).total_seconds()

    # 保存分析记录
    analysis = InstantAnalysis(
        user_id=current_user.id,
        language=req.language,
        code_content="",  # Do not persist code for privacy
        analysis_result=json.dumps(result),
        issues_count=len(result.get("issues", [])),
        quality_score=result.get("quality_score", 0),
        analysis_time=duration
    )
    db.add(analysis)
    await db.commit()
    await db.refresh(analysis)
    
    # 返回结果并附带分析记录 ID
    return {
        **result,
        "analysis_id": analysis.id,
        "analysis_time": duration
    }


@router.get("/instant/history", response_model=List[InstantAnalysisResponse])
async def get_instant_analysis_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
    limit: int = 20,
) -> Any:
    """
    获取用户即时分析历史记录。

    处理流程：
    - 查询用户历史记录
    - 按时间倒序返回
    """
    # 查询历史记录
    result = await db.execute(
        select(InstantAnalysis)
        .where(InstantAnalysis.user_id == current_user.id)
        .order_by(InstantAnalysis.created_at.desc())
        .limit(limit)
    )
    # 返回记录列表
    return result.scalars().all()


@router.delete("/instant/history/{analysis_id}")
async def delete_instant_analysis(
    analysis_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    删除指定的即时分析记录。

    处理流程：
    - 查询记录
    - 校验存在性
    - 删除并提交
    """
    # 查询分析记录
    result = await db.execute(
        select(InstantAnalysis)
        .where(InstantAnalysis.id == analysis_id)
        .where(InstantAnalysis.user_id == current_user.id)
    )
    # 获取记录对象
    analysis = result.scalar_one_or_none()
    
    if not analysis:
        raise HTTPException(status_code=404, detail="分析记录不存在")
    
    # 删除记录
    await db.delete(analysis)
    await db.commit()
    
    # 返回删除结果
    return {"message": "删除成功"}


@router.delete("/instant/history")
async def delete_all_instant_analyses(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    删除当前用户的全部即时分析记录。

    处理流程：
    - 批量删除用户记录
    - 提交事务
    """
    # 延迟导入 delete
    from sqlalchemy import delete
    
    # 执行批量删除
    await db.execute(
        delete(InstantAnalysis).where(InstantAnalysis.user_id == current_user.id)
    )
    await db.commit()
    
    # 返回删除结果
    return {"message": "已清空所有历史记录"}


@router.get("/instant/history/{analysis_id}/report/pdf")
async def export_instant_report_pdf(
    analysis_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    根据分析记录 ID 导出即时分析 PDF 报告。

    处理流程：
    - 查询分析记录
    - 解析分析结果
    - 生成 PDF 并返回
    """
    # 延迟导入响应与报告生成器
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
        analysis_result,
        analysis.language,
        analysis.analysis_time
    )
    
    # 构建文件名并返回 PDF 文件
    filename = f"instant-analysis-{analysis.language}-{analysis.id[:8]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )
