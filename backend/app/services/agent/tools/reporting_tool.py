"""
漏洞报告工具

正式记录漏洞的唯一方式，确保漏洞报告的规范性和完整性。
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from app.utils.project_paths import resolve_project_path

from .base import AgentTool, ToolResult

logger = logging.getLogger(__name__)


class VulnerabilityReportInput(BaseModel):
    """漏洞报告输入参数"""
    title: str = Field(..., description="漏洞标题")
    vulnerability_type: str = Field(
        ..., 
        description="漏洞类型: sql_injection, xss, ssrf, command_injection, path_traversal, idor, auth_bypass, etc."
    )
    severity: str = Field(
        ..., 
        description="严重程度: critical, high, medium, low, info"
    )
    description: str = Field(..., description="漏洞详细描述")
    file_path: str = Field(..., description="漏洞所在文件路径")
    line_start: Optional[int] = Field(default=None, description="起始行号")
    line_end: Optional[int] = Field(default=None, description="结束行号")
    code_snippet: Optional[str] = Field(default=None, description="相关代码片段")
    source: Optional[str] = Field(default=None, description="污点来源（用户输入点）")
    sink: Optional[str] = Field(default=None, description="危险函数（漏洞触发点）")
    poc: Optional[str] = Field(default=None, description="概念验证/利用方法")
    impact: Optional[str] = Field(default=None, description="影响分析")
    recommendation: Optional[str] = Field(default=None, description="修复建议")
    confidence: float = Field(default=0.8, description="置信度 0.0-1.0")
    cwe_id: Optional[str] = Field(default=None, description="CWE编号")
    cvss_score: Optional[float] = Field(default=None, description="CVSS评分")


class CreateVulnerabilityReportTool(AgentTool):
    """
    创建漏洞报告工具

    这是正式记录漏洞的唯一方式。只有通过这个工具创建的漏洞才会被计入最终报告。
    这个设计确保了漏洞报告的规范性和完整性。

    通常只有专门的报告Agent或验证Agent才会调用这个工具，
    确保漏洞在被正式报告之前已经经过了充分的验证。

    🔥 v2.1: 添加文件路径验证，拒绝报告不存在的文件
    """

    # 存储所有报告的漏洞
    _vulnerability_reports: List[Dict[str, Any]] = []

    def __init__(self, project_root: Optional[str] = None):
        super().__init__()
        self._reports: List[Dict[str, Any]] = []
        self.project_root = project_root  # 🔥 v2.1: 用于文件验证
    
    @property
    def name(self) -> str:
        return "create_vulnerability_report"
    
    @property
    def description(self) -> str:
        return """创建正式的漏洞报告。这是记录已确认漏洞的唯一方式。

只有在以下情况下才应该使用此工具：
1. 漏洞已经过充分分析和验证
2. 有明确的证据支持漏洞存在
3. 已经评估了漏洞的影响

必需参数:
- title: 漏洞标题
- vulnerability_type: 漏洞类型
- severity: 严重程度 (critical/high/medium/low/info)
- description: 详细描述
- file_path: 文件路径

