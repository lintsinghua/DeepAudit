"""
数据库初始化模块
检查旧版演示凭据并初始化系统模板
"""
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy import or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.config import settings
from app.core.security import get_password_hash, verify_password
from app.models.user import User
from app.models.project import Project, ProjectMember
from app.models.audit import AuditTask, AuditIssue
from app.models.analysis import InstantAnalysis

logger = logging.getLogger(__name__)

# 仅用于识别升级前生成的账户。
LEGACY_DEMO_EMAIL = "demo@example.com"
LEGACY_DEMO_PASSWORD = "demo123"


async def create_demo_data(db: AsyncSession, user: User) -> None:
    """
    为演示用户创建演示数据，用于仪表盘展示
    """
    # 检查是否已有演示数据
    result = await db.execute(select(Project).where(Project.owner_id == user.id))
    existing_projects = result.scalars().all()
    if existing_projects:
        logger.info("演示数据已存在，跳过创建")
        return
    
    logger.info("开始创建演示数据...")
    now = datetime.now(timezone.utc)
    
    # ==================== 创建演示项目 ====================
    projects_data = [
        {
            "name": "电商平台后端",
            "description": "基于 Spring Boot 的电商平台后端服务，包含用户管理、商品管理、订单处理等模块",
            "source_type": "repository",
            "repository_url": "https://github.com/example/ecommerce-backend",
            "repository_type": "github",
            "default_branch": "main",
            "programming_languages": json.dumps(["Java", "SQL"]),
        },
        {
            "name": "移动端 App",
            "description": "React Native 跨平台移动应用，支持 iOS 和 Android",
            "source_type": "repository",
            "repository_url": "https://github.com/example/mobile-app",
            "repository_type": "github",
            "default_branch": "develop",
            "programming_languages": json.dumps(["TypeScript", "JavaScript"]),
        },
        {
            "name": "数据分析平台",
            "description": "Python 数据分析和可视化平台，集成机器学习模型",
            "source_type": "zip",
            "repository_url": None,
            "repository_type": "other",
            "default_branch": "main",
            "programming_languages": json.dumps(["Python"]),
        },
        {
            "name": "微服务网关",
            "description": "基于 Go 的高性能 API 网关，支持限流、熔断、负载均衡",
            "source_type": "repository",
            "repository_url": "https://gitlab.com/example/api-gateway",
            "repository_type": "gitlab",
            "default_branch": "master",
            "programming_languages": json.dumps(["Go"]),
        },
        {
            "name": "智能客服系统",
            "description": "基于 NLP 的智能客服系统，支持多轮对话、意图识别和知识库问答",
            "source_type": "repository",
            "repository_url": "https://github.com/example/smart-customer-service",
            "repository_type": "github",
            "default_branch": "main",
            "programming_languages": json.dumps(["Python", "JavaScript"]),
        },
        {
            "name": "区块链钱包",
            "description": "多链加密货币钱包，支持 ETH、BTC 等主流币种的存储和转账",
            "source_type": "zip",
            "repository_url": None,
            "repository_type": "other",
            "default_branch": "main",
            "programming_languages": json.dumps(["Rust", "TypeScript"]),
        },
    ]
    
    projects = []
    for i, pdata in enumerate(projects_data):
        project = Project(
            owner_id=user.id,
            is_active=True,
            created_at=now - timedelta(days=30 - i * 5),
            **pdata
        )
        db.add(project)
        projects.append(project)
    
    await db.flush()
    logger.info(f"✓ 创建了 {len(projects)} 个演示项目")
    
    # ==================== 创建审计任务和问题 ====================
    tasks_data = [
        # 项目1: 电商平台后端
        {"project_idx": 0, "status": "completed", "days_ago": 25, "files": 156, "lines": 12500, "issues": 23, "score": 72.5},
        {"project_idx": 0, "status": "completed", "days_ago": 15, "files": 162, "lines": 13200, "issues": 18, "score": 78.3},
        {"project_idx": 0, "status": "completed", "days_ago": 5, "files": 168, "lines": 14100, "issues": 12, "score": 85.2},
        # 项目2: 移动端 App
        {"project_idx": 1, "status": "completed", "days_ago": 20, "files": 89, "lines": 8900, "issues": 15, "score": 68.7},
        {"project_idx": 1, "status": "completed", "days_ago": 8, "files": 95, "lines": 9500, "issues": 8, "score": 82.1},
        {"project_idx": 1, "status": "completed", "days_ago": 1, "files": 98, "lines": 9800, "issues": 6, "score": 84.5},
        # 项目3: 数据分析平台
        {"project_idx": 2, "status": "completed", "days_ago": 12, "files": 45, "lines": 5600, "issues": 9, "score": 76.4},
        {"project_idx": 2, "status": "completed", "days_ago": 2, "files": 52, "lines": 6200, "issues": 5, "score": 88.9},
        # 项目4: 微服务网关
        {"project_idx": 3, "status": "completed", "days_ago": 18, "files": 78, "lines": 9200, "issues": 11, "score": 74.8},
        {"project_idx": 3, "status": "failed", "days_ago": 3, "files": 0, "lines": 0, "issues": 0, "score": 0},
        # 项目5: 智能客服系统
        {"project_idx": 4, "status": "completed", "days_ago": 22, "files": 134, "lines": 15800, "issues": 19, "score": 71.2},
        {"project_idx": 4, "status": "completed", "days_ago": 10, "files": 142, "lines": 16500, "issues": 14, "score": 79.6},
        {"project_idx": 4, "status": "completed", "days_ago": 1, "files": 148, "lines": 17200, "issues": 7, "score": 86.8},
        # 项目6: 区块链钱包
        {"project_idx": 5, "status": "completed", "days_ago": 16, "files": 67, "lines": 8400, "issues": 16, "score": 65.3},
        {"project_idx": 5, "status": "completed", "days_ago": 6, "files": 72, "lines": 9100, "issues": 9, "score": 77.5},
    ]
    
    tasks = []
    for tdata in tasks_data:
        task_time = now - timedelta(days=tdata["days_ago"])
        task = AuditTask(
            project_id=projects[tdata["project_idx"]].id,
            created_by=user.id,
            task_type="full_scan",
            status=tdata["status"],
            branch_name="main",
            total_files=tdata["files"],
            scanned_files=tdata["files"] if tdata["status"] == "completed" else 0,
            total_lines=tdata["lines"],
            issues_count=tdata["issues"],
            quality_score=tdata["score"],
            started_at=task_time,
            completed_at=task_time + timedelta(minutes=5) if tdata["status"] == "completed" else None,
            created_at=task_time,
        )
        db.add(task)
        tasks.append(task)
    
    await db.flush()
    logger.info(f"✓ 创建了 {len(tasks)} 个审计任务")
    
    # ==================== 创建审计问题 ====================
    issue_templates = [
        {"type": "security", "severity": "critical", "title": "SQL 注入漏洞", "file": "UserService.java", "line": 45},
        {"type": "security", "severity": "high", "title": "硬编码密钥", "file": "config/secrets.py", "line": 12},
        {"type": "security", "severity": "high", "title": "XSS 跨站脚本攻击风险", "file": "components/Comment.tsx", "line": 78},
        {"type": "security", "severity": "medium", "title": "不安全的随机数生成", "file": "utils/token.go", "line": 23},
        {"type": "bug", "severity": "high", "title": "空指针异常风险", "file": "OrderController.java", "line": 156},
        {"type": "bug", "severity": "medium", "title": "数组越界访问", "file": "DataProcessor.py", "line": 89},
        {"type": "bug", "severity": "low", "title": "未处理的 Promise 拒绝", "file": "api/client.ts", "line": 34},
        {"type": "performance", "severity": "medium", "title": "N+1 查询问题", "file": "ProductRepository.java", "line": 67},
        {"type": "performance", "severity": "low", "title": "不必要的重复渲染", "file": "pages/Dashboard.tsx", "line": 112},
        {"type": "style", "severity": "low", "title": "函数过长，建议拆分", "file": "services/payment.go", "line": 45},
        {"type": "maintainability", "severity": "medium", "title": "重复代码块", "file": "handlers/auth.go", "line": 78},
        {"type": "maintainability", "severity": "low", "title": "缺少错误处理", "file": "utils/http.py", "line": 56},
    ]
    
    issue_count = 0
    for task in tasks:
        if task.status != "completed" or task.issues_count == 0:
            continue
        
        # 为每个完成的任务创建问题
        num_issues = min(task.issues_count, len(issue_templates))
        for i in range(num_issues):
            template = issue_templates[i % len(issue_templates)]
            issue = AuditIssue(
                task_id=task.id,
                file_path=f"src/{template['file']}",
                line_number=template["line"] + i * 10,
                issue_type=template["type"],
                severity=template["severity"],
                title=template["title"],
                message=template["title"],
                description=f"在文件 {template['file']} 第 {template['line'] + i * 10} 行发现 {template['title']}，这可能导致安全风险或程序异常。",
                suggestion="建议进行代码审查并修复此问题。详细修复方案请参考相关安全规范。",
                status="open" if i % 3 != 0 else "resolved",
                resolved_by=user.id if i % 3 == 0 else None,
                resolved_at=now - timedelta(days=i) if i % 3 == 0 else None,
                created_at=task.created_at,
            )
            db.add(issue)
            issue_count += 1
    
    await db.flush()
    logger.info(f"✓ 创建了 {issue_count} 个审计问题")
    
    # ==================== 创建即时分析记录 ====================
    analyses_data = [
        {"lang": "Python", "issues": 3, "score": 75.5, "days_ago": 10},
        {"lang": "JavaScript", "issues": 5, "score": 68.2, "days_ago": 8},
        {"lang": "Java", "issues": 2, "score": 82.1, "days_ago": 6},
        {"lang": "Go", "issues": 1, "score": 91.3, "days_ago": 4},
        {"lang": "TypeScript", "issues": 4, "score": 72.8, "days_ago": 2},
        {"lang": "Python", "issues": 0, "score": 95.0, "days_ago": 1},
    ]
    
    for adata in analyses_data:
        analysis = InstantAnalysis(
            user_id=user.id,
            language=adata["lang"],
            code_content="# 演示代码\nprint('Hello, World!')",
            analysis_result=json.dumps({"issues": [], "summary": "演示分析结果"}),
            issues_count=adata["issues"],
            quality_score=adata["score"],
            analysis_time=2.5,
            created_at=now - timedelta(days=adata["days_ago"]),
        )
        db.add(analysis)
    
    await db.flush()
    logger.info(f"✓ 创建了 {len(analyses_data)} 条即时分析记录")
    
    await db.commit()
    logger.info("✓ 演示数据创建完成")


