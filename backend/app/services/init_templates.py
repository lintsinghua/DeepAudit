"""
初始化系统预置的提示词模板和审计规则
"""

import json
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.prompt_template import PromptTemplate
from app.models.audit_rule import AuditRuleSet, AuditRule

logger = logging.getLogger(__name__)


# ==================== 系统提示词模板 ====================

SYSTEM_PROMPT_TEMPLATES = [
    {
        "name": "默认代码审计",
        "description": "全面的代码审计提示词，涵盖安全、性能、代码质量等多个维度",
        "template_type": "system",
        "is_default": True,
        "sort_order": 0,
        "variables": {"language": "编程语言", "code": "代码内容"},
        "content_zh": """你是一个专业的代码审计助手。请从以下维度全面分析代码：
- 安全漏洞（SQL注入、XSS、命令注入、路径遍历、SSRF、XXE、反序列化、硬编码密钥等）
- 潜在的 Bug 和逻辑错误
- 性能问题和优化建议
- 编码规范和代码风格
- 可维护性和可读性
- 最佳实践和设计模式

请尽可能多地找出代码中的所有问题，不要遗漏任何安全漏洞或潜在风险！""",
        "content_en": """You are a professional code auditing assistant. Please comprehensively analyze the code from the following dimensions:
- Security vulnerabilities (SQL injection, XSS, command injection, path traversal, SSRF, XXE, deserialization, hardcoded secrets, etc.)
- Potential bugs and logical errors
- Performance issues and optimization suggestions
- Coding standards and code style
- Maintainability and readability
- Best practices and design patterns

Find as many issues as possible! Do NOT miss any security vulnerabilities or potential risks!"""
    },
    {
        "name": "安全专项审计",
        "description": "专注于安全漏洞检测的提示词模板",
        "template_type": "system",
        "is_default": False,
        "sort_order": 1,
        "variables": {"language": "编程语言", "code": "代码内容"},
        "content_zh": """你是一个专业的安全审计专家。请专注于检测以下安全问题：

【注入类漏洞】
- SQL注入（包括盲注、时间盲注、联合查询注入）
- 命令注入（OS命令执行）
- LDAP注入
- XPath注入
- NoSQL注入

【跨站脚本（XSS）】
- 反射型XSS
- 存储型XSS
- DOM型XSS

【认证与授权】
- 硬编码凭证
- 弱密码策略
- 会话管理问题
- 权限绕过

【敏感数据】
- 敏感信息泄露
- 不安全的加密
- 明文传输敏感数据

【其他安全问题】
- SSRF（服务端请求伪造）
- XXE（XML外部实体注入）
- 反序列化漏洞
- 路径遍历
- 文件上传漏洞
- CSRF（跨站请求伪造）

请详细说明每个漏洞的风险等级、利用方式和修复建议。""",
        "content_en": """You are a professional security audit expert. Please focus on detecting the following security issues:

【Injection Vulnerabilities】
- SQL Injection (including blind, time-based, union-based)
- Command Injection (OS command execution)
- LDAP Injection
- XPath Injection
- NoSQL Injection

【Cross-Site Scripting (XSS)】
- Reflected XSS
- Stored XSS
- DOM-based XSS

【Authentication & Authorization】
- Hardcoded credentials
- Weak password policies
- Session management issues
- Authorization bypass

【Sensitive Data】
- Sensitive information disclosure
- Insecure cryptography
- Plaintext transmission of sensitive data

【Other Security Issues】
- SSRF (Server-Side Request Forgery)
- XXE (XML External Entity Injection)
- Deserialization vulnerabilities
- Path traversal
- File upload vulnerabilities
- CSRF (Cross-Site Request Forgery)

Please provide detailed risk level, exploitation method, and remediation suggestions for each vulnerability."""
    },
    {
        "name": "性能优化审计",
        "description": "专注于性能问题检测的提示词模板",
        "template_type": "system",
        "is_default": False,
        "sort_order": 2,
        "variables": {"language": "编程语言", "code": "代码内容"},
        "content_zh": """你是一个专业的性能优化专家。请专注于检测以下性能问题：

【数据库性能】
- N+1查询问题
- 缺少索引
- 不必要的全表扫描
- 大量数据一次性加载
- 未使用连接池

【内存问题】
- 内存泄漏
- 大对象未及时释放
- 缓存使用不当
- 循环中创建大量对象

【算法效率】
- 时间复杂度过高
- 不必要的重复计算
- 可优化的循环
- 递归深度过大

【并发问题】
- 线程安全问题
- 死锁风险
- 资源竞争
- 不必要的同步

【I/O性能】
- 同步阻塞I/O
- 未使用缓冲
- 频繁的小文件操作
- 网络请求未优化

请提供具体的优化建议和预期的性能提升。""",
        "content_en": """You are a professional performance optimization expert. Please focus on detecting the following performance issues:

【Database Performance】
- N+1 query problems
- Missing indexes
- Unnecessary full table scans
- Loading large amounts of data at once
- Not using connection pools

【Memory Issues】
- Memory leaks
- Large objects not released timely
- Improper cache usage
- Creating many objects in loops

【Algorithm Efficiency】
- High time complexity
- Unnecessary repeated calculations
- Optimizable loops
- Excessive recursion depth

【Concurrency Issues】
- Thread safety problems
- Deadlock risks
- Resource contention
- Unnecessary synchronization

【I/O Performance】
- Synchronous blocking I/O
- Not using buffers
- Frequent small file operations
- Unoptimized network requests

Please provide specific optimization suggestions and expected performance improvements."""
    },
    {
        "name": "代码质量审计",
        "description": "专注于代码质量和可维护性的提示词模板",
        "template_type": "system",
        "is_default": False,
        "sort_order": 3,
        "variables": {"language": "编程语言", "code": "代码内容"},
        "content_zh": """你是一个专业的代码质量审计专家。请专注于检测以下代码质量问题：

【代码规范】
- 命名不规范（变量、函数、类）
- 代码格式不一致
- 注释缺失或过时
- 魔法数字/字符串

【代码结构】
- 函数过长（超过50行）
- 类职责不单一
- 嵌套层级过深
- 重复代码

【可维护性】
- 高耦合低内聚
- 缺少错误处理
- 硬编码配置
- 缺少日志记录

【设计模式】
- 违反SOLID原则
- 可使用设计模式优化的场景
- 过度设计

【测试相关】
- 难以测试的代码
- 缺少边界条件处理
- 依赖注入问题

请提供具体的重构建议和代码示例。""",
        "content_en": """You are a professional code quality audit expert. Please focus on detecting the following code quality issues:

【Code Standards】
- Non-standard naming (variables, functions, classes)
- Inconsistent code formatting
- Missing or outdated comments
- Magic numbers/strings

【Code Structure】
- Functions too long (over 50 lines)
- Classes with multiple responsibilities
- Deep nesting levels
- Duplicate code

【Maintainability】
- High coupling, low cohesion
- Missing error handling
- Hardcoded configurations
- Missing logging

【Design Patterns】
- SOLID principle violations
- Scenarios that could benefit from design patterns
- Over-engineering

【Testing Related】
- Hard-to-test code
- Missing boundary condition handling
- Dependency injection issues

Please provide specific refactoring suggestions and code examples."""
    },
]