可选参数:
- line_start/line_end: 行号范围
- code_snippet: 代码片段
- source/sink: 数据流信息
- poc: 概念验证
- impact: 影响分析
- recommendation: 修复建议
- confidence: 置信度
- cwe_id: CWE编号
- cvss_score: CVSS评分"""
    
    @property
    def args_schema(self):
        return VulnerabilityReportInput
    
    async def _execute(
        self,
        title: str,
        vulnerability_type: str,
        severity: str,
        description: str,
        file_path: str,
        line_start: Optional[int] = None,
        line_end: Optional[int] = None,
        code_snippet: Optional[str] = None,
        source: Optional[str] = None,
        sink: Optional[str] = None,
        poc: Optional[str] = None,
        impact: Optional[str] = None,
        recommendation: Optional[str] = None,
        confidence: float = 0.8,
        cwe_id: Optional[str] = None,
        cvss_score: Optional[float] = None,
        **kwargs
    ) -> ToolResult:
        """创建漏洞报告"""
        
        # 验证必需字段
        if not title or not title.strip():
            return ToolResult(success=False, error="标题不能为空")
        
        if not description or not description.strip():
            return ToolResult(success=False, error="描述不能为空")
        
        if not file_path or not file_path.strip():
            return ToolResult(success=False, error="文件路径不能为空")

        # 🔥 v2.1: 验证文件路径存在性 - 防止幻觉
        if self.project_root:
            # 清理路径（移除可能的行号，如 "app.py:36"）
            clean_path = file_path.split(":")[0].strip() if ":" in file_path else file_path.strip()
            full_path = resolve_project_path(self.project_root, clean_path)
            if not os.path.isfile(full_path):
                return ToolResult(success=False, error=f"文件 '{file_path}' 在项目中不存在")

        # 验证严重程度
        valid_severities = ["critical", "high", "medium", "low", "info"]
        severity = severity.lower()
        if severity not in valid_severities:
            return ToolResult(
                success=False, 
                error=f"无效的严重程度 '{severity}'，必须是: {', '.join(valid_severities)}"
            )
        
        # 验证漏洞类型
        valid_types = [
            "sql_injection", "nosql_injection", "xss", "ssrf", 
            "command_injection", "code_injection", "path_traversal",
            "file_inclusion", "idor", "auth_bypass", "broken_auth",
            "sensitive_data_exposure", "hardcoded_secret", "weak_crypto",
            "xxe", "deserialization", "race_condition", "business_logic",
            "csrf", "open_redirect", "mass_assignment", "other"
        ]
        vulnerability_type = vulnerability_type.lower()
        if vulnerability_type not in valid_types:
            # 允许未知类型，但记录警告
            logger.warning(f"Unknown vulnerability type: {vulnerability_type}")
        
        # 验证置信度
        confidence = max(0.0, min(1.0, confidence))
        
        # 生成报告ID
        report_id = f"vuln_{uuid.uuid4().hex[:8]}"
        
        # 构建报告
        report = {
            "id": report_id,
            "title": title.strip(),
            "vulnerability_type": vulnerability_type,
            "severity": severity,
            "description": description.strip(),
            "file_path": file_path.strip(),
            "line_start": line_start,
            "line_end": line_end,
            "code_snippet": code_snippet,
            "source": source,
            "sink": sink,
            "poc": poc,
            "impact": impact,
            "recommendation": recommendation or self._get_default_recommendation(vulnerability_type),
            "confidence": confidence,
            "cwe_id": cwe_id,
            "cvss_score": cvss_score,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "is_verified": True,  # 通过此工具创建的都视为已验证
        }
        
        # 存储报告
        self._reports.append(report)
        CreateVulnerabilityReportTool._vulnerability_reports.append(report)
        
        logger.info(f"Created vulnerability report: [{severity.upper()}] {title}")
        
        # 返回结果
        severity_emoji = {
            "critical": "🔴",
            "high": "🟠",
            "medium": "🟡",
            "low": "🟢",
            "info": "🔵",
        }.get(severity, "⚪")
        
        return ToolResult(
            success=True,
            data={
                "message": f"漏洞报告已创建: {severity_emoji} [{severity.upper()}] {title}",
                "report_id": report_id,
                "severity": severity,
            },
            metadata=report,
        )
    
    def _get_default_recommendation(self, vuln_type: str) -> str:
        """获取默认修复建议"""
        recommendations = {
            "sql_injection": "使用参数化查询或ORM，避免字符串拼接构造SQL语句",
            "xss": "对用户输入进行HTML实体编码，使用CSP策略，避免innerHTML",
            "ssrf": "验证和限制目标URL，使用白名单，禁止访问内网地址",
            "command_injection": "避免使用shell执行，使用参数列表传递命令，严格验证输入",
            "path_traversal": "规范化路径后验证，使用白名单，限制访问目录",
            "idor": "实现细粒度访问控制，验证资源所有权，使用UUID替代自增ID",
            "auth_bypass": "加强认证逻辑，实现多因素认证，定期审计认证代码",
            "hardcoded_secret": "使用环境变量或密钥管理服务存储敏感信息",
            "weak_crypto": "使用强加密算法（AES-256, SHA-256+），避免MD5/SHA1",
            "xxe": "禁用外部实体解析，使用安全的XML解析器配置",
            "deserialization": "避免反序列化不可信数据，使用JSON替代pickle/yaml",
        }
        return recommendations.get(vuln_type, "请根据具体情况修复此安全问题")
    
    def get_reports(self) -> List[Dict[str, Any]]:
        """获取所有报告"""
        return self._reports.copy()
    
    @classmethod
    def get_all_reports(cls) -> List[Dict[str, Any]]:
        """获取所有实例的报告"""
        return cls._vulnerability_reports.copy()
    
    @classmethod
    def clear_all_reports(cls) -> None:
        """清空所有报告"""
        cls._vulnerability_reports.clear()