async def disable_legacy_credentials(db: AsyncSession) -> None:
    # 管理员可以修改邮箱，因此也检查已改名的旧版演示管理员。
    users = await db.scalars(
        select(User).where(
            or_(User.email == LEGACY_DEMO_EMAIL, User.is_superuser.is_(True)),
        ).order_by(User.id).with_for_update()
    )
    for user in users:
        if verify_password(LEGACY_DEMO_PASSWORD, user.hashed_password):
            user.is_active = False
            user.hashed_password = get_password_hash(secrets.token_urlsafe(32))
            logger.warning("已禁用沿用旧版默认密码的账户")
    # 即使部署者还未配置新管理员，也要先使旧凭据失效。
    await db.commit()


async def ensure_admin(db: AsyncSession) -> None:
    async with db.begin():
        # PostgreSQL 默认使用 READ COMMITTED。串行化多个后端副本的首次初始化。
        await db.execute(text("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE"))
        active_admin = await db.scalar(
            select(User.id).where(User.is_active.is_(True), User.is_superuser.is_(True)).limit(1)
        )
        if active_admin is not None:
            return

        email = settings.BOOTSTRAP_ADMIN_EMAIL
        secret = settings.BOOTSTRAP_ADMIN_PASSWORD
        if not email or not secret:
            raise RuntimeError("缺少可用管理员，请配置 BOOTSTRAP_ADMIN_EMAIL 和 BOOTSTRAP_ADMIN_PASSWORD")
        password = secret.get_secret_value()
        if len(password.strip()) < 12 or len(password.encode("utf-8")) > 72:
            raise RuntimeError("管理员初始密码至少需要 12 个字符，且不能超过 72 个 UTF-8 字节")
        if await db.scalar(select(User.id).where(User.email == email)) is not None:
            raise RuntimeError("管理员初始化邮箱已被占用，请为 BOOTSTRAP_ADMIN_EMAIL 选择新邮箱")

        db.add(User(
            email=email,
            hashed_password=get_password_hash(password),
            full_name="Administrator",
            role="admin",
            is_active=True,
            is_superuser=True,
        ))


async def init_db(db: AsyncSession) -> None:
    """初始化管理员、系统模板和规则。"""
    await disable_legacy_credentials(db)
    await ensure_admin(db)

    # 初始化系统模板和规则
    try:
        from app.services.init_templates import init_templates_and_rules
        await init_templates_and_rules(db)
    except Exception as e:
        logger.warning(f"初始化模板和规则跳过: {e}")
    
    logger.info("数据库初始化完成")
