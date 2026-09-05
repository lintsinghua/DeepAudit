"""Results services for agent audits."""

import json
import logging
import os
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4, uuid5

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.agent_task import (
    AgentFinding,
    FindingStatus,
    VulnerabilitySeverity,
)
from app.models.user_config import UserConfig

logger = logging.getLogger(__name__)


async def _get_user_config(db: AsyncSession, user_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """获取用户配置"""
    if not user_id:
        return None

    try:
        from app.api.v1.endpoints.config import (
            SENSITIVE_LLM_FIELDS,
            SENSITIVE_OTHER_FIELDS,
            decrypt_config,
        )

        result = await db.execute(select(UserConfig).where(UserConfig.user_id == user_id))
        config = result.scalar_one_or_none()

        if config and config.llm_config:
            user_llm_config = json.loads(config.llm_config) if config.llm_config else {}
            user_other_config = json.loads(config.other_config) if config.other_config else {}

            user_llm_config = decrypt_config(user_llm_config, SENSITIVE_LLM_FIELDS)
            user_other_config = decrypt_config(user_other_config, SENSITIVE_OTHER_FIELDS)

            return {
                "llmConfig": user_llm_config,
                "otherConfig": user_other_config,
            }
    except Exception as e:
        logger.warning(f"Failed to get user config: {e}")

    return None


async def _save_findings(
    db: AsyncSession,
    task_id: str,
    findings: List[Dict],
    project_root: Optional[str] = None,
) -> int:
    """
    保存发现到数据库

    🔥 增强版：支持多种 Agent 输出格式，健壮的字段映射
    🔥 v2.1: 添加文件路径验证，过滤幻觉发现

    Args:
        db: 数据库会话
        task_id: 任务ID
        findings: 发现列表
        project_root: 项目根目录（用于验证文件路径）

    Returns:
        int: 实际保存的发现数量
    """
    from app.models.agent_task import VulnerabilityType

    logger.info(f"[SaveFindings] Starting to save {len(findings)} findings for task {task_id}")

    if not findings:
        logger.warning(f"[SaveFindings] No findings to save for task {task_id}")
        return 0

    # 🔥 Case-insensitive mapping preparation
    severity_map = {
        "critical": VulnerabilitySeverity.CRITICAL,
        "high": VulnerabilitySeverity.HIGH,
        "medium": VulnerabilitySeverity.MEDIUM,
        "low": VulnerabilitySeverity.LOW,
        "info": VulnerabilitySeverity.INFO,
    }

    type_map = {
        "sql_injection": VulnerabilityType.SQL_INJECTION,
        "nosql_injection": VulnerabilityType.NOSQL_INJECTION,
        "xss": VulnerabilityType.XSS,
        "command_injection": VulnerabilityType.COMMAND_INJECTION,
        "code_injection": VulnerabilityType.CODE_INJECTION,
        "path_traversal": VulnerabilityType.PATH_TRAVERSAL,
        "ssrf": VulnerabilityType.SSRF,
        "xxe": VulnerabilityType.XXE,
        "auth_bypass": VulnerabilityType.AUTH_BYPASS,
        "idor": VulnerabilityType.IDOR,
        "sensitive_data_exposure": VulnerabilityType.SENSITIVE_DATA_EXPOSURE,
        "hardcoded_secret": VulnerabilityType.HARDCODED_SECRET,
        "deserialization": VulnerabilityType.DESERIALIZATION,
        "weak_crypto": VulnerabilityType.WEAK_CRYPTO,
        "file_inclusion": VulnerabilityType.FILE_INCLUSION,
        "race_condition": VulnerabilityType.RACE_CONDITION,
        "business_logic": VulnerabilityType.BUSINESS_LOGIC,
        "memory_corruption": VulnerabilityType.MEMORY_CORRUPTION,
    }

    existing_ids = set(
        await db.scalars(select(AgentFinding.id).where(AgentFinding.task_id == task_id))
    )
    seen_ids = set()
    saved_count = 0
    logger.info(f"Saving {len(findings)} findings for task {task_id}")

    for finding in findings:
        if not isinstance(finding, dict):
            logger.debug(f"[SaveFindings] Skipping non-dict finding: {type(finding)}")
            continue

        try:
            # 🔥 Handle severity (case-insensitive, support multiple field names)
            raw_severity = (
                str(finding.get("severity") or finding.get("risk") or "medium").lower().strip()
            )
            severity_enum = severity_map.get(raw_severity, VulnerabilitySeverity.MEDIUM)

            # 🔥 Handle vulnerability type (case-insensitive & snake_case normalization)
            # Support multiple field names: vulnerability_type, type, vuln_type
            raw_type = (
                str(
                    finding.get("vulnerability_type")
                    or finding.get("type")
                    or finding.get("vuln_type")
                    or "other"
                )
                .lower()
                .strip()
                .replace(" ", "_")
                .replace("-", "_")
            )

            type_enum = type_map.get(raw_type, VulnerabilityType.OTHER)

            # 🔥 Additional fallback for common Agent output variations
            if "sqli" in raw_type or "sql" in raw_type:
                type_enum = VulnerabilityType.SQL_INJECTION
            if "xss" in raw_type:
                type_enum = VulnerabilityType.XSS
            if "rce" in raw_type or "command" in raw_type or "cmd" in raw_type:
                type_enum = VulnerabilityType.COMMAND_INJECTION
            if "traversal" in raw_type or "lfi" in raw_type or "rfi" in raw_type:
                type_enum = VulnerabilityType.PATH_TRAVERSAL
            if "ssrf" in raw_type:
                type_enum = VulnerabilityType.SSRF
            if "xxe" in raw_type:
                type_enum = VulnerabilityType.XXE
            if "auth" in raw_type:
                type_enum = VulnerabilityType.AUTH_BYPASS
            if "secret" in raw_type or "credential" in raw_type or "password" in raw_type:
                type_enum = VulnerabilityType.HARDCODED_SECRET
            if "deserial" in raw_type:
                type_enum = VulnerabilityType.DESERIALIZATION

            # 🔥 Handle file path (support multiple field names)
            file_path = (
                finding.get("file_path")
                or finding.get("file")
                or finding.get("location", "").split(":")[0]
                if ":" in finding.get("location", "")
                else finding.get("location")
            )

            # 🔥 v2.1: 文件路径验证 - 过滤幻觉发现
            if project_root and file_path:
                # 清理路径（移除可能的行号）
                clean_path = (
                    file_path.split(":")[0].strip() if ":" in file_path else file_path.strip()
                )
                full_path = os.path.join(project_root, clean_path)

                if not os.path.isfile(full_path):
                    # 尝试作为绝对路径
                    if not (os.path.isabs(clean_path) and os.path.isfile(clean_path)):
                        logger.warning(
                            f"[SaveFindings] 🚫 跳过幻觉发现: 文件不存在 '{file_path}' "
                            f"(title: {finding.get('title', 'N/A')[:50]})"
                        )
                        continue  # 跳过这个发现

            # 🔥 Handle line numbers (support multiple formats)
            line_start = finding.get("line_start") or finding.get("line")
            if not line_start and ":" in finding.get("location", ""):
                try:
                    line_start = int(finding.get("location", "").split(":")[1])
                except (ValueError, IndexError):
                    line_start = None

            line_end = finding.get("line_end") or line_start

            # 🔥 Handle code snippet (support multiple field names)
            code_snippet = (
                finding.get("code_snippet") or finding.get("code") or finding.get("vulnerable_code")
            )

            # 🔥 Handle title (generate from type if not provided)
            title = finding.get("title")
            if not title:
                # Generate title from vulnerability type and file
                type_display = raw_type.replace("_", " ").title()
                if file_path:
                    title = f"{type_display} in {os.path.basename(file_path)}"
                else:
                    title = f"{type_display} Vulnerability"

            # 🔥 Handle description (support multiple field names)
            description = (
                finding.get("description")
                or finding.get("details")
                or finding.get("explanation")
                or finding.get("impact")
                or ""
            )

            # 🔥 Handle suggestion/recommendation
            suggestion = (
                finding.get("suggestion")
                or finding.get("recommendation")
                or finding.get("remediation")
                or finding.get("fix")
            )

            # 🔥 Handle confidence (map to ai_confidence field in model)
            confidence = finding.get("confidence") or finding.get("ai_confidence") or 0.5
            if isinstance(confidence, str):
                try:
                    confidence = float(confidence)
                except ValueError:
                    confidence = 0.5

            # 🔥 Handle verification status
            is_verified = finding.get("is_verified", False)
            if finding.get("verdict") == "confirmed":
                is_verified = True

            # 🔥 Handle PoC information
            poc_data = finding.get("poc", {})
            has_poc = bool(poc_data)
            poc_code = None
            poc_description = None
            poc_steps = None

            if isinstance(poc_data, dict):
                poc_description = poc_data.get("description")
                poc_steps = poc_data.get("steps")
                poc_code = poc_data.get("payload") or poc_data.get("code")
            elif isinstance(poc_data, str):
                poc_description = poc_data

            # 🔥 Handle verification details
            verification_method = finding.get("verification_method")
            verification_result = None
            if finding.get("verification_details"):
                verification_result = {"details": finding.get("verification_details")}

            # 🔥 Handle CWE and CVSS
            cwe_id = finding.get("cwe_id") or finding.get("cwe")
            cvss_score = finding.get("cvss_score") or finding.get("cvss")
            if isinstance(cvss_score, str):
                try:
                    cvss_score = float(cvss_score)
                except ValueError:
                    cvss_score = None

            identity = json.dumps([file_path, line_start, title, type_enum], ensure_ascii=False)
            finding_id = str(uuid5(UUID(task_id), identity))
            if finding_id in seen_ids:
                continue
            seen_ids.add(finding_id)
            if finding_id in existing_ids:
                saved_count += 1
                continue
            db_finding = AgentFinding(
                id=finding_id,
                task_id=task_id,
                vulnerability_type=type_enum,
                severity=severity_enum,
                title=title[:500] if title else "Unknown Vulnerability",
                description=description[:5000] if description else "",
                file_path=file_path[:500] if file_path else None,
                line_start=line_start,
                line_end=line_end,
                code_snippet=code_snippet[:10000] if code_snippet else None,
                suggestion=suggestion[:5000] if suggestion else None,
                is_verified=is_verified,
                ai_confidence=confidence,  # 🔥 FIX: Use ai_confidence, not confidence
                status=FindingStatus.VERIFIED if is_verified else FindingStatus.NEW,
                # 🔥 Additional fields
                has_poc=has_poc,
                poc_code=poc_code,
                poc_description=poc_description,
                poc_steps=poc_steps,
                verification_method=verification_method,
                verification_result=verification_result,
                cvss_score=cvss_score,
                # References for CWE
                references=[{"cwe": cwe_id}] if cwe_id else None,
            )
            db.add(db_finding)
            saved_count += 1
            logger.debug(f"[SaveFindings] Prepared finding: {title[:50]}... ({severity_enum})")

        except Exception as e:
            logger.warning(f"Failed to save finding: {e}, data: {finding}")
            import traceback

            logger.debug(f"[SaveFindings] Traceback: {traceback.format_exc()}")

    logger.info(f"Successfully prepared {saved_count} findings for commit")

    try:
        await db.commit()
        logger.info(f"[SaveFindings] Successfully committed {saved_count} findings to database")
    except Exception as e:
        logger.error(f"Failed to commit findings: {e}")
        await db.rollback()
        raise

    return saved_count


def _calculate_security_score(findings: List[Dict]) -> float:
    """计算安全评分"""
    if not findings:
        return 100.0

    # 基于发现的严重程度计算扣分
    deductions = {
        "critical": 25,
        "high": 15,
        "medium": 8,
        "low": 3,
        "info": 1,
    }

    total_deduction = 0
    for f in findings:
        if isinstance(f, dict):
            sev = f.get("severity", "low")
            total_deduction += deductions.get(sev, 3)

    score = max(0, 100 - total_deduction)
    return float(score)


async def _save_agent_tree(db: AsyncSession, task_id: str) -> None:
    """
    保存 Agent 树到数据库

    🔥 在任务完成前调用，将内存中的 Agent 树持久化到数据库
    """
    from app.models.agent_task import AgentTreeNode
    from app.services.agent.core import agent_registry

    try:
        tree = agent_registry.get_agent_tree()
        nodes = tree.get("nodes", {})

        if not nodes:
            logger.warning(f"[SaveAgentTree] No agent nodes to save for task {task_id}")
            return

        logger.info(f"[SaveAgentTree] Saving {len(nodes)} agent nodes for task {task_id}")

        # 计算每个节点的深度
        def get_depth(agent_id: str, visited: set = None) -> int:
            if visited is None:
                visited = set()
            if agent_id in visited:
                return 0
            visited.add(agent_id)
            node = nodes.get(agent_id)
            if not node:
                return 0
            parent_id = node.get("parent_id")
            if not parent_id:
                return 0
            return 1 + get_depth(parent_id, visited)

        from sqlalchemy import delete

        await db.execute(delete(AgentTreeNode).where(AgentTreeNode.task_id == task_id))
        saved_count = 0
        for agent_id, node_data in nodes.items():
            # 获取 Agent 实例的统计数据
            agent_instance = agent_registry.get_agent(agent_id)
            iterations = 0
            tool_calls = 0
            tokens_used = 0

            if agent_instance and hasattr(agent_instance, "get_stats"):
                stats = agent_instance.get_stats()
                iterations = stats.get("iterations", 0)
                tool_calls = stats.get("tool_calls", 0)
                tokens_used = stats.get("tokens_used", 0)

            # 从结果中获取发现数量
            findings_count = 0
            result_summary = None
            if node_data.get("result"):
                result = node_data.get("result", {})
                if isinstance(result, dict):
                    findings_count = len(result.get("findings", []))
                    if result.get("summary"):
                        result_summary = str(result.get("summary"))[:2000]

            tree_node = AgentTreeNode(
                id=str(uuid4()),
                task_id=task_id,
                agent_id=agent_id,
                agent_name=node_data.get("name", "Unknown"),
                agent_type=node_data.get("type", "unknown"),
                parent_agent_id=node_data.get("parent_id"),
                depth=get_depth(agent_id),
                task_description=node_data.get("task"),
                knowledge_modules=node_data.get("knowledge_modules"),
                status=node_data.get("status", "unknown"),
                result_summary=result_summary,
                findings_count=findings_count,
                iterations=iterations,
                tool_calls=tool_calls,
                tokens_used=tokens_used,
            )
            db.add(tree_node)
            saved_count += 1

        await db.commit()
        logger.info(f"[SaveAgentTree] Successfully saved {saved_count} agent nodes to database")

    except Exception as e:
        logger.error(f"[SaveAgentTree] Failed to save agent tree: {e}", exc_info=True)
        await db.rollback()
