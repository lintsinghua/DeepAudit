"""
漏洞类型知识模块

包含Web3/智能合约安全漏洞的专业知识
"""

# ============ Web3 漏洞库 ============
# 智能合约和区块链安全漏洞
try:
    from .SC_algebra import SC_INTEGER_OVERFLOW_UNDERFLOW
    from .SC_auth import SC_ACCESS_CONTROL
    from .SC_business_logic import SC_REENTRANCY, SC_FLASH_LOAN, SC_LOGIC_ERROR
    from .SC_dos import SC_DOS
    from .SC_external import SC_UNCHECKED_EXTERNAL_CALL
    from .SC_program_logic import SC_COMPUTATION_ERROR
    from .SC_proxy import SC_PROXY_UPGRADEABILITY
    from .SC_time import SC_TIMESTAMP_DEPENDENCY
    
    ALL_VULNERABILITY_DOCS = [
        SC_INTEGER_OVERFLOW_UNDERFLOW,
        SC_ACCESS_CONTROL,
        SC_REENTRANCY,
        SC_FLASH_LOAN,
        SC_LOGIC_ERROR,
        SC_DOS,
        SC_UNCHECKED_EXTERNAL_CALL,
        SC_COMPUTATION_ERROR,
        SC_PROXY_UPGRADEABILITY,
        SC_TIMESTAMP_DEPENDENCY,
    ]
except ImportError:
    # 如果Web3漏洞库未完全实现，使用空列表
    ALL_VULNERABILITY_DOCS = []


__all__ = [
    "ALL_VULNERABILITY_DOCS",
]

