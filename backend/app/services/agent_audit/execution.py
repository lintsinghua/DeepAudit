"""Execution services for agent audits."""

import asyncio
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.encryption import decrypt_sensitive_data
from app.db.session import async_session_factory
from app.models.agent_task import (
    AgentEvent,
    AgentTask,
    AgentTaskPhase,
    AgentTaskStatus,
)
from app.services.agent.agents.base import AgentResult
from app.services.audit_queue import load_checkpoint, save_checkpoint

logger = logging.getLogger(__name__)
from .results import _calculate_security_score, _get_user_config, _save_agent_tree, _save_findings
from .runtime import (
    _cancelled_tasks,
    _running_asyncio_tasks,
    _running_event_managers,
    _running_orchestrators,
    _running_tasks,
    is_task_cancelled,
)
from .tools import _collect_project_info, _initialize_tools
from .workspace import _get_project_root


async def _execute_agent_task(task_id: str, user_config_override=None):
    """
    在后台执行 Agent 任务 - 使用动态 Agent 树架构

    架构：OrchestratorAgent 作为大脑，动态调度子 Agent
    """
    import time

    from app.core.config import settings
    from app.services.agent.agents import (
        AnalysisAgent,
        OrchestratorAgent,
        ReconAgent,
        VerificationAgent,
    )
    from app.services.agent.core import agent_registry
    from app.services.agent.event_manager import AgentEventEmitter, EventManager
    from app.services.agent.tools import SandboxManager
    from app.services.llm.service import LLMService

    # 🔥 在任务最开始就初始化 Docker 沙箱管理器
    # 这样可以确保整个任务生命周期内使用同一个管理器，并且尽早发现 Docker 问题
    logger.info(f"🚀 Starting execution for task {task_id}")
    sandbox_manager = SandboxManager()
    await sandbox_manager.initialize()
    logger.info(
        f"🐳 Global Sandbox Manager initialized (Available: {sandbox_manager.is_available})"
    )

    # 🔥 提前创建事件管理器，以便在克隆仓库和索引时发送实时日志
    from app.services.agent.event_manager import AgentEventEmitter, EventManager

    event_manager = EventManager(db_session_factory=async_session_factory)
    event_manager.create_queue(task_id)
    event_emitter = AgentEventEmitter(task_id, event_manager)
    async with async_session_factory() as event_db:
        event_emitter._sequence = (
            await event_db.scalar(
                select(func.max(AgentEvent.sequence)).where(AgentEvent.task_id == task_id)
            )
        ) or 0
    _running_event_managers[task_id] = event_manager

    async with async_session_factory() as db:
        orchestrator = None
        start_time = time.time()

        try:
            # 获取任务
            task = await db.get(AgentTask, task_id, options=[selectinload(AgentTask.project)])
            if not task:
                logger.error(f"Task {task_id} not found")
                return

            # 获取项目
            project = task.project
            if not project:
                logger.error(f"Project not found for task {task_id}")
                return

            # 🔥 发送任务开始事件 - 使用 phase_start 让前端知道进入准备阶段
            await event_emitter.emit_phase_start("preparation", f"🚀 任务开始执行: {project.name}")

            # 更新任务阶段为准备中
            task.status = AgentTaskStatus.RUNNING
            task.started_at = datetime.now(timezone.utc)
            task.current_phase = AgentTaskPhase.PLANNING  # preparation 对应 PLANNING
            await db.commit()

            # 获取用户配置（需要在获取项目根目录之前，以便传递 token）
            user_config = (
                user_config_override
                if user_config_override is not None
                else await _get_user_config(db, task.created_by)
            )

            # 从用户配置中提取 token和SSH密钥（用于私有仓库克隆）
            other_config = (user_config or {}).get("otherConfig", {})
            github_token = other_config.get("githubToken") or settings.GITHUB_TOKEN
            gitlab_token = other_config.get("gitlabToken") or settings.GITLAB_TOKEN
            gitea_token = other_config.get("giteaToken") or settings.GITEA_TOKEN

            # 解密SSH私钥
            ssh_private_key = None
            if "sshPrivateKey" in other_config:
                try:
                    encrypted_key = other_config["sshPrivateKey"]
                    ssh_private_key = decrypt_sensitive_data(encrypted_key)
                    logger.info("成功解密SSH私钥")
                except Exception as e:
                    logger.warning(f"解密SSH私钥失败: {e}")

            # 获取项目根目录（传递任务指定的分支和认证 token/SSH密钥）
            # 🔥 传递 event_emitter 以发送克隆进度
            project_root = await _get_project_root(
                project,
                task_id,
                task.branch_name,
                github_token=github_token,
                gitlab_token=gitlab_token,
                gitea_token=gitea_token,  # 🔥 新增
                ssh_private_key=ssh_private_key,  # 🔥 新增SSH密钥
                event_emitter=event_emitter,  # 🔥 新增
            )

            # 🔥 自动修正 target_files 路径
            # 如果发生了目录调整（例如 ZIP 解压后只有一层目录，root 被下移），
            # 原有的 target_files (如 "Prefix/file.php") 可能无法匹配。
            # 我们需要检测并移除这些无效的前缀。
            if task.target_files and len(task.target_files) > 0:
                # 1. 检查是否存在不匹配的文件
                all_exist = True
                for tf in task.target_files:
                    if not os.path.exists(os.path.join(project_root, tf)):
                        all_exist = False
                        break

                if not all_exist:
                    logger.info(f"Target files path mismatch detected in {project_root}")
                    # 尝试通过路径匹配来修复
                    # 获取当前根目录的名称
                    root_name = os.path.basename(project_root)

                    new_target_files = []
                    fixed_count = 0

                    for tf in task.target_files:
                        # 检查文件是否以 root_name 开头（例如 "PHP-Project/index.php" 而 root 是 ".../PHP-Project"）
                        if tf.startswith(root_name + "/"):
                            fixed_path = tf[len(root_name) + 1 :]
                            if os.path.exists(os.path.join(project_root, fixed_path)):
                                new_target_files.append(fixed_path)
                                fixed_count += 1
                                continue

                        # 如果上面的没匹配，尝试暴力搜索（只针对未找到的文件）
                        # 这种情况比较少见，先保留原样或标记为丢失
                        if os.path.exists(os.path.join(project_root, tf)):
                            new_target_files.append(tf)
                        else:
                            # 尝试查看 tf 的 basename 是否在根目录直接存在（针对常见的最简情况）
                            basename = os.path.basename(tf)
                            if os.path.exists(os.path.join(project_root, basename)):
                                new_target_files.append(basename)
                                fixed_count += 1
                            else:
                                # 实在找不到，保留原样，让后续流程报错或忽略
                                new_target_files.append(tf)

                    if fixed_count > 0:
                        logger.info(f"🔧 Auto-fixed {fixed_count} target file paths")
                        await event_emitter.emit_info(
                            f"🔧 自动修正了 {fixed_count} 个目标文件的路径"
                        )
                        task.target_files = new_target_files

            # 🔥 重新验证修正后的文件
            valid_target_files = []
            if task.target_files:
                for tf in task.target_files:
                    if os.path.exists(os.path.join(project_root, tf)):
                        valid_target_files.append(tf)
                    else:
                        logger.warning(f"⚠️ Target file not found: {tf}")

                if not valid_target_files:
                    raise ValueError("找不到指定的扫描文件，请检查文件路径后重试")
                elif len(valid_target_files) < len(task.target_files):
                    logger.warning(
                        f"⚠️ Partial target files missing. Found {len(valid_target_files)}/{len(task.target_files)}"
                    )
                    task.target_files = valid_target_files

            logger.info(f"🚀 Task {task_id} started with Dynamic Agent Tree architecture")

            # 🔥 获取项目根目录后检查取消
            if is_task_cancelled(task_id):
                logger.info(f"[Cancel] Task {task_id} cancelled after project preparation")
                raise asyncio.CancelledError("任务已取消")

            checkpoint = await load_checkpoint(task_id)
            if checkpoint.get("result"):
                result = AgentResult(**checkpoint["result"])
                sub_agent_stats = checkpoint.get("sub_agent_stats", [])
                await event_emitter.emit_info("♻️ 恢复已完成的分析结果")
            else:
                # 创建 LLM 服务
                llm_service = LLMService(user_config=user_config)

                # 初始化工具集 - 传递排除模式和目标文件以及预初始化的 sandbox_manager
                # 🔥 传递 event_emitter 以发送索引进度，传递 task_id 以支持取消
                tools = await _initialize_tools(
                    project_root,
                    llm_service,
                    user_config,
                    sandbox_manager=sandbox_manager,
                    exclude_patterns=task.exclude_patterns,
                    target_files=task.target_files,
                    project_id=str(project.id),  # 🔥 传递 project_id 用于 RAG
                    event_emitter=event_emitter,  # 🔥 新增
                    task_id=task_id,  # 🔥 新增：用于取消检查
                )

                # 🔥 初始化工具后检查取消
                if is_task_cancelled(task_id):
                    logger.info(f"[Cancel] Task {task_id} cancelled after tools initialization")
                    raise asyncio.CancelledError("任务已取消")

                # 创建子 Agent
                recon_agent = ReconAgent(
                    llm_service=llm_service,
                    tools=tools.get("recon", {}),
                    event_emitter=event_emitter,
                )

                analysis_agent = AnalysisAgent(
                    llm_service=llm_service,
                    tools=tools.get("analysis", {}),
                    event_emitter=event_emitter,
                )

                verification_agent = VerificationAgent(
                    llm_service=llm_service,
                    tools=tools.get("verification", {}),
                    event_emitter=event_emitter,
                )

                # 创建 Orchestrator Agent
                orchestrator = OrchestratorAgent(
                    llm_service=llm_service,
                    tools=tools.get("orchestrator", {}),
                    event_emitter=event_emitter,
                    sub_agents={
                        "recon": recon_agent,
                        "analysis": analysis_agent,
                        "verification": verification_agent,
                    },
                )

                # 🔥 设置外部取消检查回调
                # 这确保即使 runner.cancel() 失败，Agent 也能通过 checking 全局标志感知取消
                def check_global_cancel():
                    return is_task_cancelled(task_id)

                orchestrator.set_cancel_callback(check_global_cancel)
                # 同时也为子 Agent 设置（虽然 Orchestrator 会传播）
                recon_agent.set_cancel_callback(check_global_cancel)
                analysis_agent.set_cancel_callback(check_global_cancel)
                verification_agent.set_cancel_callback(check_global_cancel)

                # 注册到全局
                _running_orchestrators[task_id] = orchestrator
                _running_tasks[task_id] = orchestrator  # 兼容旧的取消逻辑
                _running_event_managers[task_id] = event_manager  # 用于 SSE 流

                # 🔥 清理旧的 Agent 注册表，避免显示多个树
                from app.services.agent.core import agent_registry

                agent_registry.clear()

                # 注册 Orchestrator 到 Agent Registry（使用其内置方法）
                orchestrator._register_to_registry(task="Root orchestrator for security audit")

                await event_emitter.emit_info("🧠 动态 Agent 树架构启动")
                await event_emitter.emit_info(f"📁 项目路径: {project_root}")

                # 收集项目信息 - 传递排除模式和目标文件
                project_info = await _collect_project_info(
                    project_root,
                    project.name,
                    exclude_patterns=task.exclude_patterns,
                    target_files=task.target_files,
                )

                # 更新任务文件统计
                task.total_files = project_info.get("file_count", 0)
                await db.commit()

                # 构建输入数据
                input_data = {
                    "project_info": project_info,
                    "config": {
                        "target_vulnerabilities": task.target_vulnerabilities or [],
                        "verification_level": task.verification_level or "sandbox",
                        "exclude_patterns": task.exclude_patterns or [],
                        "target_files": task.target_files or [],
                        "max_iterations": task.max_iterations or 50,
                    },
                    "project_root": project_root,
                    "task_id": task_id,
                }

                # 执行 Orchestrator
                await event_emitter.emit_phase_start(
                    "orchestration", "🎯 Orchestrator 开始编排审计流程"
                )
                task.current_phase = AgentTaskPhase.ANALYSIS
                await db.commit()

                # 🔥 将 orchestrator.run() 包装在 asyncio.Task 中，以便可以强制取消
                run_task = asyncio.create_task(orchestrator.run(input_data))
                _running_asyncio_tasks[task_id] = run_task

                try:
                    result = await run_task
                finally:
                    _running_asyncio_tasks.pop(task_id, None)

                sub_agent_stats = [
                    agent.get_stats()
                    for agent in orchestrator.sub_agents.values()
                    if hasattr(agent, "get_stats")
                ]
                if result.success:
                    await save_checkpoint(
                        task_id, result=result.to_dict(), sub_agent_stats=sub_agent_stats
                    )

            # 处理结果
            duration_ms = int((time.time() - start_time) * 1000)

            await db.refresh(task)

            if result.success:
                # 🔥 CRITICAL FIX: Log and save findings with detailed debugging
                findings = result.data.get("findings", [])
                logger.info(
                    f"[AgentTask] Task {task_id} completed with {len(findings)} findings from Orchestrator"
                )

                # 🔥 Debug: Log each finding for verification
                for i, f in enumerate(findings[:5]):  # Log first 5
                    if isinstance(f, dict):
                        logger.debug(
                            f"[AgentTask] Finding {i + 1}: {f.get('title', 'N/A')[:50]} - {f.get('severity', 'N/A')}"
                        )

                # 🔥 v2.1: 传递 project_root 用于文件路径验证
                saved_count = await _save_findings(db, task_id, findings, project_root=project_root)
                logger.info(
                    f"[AgentTask] Saved {saved_count}/{len(findings)} findings (filtered {len(findings) - saved_count} hallucinations)"
                )

                # 更新任务统计
                # 🔥 CRITICAL FIX: 在设置完成前再次检查取消状态
                # 避免 "取消后后端继续运行并最终标记为完成" 的问题
                if is_task_cancelled(task_id):
                    logger.info(
                        f"[AgentTask] Task {task_id} was cancelled, overriding success result"
                    )
                    task.status = AgentTaskStatus.CANCELLED
                else:
                    task.status = AgentTaskStatus.COMPLETED
                task.completed_at = datetime.now(timezone.utc)
                task.current_phase = AgentTaskPhase.REPORTING
                task.findings_count = saved_count  # 🔥 v2.1: 使用实际保存的数量（排除幻觉）

                # 🔥 CRITICAL FIX: 累加所有子 Agent 的统计，而不仅仅是 Orchestrator 的
                total_iterations = result.iterations
                tool_calls_count = result.tool_calls
                tokens_used = result.tokens_used

                for sub_stats in sub_agent_stats:
                    total_iterations += sub_stats.get("iterations", 0)
                    tool_calls_count += sub_stats.get("tool_calls", 0)
                    tokens_used += sub_stats.get("tokens_used", 0)

                task.total_iterations = total_iterations
                task.tool_calls_count = tool_calls_count
                task.tokens_used = tokens_used

                # 🔥 统计文件数量
                # analyzed_files = 实际扫描过的文件数（任务完成时等于 total_files）
                # files_with_findings = 有漏洞发现的唯一文件数
                task.analyzed_files = task.total_files  # Agent 扫描了所有符合条件的文件

                files_with_findings_set = set()
                for f in findings:
                    if isinstance(f, dict):
                        file_path = (
                            f.get("file_path")
                            or f.get("file")
                            or f.get("location", "").split(":")[0]
                        )
                        if file_path:
                            files_with_findings_set.add(file_path)
                task.files_with_findings = len(files_with_findings_set)

                # 统计严重程度和验证状态
                verified_count = 0
                task.critical_count = task.high_count = task.medium_count = task.low_count = 0
                for f in findings:
                    if isinstance(f, dict):
                        sev = str(f.get("severity", "low")).lower()
                        if sev == "critical":
                            task.critical_count += 1
                        elif sev == "high":
                            task.high_count += 1
                        elif sev == "medium":
                            task.medium_count += 1
                        elif sev == "low":
                            task.low_count += 1
                        # 🔥 统计已验证的发现
                        if f.get("is_verified") or f.get("verdict") == "confirmed":
                            verified_count += 1
                task.verified_count = verified_count

                # 计算安全评分
                task.security_score = _calculate_security_score(findings)
                task.quality_score = _calculate_security_score(findings)
                # 🔥 注意: progress_percentage 是计算属性，不需要手动设置
                # 当 status = COMPLETED 时会自动返回 100.0

                await db.commit()

                await event_emitter.emit_task_complete(
                    findings_count=len(findings),
                    duration_ms=duration_ms,
                )

                logger.info(
                    f"✅ Task {task_id} completed: {len(findings)} findings, {duration_ms}ms"
                )
            else:
                # 🔥 检查是否是取消导致的失败
                if result.error == "任务已取消":
                    # 状态可能已经被 cancel API 更新，只需确保一致性
                    if task.status != AgentTaskStatus.CANCELLED:
                        task.status = AgentTaskStatus.CANCELLED
                        task.completed_at = datetime.now(timezone.utc)
                        await db.commit()
                    logger.info(f"🛑 Task {task_id} cancelled")
                else:
                    task.status = AgentTaskStatus.FAILED
                    task.error_message = result.error or "Unknown error"
                    task.completed_at = datetime.now(timezone.utc)
                    await db.commit()

                    await event_emitter.emit_error(result.error or "Unknown error")
                    logger.error(f"❌ Task {task_id} failed: {result.error}")

        except asyncio.CancelledError:
            logger.info(f"Task {task_id} cancelled")
            try:
                task = await db.get(AgentTask, task_id)
                if task:
                    task.status = AgentTaskStatus.CANCELLED
                    task.completed_at = datetime.now(timezone.utc)
                    await db.commit()
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}", exc_info=True)

            try:
                task = await db.get(AgentTask, task_id)
                if task:
                    task.status = AgentTaskStatus.FAILED
                    task.error_message = str(e)[:1000]
                    task.completed_at = datetime.now(timezone.utc)
                    await db.commit()
            except Exception as db_error:
                logger.error(f"Failed to update task status: {db_error}")

        finally:
            # 🔥 在清理之前保存 Agent 树到数据库
            try:
                async with async_session_factory() as save_db:
                    await _save_agent_tree(save_db, task_id)
            except Exception as save_error:
                logger.error(f"Failed to save agent tree: {save_error}")

            # 清理
            _running_orchestrators.pop(task_id, None)
            _running_tasks.pop(task_id, None)
            _running_event_managers.pop(task_id, None)
            _running_asyncio_tasks.pop(task_id, None)  # 🔥 清理 asyncio task
            await event_manager.flush_tokens()
            _cancelled_tasks.discard(task_id)  # 🔥 清理取消标志

            # 🔥 清理整个 Agent 注册表（包括所有子 Agent）
            agent_registry.clear()

            logger.debug(f"Task {task_id} cleaned up")
