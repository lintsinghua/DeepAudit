"""
知识查询工具 - 让Agent可以在运行时查询安全知识

基于RAG的知识检索工具
"""

import logging
from typing import Dict, Any, Optional, List, Type
from pydantic import BaseModel, Field

from ..tools.base import AgentTool, ToolResult
from .rag_knowledge import security_knowledge_rag, KnowledgeCategory

logger = logging.getLogger(__name__)


class SecurityKnowledgeQueryInput(BaseModel):
    """安全知识查询输入"""
    query: str = Field(..., description="搜索查询，如漏洞类型、技术名称、安全概念等")
    category: Optional[str] = Field(
        None,
        description="知识类别过滤: vulnerability, best_practice, remediation, code_pattern, compliance"
    )
    top_k: int = Field(3, description="返回结果数量", ge=1, le=10)


class SecurityKnowledgeQueryTool(AgentTool):
    """
    安全知识查询工具
    
    用于查询安全漏洞知识、最佳实践、修复建议等
    """
    
    @property
    def name(self) -> str:
        return "query_security_knowledge"
    
    @property
    def description(self) -> str:
        return """查询安全知识库，获取漏洞类型、检测方法、修复建议等专业知识。

使用场景：
- 需要了解某种漏洞类型的详细信息
- 查找安全最佳实践
- 获取修复建议
- 了解特定技术的安全考量

示例查询：
- "Flash Loan Attacks detection methods"
- "Integer Overflow and Underflow prevention best practices"
- "Unchecked External Calls vulnerability patterns"
- "Reentrancy Attacks Limitation"
"""
    
    @property
    def args_schema(self) -> Type[BaseModel]:
        return SecurityKnowledgeQueryInput
    
    async def _execute(
        self,
        query: str,
        category: Optional[str] = None,
        top_k: int = 3,
    ) -> ToolResult:
        """执行知识查询"""
        try:
            # 转换类别
            knowledge_category = None
            if category:
                try:
                    knowledge_category = KnowledgeCategory(category.lower())
                except ValueError:
                    pass
            
            # 执行搜索
            results = await security_knowledge_rag.search(
                query=query,
                category=knowledge_category,
                top_k=top_k,
            )
            
            if not results:
                return ToolResult(
                    success=True,
                    data="未找到相关的安全知识。请尝试使用不同的关键词。",
                    metadata={"query": query, "results_count": 0},
                )
            
            # 格式化结果
            formatted_results = []
            for i, result in enumerate(results, 1):
                formatted = f"### 结果 {i}"
                if result.get("title"):
                    formatted += f": {result['title']}"
                formatted += f"\n相关度: {result.get('score', 0):.2f}\n"
                if result.get("tags"):
                    formatted += f"标签: {', '.join(result['tags'])}\n"
                if result.get("cwe_ids"):
                    formatted += f"CWE: {', '.join(result['cwe_ids'])}\n"
                formatted += f"\n{result.get('content', '')}"
                formatted_results.append(formatted)
            
            output = f"找到 {len(results)} 条相关知识:\n\n" + "\n\n---\n\n".join(formatted_results)
            
            return ToolResult(
                success=True,
                data=output,
                metadata={
                    "query": query,
                    "results_count": len(results),
                    "results": results,
                },
            )
            
        except Exception as e:
            logger.error(f"Knowledge query failed: {e}")
            return ToolResult(
                success=False,
                error=f"知识查询失败: {str(e)}",
            )


class VulnerabilityKnowledgeInput(BaseModel):
    """漏洞知识查询输入"""
    vulnerability_type: str = Field(
        ...,
        description="漏洞类型，如: unchecked_external_calls, integer_overflow_underflow, flash_loan, reentrancy, DoS, timestamp_dependence, logic_errors, access_control"
    )
    project_language: Optional[str] = Field(
        None,
        description="目标项目的主要编程语言（如 python, php, javascript, solidity, Move），用于过滤相关示例"
    )


