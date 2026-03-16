"""
混合 Agent 架构
包含 Orchestrator、Recon、Analysis 和 Verification Agent

协作机制：
- Agent 之间通过 TaskHandoff 传递结构化上下文
- 每个 Agent 完成后生成 handoff 给下一个 Agent
"""

from .base import BaseAgent, AgentConfig, AgentResult, TaskHandoff
from .smart_contract_orchestrator import OrchestratorAgent
from .smart_contract_recon import ReconAgent
from .smart_contract_analysis import AnalysisAgent
from .smart_contract_verification import VerificationAgent

__all__ = [
    "BaseAgent",
    "AgentConfig",
    "AgentResult",
    "TaskHandoff",
    "OrchestratorAgent",
    "ReconAgent",
    "AnalysisAgent",
    "VerificationAgent",
]