# ==================== 系统审计规则集 ====================

SYSTEM_RULE_SETS = [
    {
        "name": "OWASP Top 10",
        "description": "基于 OWASP Top 10 2021 的安全审计规则集",
        "language": "all",
        "rule_type": "security",
        "is_default": True,
        "sort_order": 0,
        "severity_weights": {"critical": 10, "high": 5, "medium": 2, "low": 1},
        "rules": [
            {
                "rule_code": "A01",
                "name": "访问控制失效",
                "description": "检测权限绕过、越权访问、IDOR等访问控制问题",
                "category": "security",
                "severity": "critical",
                "custom_prompt": "检查是否存在访问控制失效问题：权限检查缺失、越权访问、IDOR（不安全的直接对象引用）、CORS配置错误",
                "fix_suggestion": "实施最小权限原则，在服务端进行权限验证，使用基于角色的访问控制(RBAC)",
                "reference_url": "https://owasp.org/Top10/A01_2021-Broken_Access_Control/",
            },
            {
                "rule_code": "A02",
                "name": "加密机制失效",
                "description": "检测弱加密、明文传输、密钥管理不当等问题",
                "category": "security",
                "severity": "critical",
                "custom_prompt": "检查是否存在加密问题：使用弱加密算法(MD5/SHA1/DES)、明文存储密码、硬编码密钥、不安全的随机数生成",
                "fix_suggestion": "使用强加密算法(AES-256/RSA-2048)，使用安全的密码哈希(bcrypt/Argon2)，妥善管理密钥",
                "reference_url": "https://owasp.org/Top10/A02_2021-Cryptographic_Failures/",
            },
            {
                "rule_code": "A03",
                "name": "注入攻击",
                "description": "检测SQL注入、命令注入、LDAP注入等注入漏洞",
                "category": "security",
                "severity": "critical",
                "custom_prompt": "检查是否存在注入漏洞：SQL注入、命令注入、LDAP注入、XPath注入、NoSQL注入、表达式语言注入",
                "fix_suggestion": "使用参数化查询，输入验证和转义，使用ORM框架，最小权限原则",
                "reference_url": "https://owasp.org/Top10/A03_2021-Injection/",
            },
            {
                "rule_code": "A04",
                "name": "不安全设计",
                "description": "检测业务逻辑漏洞、缺少安全控制等设计问题",
                "category": "security",
                "severity": "high",
                "custom_prompt": "检查是否存在不安全的设计：缺少速率限制、业务逻辑漏洞、缺少输入验证、信任边界不清",
                "fix_suggestion": "采用安全设计原则，威胁建模，实施深度防御",
                "reference_url": "https://owasp.org/Top10/A04_2021-Insecure_Design/",
            },
            {
                "rule_code": "A05",
                "name": "安全配置错误",
                "description": "检测默认配置、不必要的功能、错误的权限设置",
                "category": "security",
                "severity": "high",
                "custom_prompt": "检查是否存在安全配置错误：默认凭证、不必要的功能启用、详细错误信息泄露、缺少安全头",
                "fix_suggestion": "最小化安装，禁用不必要功能，定期审查配置，自动化配置检查",
                "reference_url": "https://owasp.org/Top10/A05_2021-Security_Misconfiguration/",
            },
            {
                "rule_code": "A06",
                "name": "易受攻击和过时的组件",
                "description": "检测使用已知漏洞的依赖库",
                "category": "security",
                "severity": "high",
                "custom_prompt": "检查是否使用了已知漏洞的组件：过时的依赖库、未修补的漏洞、不安全的第三方组件",
                "fix_suggestion": "定期更新依赖，使用依赖扫描工具，订阅安全公告",
                "reference_url": "https://owasp.org/Top10/A06_2021-Vulnerable_and_Outdated_Components/",
            },
            {
                "rule_code": "A07",
                "name": "身份认证失效",
                "description": "检测弱密码、会话管理问题、凭证泄露",
                "category": "security",
                "severity": "critical",
                "custom_prompt": "检查是否存在身份认证问题：弱密码策略、会话固定、凭证明文存储、缺少多因素认证",
                "fix_suggestion": "实施强密码策略，使用MFA，安全的会话管理，防止暴力破解",
                "reference_url": "https://owasp.org/Top10/A07_2021-Identification_and_Authentication_Failures/",
            },
            {
                "rule_code": "A08",
                "name": "软件和数据完整性失效",
                "description": "检测不安全的反序列化、CI/CD安全问题",
                "category": "security",
                "severity": "critical",
                "custom_prompt": "检查是否存在完整性问题：不安全的反序列化、未验证的更新、CI/CD管道安全",
                "fix_suggestion": "验证数据完整性，使用数字签名，安全的反序列化",
                "reference_url": "https://owasp.org/Top10/A08_2021-Software_and_Data_Integrity_Failures/",
            },
            {
                "rule_code": "A09",
                "name": "安全日志和监控失效",
                "description": "检测日志记录不足、监控缺失",
                "category": "security",
                "severity": "medium",
                "custom_prompt": "检查是否存在日志监控问题：缺少安全日志、敏感信息记录到日志、缺少告警机制",
                "fix_suggestion": "记录安全相关事件，实施监控和告警，定期审查日志",
                "reference_url": "https://owasp.org/Top10/A09_2021-Security_Logging_and_Monitoring_Failures/",
            },
            {
                "rule_code": "A10",
                "name": "服务端请求伪造(SSRF)",
                "description": "检测SSRF漏洞",
                "category": "security",
                "severity": "high",
                "custom_prompt": "检查是否存在SSRF漏洞：未验证的URL输入、内网资源访问、云元数据访问",
                "fix_suggestion": "验证和过滤URL，使用白名单，禁用不必要的协议",
                "reference_url": "https://owasp.org/Top10/A10_2021-Server-Side_Request_Forgery_%28SSRF%29/",
            },
        ]
    },
    {
        "name": "代码质量规则",
        "description": "通用代码质量检查规则集",
        "language": "all",
        "rule_type": "quality",
        "is_default": False,
        "sort_order": 1,
        "severity_weights": {"critical": 10, "high": 5, "medium": 2, "low": 1},
        "rules": [
            {
                "rule_code": "CQ001",
                "name": "函数过长",
                "description": "函数超过50行，建议拆分",
                "category": "maintainability",
                "severity": "medium",
                "custom_prompt": "检查函数是否过长（超过50行），是否应该拆分为更小的函数",
                "fix_suggestion": "将大函数拆分为多个小函数，每个函数只做一件事",
            },
            {
                "rule_code": "CQ002",
                "name": "重复代码",
                "description": "检测重复的代码块",
                "category": "maintainability",
                "severity": "medium",
                "custom_prompt": "检查是否存在重复的代码块，可以提取为公共函数或类",
                "fix_suggestion": "提取重复代码为公共函数、类或模块",
            },
            {
                "rule_code": "CQ003",
                "name": "嵌套过深",
                "description": "代码嵌套层级超过4层",
                "category": "maintainability",
                "severity": "low",
                "custom_prompt": "检查代码嵌套是否过深（超过4层），影响可读性",
                "fix_suggestion": "使用早返回、提取函数等方式减少嵌套",
            },
            {
                "rule_code": "CQ004",
                "name": "魔法数字",
                "description": "代码中使用未命名的常量",
                "category": "style",
                "severity": "low",
                "custom_prompt": "检查是否存在魔法数字或魔法字符串，应该定义为常量",
                "fix_suggestion": "将魔法数字定义为有意义的常量",
            },
            {
                "rule_code": "CQ005",
                "name": "缺少错误处理",
                "description": "缺少异常捕获或错误处理",
                "category": "bug",
                "severity": "high",
                "custom_prompt": "检查是否缺少必要的错误处理，可能导致程序崩溃",
                "fix_suggestion": "添加适当的try-catch或错误检查",
            },
            {
                "rule_code": "CQ006",
                "name": "未使用的变量",
                "description": "声明但未使用的变量",
                "category": "style",
                "severity": "low",
                "custom_prompt": "检查是否存在声明但未使用的变量",
                "fix_suggestion": "删除未使用的变量或使用它们",
            },
            {
                "rule_code": "CQ007",
                "name": "命名不规范",
                "description": "变量、函数、类命名不符合规范",
                "category": "style",
                "severity": "low",
                "custom_prompt": "检查命名是否符合语言规范和最佳实践",
                "fix_suggestion": "使用有意义的、符合规范的命名",
            },
            {
                "rule_code": "CQ008",
                "name": "注释缺失",
                "description": "复杂逻辑缺少必要注释",
                "category": "maintainability",
                "severity": "low",
                "custom_prompt": "检查复杂逻辑是否缺少必要的注释说明",
                "fix_suggestion": "为复杂逻辑添加清晰的注释",
            },
        ]
    },
    {
        "name": "性能优化规则",
        "description": "性能问题检测规则集",
        "language": "all",
        "rule_type": "performance",
        "is_default": False,
        "sort_order": 2,
        "severity_weights": {"critical": 10, "high": 5, "medium": 2, "low": 1},
        "rules": [
            {
                "rule_code": "PERF001",
                "name": "N+1查询",
                "description": "检测数据库N+1查询问题",
                "category": "performance",
                "severity": "high",
                "custom_prompt": "检查是否存在N+1查询问题，在循环中执行数据库查询",
                "fix_suggestion": "使用JOIN查询或批量查询替代循环查询",
            },
            {
                "rule_code": "PERF002",
                "name": "内存泄漏",
                "description": "检测潜在的内存泄漏",
                "category": "performance",
                "severity": "critical",
                "custom_prompt": "检查是否存在内存泄漏：未关闭的资源、循环引用、大对象未释放",
                "fix_suggestion": "使用try-finally或with语句确保资源释放",
            },
            {
                "rule_code": "PERF003",
                "name": "低效算法",
                "description": "检测时间复杂度过高的算法",
                "category": "performance",
                "severity": "medium",
                "custom_prompt": "检查是否存在低效算法，如O(n²)可优化为O(n)或O(nlogn)",
                "fix_suggestion": "使用更高效的算法或数据结构",
            },
            {
                "rule_code": "PERF004",
                "name": "不必要的对象创建",
                "description": "在循环中创建不必要的对象",
                "category": "performance",
                "severity": "medium",
                "custom_prompt": "检查是否在循环中创建不必要的对象，应该移到循环外",
                "fix_suggestion": "将对象创建移到循环外部，或使用对象池",
            },
            {
                "rule_code": "PERF005",
                "name": "同步阻塞",
                "description": "检测同步阻塞操作",
                "category": "performance",
                "severity": "medium",
                "custom_prompt": "检查是否存在同步阻塞操作，应该使用异步方式",
                "fix_suggestion": "使用异步I/O或多线程处理",
            }
        ]
    },
    {
        "name": "PHP 安全规则",
        "description": "PHP 专属安全审计规则集：覆盖代码执行、反序列化、文件包含、SQL注入、XSS、命令注入、弱类型比较等 PHP 高危漏洞",
        "language": "php",
        "rule_type": "security",
        "is_default": False,
        "is_system": True,
        "sort_order": 3,
        "severity_weights": {"critical": 10, "high": 5, "medium": 2, "low": 1},
        "rules": [
            {
                "rule_code": "PHP001",
                "name": "危险代码执行函数",
                "description": "检测 eval()、assert()、create_function()、preg_replace() 的 /e 修饰符等可导致任意代码执行的危险函数",
                "category": "security",
                "severity": "critical",
                "custom_prompt": "检查是否存在 eval()、assert()、create_function()、preg_replace() 使用 /e 修饰符等可导致任意代码执行的危险函数，尤其当参数来自用户输入($_GET/$_POST/$_REQUEST/$_COOKIE)时",
                "fix_suggestion": "避免使用 eval() 等危险函数；如需动态执行请对入参做白名单校验；使用 password_verify() 等安全替代方案",
                "reference_url": "https://owasp.org/www-community/vulnerabilities/PHP_Code_Injection",
            },
            {
                "rule_code": "PHP002",
                "name": "不安全的反序列化",
                "description": "检测 unserialize() 反序列化用户输入，可能导致对象注入甚至远程代码执行",
                "category": "security",
                "severity": "critical",
                "custom_prompt": "检查是否存在 unserialize() 反序列化来自用户输入的数据；PHP 反序列化不可信数据可能触发 Magic Methods(__wakeup/__destruct)导致对象注入，甚至结合 gadget 链形成远程代码执行",
                "fix_suggestion": "不要反序列化不可信数据；改用 json_encode/json_decode；若必须使用序列化，用 HMAC 签名校验数据完整性并做类名白名单",
                "reference_url": "https://owasp.org/www-community/vulnerabilities/PHP_Object_Injection",
            },
            {
                "rule_code": "PHP003",
                "name": "动态文件包含",
                "description": "检测 include/require 使用用户可控变量作为文件路径，可能导致本地/远程文件包含(LFI/RFI)",
                "category": "security",
                "severity": "high",
                "custom_prompt": "检查 include/require/include_once/require_once 是否使用了来自用户输入($_GET/$_POST/$_REQUEST)的可控变量作为文件路径，可能导致任意文件包含",
                "fix_suggestion": "使用白名单映射，禁止直接将用户输入拼接到包含路径；使用 realpath() 校验解析后的真实路径",
                "reference_url": "https://owasp.org/www-community/attacks/Path_Traversal",
            },
            {
                "rule_code": "PHP004",
                "name": "SQL注入",
                "description": "检测字符串拼接构造 SQL 或直接使用 $_GET 拼 SQL 查询",
                "category": "security",
                "severity": "critical",
                "custom_prompt": "检查是否使用字符串拼接或直接插入 $_GET/$_POST 变量构造 SQL 查询(如 mysql_query/mysqli_query/PDO query/exec/prepare)，应使用预处理语句参数化查询",
                "fix_suggestion": "使用 PDO 预处理语句或 mysqli prepared statements，通过占位符绑定参数；禁止将用户输入拼接进 SQL",
                "reference_url": "https://owasp.org/Top10/A03_2021-Injection/",
            },
            {
                "rule_code": "PHP005",
                "name": "XSS反射输出",
                "description": "检测 echo/print 直接输出用户输入到响应体而未转义",
                "category": "security",
                "severity": "high",
                "custom_prompt": "检查 echo/print/<?= ?> 是否直接输出 $_GET/$_POST/$_REQUEST 等用户输入，未经过 htmlspecialchars() 转义，可能导致反射型XSS",
                "fix_suggestion": "对所有输出使用 htmlspecialchars($var, ENT_QUOTES, 'UTF-8') 转义；优先使用支持自动转义的模板引擎",
                "reference_url": "https://owasp.org/Top10/A03_2021-Injection/",
            },
            {
                "rule_code": "PHP006",
                "name": "命令注入",
                "description": "检测 exec/system/shell_exec/passthru/proc_open/反引号执行用户可控命令",
                "category": "security",
                "severity": "critical",
                "custom_prompt": "检查 exec/system/shell_exec/passthru/proc_open/popen 或反引号 是否执行了通过字符串拼接用户输入构造的命令",
                "fix_suggestion": "尽量避免调用系统命令；必须调用时使用 escapeshellarg()/escapeshellcmd() 转义，或采用参数数组方式传参；使用命令白名单校验",
                "reference_url": "https://owasp.org/www-community/attacks/Command_Injection",
            },
            {
                "rule_code": "PHP007",
                "name": "硬编码密钥与弱加密",
                "description": "检测硬编码密钥、弱哈希(md5/sha1)、不安全随机数",
                "category": "security",
                "severity": "medium",
                "custom_prompt": "检查是否存在硬编码密钥/密码/Token，或使用 md5()/sha1() 处理密码，或使用 rand()/mt_rand() 生成安全相关随机值",
                "fix_suggestion": "使用 password_hash()/password_verify() 处理密码；密钥存入环境变量或密钥管理服务；使用 random_int()/random_bytes()",
                "reference_url": "https://owasp.org/Top10/A02_2021-Cryptographic_Failures/",
            },
            {
                "rule_code": "PHP008",
                "name": "弱类型比较",
                "description": "检测 == 松脆比较及未开启严格模式的类型函数，可能导致 type juggling 漏洞",
                "category": "security",
                "severity": "medium",
                "custom_prompt": "检查是否使用 == 进行敏感比较(如密码/哈希校验)，PHP == 弱类型比较可能被 '0'=='abc'、'1e3' 等 type juggling 绕过；检查 in_array()/array_search() 是否未传入第三个参数 true 开启严格模式",
                "fix_suggestion": "敏感比较一律使用 === 严格比较；in_array()/array_search() 传入第三个参数 true；字符串哈希比较使用 hash_equals()",
            },
            {
                "rule_code": "PHP009",
                "name": "不安全的随机数与令牌",
                "description": "检测使用 rand()/mt_rand() 生成 CSRF token、重置 token 等安全敏感随机值",
                "category": "security",
                "severity": "medium",
                "custom_prompt": "检查是否使用 rand() 或 mt_rand() 生成 CSRF token、密码重置 token、一次性随机码等安全敏感随机值，它们不够安全可被预测",
                "fix_suggestion": "使用 random_int() 或 random_bytes()，或 bin2hex(random_bytes($len)) 生成安全随机值",
            },
            {
                "rule_code": "PHP010",
                "name": "危险文件函数",
                "description": "检测 file_get_contents/fopen/readfile/unlink 等函数处理用户可控路径",
                "category": "security",
                "severity": "high",
                "custom_prompt": "检查 file_get_contents()/fopen()/readfile()/unlink()/copy() 等文件函数是否使用来自用户输入的可控变量作为路径，可能导致路径遍历或任意文件读取/删除",
                "fix_suggestion": "使用 basename() 提取文件名并做白名单校验；拒绝包含 .. 等特殊字符的路径",
                "reference_url": "https://owasp.org/www-community/attacks/Path_Traversal",
            },
        ]
    },
]