class GetVulnerabilityKnowledgeTool(AgentTool):
    """
    获取特定漏洞类型的完整知识
    
    返回该漏洞类型的检测方法、危险模式、修复建议等完整信息
    """
    
    @property
    def name(self) -> str:
        return "get_vulnerability_knowledge"
    
    @property
    def description(self) -> str:
        return """获取特定漏洞类型的完整专业知识。

支持的漏洞类型：
- integer_overflow_underflow: 整数上溢出和下溢
- insecure_randomness: 不安全的随机性
- arithmetic_errors: 计算错误
- access_control: 访问控制漏洞
- logic_errors: 逻辑错误
- flash_loan: 闪贷攻击
- gas_limit: Gas限制漏洞
- denial_of_service: 拒绝服务攻击
- unchecked_external_calls: 未检查的外部调用
- price_oracle_manipulation: 操纵价格
- lack_of_input_validation: 缺少输入验证
- reentrancy: 可重入攻击
- short_address: 短地址攻击
- assert_failure: 断言失败
- proxy_upgradeability: 代理和可升级性漏洞
- front_running: 抢跑攻击
- timestamp_dependence: 时间戳依赖

返回内容包括：
- 漏洞概述和危害
- 危险代码模式
- 检测方法
- 安全实践
- 修复示例
"""
    
    @property
    def args_schema(self) -> Type[BaseModel]:
        return VulnerabilityKnowledgeInput
    
    async def _execute(self, vulnerability_type: str, project_language: Optional[str] = None) -> ToolResult:
        """获取漏洞知识"""
        try:
            knowledge = await security_knowledge_rag.get_vulnerability_knowledge(
                vulnerability_type
            )

            if not knowledge:
                available = security_knowledge_rag.get_all_vulnerability_types()
                return ToolResult(
                    success=True,
                    data=f"未找到漏洞类型 '{vulnerability_type}' 的知识。\n\n可用的漏洞类型: {', '.join(available)}",
                    metadata={"available_types": available},
                )

            # 格式化输出
            output_parts = [
                f"# {knowledge.get('title', vulnerability_type)}",
                f"严重程度: {knowledge.get('severity', 'N/A')}",
            ]

            if knowledge.get("cwe_ids"):
                output_parts.append(f"CWE: {', '.join(knowledge['cwe_ids'])}")
            if knowledge.get("owasp_ids"):
                output_parts.append(f"OWASP: {', '.join(knowledge['owasp_ids'])}")

            # 🔥 v2.2: 添加语言不匹配警告
            content = knowledge.get("content", "")
            knowledge_lang = self._detect_code_language(content)

            if project_language and knowledge_lang:
                project_lang_lower = project_language.lower()
                if knowledge_lang.lower() != project_lang_lower:
                    output_parts.append("")
                    output_parts.append("=" * 60)
                    output_parts.append(f"⚠️ **重要警告**: 以下示例代码是 {knowledge_lang.upper()} 语言")
                    output_parts.append(f"   你正在审计的项目是 {project_language.upper()} 项目")
                    output_parts.append("   **这些代码示例仅供概念参考，不要直接套用到目标项目！**")
                    output_parts.append("   请在目标项目中查找该语言特有的等效漏洞模式。")
                    output_parts.append("=" * 60)

            output_parts.append("")
            output_parts.append(content)

            # 🔥 v2.2: 添加使用指南
            output_parts.append("")
            output_parts.append("---")
            output_parts.append("📌 **使用指南**:")
            output_parts.append("1. 以上知识仅供参考，你必须在实际代码中验证漏洞是否存在")
            output_parts.append("2. 不要假设项目中存在示例中的代码模式")
            output_parts.append("3. 只有在 read_file 读取到的代码中确实存在问题时才报告漏洞")
            output_parts.append("4. 如果示例语言与项目语言不同，请查找该语言的等效漏洞模式")

            return ToolResult(
                success=True,
                data="\n".join(output_parts),
                metadata={
                    **knowledge,
                    "knowledge_language": knowledge_lang,
                    "project_language": project_language,
                },
            )

        except Exception as e:
            logger.error(f"Get vulnerability knowledge failed: {e}")
            return ToolResult(
                success=False,
                error=f"获取漏洞知识失败: {str(e)}",
            )

    def _detect_code_language(self, content: str) -> Optional[str]:
        """检测知识内容中的主要代码语言"""
        # 检测代码块中的语言标记
        import re
        code_blocks = re.findall(r'```(\w+)', content)
        if code_blocks:
            # 统计最常见的语言
            from collections import Counter
            lang_counts = Counter(code_blocks)
            most_common = lang_counts.most_common(1)
            if most_common:
                return most_common[0][0]

        # 基于内容特征检测
        if "def " in content or "import " in content or "@app.route" in content:
            return "python"
        if "<?php" in content or "$_GET" in content or "$_POST" in content:
            return "php"
        if "function " in content and ("const " in content or "let " in content):
            return "javascript"
        if "func " in content and "package " in content:
            return "go"
        if "fn " in content and "let mut" in content:
            return "rust"
        if "public class" in content or "private void" in content:
            return "java"
        if "pragma solidity" in content or ("contract " in content and ("msg.sender" in content or "mapping(" in content)):
            return "solidity"
        if "public fun " in content or "acquires " in content or ("module " in content and ("has key" in content or "has store" in content)):
            return "move"
        return None


class ListKnowledgeModulesInput(BaseModel):
    """列出知识模块输入"""
    category: Optional[str] = Field(
        None,
        description="按类别过滤: vulnerability, best_practice, remediation"
    )


class ListKnowledgeModulesTool(AgentTool):
    """
    列出所有可用的知识模块
    """
    
    @property
    def name(self) -> str:
        return "list_knowledge_modules"
    
    @property
    def description(self) -> str:
        return "列出所有可用的安全知识模块，包括漏洞类型、最佳实践等"
    
    @property
    def args_schema(self) -> Type[BaseModel]:
        return ListKnowledgeModulesInput
    
    async def _execute(self, category: Optional[str] = None) -> ToolResult:
        """列出知识模块"""
        try:
            modules = security_knowledge_rag.get_all_vulnerability_types()
            
            output = "可用的安全知识模块:\n\n"
            output += "## 漏洞类型\n"
            for module in modules:
                output += f"- {module}\n"
            
            return ToolResult(
                success=True,
                data=output,
                metadata={"modules": modules},
            )
            
        except Exception as e:
            logger.error(f"List knowledge modules failed: {e}")
            return ToolResult(
                success=False,
                error=f"列出知识模块失败: {str(e)}",
            )
