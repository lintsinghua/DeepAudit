from app.services.analysis_checkpoint import analyze_file
from app.services.archive import extract_zip
from datetime import datetime, timezone
import shutil
import os
import json
from pathlib import Path
import zipfile
import asyncio

from app.models.audit import AuditTask, AuditIssue
from app.services.llm.service import LLMService
from app.services.scanner import (
    task_control,
    is_text_file,
    should_exclude,
    get_language_from_path,
    get_analysis_config,
)
from app.core.config import settings


def normalize_path(path: str) -> str:
    """
    统一路径分隔符为正斜杠，确保跨平台兼容性
    Windows 使用反斜杠 (\)，Unix/Mac 使用正斜杠 (/)
    统一转换为正斜杠以保证一致性
    """
    return path.replace("\\", "/")


async def process_zip_task(
    task_id: str,
    file_path: str,
    db_session_factory,
    user_config: dict = None,
    *,
    project_root: str | None = None,
):
    """后台ZIP文件处理任务"""
    async with db_session_factory() as db:
        task = await db.get(AuditTask, task_id)
        if not task:
            return

        extract_dir = Path(project_root) if project_root else Path(f"/tmp/{task_id}")
        try:
            task.status = "running"
            task.started_at = datetime.now(timezone.utc)
            await db.commit()

            # 创建使用用户配置的LLM服务实例
            llm_service = LLMService(user_config=user_config or {})

            if not project_root:
                if extract_dir.exists():
                    await asyncio.to_thread(shutil.rmtree, extract_dir)
                extract_dir.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(file_path, "r") as zip_ref:
                    await asyncio.to_thread(
                        extract_zip,
                        zip_ref,
                        str(extract_dir),
                        cancel_check=lambda: task_control.is_cancelled(task_id),
                    )

            # 获取用户自定义排除模式
            scan_config = (user_config or {}).get("scan_config", {})
            custom_exclude_patterns = scan_config.get("exclude_patterns", [])

            # Find files
            files_to_scan = []
            for root, dirs, files in os.walk(extract_dir):
                dirs.sort()
                files.sort()
                # 排除常见非代码目录
                dirs[:] = [
                    d
                    for d in dirs
                    if d not in ["node_modules", "__pycache__", ".git", "dist", "build", "vendor"]
                ]

                for file in files:
                    full_path = Path(root) / file
                    # 统一使用正斜杠，确保跨平台兼容性
                    rel_path = normalize_path(str(full_path.relative_to(extract_dir)))

                    # 检查文件类型和排除规则（包含用户自定义排除模式）
                    if (
                        not full_path.is_symlink()
                        and is_text_file(rel_path)
                        and not should_exclude(rel_path, custom_exclude_patterns)
                    ):
                        try:
                            if full_path.stat().st_size > settings.MAX_FILE_SIZE_BYTES:
                                continue
                            if full_path.stat().st_size <= settings.MAX_FILE_SIZE_BYTES:
                                files_to_scan.append(
                                    {
                                        "path": rel_path,
                                    }
                                )
                        except:
                            pass

            # 获取分析配置（优先使用用户配置）
            analysis_config = get_analysis_config(user_config)
            max_analyze_files = analysis_config["max_analyze_files"]
            llm_gap_ms = analysis_config["llm_gap_ms"]

            # 限制文件数量
            # 如果指定了特定文件，则只分析这些文件
            target_files = scan_config.get("file_paths", [])
            if target_files:
                # 统一目标文件路径的分隔符，确保匹配一致性
                normalized_targets = {normalize_path(p) for p in target_files}
                print(f"🎯 ZIP任务: 指定分析 {len(normalized_targets)} 个文件")
                files_to_scan = [f for f in files_to_scan if f["path"] in normalized_targets]
            elif max_analyze_files > 0:
                files_to_scan = files_to_scan[:max_analyze_files]

            task.total_files = len(files_to_scan)
            await db.commit()

            print(
                f"📊 ZIP任务 {task_id}: 找到 {len(files_to_scan)} 个文件 (最大文件数: {max_analyze_files}, 请求间隔: {llm_gap_ms}ms)"
            )

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
                    content = await asyncio.to_thread(
                        (extract_dir / file_info["path"]).read_text, errors="ignore"
                    )
                    total_lines += content.count("\n") + 1
                    language = get_language_from_path(file_info["path"])

                    # 获取规则集和提示词模板ID
                    scan_config = (user_config or {}).get("scan_config", {})
                    rule_set_id = scan_config.get("rule_set_id")
                    prompt_template_id = scan_config.get("prompt_template_id")

                    # 使用规则集和提示词模板进行分析
                    result = await analyze_file(
                        task_id,
                        file_info["path"],
                        content,
                        llm_service,
                        language,
                        rule_set_id=rule_set_id,
                        prompt_template_id=prompt_template_id,
                        db=db,
                    )

                    issues = result.get("issues", [])
                    for i in issues:
                        issue = AuditIssue(
                            task_id=task.id,
                            file_path=file_info["path"],
                            line_number=i.get("line", 1),
                            column_number=i.get("column"),
                            issue_type=i.get("type", "maintainability"),
                            severity=i.get("severity", "low"),
                            title=i.get("title", "Issue"),
                            message=i.get("title", "Issue"),
                            description=i.get("description"),
                            suggestion=i.get("suggestion"),
                            code_snippet=i.get("code_snippet"),
                            ai_explanation=json.dumps(i.get("xai")) if i.get("xai") else None,
                            status="open",
                        )
                        db.add(issue)
                        total_issues += 1

                    if "quality_score" in result:
                        quality_scores.append(result["quality_score"])

                    scanned_files += 1
                    task.scanned_files = scanned_files
                    task.total_lines = total_lines
                    task.issues_count = total_issues
                    await db.commit()

                    print(f"📈 ZIP任务 {task_id}: 进度 {scanned_files}/{len(files_to_scan)}")

                    # 请求间隔
                    await asyncio.sleep(llm_gap_ms / 1000)

                except Exception as file_error:
                    failed_files += 1
                    print(f"❌ ZIP任务分析文件失败 ({file_info['path']}): {file_error}")
                    await asyncio.sleep(llm_gap_ms / 1000)

            # 完成任务
            avg_quality_score = (
                sum(quality_scores) / len(quality_scores) if quality_scores else 100.0
            )

            # 如果有文件需要分析但全部失败，标记为失败
            if len(files_to_scan) > 0 and scanned_files == 0:
                task.status = "failed"
                task.completed_at = datetime.now(timezone.utc)
                task.scanned_files = 0
                task.total_lines = total_lines
                task.issues_count = 0
                task.quality_score = 0
                await db.commit()
                print(
                    f"❌ ZIP任务 {task_id} 失败: 所有 {len(files_to_scan)} 个文件分析均失败，请检查 LLM API 配置"
                )
            else:
                task.status = "completed"
                task.completed_at = datetime.now(timezone.utc)
                task.scanned_files = scanned_files
                task.total_lines = total_lines
                task.issues_count = total_issues
                task.quality_score = avg_quality_score
                await db.commit()
                print(
                    f"✅ ZIP任务 {task_id} 完成: 扫描 {scanned_files} 个文件, 发现 {total_issues} 个问题"
                )
            task_control.cleanup_task(task_id)

        except Exception as e:
            print(f"❌ ZIP扫描失败: {e}")
            task.status = "failed"
            task.completed_at = datetime.now(timezone.utc)
            await db.commit()
            task_control.cleanup_task(task_id)
        finally:
            # Cleanup - 只清理解压目录，不删除源ZIP文件（已持久化存储）
            if not project_root and extract_dir.exists():
                await asyncio.to_thread(shutil.rmtree, extract_dir)
