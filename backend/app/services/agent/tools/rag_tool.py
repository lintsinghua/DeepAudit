"""
RAG 检索工具
支持语义检索代码
"""

from typing import Optional, List
from pydantic import BaseModel, Field

from .base import AgentTool, ToolResult
from app.services.rag import CodeRetriever


class RAGQueryInput(BaseModel):
    """RAG 查询输入参数"""
    query: str = Field(description="搜索查询，描述你要找的代码功能或特征")
    top_k: int = Field(default=10, description="返回结果数量")
    file_path: Optional[str] = Field(default=None, description="限定搜索的文件路径")
    language: Optional[str] = Field(default=None, description="限定编程语言")
    

class RAGQueryTool(AgentTool):
    """
    RAG 代码检索工具
    使用语义搜索在代码库中查找相关代码
    """
    
    def __init__(self, retriever: CodeRetriever):
        super().__init__()
        self.retriever = retriever
    
    @property
    def name(self) -> str:
        return "rag_query"
    
    @property
    def description(self) -> str:
        return """在代码库中进行语义搜索。
使用场景:
- 查找特定功能的实现代码
- 查找调用某个函数的代码
- 查找处理用户输入的代码
- 查找数据库操作相关代码
- 查找认证/授权相关代码

输入: 
- query: 描述你要查找的代码，例如 "处理用户登录的函数"、"SQL查询执行"、"文件上传处理"
- top_k: 返回结果数量（默认10）
- file_path: 可选，限定在某个文件中搜索
- language: 可选，限定编程语言

输出: 相关的代码片段列表，包含文件路径、行号、代码内容和相似度分数"""
    
    @property
    def args_schema(self):
        return RAGQueryInput
    
    async def _execute(
        self,
        query: str,
        top_k: int = 10,
        file_path: Optional[str] = None,
        language: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """执行 RAG 检索"""
        try:
            results = await self.retriever.retrieve(
                query=query,
                top_k=top_k,
                filter_file_path=file_path,
                filter_language=language,
            )
            
            if not results:
                return ToolResult(
                    success=True,
                    data="没有找到相关代码",
                    metadata={"query": query, "results_count": 0}
                )
            
            # 格式化输出
            output_parts = [f"找到 {len(results)} 个相关代码片段:\n"]
            
            for i, result in enumerate(results):
                output_parts.append(f"\n--- 结果 {i+1} (相似度: {result.score:.2f}) ---")
                output_parts.append(f"文件: {result.file_path}")
                output_parts.append(f"行号: {result.line_start}-{result.line_end}")
                if result.name:
                    output_parts.append(f"名称: {result.name}")
                if result.security_indicators:
                    output_parts.append(f"安全指标: {', '.join(result.security_indicators)}")
                output_parts.append(f"代码:\n```{result.language}\n{result.content}\n```")
            
            return ToolResult(
                success=True,
                data="\n".join(output_parts),
                metadata={
                    "query": query,
                    "results_count": len(results),
                    "results": [r.to_dict() for r in results],
                }
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"RAG 检索失败: {str(e)}",
            )


class SecurityCodeSearchInput(BaseModel):
    """安全代码搜索输入"""
    vulnerability_type: str = Field(
        description="漏洞类型: sql_injection, xss, command_injection, path_traversal, ssrf, deserialization, auth_bypass, hardcoded_secret"
    )
    top_k: int = Field(default=20, description="返回结果数量")


class SecurityCodeSearchTool(AgentTool):
    """
    安全相关代码搜索工具
    专门用于查找可能存在安全漏洞的代码
    """
    
    def __init__(self, retriever: CodeRetriever):
        super().__init__()
        self.retriever = retriever
    
    @property
    def name(self) -> str:
        return "security_code_search"
    
    @property
    def description(self) -> str:
        return """搜索可能存在安全漏洞的代码。
专门针对特定漏洞类型进行搜索。

支持的漏洞类型:
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
- timestamp_dependence: 时间戳依赖"""

    
    @property
    def args_schema(self):
        return SecurityCodeSearchInput
    
    async def _execute(
        self,
        vulnerability_type: str,
        top_k: int = 20,
        **kwargs
    ) -> ToolResult:
        """执行安全代码搜索"""
        try:
            results = await self.retriever.retrieve_security_related(
                vulnerability_type=vulnerability_type,
                top_k=top_k,
            )
            
            if not results:
                return ToolResult(
                    success=True,
                    data=f"没有找到与 {vulnerability_type} 相关的代码",
                    metadata={"vulnerability_type": vulnerability_type, "results_count": 0}
                )
            
            # 格式化输出
            output_parts = [f"找到 {len(results)} 个可能与 {vulnerability_type} 相关的代码:\n"]
            
            for i, result in enumerate(results):
                output_parts.append(f"\n--- 可疑代码 {i+1} ---")
                output_parts.append(f"文件: {result.file_path}:{result.line_start}")
                if result.security_indicators:
                    output_parts.append(f"⚠️ 安全指标: {', '.join(result.security_indicators)}")
                output_parts.append(f"代码:\n```{result.language}\n{result.content}\n```")
            
            return ToolResult(
                success=True,
                data="\n".join(output_parts),
                metadata={
                    "vulnerability_type": vulnerability_type,
                    "results_count": len(results),
                }
            )
            
        except Exception as e:
            error_msg = str(e)
            # 提供更友好的错误信息
            if "401" in error_msg or "Unauthorized" in error_msg:
                return ToolResult(
                    success=False,
                    error=f"安全代码搜索失败: API 认证失败（401 Unauthorized）。\n"
                          f"请检查系统配置中的 LLM API Key 是否正确设置。\n"
                          f"错误详情: {error_msg[:200]}",
                )
            elif "403" in error_msg or "Forbidden" in error_msg:
                return ToolResult(
                    success=False,
                    error=f"安全代码搜索失败: API 访问被拒绝（403 Forbidden）。\n"
                          f"请检查 API Key 是否有足够的权限。\n"
                          f"错误详情: {error_msg[:200]}",
                )
            else:
                return ToolResult(
                    success=False,
                    error=f"安全代码搜索失败: {error_msg[:500]}",
                )


class FunctionContextInput(BaseModel):
    """函数上下文搜索输入"""
    function_name: str = Field(description="函数名称")
    file_path: Optional[str] = Field(default=None, description="文件路径")
    include_callers: bool = Field(default=True, description="是否包含调用者")
    include_callees: bool = Field(default=True, description="是否包含被调用的函数")


class FunctionContextTool(AgentTool):
    """
    函数上下文搜索工具
    查找函数的定义、调用者和被调用者
    """
    
    def __init__(self, retriever: CodeRetriever):
        super().__init__()
        self.retriever = retriever
    
    @property
    def name(self) -> str:
        return "function_context"
    
    @property
    def description(self) -> str:
        return """查找函数的上下文信息，包括定义、调用者和被调用的函数。
用于追踪数据流和理解函数的使用方式。

输入:
- function_name: 要查找的函数名
- file_path: 可选，限定文件路径
- include_callers: 是否查找调用此函数的代码
- include_callees: 是否查找此函数调用的其他函数"""
    
    @property
    def args_schema(self):
        return FunctionContextInput
    
    async def _execute(
        self,
        function_name: str,
        file_path: Optional[str] = None,
        include_callers: bool = True,
        include_callees: bool = True,
        **kwargs
    ) -> ToolResult:
        """执行函数上下文搜索"""
        try:
            context = await self.retriever.retrieve_function_context(
                function_name=function_name,
                file_path=file_path,
                include_callers=include_callers,
                include_callees=include_callees,
            )
            
            output_parts = [f"函数 '{function_name}' 的上下文分析:\n"]
            
            # 函数定义
            if context["definition"]:
                output_parts.append("### 函数定义:")
                for result in context["definition"]:
                    output_parts.append(f"文件: {result.file_path}:{result.line_start}")
                    output_parts.append(f"```{result.language}\n{result.content}\n```")
            else:
                output_parts.append("未找到函数定义")
            
            # 调用者
            if context["callers"]:
                output_parts.append(f"\n### 调用此函数的代码 ({len(context['callers'])} 处):")
                for result in context["callers"][:5]:
                    output_parts.append(f"- {result.file_path}:{result.line_start}")
                    output_parts.append(f"```{result.language}\n{result.content[:500]}\n```")
            
            # 被调用者
            if context["callees"]:
                output_parts.append(f"\n### 此函数调用的其他函数:")
                for result in context["callees"][:5]:
                    if result.name:
                        output_parts.append(f"- {result.name} ({result.file_path})")
            
            return ToolResult(
                success=True,
                data="\n".join(output_parts),
                metadata={
                    "function_name": function_name,
                    "definition_count": len(context["definition"]),
                    "callers_count": len(context["callers"]),
                    "callees_count": len(context["callees"]),
                }
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"函数上下文搜索失败: {str(e)}",
            )

