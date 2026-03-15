"""
漏洞类型知识模块

包含各种漏洞类型的专业知识
"""

from .injection import SQL_INJECTION, NOSQL_INJECTION, COMMAND_INJECTION, CODE_INJECTION
from .xss import XSS_REFLECTED, XSS_STORED, XSS_DOM
from .auth import AUTH_BYPASS, IDOR, BROKEN_ACCESS_CONTROL
from .crypto import WEAK_CRYPTO, HARDCODED_SECRETS
from .ssrf import SSRF
from .deserialization import INSECURE_DESERIALIZATION
from .path_traversal import PATH_TRAVERSAL
from .xxe import XXE
from .race_condition import RACE_CONDITION
from .csrf import CSRF
from .business_logic import BUSINESS_LOGIC, RATE_LIMITING
from .open_redirect import OPEN_REDIRECT

# 所有漏洞知识文档
ALL_VULNERABILITY_DOCS = [
    # 注入类
    SQL_INJECTION,
    NOSQL_INJECTION,
    COMMAND_INJECTION,
    CODE_INJECTION,
    # XSS类
    XSS_REFLECTED,
    XSS_STORED,
    XSS_DOM,
    # 认证授权类
    AUTH_BYPASS,
    IDOR,
    BROKEN_ACCESS_CONTROL,
    # 加密类
    WEAK_CRYPTO,
    HARDCODED_SECRETS,
    # 请求伪造
    CSRF,
    SSRF,
    # 其他
    INSECURE_DESERIALIZATION,
    PATH_TRAVERSAL,
    XXE,
    RACE_CONDITION,
    BUSINESS_LOGIC,
    RATE_LIMITING,
    OPEN_REDIRECT,
]

__all__ = [
    "ALL_VULNERABILITY_DOCS",
    # 注入类
    "SQL_INJECTION",
    "NOSQL_INJECTION", 
    "COMMAND_INJECTION",
    "CODE_INJECTION",
    # XSS类
    "XSS_REFLECTED",
    "XSS_STORED",
    "XSS_DOM",
    # 认证授权类
    "AUTH_BYPASS",
    "IDOR",
    "BROKEN_ACCESS_CONTROL",
    # 加密类
    "WEAK_CRYPTO",
    "HARDCODED_SECRETS",
    # 请求伪造
    "CSRF",
    "SSRF",
    # 其他
    "INSECURE_DESERIALIZATION",
    "PATH_TRAVERSAL",
    "XXE",
    "RACE_CONDITION",
    "BUSINESS_LOGIC",
    "RATE_LIMITING",
    "OPEN_REDIRECT",
]

# 所有漏洞知识文档
ALL_VULNERABILITY_DOCS = [
    # 注入类
    SQL_INJECTION,
    NOSQL_INJECTION,
    COMMAND_INJECTION,
    CODE_INJECTION,
    # XSS类
    XSS_REFLECTED,
    XSS_STORED,
    XSS_DOM,
    # 认证授权类
    AUTH_BYPASS,
    IDOR,
    BROKEN_ACCESS_CONTROL,
    # 加密类
    WEAK_CRYPTO,
    HARDCODED_SECRETS,
    # 请求伪造
    CSRF,
    SSRF,
    # 其他
    INSECURE_DESERIALIZATION,
    PATH_TRAVERSAL,
    XXE,
    RACE_CONDITION,
    BUSINESS_LOGIC,
    RATE_LIMITING,
    OPEN_REDIRECT,
]

__all__ = [
    "ALL_VULNERABILITY_DOCS",
    # 注入类
    "SQL_INJECTION",
    "NOSQL_INJECTION",
    "COMMAND_INJECTION",
    "CODE_INJECTION",
    # XSS类
    "XSS_REFLECTED",
    "XSS_STORED",
    "XSS_DOM",
    # 认证授权类
    "AUTH_BYPASS",
    "IDOR",
    "BROKEN_ACCESS_CONTROL",
    # 加密类
    "WEAK_CRYPTO",
    "HARDCODED_SECRETS",
    # 请求伪造
    "CSRF",
    "SSRF",
    # 其他
    "INSECURE_DESERIALIZATION",
    "PATH_TRAVERSAL",
    "XXE",
    "RACE_CONDITION",
    "BUSINESS_LOGIC",
    "RATE_LIMITING",
    "OPEN_REDIRECT",
]

