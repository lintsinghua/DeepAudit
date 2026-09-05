"""Agent Reports HTTP endpoints."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api import deps
from app.db.session import get_db
from app.models.agent_task import (
    AgentFinding,
    AgentTask,
)
from app.models.project import Project
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{task_id}/report")
async def generate_audit_report(
    task_id: str,
    format: str = Query("markdown", regex="^(markdown|json)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    生成审计报告

    支持 Markdown 和 JSON 格式
    """
    task = await db.get(AgentTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    project = await db.get(Project, task.project_id)
    if not project or project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此任务")

    # 获取此任务的所有发现
    findings = await db.execute(
        select(AgentFinding)
        .where(AgentFinding.task_id == task_id)
        .order_by(
            case(
                (AgentFinding.severity == "critical", 1),
                (AgentFinding.severity == "high", 2),
                (AgentFinding.severity == "medium", 3),
                (AgentFinding.severity == "low", 4),
                else_=5,
            ),
            AgentFinding.created_at.desc(),
        )
    )
    findings = findings.scalars().all()

    # 🔥 Helper function to normalize severity for comparison (case-insensitive)
    def normalize_severity(sev: str) -> str:
        return str(sev).lower().strip() if sev else ""

    # Log findings for debugging
    logger.info(f"[Report] Task {task_id}: Found {len(findings)} findings from database")
    if findings:
        for i, f in enumerate(findings[:3]):  # Log first 3
            logger.debug(
                f"[Report] Finding {i + 1}: severity='{f.severity}', title='{f.title[:50] if f.title else 'N/A'}'"
            )

    if format == "json":
        # Enhanced JSON report with full metadata
        return {
            "report_metadata": {
                "task_id": task.id,
                "project_id": task.project_id,
                "project_name": project.name,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "task_status": task.status,
                "duration_seconds": int((task.completed_at - task.started_at).total_seconds())
                if task.completed_at and task.started_at
                else None,
            },
            "summary": {
                "security_score": task.security_score,
                "total_files_analyzed": task.analyzed_files,
                "total_findings": len(findings),
                "verified_findings": sum(1 for f in findings if f.is_verified),
                "severity_distribution": {
                    "critical": sum(
                        1 for f in findings if normalize_severity(f.severity) == "critical"
                    ),
                    "high": sum(1 for f in findings if normalize_severity(f.severity) == "high"),
                    "medium": sum(
                        1 for f in findings if normalize_severity(f.severity) == "medium"
                    ),
                    "low": sum(1 for f in findings if normalize_severity(f.severity) == "low"),
                },
                "agent_metrics": {
                    "total_iterations": task.total_iterations,
                    "tool_calls": task.tool_calls_count,
                    "tokens_used": task.tokens_used,
                },
            },
            "findings": [
                {
                    "id": f.id,
                    "title": f.title,
                    "severity": f.severity,
                    "vulnerability_type": f.vulnerability_type,
                    "description": f.description,
                    "file_path": f.file_path,
                    "line_start": f.line_start,
                    "line_end": f.line_end,
                    "code_snippet": f.code_snippet,
                    "is_verified": f.is_verified,
                    "has_poc": f.has_poc,
                    "poc_code": f.poc_code,
                    "poc_description": f.poc_description,
                    "poc_steps": f.poc_steps,
                    "confidence": f.ai_confidence,
                    "suggestion": f.suggestion,
                    "fix_code": f.fix_code,
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                }
                for f in findings
            ],
        }

    # Generate Enhanced Markdown Report
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Calculate statistics
    total = len(findings)
    critical = sum(1 for f in findings if normalize_severity(f.severity) == "critical")
    high = sum(1 for f in findings if normalize_severity(f.severity) == "high")
    medium = sum(1 for f in findings if normalize_severity(f.severity) == "medium")
    low = sum(1 for f in findings if normalize_severity(f.severity) == "low")
    verified = sum(1 for f in findings if f.is_verified)
    with_poc = sum(1 for f in findings if f.has_poc)

    # Calculate duration
    duration_str = "N/A"
    if task.completed_at and task.started_at:
        duration = (task.completed_at - task.started_at).total_seconds()
        if duration >= 3600:
            duration_str = f"{duration / 3600:.1f} 小时"
        elif duration >= 60:
            duration_str = f"{duration / 60:.1f} 分钟"
        else:
            duration_str = f"{int(duration)} 秒"

    md_lines = []

    # Header
    md_lines.append("# DeepAudit 安全审计报告")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")

    # Report Info
    md_lines.append("## 报告信息")
    md_lines.append("")
    md_lines.append(f"| 属性 | 内容 |")
    md_lines.append(f"|----------|-------|")
    md_lines.append(f"| **项目名称** | {project.name} |")
    md_lines.append(f"| **任务 ID** | `{task.id[:8]}...` |")
    md_lines.append(f"| **生成时间** | {timestamp} |")
    md_lines.append(f"| **任务状态** | {task.status.upper()} |")
    md_lines.append(f"| **耗时** | {duration_str} |")
    md_lines.append("")

    # Executive Summary
    md_lines.append("## 执行摘要")
    md_lines.append("")

    score = task.security_score
    if score is not None:
        if score >= 80:
            score_assessment = "良好 - 建议进行少量优化"
            score_icon = "通过"
        elif score >= 60:
            score_assessment = "中等 - 存在若干问题需要关注"
            score_icon = "警告"
        else:
            score_assessment = "严重 - 需要立即进行修复"
            score_icon = "未通过"
        md_lines.append(f"**安全评分: {int(score)}/100** [{score_icon}]")
        md_lines.append(f"*{score_assessment}*")
    else:
        md_lines.append("**安全评分:** 未计算")
    md_lines.append("")

    # Findings Summary
    md_lines.append("### 漏洞发现概览")
    md_lines.append("")
    md_lines.append(f"| 严重程度 | 数量 | 已验证 |")
    md_lines.append(f"|----------|-------|----------|")
    if critical > 0:
        md_lines.append(
            f"| **严重 (CRITICAL)** | {critical} | {sum(1 for f in findings if normalize_severity(f.severity) == 'critical' and f.is_verified)} |"
        )
    if high > 0:
        md_lines.append(
            f"| **高危 (HIGH)** | {high} | {sum(1 for f in findings if normalize_severity(f.severity) == 'high' and f.is_verified)} |"
        )
    if medium > 0:
        md_lines.append(
            f"| **中危 (MEDIUM)** | {medium} | {sum(1 for f in findings if normalize_severity(f.severity) == 'medium' and f.is_verified)} |"
        )
    if low > 0:
        md_lines.append(
            f"| **低危 (LOW)** | {low} | {sum(1 for f in findings if normalize_severity(f.severity) == 'low' and f.is_verified)} |"
        )
    md_lines.append(f"| **总计** | {total} | {verified} |")
    md_lines.append("")

    # Audit Metrics
    md_lines.append("### 审计指标")
    md_lines.append("")
    md_lines.append(f"- **分析文件数:** {task.analyzed_files} / {task.total_files}")
    md_lines.append(f"- **Agent 迭代次数:** {task.total_iterations}")
    md_lines.append(f"- **工具调用次数:** {task.tool_calls_count}")
    md_lines.append(f"- **Token 消耗:** {task.tokens_used:,}")
    if with_poc > 0:
        md_lines.append(f"- **生成的 PoC:** {with_poc}")
    md_lines.append("")

    # Detailed Findings
    if not findings:
        md_lines.append("## 漏洞详情")
        md_lines.append("")
        md_lines.append("*本次审计未发现安全漏洞。*")
        md_lines.append("")
    else:
        # Group findings by severity
        severity_map = {
            "critical": "严重 (Critical)",
            "high": "高危 (High)",
            "medium": "中危 (Medium)",
            "low": "低危 (Low)",
        }

        for severity_level, severity_name in severity_map.items():
            severity_findings = [
                f for f in findings if normalize_severity(f.severity) == severity_level
            ]
            if not severity_findings:
                continue

            md_lines.append(f"## {severity_name} 漏洞")
            md_lines.append("")

            for i, f in enumerate(severity_findings, 1):
                verified_badge = "[已验证]" if f.is_verified else "[未验证]"
                poc_badge = " [含 PoC]" if f.has_poc else ""

                md_lines.append(f"### {severity_level.upper()}-{i}: {f.title}")
                md_lines.append("")
                md_lines.append(f"**{verified_badge}**{poc_badge} | 类型: `{f.vulnerability_type}`")
                md_lines.append("")

                if f.file_path:
                    location = f"`{f.file_path}"
                    if f.line_start:
                        location += f":{f.line_start}"
                        if f.line_end and f.line_end != f.line_start:
                            location += f"-{f.line_end}"
                    location += "`"
                    md_lines.append(f"**位置:** {location}")
                    md_lines.append("")

                if f.ai_confidence:
                    md_lines.append(f"**AI 置信度:** {int(f.ai_confidence * 100)}%")
                    md_lines.append("")

                if f.description:
                    md_lines.append("**漏洞描述:**")
                    md_lines.append("")
                    md_lines.append(f.description)
                    md_lines.append("")

                if f.code_snippet:
                    # 🔥 v2.1: 增强语言检测，避免默认 python 标记错误
                    lang = "text"  # 默认使用 text 而非 python
                    if f.file_path:
                        ext = f.file_path.split(".")[-1].lower()
                        lang_map = {
                            # Python
                            "py": "python",
                            "pyw": "python",
                            "pyi": "python",
                            # JavaScript/TypeScript
                            "js": "javascript",
                            "mjs": "javascript",
                            "cjs": "javascript",
                            "ts": "typescript",
                            "mts": "typescript",
                            "jsx": "jsx",
                            "tsx": "tsx",
                            # Web
                            "html": "html",
                            "htm": "html",
                            "css": "css",
                            "scss": "scss",
                            "sass": "sass",
                            "less": "less",
                            "vue": "vue",
                            "svelte": "svelte",
                            # Backend
                            "java": "java",
                            "kt": "kotlin",
                            "kts": "kotlin",
                            "go": "go",
                            "rs": "rust",
                            "rb": "ruby",
                            "erb": "erb",
                            "php": "php",
                            "phtml": "php",
                            # C-family
                            "c": "c",
                            "h": "c",
                            "cpp": "cpp",
                            "cc": "cpp",
                            "cxx": "cpp",
                            "hpp": "cpp",
                            "cs": "csharp",
                            # Shell/Script
                            "sh": "bash",
                            "bash": "bash",
                            "zsh": "zsh",
                            "ps1": "powershell",
                            "psm1": "powershell",
                            # Config
                            "json": "json",
                            "yaml": "yaml",
                            "yml": "yaml",
                            "toml": "toml",
                            "ini": "ini",
                            "cfg": "ini",
                            "xml": "xml",
                            "xhtml": "xml",
                            # Database
                            "sql": "sql",
                            # Other
                            "md": "markdown",
                            "markdown": "markdown",
                            "sol": "solidity",
                            "swift": "swift",
                            "r": "r",
                            "R": "r",
                            "lua": "lua",
                            "pl": "perl",
                            "pm": "perl",
                            "ex": "elixir",
                            "exs": "elixir",
                            "erl": "erlang",
                            "hs": "haskell",
                            "scala": "scala",
                            "sc": "scala",
                            "clj": "clojure",
                            "cljs": "clojure",
                            "dart": "dart",
                            "groovy": "groovy",
                            "gradle": "groovy",
                        }
                        lang = lang_map.get(ext, "text")
                    md_lines.append("**漏洞代码:**")
                    md_lines.append("")
                    md_lines.append(f"```{lang}")
                    md_lines.append(f.code_snippet.strip())
                    md_lines.append("```")
                    md_lines.append("")

                if f.suggestion:
                    md_lines.append("**修复建议:**")
                    md_lines.append("")
                    md_lines.append(f.suggestion)
                    md_lines.append("")

                if f.fix_code:
                    md_lines.append("**参考修复代码:**")
                    md_lines.append("")
                    md_lines.append(f"```{lang if f.file_path else 'text'}")
                    md_lines.append(f.fix_code.strip())
                    md_lines.append("```")
                    md_lines.append("")

                # 🔥 添加 PoC 详情
                if f.has_poc:
                    md_lines.append("**概念验证 (PoC):**")
                    md_lines.append("")

                    if f.poc_description:
                        md_lines.append(f"*{f.poc_description}*")
                        md_lines.append("")

                    if f.poc_steps:
                        md_lines.append("**复现步骤:**")
                        md_lines.append("")
                        for step_idx, step in enumerate(f.poc_steps, 1):
                            md_lines.append(f"{step_idx}. {step}")
                        md_lines.append("")

                    if f.poc_code:
                        md_lines.append("**PoC 代码:**")
                        md_lines.append("")
                        md_lines.append("```")
                        md_lines.append(f.poc_code.strip())
                        md_lines.append("```")
                        md_lines.append("")

                md_lines.append("---")
                md_lines.append("")

    # Remediation Priority
    if critical > 0 or high > 0:
        md_lines.append("## 修复优先级建议")
        md_lines.append("")
        md_lines.append("基于已发现的漏洞，我们建议按以下优先级进行修复：")
        md_lines.append("")
        priority_idx = 1
        if critical > 0:
            md_lines.append(
                f"{priority_idx}. **立即修复:** 处理 {critical} 个严重漏洞 - 可能造成严重影响"
            )
            priority_idx += 1
        if high > 0:
            md_lines.append(f"{priority_idx}. **高优先级:** 在 1 周内修复 {high} 个高危漏洞")
            priority_idx += 1
        if medium > 0:
            md_lines.append(f"{priority_idx}. **中优先级:** 在 2-4 周内修复 {medium} 个中危漏洞")
            priority_idx += 1
        if low > 0:
            md_lines.append(f"{priority_idx}. **低优先级:** 在日常维护中处理 {low} 个低危漏洞")
            priority_idx += 1
        md_lines.append("")

    # Footer
    md_lines.append("---")
    md_lines.append("")
    md_lines.append("*本报告由 DeepAudit - AI 驱动的安全分析系统生成*")
    md_lines.append("")
    content = "\n".join(md_lines)

    filename = f"audit_report_{task.id[:8]}_{datetime.now().strftime('%Y%m%d')}.md"

    from fastapi.responses import Response

    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
