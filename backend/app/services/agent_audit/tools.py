"""Tools services for agent audits."""

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from app.services.audit_queue import workspace_for

logger = logging.getLogger(__name__)
from .runtime import is_task_cancelled


async def _initialize_tools(
    project_root: str,
    llm_service,
    user_config: Optional[Dict[str, Any]],
    sandbox_manager: Any,  # 传递预初始化的 SandboxManager
    exclude_patterns: Optional[List[str]] = None,
    target_files: Optional[List[str]] = None,
    project_id: Optional[str] = None,  # 🔥 用于 RAG collection_name
    event_emitter: Optional[Any] = None,  # 🔥 新增：用于发送实时日志
    task_id: Optional[str] = None,  # 🔥 新增：用于取消检查
) -> Dict[str, Dict[str, Any]]:
    """初始化工具集

    Args:
        project_root: 项目根目录
        llm_service: LLM 服务
        user_config: 用户配置
        sandbox_manager: 沙箱管理器
        exclude_patterns: 排除模式列表
        target_files: 目标文件列表
        project_id: 项目 ID（用于 RAG collection_name）
        event_emitter: 事件发送器（用于发送实时日志）
        task_id: 任务 ID（用于取消检查）
    """
    from app.core.config import settings
    from app.services.agent.knowledge import (
        GetVulnerabilityKnowledgeTool,
        SecurityKnowledgeQueryTool,
    )
    from app.services.agent.tools import (
        BanditTool,
        CreateVulnerabilityReportTool,
        DataFlowAnalysisTool,
        FileReadTool,
        FileSearchTool,
        FunctionContextTool,
        GitleaksTool,
        ListFilesTool,
        NpmAuditTool,  # 🔥 Added missing tools
        OSVScannerTool,
        PatternMatchTool,
        RAGQueryTool,
        ReflectTool,
        SafetyTool,
        SecurityCodeSearchTool,
        SemgrepTool,
        ThinkTool,
        TruffleHogTool,
    )

    # 🔥 RAG 相关导入
    from app.services.rag import CodeIndexer, CodeRetriever, EmbeddingService, IndexUpdateMode

    # 辅助函数：发送事件
    async def emit(message: str, level: str = "info"):
        if event_emitter:
            logger.debug(f"[EMIT-TOOLS] Sending {level}: {message[:60]}...")
            if level == "info":
                await event_emitter.emit_info(message)
            elif level == "warning":
                await event_emitter.emit_warning(message)
            elif level == "error":
                await event_emitter.emit_error(message)
        else:
            logger.warning(f"[EMIT-TOOLS] No event_emitter, skipping: {message[:60]}...")

    # ============ 🔥 初始化 RAG 系统 ============
    retriever = None
    try:
        await emit(f"🔍 正在初始化 RAG 系统...")

        # 从用户配置中获取 embedding 配置
        user_llm_config = (user_config or {}).get("llmConfig", {})
        user_other_config = (user_config or {}).get("otherConfig", {})
        user_embedding_config = user_other_config.get("embedding_config", {})

        # Embedding Provider 优先级：用户嵌入配置 > 环境变量
        embedding_provider = user_embedding_config.get("provider") or getattr(
            settings, "EMBEDDING_PROVIDER", "openai"
        )

        # Embedding Model 优先级：用户嵌入配置 > 环境变量
        embedding_model = user_embedding_config.get("model") or getattr(
            settings, "EMBEDDING_MODEL", "text-embedding-3-small"
        )

        # API Key 优先级：用户嵌入配置 > 环境变量 EMBEDDING_API_KEY > 用户 LLM 配置 > 环境变量 LLM_API_KEY
        # 注意：API Key 可以共享，因为很多用户使用同一个 OpenAI Key 做 LLM 和 Embedding
        embedding_api_key = (
            user_embedding_config.get("api_key")
            or getattr(settings, "EMBEDDING_API_KEY", None)
            or user_llm_config.get("llmApiKey")
            or getattr(settings, "LLM_API_KEY", "")
            or ""
        )

        # Base URL 优先级：用户嵌入配置 > 环境变量 EMBEDDING_BASE_URL > None（使用提供商默认地址）
        # 🔥 重要：Base URL 不应该回退到 LLM 的 base_url，因为 Embedding 和 LLM 可能使用完全不同的服务
        # 例如：LLM 使用 SiliconFlow，但 Embedding 使用 HuggingFace
        embedding_base_url = (
            user_embedding_config.get("base_url")
            or getattr(settings, "EMBEDDING_BASE_URL", None)
            or None
        )

        logger.info(
            f"RAG 配置: provider={embedding_provider}, model={embedding_model}, base_url={embedding_base_url or '(使用默认)'}"
        )
        await emit(f"📊 Embedding 配置: {embedding_provider}/{embedding_model}")

        # 创建 Embedding 服务
        embedding_service = EmbeddingService(
            provider=embedding_provider,
            model=embedding_model,
            api_key=embedding_api_key,
            base_url=embedding_base_url,
        )
        # 使用用户配置的 batch_size
        embedding_service.batch_size = user_embedding_config.get("batch_size", 100)

        # 创建 collection_name（基于 project_id）
        collection_name = f"project_{project_id}" if project_id else "default_project"

        # 🔥 v2.0: 创建 CodeIndexer 并进行智能索引
        # 智能索引会自动：
        # - 检测 embedding 模型变更，如需要则自动重建
        # - 对比文件 hash，只更新变化的文件（增量更新）
        indexer = CodeIndexer(
            collection_name=collection_name,
            embedding_service=embedding_service,
            persist_directory=str(workspace_for(task_id) / "vectors")
            if task_id
            else settings.VECTOR_DB_PATH,
        )

        logger.info(f"📝 开始智能索引项目: {project_root}")
        await emit(f"📝 正在构建代码向量索引...")

        index_progress = None
        last_progress_update = 0
        last_embedding_progress = [0]  # 使用列表以便在闭包中修改
        embedding_total = [0]  # 记录总数

        # 🔥 嵌入进度回调函数（同步，但会调度异步任务）
        def on_embedding_progress(processed: int, total: int):
            embedding_total[0] = total
            # 每处理 50 个或完成时更新
            if processed - last_embedding_progress[0] >= 50 or processed == total:
                last_embedding_progress[0] = processed
                percentage = (processed / total * 100) if total > 0 else 0
                msg = f"🔢 嵌入进度: {processed}/{total} ({percentage:.0f}%)"
                logger.info(msg)
                # 使用 asyncio.create_task 调度异步 emit
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(emit(msg))
                except Exception as e:
                    logger.warning(f"Failed to emit embedding progress: {e}")

        # 🔥 创建取消检查函数，用于在嵌入批处理中检查取消状态
        def check_cancelled() -> bool:
            return task_id is not None and is_task_cancelled(task_id)

        async for progress in indexer.smart_index_directory(
            directory=project_root,
            exclude_patterns=exclude_patterns or [],
            include_patterns=target_files,  # 🔥 传递 target_files 限制索引范围
            update_mode=IndexUpdateMode.SMART,
            embedding_progress_callback=on_embedding_progress,
            cancel_check=check_cancelled,  # 🔥 传递取消检查函数
        ):
            # 🔥 在索引过程中检查取消状态
            if check_cancelled():
                logger.info(f"[Cancel] RAG indexing cancelled for task {task_id}")
                raise asyncio.CancelledError("任务已取消")

            index_progress = progress
            # 每处理 10 个文件或有重要变化时发送进度更新
            if (
                progress.processed_files - last_progress_update >= 10
                or progress.processed_files == progress.total_files
            ):
                if progress.total_files > 0:
                    await emit(
                        f"📝 索引进度: {progress.processed_files}/{progress.total_files} 文件 "
                        f"({progress.progress_percentage:.0f}%)"
                    )
                last_progress_update = progress.processed_files

            # 🔥 发送状态消息（如嵌入向量生成进度）
            if progress.status_message:
                await emit(progress.status_message)
                progress.status_message = ""  # 清空已发送的消息

        if index_progress:
            summary = (
                f"✅ 索引完成: 模式={index_progress.update_mode}, "
                f"新增={index_progress.added_files}, "
                f"更新={index_progress.updated_files}, "
                f"删除={index_progress.deleted_files}, "
                f"代码块={index_progress.indexed_chunks}"
            )
            logger.info(summary)
            await emit(summary)

        # 创建 CodeRetriever（用于搜索）
        # 🔥 传递 api_key，用于自动适配 collection 的 embedding 配置
        retriever = CodeRetriever(
            collection_name=collection_name,
            embedding_service=embedding_service,
            persist_directory=str(workspace_for(task_id) / "vectors")
            if task_id
            else settings.VECTOR_DB_PATH,
            api_key=embedding_api_key,  # 🔥 传递 api_key 以支持自动切换 embedding
        )

        logger.info(f"✅ RAG 系统初始化成功: collection={collection_name}")
        await emit(f"✅ RAG 系统初始化成功")

    except Exception as e:
        logger.warning(f"⚠️ RAG 系统初始化失败: {e}")
        await emit(f"⚠️ RAG 系统初始化失败: {e}", "warning")
        import traceback

        logger.debug(f"RAG 初始化异常详情:\n{traceback.format_exc()}")
        retriever = None

    # 基础工具 - 传递排除模式和目标文件
    base_tools = {
        "read_file": FileReadTool(project_root, exclude_patterns, target_files),
        "list_files": ListFilesTool(project_root, exclude_patterns, target_files),
        "search_code": FileSearchTool(project_root, exclude_patterns, target_files),
        "think": ThinkTool(),
        "reflect": ReflectTool(),
    }

    # Recon 工具
    recon_tools = {
        **base_tools,
        # 🔥 外部侦察工具 (Recon 阶段也需要使用这些工具来收集初步信息)
        "semgrep_scan": SemgrepTool(project_root, sandbox_manager),
        "bandit_scan": BanditTool(project_root, sandbox_manager),
        "gitleaks_scan": GitleaksTool(project_root, sandbox_manager),
        "npm_audit": NpmAuditTool(project_root, sandbox_manager),
        "safety_scan": SafetyTool(project_root, sandbox_manager),
        "trufflehog_scan": TruffleHogTool(project_root, sandbox_manager),
        "osv_scan": OSVScannerTool(project_root, sandbox_manager),
    }

    # 🔥 注册 RAG 工具到 Recon Agent
    if retriever:
        recon_tools["rag_query"] = RAGQueryTool(retriever)
        logger.info("✅ RAG 工具 (rag_query) 已注册到 Recon Agent")

    # Analysis 工具
    # 🔥 导入智能扫描工具
    from app.services.agent.tools import QuickAuditTool, SmartScanTool

    analysis_tools = {
        **base_tools,
        # 🔥 智能扫描工具（推荐首先使用）
        "smart_scan": SmartScanTool(project_root),
        "quick_audit": QuickAuditTool(project_root),
        # 模式匹配工具（增强版）
        "pattern_match": PatternMatchTool(project_root),
        # 数据流分析
        "dataflow_analysis": DataFlowAnalysisTool(llm_service),
        # 外部安全工具 (传入共享的 sandbox_manager)
        "semgrep_scan": SemgrepTool(project_root, sandbox_manager),
        "bandit_scan": BanditTool(project_root, sandbox_manager),
        "gitleaks_scan": GitleaksTool(project_root, sandbox_manager),
        "npm_audit": NpmAuditTool(project_root, sandbox_manager),
        "safety_scan": SafetyTool(project_root, sandbox_manager),
        "trufflehog_scan": TruffleHogTool(project_root, sandbox_manager),
        "osv_scan": OSVScannerTool(project_root, sandbox_manager),
        # 安全知识查询
        "query_security_knowledge": SecurityKnowledgeQueryTool(),
        "get_vulnerability_knowledge": GetVulnerabilityKnowledgeTool(),
    }

    # 🔥 注册 RAG 工具到 Analysis Agent
    if retriever:
        analysis_tools["rag_query"] = RAGQueryTool(retriever)
        analysis_tools["security_search"] = SecurityCodeSearchTool(retriever)
        analysis_tools["function_context"] = FunctionContextTool(retriever)
        logger.info(
            "✅ RAG 工具 (rag_query, security_search, function_context) 已注册到 Analysis Agent"
        )
    else:
        logger.warning("⚠️ RAG 未初始化，rag_query/security_search/function_context 工具不可用")

    # Verification 工具
    # 🔥 导入沙箱工具
    from app.services.agent.tools import (
        # 漏洞验证专用工具
        CommandInjectionTestTool,
        DeserializationTestTool,
        ExtractFunctionTool,
        GoTestTool,
        JavaScriptTestTool,
        JavaTestTool,
        PathTraversalTestTool,
        # 多语言代码测试工具
        PhpTestTool,
        PythonTestTool,
        RubyTestTool,
        # 🔥 新增：通用代码执行工具 (LLM 驱动的 Fuzzing Harness)
        RunCodeTool,
        SandboxHttpTool,
        SandboxTool,
        ShellTestTool,
        SqlInjectionTestTool,
        SstiTestTool,
        UniversalCodeTestTool,
        UniversalVulnTestTool,
        VulnerabilityVerifyTool,
        XssTestTool,
    )

    verification_tools = {
        **base_tools,
        # 🔥 沙箱验证工具
        "sandbox_exec": SandboxTool(sandbox_manager),
        "sandbox_http": SandboxHttpTool(sandbox_manager),
        "verify_vulnerability": VulnerabilityVerifyTool(sandbox_manager),
        # 🔥 多语言代码测试工具
        "php_test": PhpTestTool(sandbox_manager, project_root),
        "python_test": PythonTestTool(sandbox_manager, project_root),
        "javascript_test": JavaScriptTestTool(sandbox_manager, project_root),
        "java_test": JavaTestTool(sandbox_manager, project_root),
        "go_test": GoTestTool(sandbox_manager, project_root),
        "ruby_test": RubyTestTool(sandbox_manager, project_root),
        "shell_test": ShellTestTool(sandbox_manager, project_root),
        "universal_code_test": UniversalCodeTestTool(sandbox_manager, project_root),
        # 🔥 漏洞验证专用工具
        "test_command_injection": CommandInjectionTestTool(sandbox_manager, project_root),
        "test_sql_injection": SqlInjectionTestTool(sandbox_manager, project_root),
        "test_xss": XssTestTool(sandbox_manager, project_root),
        "test_path_traversal": PathTraversalTestTool(sandbox_manager, project_root),
        "test_ssti": SstiTestTool(sandbox_manager, project_root),
        "test_deserialization": DeserializationTestTool(sandbox_manager, project_root),
        "universal_vuln_test": UniversalVulnTestTool(sandbox_manager, project_root),
        # 🔥 新增：通用代码执行工具 (LLM 驱动的 Fuzzing Harness)
        "run_code": RunCodeTool(sandbox_manager, project_root),
        "extract_function": ExtractFunctionTool(project_root),
        # 报告工具 - 🔥 v2.1: 传递 project_root 用于文件验证
        "create_vulnerability_report": CreateVulnerabilityReportTool(project_root),
    }

    # Orchestrator 工具（主要是思考工具）
    orchestrator_tools = {
        "think": ThinkTool(),
        "reflect": ReflectTool(),
    }

    return {
        "recon": recon_tools,
        "analysis": analysis_tools,
        "verification": verification_tools,
        "orchestrator": orchestrator_tools,
    }