async def init_system_templates(db: AsyncSession) -> None:
    """初始化系统提示词模板"""
    for template_data in SYSTEM_PROMPT_TEMPLATES:
        # 检查是否已存在
        result = await db.execute(
            select(PromptTemplate).where(
                PromptTemplate.name == template_data["name"],
                PromptTemplate.is_system == True
            )
        )
        existing = result.scalar_one_or_none()
        
        if not existing:
            template = PromptTemplate(
                name=template_data["name"],
                description=template_data["description"],
                template_type=template_data["template_type"],
                content_zh=template_data["content_zh"],
                content_en=template_data["content_en"],
                variables=json.dumps(template_data.get("variables", {})),
                is_default=template_data.get("is_default", False),
                is_system=True,
                is_active=True,
                sort_order=template_data.get("sort_order", 0),
            )
            db.add(template)
            logger.info(f"✓ 创建系统提示词模板: {template_data['name']}")
    
    await db.flush()


async def init_system_rule_sets(db: AsyncSession) -> None:
    """初始化系统审计规则集"""
    for rule_set_data in SYSTEM_RULE_SETS:
        # 检查是否已存在
        result = await db.execute(
            select(AuditRuleSet).where(
                AuditRuleSet.name == rule_set_data["name"],
                AuditRuleSet.is_system == True
            )
        )
        existing = result.scalar_one_or_none()
        
        if not existing:
            rule_set = AuditRuleSet(
                name=rule_set_data["name"],
                description=rule_set_data["description"],
                language=rule_set_data["language"],
                rule_type=rule_set_data["rule_type"],
                severity_weights=json.dumps(rule_set_data.get("severity_weights", {})),
                is_default=rule_set_data.get("is_default", False),
                is_system=True,
                is_active=True,
                sort_order=rule_set_data.get("sort_order", 0),
            )
            db.add(rule_set)
            await db.flush()
            
            # 创建规则
            for rule_data in rule_set_data.get("rules", []):
                rule = AuditRule(
                    rule_set_id=rule_set.id,
                    rule_code=rule_data["rule_code"],
                    name=rule_data["name"],
                    description=rule_data.get("description"),
                    category=rule_data["category"],
                    severity=rule_data.get("severity", "medium"),
                    custom_prompt=rule_data.get("custom_prompt"),
                    fix_suggestion=rule_data.get("fix_suggestion"),
                    reference_url=rule_data.get("reference_url"),
                    enabled=True,
                    sort_order=rule_data.get("sort_order", 0),
                )
                db.add(rule)
            
            logger.info(f"✓ 创建系统规则集: {rule_set_data['name']} ({len(rule_set_data.get('rules', []))} 条规则)")
    
    await db.flush()


async def init_templates_and_rules(db: AsyncSession) -> None:
    """初始化所有系统模板和规则"""
    logger.info("开始初始化系统模板和规则...")
    
    try:
        await init_system_templates(db)
        await init_system_rule_sets(db)
        await db.commit()
        logger.info("✓ 系统模板和规则初始化完成")
    except Exception as e:
        logger.warning(f"初始化模板和规则时出错（可能表不存在）: {e}")
        await db.rollback()
