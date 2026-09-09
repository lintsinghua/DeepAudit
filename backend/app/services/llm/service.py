"""
LLM服务 - 代码分析核心服务
支持中英文双语输出
"""

import json
import re
import logging
from typing import Dict, Any, Optional, List
from .types import LLMConfig, LLMProvider, LLMMessage, LLMRequest, DEFAULT_MODELS
from .factory import LLMFactory, NATIVE_ONLY_PROVIDERS
from app.core.config import settings

# json-repair 库用于修复损坏的 JSON
try:
    from json_repair import repair_json
    JSON_REPAIR_AVAILABLE = True
except ImportError:
    JSON_REPAIR_AVAILABLE = False

logger = logging.getLogger(__name__)


class LLMService:
    """LLM服务类"""

    def __init__(self, user_config: Optional[Dict[str, Any]] = None):
        """
        初始化LLM服务

        Args:
            user_config: 用户配置字典，包含llmConfig字段
        """
        self._config: Optional[LLMConfig] = None
        self._user_config = user_config or {}

    def get_agent_timeout_config(self) -> Dict[str, int]:
        """
        获取Agent超时配置（秒）

        Returns:
            包含各种超时配置的字典
        """
        user_llm_config = self._user_config.get('llmConfig', {})

        return {
            'llm_first_token_timeout': user_llm_config.get('llmFirstTokenTimeout') or getattr(settings, 'LLM_FIRST_TOKEN_TIMEOUT', 30),
            'llm_stream_timeout': user_llm_config.get('llmStreamTimeout') or getattr(settings, 'LLM_STREAM_TIMEOUT', 60),
            'agent_timeout': user_llm_config.get('agentTimeout') or getattr(settings, 'AGENT_TIMEOUT_SECONDS', 1800),
            'sub_agent_timeout': user_llm_config.get('subAgentTimeout') or getattr(settings, 'SUB_AGENT_TIMEOUT_SECONDS', 600),
            'tool_timeout': user_llm_config.get('toolTimeout') or getattr(settings, 'TOOL_TIMEOUT_SECONDS', 60),
        }
    
    @property
    def config(self) -> LLMConfig:
        """
        获取LLM配置
        
        🔥 优先级（从高到低）：
        1. 数据库用户配置（系统配置页面保存的配置）
        2. 环境变量配置（.env 文件中的配置）
        
        如果用户配置中某个字段为空，则自动回退到环境变量。
        """
        if self._config is None:
            user_llm_config = self._user_config.get('llmConfig', {})
            
            # 🔥 Provider 优先级：用户配置 > 环境变量
            provider_str = user_llm_config.get('llmProvider') or getattr(settings, 'LLM_PROVIDER', 'openai')
            provider = self._parse_provider(provider_str)
            
            # 🔥 API Key 优先级：用户配置 > 环境变量通用配置 > 环境变量平台专属配置
            api_key = (
                user_llm_config.get('llmApiKey') or
                getattr(settings, 'LLM_API_KEY', '') or
                self._get_provider_api_key_from_user_config(provider, user_llm_config) or
                self._get_provider_api_key(provider)
            )
            
            # 🔥 Base URL 优先级：用户配置 > 环境变量
            base_url = (
                user_llm_config.get('llmBaseUrl') or
                getattr(settings, 'LLM_BASE_URL', None) or
                self._get_provider_base_url(provider)
            )
            
            # 🔥 Model 优先级：用户配置 > 环境变量 > 默认模型
            model = (
                user_llm_config.get('llmModel') or
                getattr(settings, 'LLM_MODEL', '') or
                DEFAULT_MODELS.get(provider, 'gpt-4o-mini')
            )
            
            # 🔥 Timeout 优先级：用户配置（毫秒） > 环境变量（秒）
            timeout_ms = user_llm_config.get('llmTimeout')
            if timeout_ms:
                # 用户配置是毫秒，转换为秒
                timeout = int(timeout_ms / 1000) if timeout_ms > 1000 else int(timeout_ms)
            else:
                # 环境变量是秒
                timeout = int(getattr(settings, 'LLM_TIMEOUT', 150))
            
            # 🔥 Temperature 优先级：用户配置 > 环境变量
            temperature = user_llm_config.get('llmTemperature') if user_llm_config.get('llmTemperature') is not None else float(getattr(settings, 'LLM_TEMPERATURE', 0.1))
            
            # 🔥 Max Tokens 优先级：用户配置 > 环境变量
            max_tokens = user_llm_config.get('llmMaxTokens') or int(getattr(settings, 'LLM_MAX_TOKENS', 4096))
            
            self._config = LLMConfig(
                provider=provider,
                api_key=api_key,
                model=model,
                base_url=base_url,
                timeout=timeout,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        return self._config
    
    def _get_provider_api_key_from_user_config(self, provider: LLMProvider, user_llm_config: Dict[str, Any]) -> Optional[str]:
        """从用户配置中获取平台专属API Key"""
        provider_key_map = {
            LLMProvider.OPENAI: 'openaiApiKey',
            LLMProvider.GEMINI: 'geminiApiKey',
            LLMProvider.CLAUDE: 'claudeApiKey',
            LLMProvider.QWEN: 'qwenApiKey',
            LLMProvider.DEEPSEEK: 'deepseekApiKey',
            LLMProvider.ZHIPU: 'zhipuApiKey',
            LLMProvider.MOONSHOT: 'moonshotApiKey',
            LLMProvider.BAIDU: 'baiduApiKey',
            LLMProvider.MINIMAX: 'minimaxApiKey',
            LLMProvider.DOUBAO: 'doubaoApiKey',
        }
        key_name = provider_key_map.get(provider)
        if key_name:
            return user_llm_config.get(key_name)
        return None
    
    def _get_provider_api_key(self, provider: LLMProvider) -> str:
        """根据提供商获取API Key"""
        provider_key_map = {
            LLMProvider.OPENAI: 'OPENAI_API_KEY',
            LLMProvider.GEMINI: 'GEMINI_API_KEY',
            LLMProvider.CLAUDE: 'CLAUDE_API_KEY',
            LLMProvider.QWEN: 'QWEN_API_KEY',
            LLMProvider.DEEPSEEK: 'DEEPSEEK_API_KEY',
            LLMProvider.ZHIPU: 'ZHIPU_API_KEY',
            LLMProvider.MOONSHOT: 'MOONSHOT_API_KEY',
            LLMProvider.BAIDU: 'BAIDU_API_KEY',
            LLMProvider.MINIMAX: 'MINIMAX_API_KEY',
            LLMProvider.DOUBAO: 'DOUBAO_API_KEY',
            LLMProvider.OLLAMA: None,  # Ollama 不需要 API Key
        }
        key_name = provider_key_map.get(provider)
        if key_name:
            return getattr(settings, key_name, '') or ''
        return 'ollama'  # Ollama的默认值
    
    def _get_provider_base_url(self, provider: LLMProvider) -> Optional[str]:
        """根据提供商获取Base URL"""
        if provider == LLMProvider.OPENAI:
            return getattr(settings, 'OPENAI_BASE_URL', None)
        elif provider == LLMProvider.OLLAMA:
            return getattr(settings, 'OLLAMA_BASE_URL', 'http://localhost:11434/v1')
        return None
    
    def _parse_provider(self, provider_str: str) -> LLMProvider:
        """解析provider字符串"""
        provider_map = {
            'gemini': LLMProvider.GEMINI,
            'openai': LLMProvider.OPENAI,
            'claude': LLMProvider.CLAUDE,
            'qwen': LLMProvider.QWEN,
            'deepseek': LLMProvider.DEEPSEEK,
            'zhipu': LLMProvider.ZHIPU,
            'moonshot': LLMProvider.MOONSHOT,
            'baidu': LLMProvider.BAIDU,
            'minimax': LLMProvider.MINIMAX,
            'doubao': LLMProvider.DOUBAO,
            'ollama': LLMProvider.OLLAMA,
        }
        return provider_map.get(provider_str.lower(), LLMProvider.OPENAI)
    
    def _get_output_language(self) -> str:
        """获取输出语言配置（优先使用用户配置）"""
        user_other_config = self._user_config.get('otherConfig', {})
        return user_other_config.get('outputLanguage') or getattr(settings, 'OUTPUT_LANGUAGE', 'zh-CN')
    
    def _build_system_prompt(self, is_chinese: bool) -> str:
        """构建系统提示词（支持中英文）"""
        schema = """{
    "issues": [
        {
            "type": "security|bug|performance|style|maintainability",
            "severity": "critical|high|medium|low",
            "title": "string",
            "description": "string",
            "suggestion": "string",
            "line": 1,
            "column": 1,
            "code_snippet": "string",
            "ai_explanation": "string",
            "xai": {
                "what": "string",
                "why": "string",
                "how": "string",
                "learn_more": "string(optional)"
            }
        }
    ],
    "quality_score": 0-100,
    "summary": {
        "total_issues": number,
        "critical_issues": number,
        "high_issues": number,
        "medium_issues": number,
        "low_issues": number
    },
    "metrics": {
        "complexity": 0-100,
        "maintainability": 0-100,
        "security": 0-100,
        "performance": 0-100
    }
}"""

        if is_chinese:
            return f"""⚠️⚠️⚠️ 只输出JSON，禁止输出其他任何格式！禁止markdown！禁止文本分析！⚠️⚠️⚠️

你是一个专业的代码审计助手。你的任务是分析代码并返回严格符合JSON Schema的结果。

【最重要】输出格式要求：
1. 必须只输出纯JSON对象，从{{开始，到}}结束
2. 禁止在JSON前后添加任何文字、说明、markdown标记
3. 禁止输出```json或###等markdown语法
4. 如果是文档文件（如README），也必须以JSON格式输出分析结果

【内容要求】：
1. 所有文本内容必须统一使用简体中文
2. JSON字符串值中的特殊字符必须正确转义（换行用\\n，双引号用\\"，反斜杠用\\\\）
3. code_snippet字段必须使用\\n表示换行

请从以下维度全面、彻底地分析代码，找出所有问题：
- 安全漏洞（SQL注入、XSS、命令注入、路径遍历、SSRF、XXE、反序列化、硬编码密钥等）
- 潜在的 Bug 和逻辑错误
- 性能问题和优化建议
- 编码规范和代码风格
- 可维护性和可读性
- 最佳实践和设计模式

【重要】请尽可能多地找出代码中的所有问题，不要遗漏任何安全漏洞或潜在风险！

输出格式必须严格符合以下 JSON Schema：

{schema}

注意：
- title: 问题的简短标题（中文）
- description: 详细描述问题（中文）
- suggestion: 具体的修复建议（中文）
- line: 问题所在的行号（从1开始计数，必须准确对应代码中的行号）
- column: 问题所在的列号（从1开始计数，指向问题代码的起始位置）
- code_snippet: 包含问题的代码片段（建议包含问题行及其前后1-2行作为上下文，保持原始缩进格式）
- ai_explanation: AI 的深入解释（中文）
- xai.what: 这是什么问题（中文）
- xai.why: 为什么会有这个问题（中文）
- xai.how: 如何修复这个问题（中文）

【重要】关于行号和代码片段：
1. line 必须是问题代码的行号！！！代码左侧有"行号|"标注，例如"25| const x = 1"表示第25行，line字段必须填25
2. column 是问题代码在该行中的起始列位置（从1开始，不包括"行号|"前缀部分）
3. code_snippet 应该包含问题代码及其上下文（前后各1-2行），去掉"行号|"前缀，保持原始代码的缩进
4. 如果代码片段包含多行，必须使用 \\n 表示换行符（这是JSON的要求）
5. 如果无法确定准确的行号，不要填写line和column字段（不要填0）

【严格禁止】：
- 禁止在任何字段中使用英文，所有内容必须是简体中文
- 禁止在JSON字符串值中使用真实换行符，必须用\\n转义
- 禁止输出markdown代码块标记（如```json）

⚠️ 重要提醒：line字段必须从代码左侧的行号标注中读取，不要猜测或填0！"""
        else:
            return f"""⚠️⚠️⚠️ OUTPUT JSON ONLY! NO OTHER FORMAT! NO MARKDOWN! NO TEXT ANALYSIS! ⚠️⚠️⚠️

You are a professional code auditing assistant. Your task is to analyze code and return results in strict JSON Schema format.

【MOST IMPORTANT】Output format requirements:
1. MUST output pure JSON object only, starting with {{ and ending with }}
2. NO text, explanation, or markdown markers before or after JSON
3. NO ```json or ### markdown syntax
4. Even for document files (like README), output analysis in JSON format

【Content requirements】:
1. All text content MUST be in English ONLY
2. Special characters in JSON strings must be properly escaped (\\n for newlines, \\" for quotes, \\\\ for backslashes)
3. code_snippet field MUST use \\n for newlines

Please comprehensively and thoroughly analyze the code, finding ALL issues from the following dimensions:
- Security vulnerabilities (SQL injection, XSS, command injection, path traversal, SSRF, XXE, deserialization, hardcoded secrets, etc.)
- Potential bugs and logical errors
- Performance issues and optimization suggestions
- Coding standards and code style
- Maintainability and readability
- Best practices and design patterns

【IMPORTANT】Find as many issues as possible! Do NOT miss any security vulnerabilities or potential risks!

The output format MUST strictly conform to the following JSON Schema:

{schema}

Note:
- title: Brief title of the issue (in English)
- description: Detailed description of the issue (in English)
- suggestion: Specific fix suggestions (in English)
- line: Line number where the issue occurs (1-indexed, must accurately correspond to the line in the code)
- column: Column number where the issue starts (1-indexed, pointing to the start position of the problematic code)
- code_snippet: Code snippet containing the issue (should include the problem line plus 1-2 lines before and after for context, preserve original indentation)
- ai_explanation: AI's in-depth explanation (in English)
- xai.what: What is this issue (in English)
- xai.why: Why does this issue exist (in English)
- xai.how: How to fix this issue (in English)

【IMPORTANT】About line numbers and code snippets:
1. 'line' MUST be the line number from code!!! Code has "lineNumber|" prefix, e.g. "25| const x = 1" means line 25, you MUST set line to 25
2. 'column' is the starting column position in that line (1-indexed, excluding the "lineNumber|" prefix)
3. 'code_snippet' should include the problematic code with context (1-2 lines before/after), remove "lineNumber|" prefix, preserve indentation
4. If code snippet has multiple lines, use \\n for newlines (JSON requirement)
5. If you cannot determine the exact line number, do NOT fill line and column fields (don't use 0)

【STRICTLY PROHIBITED】:
- NO Chinese characters in any field - English ONLY
- NO real newline characters in JSON string values - must use \\n
- NO markdown code block markers (like ```json)

⚠️ CRITICAL: Read line numbers from the "lineNumber|" prefix on the left of each code line. Do NOT guess or use 0!"""

    async def analyze_code(self, code: str, language: str) -> Dict[str, Any]:
        """
        分析代码并返回结构化问题
        支持中英文输出
        
        Raises:
            Exception: 当LLM调用失败或返回无效响应时抛出异常
        """
        # 获取输出语言配置
        output_language = self._get_output_language()
        is_chinese = output_language == 'zh-CN'
        
        # 添加行号帮助LLM定位问题
        code_with_lines = '\n'.join(
            f"{i+1}| {line}" for i, line in enumerate(code.split('\n'))
        )
        
        # 构建系统提示词
        system_prompt = self._build_system_prompt(is_chinese)
        
        # 构建用户提示词
        if is_chinese:
            user_prompt = f"""编程语言: {language}

⚠️ 代码已标注行号（格式：行号| 代码内容），请根据行号准确填写 line 字段！

请分析以下代码:

{code_with_lines}"""
        else:
            user_prompt = f"""Programming Language: {language}

⚠️ Code is annotated with line numbers (format: lineNumber| code), please fill the 'line' field accurately based on these numbers!

Please analyze the following code:

{code_with_lines}"""
        
        try:
            adapter = LLMFactory.create_adapter(self.config)
            
            # 使用用户配置的 temperature（如果未设置则使用 config 中的默认值）
            request = LLMRequest(
                messages=[
                    LLMMessage(role="system", content=system_prompt),
                    LLMMessage(role="user", content=user_prompt)
                ],
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )
            
            response = await adapter.complete(request)
            content = response.content
            
            # 记录 LLM 原始响应（用于调试）
            logger.debug(f"📥 LLM 原始响应长度: {len(content) if content else 0} 字符")
            logger.debug(f"📥 LLM 原始响应内容:\n{content[:500]}..." if content and len(content) > 500 else f"📥 LLM 原始响应内容:\n{content}")
            
            # 检查响应内容是否为空
            if not content or not content.strip():
                error_msg = f"LLM返回空响应 - Provider: {self.config.provider.value}, Model: {self.config.model}"
                logger.error(error_msg)
                logger.error(f"响应详情 - Finish Reason: {response.finish_reason}, Usage: {response.usage}")
                raise Exception(error_msg)
            
            # 尝试从响应中提取JSON
            result = self._parse_json(content)
            
            # 记录解析后的问题数量
            issues_count = len(result.get("issues", []))
            logger.info(f"📊 LLM 分析结果: 发现 {issues_count} 个问题, 质量评分: {result.get('quality_score', 'N/A')}")
            
            # 检查解析结果是否有效（不是默认响应）
            if result == self._get_default_response():
                error_msg = f"无法解析LLM响应为有效的分析结果 - Provider: {self.config.provider.value}"
                logger.error(error_msg)
                raise Exception(error_msg)
            
            return result
            
        except Exception as e:
            logger.error(f"LLM Analysis failed: {e}", exc_info=True)
            logger.error(f"Provider: {self.config.provider.value}, Model: {self.config.model}")
            # 重新抛出异常，让调用者处理
            raise

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        🔥 Agent 使用的聊天完成接口（支持工具调用）

        Args:
            messages: 消息列表，格式为 [{"role": "user", "content": "..."}]
            temperature: 温度参数（None 时使用用户配置）
            max_tokens: 最大token数（None 时使用用户配置）
            tools: 工具描述列表（可选）

        Returns:
            包含 content、usage 和 tool_calls 的字典
        """
        # 使用用户配置作为默认值
        actual_temperature = temperature if temperature is not None else self.config.temperature
        actual_max_tokens = max_tokens if max_tokens is not None else self.config.max_tokens

        # 转换消息格式
        llm_messages = [
            LLMMessage(role=msg["role"], content=msg["content"])
            for msg in messages
        ]

        request = LLMRequest(
            messages=llm_messages,
            temperature=actual_temperature,
            max_tokens=actual_max_tokens,
            tools=tools,
        )

        adapter = LLMFactory.create_adapter(self.config)
        response = await adapter.complete(request)

        result = {
            "content": response.content,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            },
        }

        # 添加工具调用信息
        if response.tool_calls:
            result["tool_calls"] = response.tool_calls

        return result

    async def chat_completion_raw(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        🔥 Agent 使用的原始聊天完成接口（兼容旧接口）

        Args:
            messages: 消息列表，格式为 [{"role": "user", "content": "..."}]
            temperature: 温度参数（None 时使用用户配置）
            max_tokens: 最大token数（None 时使用用户配置）

        Returns:
            包含 content 和 usage 的字典
        """
        # 使用用户配置作为默认值
        actual_temperature = temperature if temperature is not None else self.config.temperature
        actual_max_tokens = max_tokens if max_tokens is not None else self.config.max_tokens

        # 转换消息格式
        llm_messages = [
            LLMMessage(role=msg["role"], content=msg["content"])
            for msg in messages
        ]

        request = LLMRequest(
            messages=llm_messages,
            temperature=actual_temperature,
            max_tokens=actual_max_tokens,
        )

        adapter = LLMFactory.create_adapter(self.config)
        response = await adapter.complete(request)

        return {
            "content": response.content,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            },
        }
    
    async def chat_completion_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ):
        """
        流式聊天完成接口，逐 token 返回

        Args:
            messages: 消息列表
            temperature: 温度参数（None 时使用用户配置）
            max_tokens: 最大token数（None 时使用用户配置）

        Yields:
            dict: {"type": "token", "content": str} 或 {"type": "done", ...}
        """
        # 使用用户配置作为默认值
        actual_temperature = temperature if temperature is not None else self.config.temperature
        actual_max_tokens = max_tokens if max_tokens is not None else self.config.max_tokens

        llm_messages = [
            LLMMessage(role=msg["role"], content=msg["content"])
            for msg in messages
        ]

        request = LLMRequest(
            messages=llm_messages,
            temperature=actual_temperature,
            max_tokens=actual_max_tokens,
        )
        
        if self.config.provider in NATIVE_ONLY_PROVIDERS:
            adapter = LLMFactory.create_adapter(self.config)
            response = await adapter.complete(request)
            content = response.content or ""
            usage = None
            if response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens or 0,
                    "completion_tokens": response.usage.completion_tokens or 0,
                    "total_tokens": response.usage.total_tokens or 0,
                }
            if not content:
                yield {
                    "type": "done",
                    "content": "",
                    "usage": usage,
                    "finish_reason": response.finish_reason or "stop",
                }
            else:
                accumulated = ""
                chunk_size = 20
                for i in range(0, len(content), chunk_size):
                    part = content[i:i + chunk_size]
                    accumulated += part
                    yield {
                        "type": "token",
                        "content": part,
                        "accumulated": accumulated,
                    }
                yield {
                    "type": "done",
                    "content": content,
                    "usage": usage,
                    "finish_reason": response.finish_reason or "stop",
                }
        else:
            from .adapters.litellm_adapter import LiteLLMAdapter
            adapter = LiteLLMAdapter(self.config)
            async for chunk in adapter.stream_complete(request):
                yield chunk
    
    def _parse_json(self, text: str) -> Dict[str, Any]:
        """从LLM响应中解析JSON（增强版）"""
        
        # 检查输入是否为空
        if not text or not text.strip():
            logger.error("LLM响应内容为空，无法解析JSON")
            raise ValueError("LLM响应内容为空")
        
        def clean_text(s: str) -> str:
            """清理文本中的控制字符"""
            # 移除BOM和零宽字符
            s = s.replace('\ufeff', '').replace('\u200b', '').replace('\u200c', '').replace('\u200d', '')
            return s
        
        def fix_json_format(s: str) -> str:
            """修复常见的JSON格式问题"""
            s = s.strip()
            # 移除尾部逗号
            s = re.sub(r',(\s*[}\]])', r'\1', s)
            # 修复未转义的换行符（在字符串值中）
            s = re.sub(r':\s*"([^"]*)\n([^"]*)"', r': "\1\\n\2"', s)
            return s
        
        def aggressive_fix_json(s: str) -> str:
            """激进的JSON修复：尝试修复更多格式问题"""
            s = clean_text(s)
            s = s.strip()
            
            # 找到第一个 { 和最后一个 }
            start_idx = s.find('{')
            if start_idx == -1:
                raise ValueError("No JSON object found")
            
            # 尝试找到最后一个 }
            last_brace = s.rfind('}')
            if last_brace > start_idx:
                s = s[start_idx:last_brace + 1]
            
            # 修复常见的JSON问题
            # 1. 移除尾部逗号
            s = re.sub(r',(\s*[}\]])', r'\1', s)
            # 2. 修复单引号为双引号（仅在键名中，小心处理）
            s = re.sub(r"'(\w+)'\s*:", r'"\1":', s)
            # 3. 修复未转义的控制字符（在字符串值中，但不在键名中）
            # 只移除不在引号内的控制字符，或未转义的换行符/制表符
            lines = []
            in_string = False
            escape_next = False
            for char in s:
                if escape_next:
                    escape_next = False
                    lines.append(char)
                    continue
                if char == '\\':
                    escape_next = True
                    lines.append(char)
                    continue
                if char == '"':
                    in_string = not in_string
                    lines.append(char)
                    continue
                # 如果在字符串外，移除控制字符；如果在字符串内，保留（假设已转义）
                if not in_string and ord(char) < 32 and char not in ['\n', '\t', '\r']:
                    continue  # 跳过控制字符
                lines.append(char)
            s = ''.join(lines)
            
            return s
        
        # 尝试多种方式解析
        attempts = [
            # 1. 直接解析
            lambda: json.loads(text),
            # 2. 清理后解析
            lambda: json.loads(fix_json_format(clean_text(text))),
            # 3. 从markdown代码块提取
            lambda: self._extract_from_markdown(text),
            # 4. 智能提取JSON对象
            lambda: self._extract_json_object(clean_text(text)),
            # 5. 修复截断的JSON
            lambda: self._fix_truncated_json(clean_text(text)),
            # 6. 激进修复后解析
            lambda: json.loads(aggressive_fix_json(text)),
            # 7. 使用 json-repair 库作为最终兜底方案
            lambda: self._repair_json_with_library(text),
        ]
        
        last_error = None
        for i, attempt in enumerate(attempts):
            try:
                result = attempt()
                if result and isinstance(result, dict):
                    if i > 0:
                        logger.info(f"✅ JSON解析成功（方法 {i + 1}/{len(attempts)}）")
                    return result
            except Exception as e:
                last_error = e
                if i == 0:
                    logger.debug(f"直接解析失败，尝试其他方法... {e}")
        
        # 所有尝试都失败
        logger.error("❌ 无法解析LLM响应为JSON")
        logger.error(f"原始内容长度: {len(text)} 字符")
        logger.error(f"原始内容（前500字符）: {text[:500]}")
        logger.error(f"原始内容（后500字符）: {text[-500:] if len(text) > 500 else text}")
        if last_error:
            logger.error(f"最后错误: {type(last_error).__name__}: {str(last_error)}")
        # 抛出异常而不是返回默认响应
        raise ValueError(f"无法解析LLM响应为有效的JSON格式: {str(last_error) if last_error else '未知错误'}")
    
    def _extract_from_markdown(self, text: str) -> Dict[str, Any]:
        """从markdown代码块提取JSON"""
        match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
        if match:
            return json.loads(match.group(1))
        raise ValueError("No markdown code block found")
    
    def _extract_json_object(self, text: str) -> Dict[str, Any]:
        """智能提取JSON对象"""
        start_idx = text.find('{')
        if start_idx == -1:
            raise ValueError("No JSON object found")
        
        # 考虑字符串内的花括号和转义字符
        brace_count = 0
        bracket_count = 0
        in_string = False
        escape_next = False
        end_idx = -1
        
        for i in range(start_idx, len(text)):
            char = text[i]
            
            if escape_next:
                escape_next = False
                continue
            
            if char == '\\':
                escape_next = True
                continue
            
            if char == '"' and not escape_next:
                in_string = not in_string
                continue
            
            if not in_string:
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0 and bracket_count == 0:
                        end_idx = i + 1
                        break
                elif char == '[':
                    bracket_count += 1
                elif char == ']':
                    bracket_count -= 1
        
        if end_idx == -1:
            # 如果找不到完整的JSON，尝试使用最后一个 }
            last_brace = text.rfind('}')
            if last_brace > start_idx:
                end_idx = last_brace + 1
            else:
                raise ValueError("Incomplete JSON object")
        
        json_str = text[start_idx:end_idx]
        # 修复格式问题
        json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
        # 尝试修复未闭合的括号
        open_braces = json_str.count('{') - json_str.count('}')
        open_brackets = json_str.count('[') - json_str.count(']')
        if open_braces > 0:
            json_str += '}' * open_braces
        if open_brackets > 0:
            json_str += ']' * open_brackets
        
        return json.loads(json_str)
    
    def _fix_truncated_json(self, text: str) -> Dict[str, Any]:
        """修复截断的JSON"""
        start_idx = text.find('{')
        if start_idx == -1:
            raise ValueError("Cannot fix truncated JSON")
        
        json_str = text[start_idx:]
        
        # 计算缺失的闭合符号
        open_braces = json_str.count('{')
        close_braces = json_str.count('}')
        open_brackets = json_str.count('[')
        close_brackets = json_str.count(']')
        
        # 补全缺失的闭合符号
        json_str += ']' * max(0, open_brackets - close_brackets)
        json_str += '}' * max(0, open_braces - close_braces)
        
        # 修复格式
        json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
        return json.loads(json_str)
    
    def _repair_json_with_library(self, text: str) -> Dict[str, Any]:
        """使用 json-repair 库修复损坏的 JSON（兜底方案）"""
        if not JSON_REPAIR_AVAILABLE:
            raise ValueError("json-repair library not available")
        
        # 先尝试提取 JSON 部分
        start_idx = text.find('{')
        if start_idx == -1:
            raise ValueError("No JSON object found for repair")
        
        # 尝试找到最后一个 }
        end_idx = text.rfind('}')
        if end_idx > start_idx:
            json_str = text[start_idx:end_idx + 1]
        else:
            json_str = text[start_idx:]
        
        # 使用 json-repair 修复
        repaired = repair_json(json_str, return_objects=True)
        
        if isinstance(repaired, dict):
            logger.info("✅ json-repair 库成功修复 JSON")
            return repaired
        
        raise ValueError(f"json-repair returned unexpected type: {type(repaired)}")
    
    def _get_default_response(self) -> Dict[str, Any]:
        """返回默认响应"""
        return {
            "issues": [],
            "quality_score": 80,
            "summary": {
                "total_issues": 0,
                "critical_issues": 0,
                "high_issues": 0,
                "medium_issues": 0,
                "low_issues": 0
            },
            "metrics": {
                "complexity": 80,
                "maintainability": 80,
                "security": 80,
                "performance": 80
            }
        }

    async def analyze_code_with_custom_prompt(
        self, 
        code: str, 
        language: str, 
        custom_prompt: str,
        rules: Optional[list] = None,
        output_language: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        使用自定义提示词分析代码
        
        Args:
            code: 要分析的代码
            language: 编程语言
            custom_prompt: 自定义系统提示词
            rules: 可选的审计规则列表
            output_language: 输出语言 (zh/en)，如果不指定则使用系统配置
        """
        if output_language:
            is_chinese = output_language == 'zh'
        else:
            system_output_language = self._get_output_language()
            is_chinese = system_output_language == 'zh-CN'
        
        # 添加行号
        code_with_lines = '\n'.join(
            f"{i+1}| {line}" for i, line in enumerate(code.split('\n'))
        )
        
        # 构建规则提示词，并提取启用的规则类别
        rules_prompt = ""
        all_categories = ["security", "bug", "performance", "style", "maintainability"]
        enabled_categories = None  # None 表示不限制（无规则时使用全部类别）

        if rules:
            # 提取启用规则的类别
            enabled_categories = sorted(set(
                rule.get('category', '') for rule in rules if rule.get('enabled', True) and rule.get('category')
            ))

            if is_chinese:
                rules_prompt = "\n\n【审计规则】请特别关注以下规则：\n"
            else:
                rules_prompt = "\n\n[Audit Rules] Please focus on the following rules:\n"
            for rule in rules:
                if rule.get('enabled', True):
                    rules_prompt += f"- [{rule.get('rule_code', '')}] {rule.get('name', '')}: {rule.get('description', '')}\n"
                    if rule.get('custom_prompt'):
                        if is_chinese:
                            rules_prompt += f"  检测要点: {rule.get('custom_prompt')}\n"
                        else:
                            rules_prompt += f"  Detection points: {rule.get('custom_prompt')}\n"

            # 添加类别约束指令
            if enabled_categories:
                category_type_map_zh = {
                    "security": "安全漏洞",
                    "bug": "Bug和逻辑错误",
                    "performance": "性能问题",
                    "style": "编码规范和代码风格",
                    "maintainability": "可维护性和可读性",
                }
                category_type_map_en = {
                    "security": "Security vulnerabilities",
                    "bug": "Bugs and logical errors",
                    "performance": "Performance issues",
                    "style": "Coding standards and code style",
                    "maintainability": "Maintainability and readability",
                }
                if is_chinese:
                    enabled_names = "、".join(category_type_map_zh.get(c, c) for c in enabled_categories)
                    rules_prompt += f"\n【重要】只审计以下类别的问题：{enabled_names}。不要报告其他类别的问题。\n"
                else:
                    enabled_names = ", ".join(category_type_map_en.get(c, c) for c in enabled_categories)
                    rules_prompt += f"\n[IMPORTANT] Only audit issues in the following categories: {enabled_names}. Do not report issues in other categories.\n"

        # 动态构建 type 枚举
        type_enum = "|".join(enabled_categories if enabled_categories else all_categories)

        # JSON Schema
        schema = """{
    "issues": [
        {
            "type": \"""" + type_enum + """",
            "severity": "critical|high|medium|low",
            "title": "string",
            "description": "string",
            "suggestion": "string",
            "line": 1,
            "column": 1,
            "code_snippet": "string",
            "rule_code": "string (optional, if matched a specific rule)"
        }
    ],
    "quality_score": 0-100,
    "summary": {
        "total_issues": number,
        "critical_issues": number,
        "high_issues": number,
        "medium_issues": number,
        "low_issues": number
    }
}"""
        
        # 构建完整的系统提示词
        if is_chinese:
            format_instruction = f"""

【输出格式要求】
1. 必须只输出纯JSON对象
2. 禁止在JSON前后添加任何文字、说明、markdown标记
3. 所有文本字段（title, description, suggestion等）必须使用中文输出
4. 输出格式必须符合以下 JSON Schema：

{schema}
{rules_prompt}"""
        else:
            format_instruction = f"""

【Output Format Requirements】
1. Must output pure JSON object only
2. Do not add any text, explanation, or markdown markers before or after JSON
3. All text fields (title, description, suggestion, etc.) must be in English
4. Output format must conform to the following JSON Schema:

{schema}
{rules_prompt}"""
        
        full_system_prompt = custom_prompt + format_instruction
        
        # 构建用户提示词
        if is_chinese:
            user_prompt = f"""编程语言: {language}

代码已标注行号（格式：行号| 代码内容），请根据行号准确填写 line 字段。

请分析以下代码:

{code_with_lines}"""
        else:
            user_prompt = f"""Programming Language: {language}

Code is annotated with line numbers (format: lineNumber| code), please fill the 'line' field accurately.

Please analyze the following code:

{code_with_lines}"""
        
        try:
            adapter = LLMFactory.create_adapter(self.config)

            # 使用用户配置的 temperature 和 max_tokens
            request = LLMRequest(
                messages=[
                    LLMMessage(role="system", content=full_system_prompt),
                    LLMMessage(role="user", content=user_prompt)
                ],
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )

            response = await adapter.complete(request)
            content = response.content
            
            if not content or not content.strip():
                raise Exception("LLM返回空响应")
            
            result = self._parse_json(content)
            return result
            
        except Exception as e:
            logger.error(f"Custom prompt analysis failed: {e}", exc_info=True)
            raise

    async def analyze_code_with_rules(
        self, 
        code: str, 
        language: str,
        rule_set_id: Optional[str] = None,
        prompt_template_id: Optional[str] = None,
        db_session = None,
        use_default_template: bool = True
    ) -> Dict[str, Any]:
        """
        使用指定的规则集和提示词模板分析代码
        
        Args:
            code: 要分析的代码
            language: 编程语言
            rule_set_id: 规则集ID（可选）
            prompt_template_id: 提示词模板ID（可选）
            db_session: 数据库会话
            use_default_template: 当没有指定模板时是否使用数据库中的默认模板
        """
        custom_prompt = None
        rules = None
        
        if db_session:
            from sqlalchemy.future import select
            from sqlalchemy.orm import selectinload
            from app.models.prompt_template import PromptTemplate
            
            # 获取提示词模板
            if prompt_template_id:
                result = await db_session.execute(
                    select(PromptTemplate).where(PromptTemplate.id == prompt_template_id)
                )
                template = result.scalar_one_or_none()
                if template:
                    output_language = self._get_output_language()
                    custom_prompt = template.content_zh if output_language == 'zh-CN' else template.content_en
            elif use_default_template:
                # 没有指定模板时，使用数据库中的默认模板
                result = await db_session.execute(
                    select(PromptTemplate).where(
                        PromptTemplate.is_default == True,
                        PromptTemplate.is_active == True,
                        PromptTemplate.template_type == 'system'
                    )
                )
                template = result.scalar_one_or_none()
                if template:
                    output_language = self._get_output_language()
                    custom_prompt = template.content_zh if output_language == 'zh-CN' else template.content_en
                    logger.info(f"📋 使用默认提示词模板: {template.name}")
            
            # 获取规则集
            if rule_set_id:
                from app.models.audit_rule import AuditRuleSet
                result = await db_session.execute(
                    select(AuditRuleSet)
                    .options(selectinload(AuditRuleSet.rules))
                    .where(AuditRuleSet.id == rule_set_id)
                )
                rule_set = result.scalar_one_or_none()
                if rule_set and rule_set.rules:
                    rules = [
                        {
                            "rule_code": r.rule_code,
                            "name": r.name,
                            "description": r.description,
                            "category": r.category,
                            "severity": r.severity,
                            "custom_prompt": r.custom_prompt,
                            "enabled": r.enabled,
                        }
                        for r in rule_set.rules if r.enabled
                    ]
        
        # 如果有自定义提示词，使用自定义分析
        if custom_prompt:
            return await self.analyze_code_with_custom_prompt(code, language, custom_prompt, rules)
        
        # 否则使用硬编码的默认分析（兜底）
        return await self.analyze_code(code, language)


# 全局服务实例
llm_service = LLMService()