async def _collect_project_info(
    project_root: str,
    project_name: str,
    exclude_patterns: Optional[List[str]] = None,
    target_files: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """收集项目信息

    Args:
        project_root: 项目根目录
        project_name: 项目名称
        exclude_patterns: 排除模式列表
        target_files: 目标文件列表

    🔥 重要：当指定了 target_files 时，返回的项目结构应该只包含目标文件相关的信息，
    以确保 Orchestrator 和子 Agent 看到的是一致的、过滤后的视图。
    """
    import fnmatch

    info = {
        "name": project_name,
        "root": project_root,
        "languages": [],
        "file_count": 0,
        "structure": {},
    }

    try:
        # 默认排除目录
        exclude_dirs = {
            "node_modules",
            "__pycache__",
            ".git",
            "venv",
            ".venv",
            "build",
            "dist",
            "target",
            ".idea",
            ".vscode",
        }

        # 从用户配置的排除模式中提取目录
        if exclude_patterns:
            for pattern in exclude_patterns:
                if pattern.endswith("/**"):
                    exclude_dirs.add(pattern[:-3])
                elif "/" not in pattern and "*" not in pattern:
                    exclude_dirs.add(pattern)

        # 目标文件集合
        target_files_set = set(target_files) if target_files else None

        lang_map = {
            ".py": "Python",
            ".js": "JavaScript",
            ".ts": "TypeScript",
            ".java": "Java",
            ".go": "Go",
            ".php": "PHP",
            ".rb": "Ruby",
            ".rs": "Rust",
            ".c": "C",
            ".cpp": "C++",
        }

        # 🔥 收集过滤后的文件列表
        filtered_files = []
        filtered_dirs = set()

        for root, dirs, files in os.walk(project_root):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]

            for f in files:
                relative_path = os.path.relpath(os.path.join(root, f), project_root)

                # 检查是否在目标文件列表中
                if target_files_set and relative_path not in target_files_set:
                    continue

                # 检查排除模式
                should_skip = False
                if exclude_patterns:
                    for pattern in exclude_patterns:
                        if fnmatch.fnmatch(relative_path, pattern) or fnmatch.fnmatch(f, pattern):
                            should_skip = True
                            break
                if should_skip:
                    continue

                info["file_count"] += 1
                filtered_files.append(relative_path)

                # 🔥 收集文件所在的目录
                dir_path = os.path.dirname(relative_path)
                if dir_path:
                    # 添加目录及其父目录
                    parts = dir_path.split(os.sep)
                    for i in range(len(parts)):
                        filtered_dirs.add(os.sep.join(parts[: i + 1]))

                ext = os.path.splitext(f)[1].lower()
                if ext in lang_map and lang_map[ext] not in info["languages"]:
                    info["languages"].append(lang_map[ext])

        # 🔥 根据是否有目标文件限制，生成不同的结构信息
        if target_files_set:
            # 当指定了目标文件时，只显示目标文件和相关目录
            info["structure"] = {
                "directories": sorted(list(filtered_dirs))[:20],
                "files": filtered_files[:30],
                "scope_limited": True,  # 🔥 标记这是限定范围的视图
                "scope_message": f"审计范围限定为 {len(filtered_files)} 个指定文件",
            }
        else:
            # 全项目审计时，显示顶层目录结构
            try:
                top_items = os.listdir(project_root)
                info["structure"] = {
                    "directories": [
                        d
                        for d in top_items
                        if os.path.isdir(os.path.join(project_root, d)) and d not in exclude_dirs
                    ],
                    "files": [
                        f for f in top_items if os.path.isfile(os.path.join(project_root, f))
                    ][:20],
                    "scope_limited": False,
                }
            except Exception:
                pass

    except Exception as e:
        logger.warning(f"Failed to collect project info: {e}")

    return info
