"""
沙箱执行工具
在 Docker 沙箱中执行代码和命令进行漏洞验证
"""

import asyncio
import json
import logging
import tempfile
import os
import shutil
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from dataclasses import dataclass

from .base import AgentTool, ToolResult
from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SandboxConfig:
    """沙箱配置"""
    image: str = None  # 默认从 settings.SANDBOX_IMAGE 读取
    memory_limit: str = "512m"
    cpu_limit: float = 1.0
    timeout: int = 60
    network_mode: str = "none"  # none, bridge, host
    read_only: bool = True
    user: str = "1000:1000"
    cap_drop: list = None  # 丢弃的 Linux 能力列表
    no_new_privileges: bool = True  # 禁止提权

    def __post_init__(self):
        if self.image is None:
            self.image = settings.SANDBOX_IMAGE
        if self.cap_drop is None:
            cap_drop_str = getattr(settings, 'SANDBOX_CAP_DROP', 'ALL')
            if cap_drop_str.upper() == 'NONE':
                self.cap_drop = []
            else:
                self.cap_drop = [c.strip() for c in cap_drop_str.split(',') if c.strip()]
        self.no_new_privileges = getattr(settings, 'SANDBOX_NO_NEW_PRIVILEGES', True)


class SandboxManager:
    """
    沙箱管理器
    管理 Docker 容器的创建、执行和清理
    """
    
    def __init__(self, config: Optional[SandboxConfig] = None):
        self.config = config or SandboxConfig()
        self._docker_client = None
        self._initialized = False
        self._init_error = None
    
    async def initialize(self):
        """初始化 Docker 客户端"""
        if self._initialized:
            logger.info("✅ SandboxManager already initialized")
            return

        try:
            import docker
            logger.info(f"🔄 Attempting to connect to Docker... (lib: {docker.__file__})")
            self._docker_client = docker.from_env()
            # 测试连接
            self._docker_client.ping()
            self._initialized = True
            self._init_error = None
            logger.info("✅ Docker sandbox manager initialized successfully")
        except ImportError as e:
            logger.error(f"❌ Docker library not installed: {e}")
            self._docker_client = None
            self._init_error = f"ImportError: {e}"
        except Exception as e:
            logger.warning(f"❌ Docker not available: {e}")
            import traceback
            logger.warning(f"Docker connection traceback: {traceback.format_exc()}")
            self._docker_client = None
            self._init_error = f"{type(e).__name__}: {str(e)}"
    
    @property
    def is_available(self) -> bool:
        """检查 Docker 是否可用"""
        return self._docker_client is not None
        
    def get_diagnosis(self) -> str:
        """获取诊断信息"""
        if self.is_available:
            return "Docker Service Available"
        return f"Docker Service Unavailable. Error: {self._init_error or 'Not initialized'}"
    
    async def execute_command(
        self,
        command: str,
        working_dir: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        在沙箱中执行命令
        
        Args:
            command: 要执行的命令
            working_dir: 工作目录
            env: 环境变量
            timeout: 超时时间（秒）
            
        Returns:
            执行结果
        """
        if not self.is_available:
            return {
                "success": False,
                "error": "Docker 不可用",
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
            }
        
        timeout = timeout or self.config.timeout

        # 禁用代理环境变量，防止 Docker 自动注入的代理干扰容器网络
        no_proxy_env = {
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "http_proxy": "",
            "https_proxy": "",
            "NO_PROXY": "*",
            "no_proxy": "*",
        }
        # 合并用户传入的环境变量（用户变量优先）
        container_env = {**no_proxy_env, **(env or {})}

        try:
            # 创建临时目录
            with tempfile.TemporaryDirectory() as temp_dir:
                # 准备容器配置
                container_config = {
                    "image": self.config.image,
                    "command": ["sh", "-c", command],
                    "detach": True,
                    "mem_limit": self.config.memory_limit,
                    "cpu_period": 100000,
                    "cpu_quota": int(100000 * self.config.cpu_limit),
                    "network_mode": self.config.network_mode,
                    "user": self.config.user,
                    "read_only": self.config.read_only,
                    "volumes": {
                        temp_dir: {"bind": "/workspace", "mode": "rw"},
                    },
                    "tmpfs": {
                            "/home/sandbox": "rw,size=100m,mode=1777",
                            "/tmp": "rw,size=100m,mode=1777"
                        },
                    "working_dir": working_dir or "/workspace",
                    "environment": container_env,
                }

                # 安全配置：可通过环境变量调整
                if self.config.cap_drop:
                    container_config["cap_drop"] = self.config.cap_drop
                if self.config.no_new_privileges:
                    container_config["security_opt"] = ["no-new-privileges:true"]
                
                # 创建并启动容器
                container = await asyncio.to_thread(
                    self._docker_client.containers.run,
                    **container_config
                )
                
                try:
                    # 等待执行完成
                    result = await asyncio.wait_for(
                        asyncio.to_thread(container.wait),
                        timeout=timeout
                    )
                    
                    # 获取日志
                    stdout = await asyncio.to_thread(
                        container.logs, stdout=True, stderr=False
                    )
                    stderr = await asyncio.to_thread(
                        container.logs, stdout=False, stderr=True
                    )
                    
                    return {
                        "success": result["StatusCode"] == 0,
                        "stdout": stdout.decode('utf-8', errors='ignore')[:10000],
                        "stderr": stderr.decode('utf-8', errors='ignore')[:2000],
                        "exit_code": result["StatusCode"],
                        "error": None,
                    }
                    
                except asyncio.TimeoutError:
                    await asyncio.to_thread(container.kill)
                    return {
                        "success": False,
                        "error": f"执行超时 ({timeout}秒)",
                        "stdout": "",
                        "stderr": "",
                        "exit_code": -1,
                    }
                    
                finally:
                    # 清理容器
                    await asyncio.to_thread(container.remove, force=True)
                    
        except Exception as e:
            logger.error(f"Sandbox execution error: {e}")
            return {
                "success": False,
                "error": str(e),
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
            }
    
    async def execute_tool_command(
        self,
        command: str,
        host_workdir: str,
        timeout: Optional[int] = None,
        env: Optional[Dict[str, str]] = None,
        network_mode: str = "none",
    ) -> Dict[str, Any]:
        """
        在沙箱中对指定目录执行工具命令
        
        Args:
            command: 要执行的命令
            host_workdir: 宿主机上的工作目录（将被挂载到 /workspace）
            timeout: 超时时间
            env: 环境变量
            network_mode: 网络模式 (none, bridge, host)
            
        Returns:
            执行结果
        """
        if not self.is_available:
            return {
                "success": False,
                "error": "Docker 不可用",
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
            }
        
        timeout = timeout or self.config.timeout

        # 禁用代理环境变量，防止 Docker 自动注入的代理干扰容器网络
        no_proxy_env = {
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "http_proxy": "",
            "https_proxy": "",
            "NO_PROXY": "*",
            "no_proxy": "*",
        }
        # 合并用户传入的环境变量（用户变量优先）
        container_env = {**no_proxy_env, **(env or {})}

        try:
            # 清除代理环境变量：在命令前添加 unset（双重保险）
            unset_proxy_prefix = "unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy 2>/dev/null; "
            wrapped_command = unset_proxy_prefix + command

            # 准备容器配置
            container_config = {
                "image": self.config.image,
                "command": ["sh", "-c", wrapped_command],
                "detach": True,
                "mem_limit": self.config.memory_limit,
                "cpu_period": 100000,
                "cpu_quota": int(100000 * self.config.cpu_limit),
                "network_mode": network_mode,
                "user": self.config.user,
                "read_only": self.config.read_only,
                "volumes": {
                    host_workdir: {"bind": "/workspace", "mode": "ro"}, # 只读挂载项目代码
                },
                "tmpfs": {
                    "/home/sandbox": "rw,size=100m,mode=1777",
                    "/tmp": "rw,size=100m,mode=1777"  # 添加 /tmp 目录供工具写入临时文件
                },
                "working_dir": "/workspace",
                "environment": container_env,
            }

            # 安全配置：可通过环境变量调整
            if self.config.cap_drop:
                container_config["cap_drop"] = self.config.cap_drop
            if self.config.no_new_privileges:
                container_config["security_opt"] = ["no-new-privileges:true"]
            
            # 创建并启动容器
            container = await asyncio.to_thread(
                self._docker_client.containers.run,
                **container_config
            )
            
            try:
                # 等待执行完成
                result = await asyncio.wait_for(
                    asyncio.to_thread(container.wait),
                    timeout=timeout
                )
                
                # 获取日志
                stdout = await asyncio.to_thread(
                    container.logs, stdout=True, stderr=False
                )
                stderr = await asyncio.to_thread(
                    container.logs, stdout=False, stderr=True
                )
                
                return {
                    "success": result["StatusCode"] == 0,
                    "stdout": stdout.decode('utf-8', errors='ignore')[:50000], # 增大日志限制
                    "stderr": stderr.decode('utf-8', errors='ignore')[:5000],
                    "exit_code": result["StatusCode"],
                    "error": None,
                }
                
            except asyncio.TimeoutError:
                await asyncio.to_thread(container.kill)
                return {
                    "success": False,
                    "error": f"执行超时 ({timeout}秒)",
                    "stdout": "",
                    "stderr": "",
                    "exit_code": -1,
                }
                
            finally:
                # 清理容器
                await asyncio.to_thread(container.remove, force=True)
                
        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return {
                "success": False,
                "error": str(e),
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
            }
    async def execute_python(
        self,
        code: str,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        在沙箱中执行 Python 代码
        
        Args:
            code: Python 代码
            timeout: 超时时间
            
        Returns:
            执行结果
        """
        # 转义代码中的单引号
        escaped_code = code.replace("'", "'\\''")
        command = f"python3 -c '{escaped_code}'"
        return await self.execute_command(command, timeout=timeout)
    
    async def execute_http_request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        data: Optional[str] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        在沙箱中执行 HTTP 请求
        
        Args:
            method: HTTP 方法
            url: URL
            headers: 请求头
            data: 请求体
            timeout: 超时
            
        Returns:
            HTTP 响应
        """
        # 构建 curl 命令
        curl_parts = ["curl", "-s", "-S", "-w", "'\\n%{http_code}'", "-X", method]
        
        if headers:
            for key, value in headers.items():
                curl_parts.extend(["-H", f"'{key}: {value}'"])
        
        if data:
            curl_parts.extend(["-d", f"'{data}'"])
        
        curl_parts.append(f"'{url}'")
        
        command = " ".join(curl_parts)
        
        # 使用带网络的镜像
        original_network = self.config.network_mode
        self.config.network_mode = "bridge"  # 允许网络访问
        
        try:
            result = await self.execute_command(command, timeout=timeout)
            
            if result["success"] and result["stdout"]:
                lines = result["stdout"].strip().split('\n')
                if lines:
                    status_code = lines[-1].strip()
                    body = '\n'.join(lines[:-1])
                    return {
                        "success": True,
                        "status_code": int(status_code) if status_code.isdigit() else 0,
                        "body": body[:5000],
                        "error": None,
                    }
            
            return {
                "success": False,
                "status_code": 0,
                "body": "",
                "error": result.get("error") or result.get("stderr"),
            }
            
        finally:
            self.config.network_mode = original_network
    
    async def verify_vulnerability(
        self,
        vulnerability_type: str,
        target_url: str,
        payload: str,
        expected_pattern: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        验证漏洞
        
        Args:
            vulnerability_type: 漏洞类型
            target_url: 目标 URL
            payload: 攻击载荷
            expected_pattern: 期望在响应中匹配的模式
            
        Returns:
            验证结果
        """
        verification_result = {
            "vulnerability_type": vulnerability_type,
            "target_url": target_url,
            "payload": payload,
            "is_vulnerable": False,
            "evidence": None,
            "error": None,
        }
        
        try:
            # 发送请求
            response = await self.execute_http_request(
                method="GET" if "?" in target_url else "POST",
                url=target_url,
                data=payload if "?" not in target_url else None,
            )
            
            if not response["success"]:
                verification_result["error"] = response.get("error")
                return verification_result
            
            body = response.get("body", "")
            status_code = response.get("status_code", 0)
            
            # 检查响应
            if expected_pattern:
                import re
                if re.search(expected_pattern, body, re.IGNORECASE):
                    verification_result["is_vulnerable"] = True
                    verification_result["evidence"] = f"响应中包含预期模式: {expected_pattern}"
            else:
                # 根据漏洞类型进行通用检查
                if vulnerability_type == "sql_injection":
                    error_patterns = [
                        r"SQL syntax",
                        r"mysql_fetch",
                        r"ORA-\d+",
                        r"PostgreSQL.*ERROR",
                        r"SQLite.*error",
                        r"ODBC.*Driver",
                    ]
                    for pattern in error_patterns:
                        if re.search(pattern, body, re.IGNORECASE):
                            verification_result["is_vulnerable"] = True
                            verification_result["evidence"] = f"SQL错误信息: {pattern}"
                            break
                
                elif vulnerability_type == "xss":
                    if payload in body:
                        verification_result["is_vulnerable"] = True
                        verification_result["evidence"] = "XSS payload 被反射到响应中"
                
                elif vulnerability_type == "command_injection":
                    # 检查命令执行结果
                    if "uid=" in body or "root:" in body:
                        verification_result["is_vulnerable"] = True
                        verification_result["evidence"] = "命令执行成功"
            
            verification_result["response_status"] = status_code
            verification_result["response_length"] = len(body)
            
        except Exception as e:
            verification_result["error"] = str(e)
        
        return verification_result


class SandboxCommandInput(BaseModel):
    """沙箱命令输入"""
    command: str = Field(description="要执行的命令")
    timeout: int = Field(default=30, description="超时时间（秒）")


class SandboxTool(AgentTool):
    """
    沙箱执行工具
    在安全隔离的环境中执行代码和命令
    """

    # 允许的命令前缀 - 放宽限制以支持更灵活的测试
    ALLOWED_COMMANDS = [
        # 编程语言解释器
        "python", "python3", "node", "php", "ruby", "perl",
        "go", "java", "javac", "bash", "sh",
        # 网络工具
        "curl", "wget", "nc", "netcat",
        # 文件操作
        "cat", "head", "tail", "grep", "find", "ls", "wc",
        "sed", "awk", "cut", "sort", "uniq", "tr", "xargs",
        # 系统信息（用于验证命令执行）
        "echo", "printf", "test", "id", "whoami", "uname",
        "env", "printenv", "pwd", "hostname",
        # 编码/解码工具
        "base64", "xxd", "od", "hexdump",
        # 其他实用工具
        "timeout", "time", "sleep", "true", "false",
        "md5sum", "sha256sum", "strings",
    ]
    
    def __init__(self, sandbox_manager: Optional[SandboxManager] = None):
        super().__init__()
        self.sandbox_manager = sandbox_manager or SandboxManager()
    
    @property
    def name(self) -> str:
        return "sandbox_exec"
    
    @property
    def description(self) -> str:
        return """在安全沙箱中执行命令或代码。
用于验证漏洞、测试 PoC 或执行安全检查。

⚠️ 安全限制:
- 命令在 Docker 容器中执行
- 网络默认隔离
- 资源有限制
- 只允许特定命令

允许的命令: python, python3, node, curl, cat, grep, find, ls, echo, id

使用场景:
- 验证命令注入漏洞
- 执行 PoC 代码
- 测试 payload 效果"""
    
    @property
    def args_schema(self):
        return SandboxCommandInput
    
    async def _execute(
        self,
        command: str,
        timeout: int = 30,
        **kwargs
    ) -> ToolResult:
        """执行沙箱命令"""
        # 初始化沙箱
        await self.sandbox_manager.initialize()
        
        if not self.sandbox_manager.is_available:
            return ToolResult(
                success=False,
                error="沙箱环境不可用（Docker 未安装或未运行）",
            )
        
        # 安全检查：验证命令是否允许
        cmd_parts = command.strip().split()
        if not cmd_parts:
            return ToolResult(success=False, error="命令不能为空")
        
        base_cmd = cmd_parts[0]
        if not any(base_cmd.startswith(allowed) for allowed in self.ALLOWED_COMMANDS):
            return ToolResult(
                success=False,
                error=f"命令 '{base_cmd}' 不在允许列表中。允许的命令: {', '.join(self.ALLOWED_COMMANDS)}",
            )
        
        # 执行命令
        result = await self.sandbox_manager.execute_command(
            command=command,
            timeout=timeout,
        )
        
        # 格式化输出
        output_parts = ["🐳 沙箱执行结果\n"]
        output_parts.append(f"命令: {command}")
        output_parts.append(f"退出码: {result['exit_code']}")
        
        if result["stdout"]:
            output_parts.append(f"\n标准输出:\n```\n{result['stdout']}\n```")
        
        if result["stderr"]:
            output_parts.append(f"\n标准错误:\n```\n{result['stderr']}\n```")
        
        if result.get("error"):
            output_parts.append(f"\n错误: {result['error']}")
        
        return ToolResult(
            success=result["success"],
            data="\n".join(output_parts),
            error=result.get("error"),
            metadata={
                "command": command,
                "exit_code": result["exit_code"],
            }
        )


class HttpRequestInput(BaseModel):
    """HTTP 请求输入"""
    method: str = Field(default="GET", description="HTTP 方法 (GET, POST, PUT, DELETE)")
    url: str = Field(description="请求 URL")
    headers: Optional[Dict[str, str]] = Field(default=None, description="请求头")
    data: Optional[str] = Field(default=None, description="请求体")
    timeout: int = Field(default=30, description="超时时间（秒）")


class SandboxHttpTool(AgentTool):
    """
    沙箱 HTTP 请求工具
    在沙箱中发送 HTTP 请求
    """
    
    def __init__(self, sandbox_manager: Optional[SandboxManager] = None):
        super().__init__()
        self.sandbox_manager = sandbox_manager or SandboxManager()
    
    @property
    def name(self) -> str:
        return "sandbox_http"
    
    @property
    def description(self) -> str:
        return """在沙箱中发送 HTTP 请求。
用于测试 Web 漏洞如 SQL 注入、XSS、SSRF 等。

输入:
- method: HTTP 方法
- url: 请求 URL
- headers: 可选，请求头
- data: 可选，请求体
- timeout: 超时时间

使用场景:
- 验证 SQL 注入漏洞
- 测试 XSS payload
- 验证 SSRF 漏洞
- 测试认证绕过"""
    
    @property
    def args_schema(self):
        return HttpRequestInput
    
    async def _execute(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        data: Optional[str] = None,
        timeout: int = 30,
        **kwargs
    ) -> ToolResult:
        """执行 HTTP 请求"""
        try:
            await self.sandbox_manager.initialize()
        except Exception as e:
            logger.warning(f"Sandbox init failed during execution: {e}")
        
        if not self.sandbox_manager.is_available:
            return ToolResult(
                success=False,
                error="沙箱环境不可用 (Docker Unavailable)",
            )
        
        result = await self.sandbox_manager.execute_http_request(
            method=method,
            url=url,
            headers=headers,
            data=data,
            timeout=timeout,
        )
        
        output_parts = ["🌐 HTTP 请求结果\n"]
        output_parts.append(f"请求: {method} {url}")
        
        if headers:
            output_parts.append(f"请求头: {json.dumps(headers, ensure_ascii=False)}")
        
        if data:
            output_parts.append(f"请求体: {data[:500]}")
        
        output_parts.append(f"\n状态码: {result.get('status_code', 'N/A')}")
        
        if result.get("body"):
            body = result["body"]
            if len(body) > 2000:
                body = body[:2000] + f"\n... (截断，共 {len(result['body'])} 字符)"
            output_parts.append(f"\n响应内容:\n```\n{body}\n```")
        
        if result.get("error"):
            output_parts.append(f"\n错误: {result['error']}")
        
        return ToolResult(
            success=result["success"],
            data="\n".join(output_parts),
            error=result.get("error"),
            metadata={
                "method": method,
                "url": url,
                "status_code": result.get("status_code"),
                "response_length": len(result.get("body", "")),
            }
        )


class VulnerabilityVerifyInput(BaseModel):
    """漏洞验证输入"""
    vulnerability_type: str = Field(description="漏洞类型 (sql_injection, xss, command_injection, etc.)")
    target_url: str = Field(description="目标 URL")
    payload: str = Field(description="攻击载荷")
    expected_pattern: Optional[str] = Field(default=None, description="期望在响应中匹配的正则模式")


class VulnerabilityVerifyTool(AgentTool):
    """
    漏洞验证工具
    在沙箱中验证漏洞是否真实存在
    """
    
    def __init__(self, sandbox_manager: Optional[SandboxManager] = None):
        super().__init__()
        self.sandbox_manager = sandbox_manager or SandboxManager()
    
    @property
    def name(self) -> str:
        return "verify_vulnerability"
    
    @property
    def description(self) -> str:
        return """验证漏洞是否真实存在。
发送包含攻击载荷的请求，分析响应判断漏洞是否可利用。

输入:
- vulnerability_type: 漏洞类型
- target_url: 目标 URL
- payload: 攻击载荷
- expected_pattern: 可选，期望在响应中匹配的模式

支持的漏洞类型:
- sql_injection: SQL 注入
- xss: 跨站脚本
- command_injection: 命令注入
- path_traversal: 路径遍历
- ssrf: 服务端请求伪造"""
    
    @property
    def args_schema(self):
        return VulnerabilityVerifyInput
    
    async def _execute(
        self,
        vulnerability_type: str,
        target_url: str,
        payload: str,
        expected_pattern: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """执行漏洞验证"""
        try:
            await self.sandbox_manager.initialize()
        except Exception as e:
            logger.warning(f"Sandbox init failed during execution: {e}")
        
        if not self.sandbox_manager.is_available:
            return ToolResult(
                success=False,
                error="沙箱环境不可用 (Docker Unavailable)",
            )
        
        result = await self.sandbox_manager.verify_vulnerability(
            vulnerability_type=vulnerability_type,
            target_url=target_url,
            payload=payload,
            expected_pattern=expected_pattern,
        )
        
        output_parts = ["🔍 漏洞验证结果\n"]
        output_parts.append(f"漏洞类型: {vulnerability_type}")
        output_parts.append(f"目标: {target_url}")
        output_parts.append(f"Payload: {payload[:200]}")
        
        if result["is_vulnerable"]:
            output_parts.append(f"\n🔴 结果: 漏洞已确认!")
            output_parts.append(f"证据: {result.get('evidence', 'N/A')}")
        else:
            output_parts.append(f"\n🟢 结果: 未能确认漏洞")
            if result.get("error"):
                output_parts.append(f"错误: {result['error']}")
        
        if result.get("response_status"):
            output_parts.append(f"\nHTTP 状态码: {result['response_status']}")
        
        return ToolResult(
            success=True,
            data="\n".join(output_parts),
            metadata={
                "vulnerability_type": vulnerability_type,
                "is_vulnerable": result["is_vulnerable"],
                "evidence": result.get("evidence"),
            }
        )


# ============ PHP 测试工具 ============

class PhpTestInput(BaseModel):
    """PHP 测试输入"""
    php_code: Optional[str] = Field(default=None, description="要执行的 PHP 代码（可选，与 file_path 二选一）")
    file_path: Optional[str] = Field(default=None, description="要测试的 PHP 文件路径（可选，与 php_code 二选一）")
    get_params: Optional[Dict[str, str]] = Field(default=None, description="模拟的 GET 参数，如 {'cmd': 'whoami'}")
    post_params: Optional[Dict[str, str]] = Field(default=None, description="模拟的 POST 参数")
    timeout: int = Field(default=30, description="超时时间（秒）")


class PhpTestTool(AgentTool):
    """
    PHP 代码测试工具
    在沙箱中执行 PHP 代码，支持模拟 GET/POST 参数
    """

    def __init__(self, sandbox_manager: Optional[SandboxManager] = None, project_root: str = "."):
        super().__init__()
        self.sandbox_manager = sandbox_manager or SandboxManager()
        self.project_root = project_root

    @property
    def name(self) -> str:
        return "php_test"

    @property
    def description(self) -> str:
        return """在沙箱中测试 PHP 代码，支持模拟 GET/POST 参数。
专门用于验证 PHP 漏洞（如命令注入、SQL 注入等）。

输入 (二选一):
- php_code: 直接提供要执行的 PHP 代码
- file_path: 项目中的 PHP 文件路径

模拟参数:
- get_params: 模拟 $_GET 参数，如 {"cmd": "whoami", "id": "1"}
- post_params: 模拟 $_POST 参数

示例:
1. 测试命令注入:
   {"file_path": "vuln.php", "get_params": {"cmd": "whoami"}}

2. 直接测试代码:
   {"php_code": "<?php echo shell_exec($_GET['cmd']); ?>", "get_params": {"cmd": "id"}}

⚠️ 在沙箱中执行，不影响真实环境。"""

    @property
    def args_schema(self):
        return PhpTestInput

    async def _execute(
        self,
        php_code: Optional[str] = None,
        file_path: Optional[str] = None,
        get_params: Optional[Dict[str, str]] = None,
        post_params: Optional[Dict[str, str]] = None,
        timeout: int = 30,
        **kwargs
    ) -> ToolResult:
        """执行 PHP 测试"""
        try:
            await self.sandbox_manager.initialize()
        except Exception as e:
            logger.warning(f"Sandbox init failed: {e}")

        if not self.sandbox_manager.is_available:
            return ToolResult(
                success=False,
                error="沙箱环境不可用 (Docker Unavailable)",
            )

        # 构建 PHP 代码
        if file_path:
            # 从文件读取
            import os
            full_path = os.path.join(self.project_root, file_path)
            if not os.path.exists(full_path):
                return ToolResult(
                    success=False,
                    error=f"文件不存在: {file_path}",
                )
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                php_code = f.read()

        if not php_code:
            return ToolResult(
                success=False,
                error="必须提供 php_code 或 file_path",
            )

        # 构建模拟 $_GET 和 $_POST 的包装代码
        wrapper_parts = ["<?php"]

        # 模拟 $_GET
        if get_params:
            for key, value in get_params.items():
                # 安全转义
                escaped_value = value.replace("'", "\\'")
                wrapper_parts.append(f"$_GET['{key}'] = '{escaped_value}';")

        # 模拟 $_POST
        if post_params:
            for key, value in post_params.items():
                escaped_value = value.replace("'", "\\'")
                wrapper_parts.append(f"$_POST['{key}'] = '{escaped_value}';")

        # 移除 php_code 开头的 <?php 标签
        clean_code = php_code.strip()
        if clean_code.startswith("<?php"):
            clean_code = clean_code[5:].strip()
        if clean_code.startswith("<?"):
            clean_code = clean_code[2:].strip()
        if clean_code.endswith("?>"):
            clean_code = clean_code[:-2].strip()

        wrapper_parts.append(clean_code)
        wrapper_parts.append("?>")

        full_php_code = "\n".join(wrapper_parts)

        # 在沙箱中执行
        # 使用 php -r 直接执行代码
        import shlex
        escaped_code = full_php_code.replace("'", "'\"'\"'")
        command = f"php -r '{escaped_code}'"

        result = await self.sandbox_manager.execute_command(
            command=command,
            timeout=timeout,
        )

        # 格式化输出
        output_parts = ["🐘 PHP 测试结果\n"]

        if get_params:
            output_parts.append(f"模拟 GET 参数: {get_params}")
        if post_params:
            output_parts.append(f"模拟 POST 参数: {post_params}")

        output_parts.append(f"\n退出码: {result['exit_code']}")

        if result["stdout"]:
            stdout = result["stdout"][:3000]
            output_parts.append(f"\n输出:\n```\n{stdout}\n```")

        if result["stderr"]:
            stderr = result["stderr"][:1000]
            output_parts.append(f"\n错误:\n```\n{stderr}\n```")

        # 判断是否执行成功
        is_vulnerable = False
        evidence = None

        if result["exit_code"] == 0 and result["stdout"]:
            # 检查是否有命令执行输出
            stdout_lower = result["stdout"].lower()
            if get_params and "cmd" in get_params:
                cmd_value = get_params["cmd"].lower()
                # 检查常见命令输出
                if cmd_value in ["whoami", "id"]:
                    if "root" in stdout_lower or "uid=" in stdout_lower or "www-data" in stdout_lower:
                        is_vulnerable = True
                        evidence = f"命令 '{get_params['cmd']}' 执行成功，输出: {result['stdout'][:200]}"
                elif cmd_value.startswith("echo "):
                    expected = cmd_value[5:].lower()
                    if expected in stdout_lower:
                        is_vulnerable = True
                        evidence = f"Echo 命令执行成功"
                else:
                    # 通用检查：有输出就可能成功
                    if len(result["stdout"].strip()) > 0:
                        is_vulnerable = True
                        evidence = f"命令可能执行成功，输出: {result['stdout'][:200]}"

        if is_vulnerable:
            output_parts.append(f"\n🔴 **漏洞确认**: {evidence}")
        else:
            output_parts.append(f"\n🟡 未能确认漏洞执行（可能需要检查输出）")

        return ToolResult(
            success=True,
            data="\n".join(output_parts),
            metadata={
                "exit_code": result["exit_code"],
                "is_vulnerable": is_vulnerable,
                "evidence": evidence,
                "stdout": result["stdout"][:500] if result["stdout"] else None,
            }
        )


# ============ 命令注入专用测试工具 ============

class CommandInjectionTestInput(BaseModel):
    """命令注入测试输入"""
    target_file: str = Field(description="目标文件路径（如 'vuln.php'）")
    param_name: str = Field(default="cmd", description="注入参数名（默认 'cmd'）")
    test_command: str = Field(default="id", description="测试命令（默认 'id'）")
    language: str = Field(default="php", description="目标语言 (php, python, node)")


class CommandInjectionTestTool(AgentTool):
    """
    命令注入专用测试工具
    智能检测和验证命令注入漏洞
    """

    def __init__(self, sandbox_manager: Optional[SandboxManager] = None, project_root: str = "."):
        super().__init__()
        self.sandbox_manager = sandbox_manager or SandboxManager()
        self.project_root = project_root

    @property
    def name(self) -> str:
        return "test_command_injection"

    @property
    def description(self) -> str:
        return """专门用于测试命令注入漏洞的工具。

输入:
- target_file: 目标文件路径
- param_name: 注入参数名（默认 'cmd'）
- test_command: 测试命令（默认 'id'，也可用 'whoami', 'echo test'）
- language: 目标语言（php, python, node）

示例:
{"target_file": "ttt/t.php", "param_name": "cmd", "test_command": "whoami"}

自动执行:
1. 读取目标文件代码
2. 构建包含测试命令的执行环境
3. 在沙箱中执行并分析结果
4. 判断命令注入是否成功"""

    @property
    def args_schema(self):
        return CommandInjectionTestInput

    async def _execute(
        self,
        target_file: str,
        param_name: str = "cmd",
        test_command: str = "id",
        language: str = "php",
        **kwargs
    ) -> ToolResult:
        """执行命令注入测试"""
        try:
            await self.sandbox_manager.initialize()
        except Exception as e:
            logger.warning(f"Sandbox init failed: {e}")

        if not self.sandbox_manager.is_available:
            return ToolResult(
                success=False,
                error="沙箱环境不可用 (Docker Unavailable)",
            )

        import os
        full_path = os.path.join(self.project_root, target_file)

        if not os.path.exists(full_path):
            return ToolResult(
                success=False,
                error=f"文件不存在: {target_file}",
            )

        # 读取文件内容
        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
            code_content = f.read()

        output_parts = ["🎯 命令注入测试\n"]
        output_parts.append(f"目标文件: {target_file}")
        output_parts.append(f"注入参数: {param_name}")
        output_parts.append(f"测试命令: {test_command}")
        output_parts.append(f"语言: {language}")

        # 根据语言构建测试
        if language.lower() == "php":
            result = await self._test_php_injection(code_content, param_name, test_command)
        elif language.lower() == "python":
            result = await self._test_python_injection(code_content, param_name, test_command)
        else:
            return ToolResult(
                success=False,
                error=f"暂不支持语言: {language}",
            )

        output_parts.append(f"\n退出码: {result['exit_code']}")

        if result.get("stdout"):
            output_parts.append(f"\n命令输出:\n```\n{result['stdout'][:2000]}\n```")

        if result.get("stderr"):
            output_parts.append(f"\n错误输出:\n```\n{result['stderr'][:500]}\n```")

        # 分析结果
        is_vulnerable = False
        evidence = None
        poc = None

        if result["exit_code"] == 0 and result.get("stdout"):
            stdout = result["stdout"].strip()
            # 检查命令执行特征
            if test_command in ["id", "whoami"]:
                if "uid=" in stdout or "root" in stdout or "www-data" in stdout or stdout.strip():
                    is_vulnerable = True
                    evidence = f"命令 '{test_command}' 成功执行，输出: {stdout[:200]}"
                    poc = f"curl 'http://target/{target_file}?{param_name}={test_command}'"
            elif test_command.startswith("echo "):
                expected = test_command[5:]
                if expected in stdout:
                    is_vulnerable = True
                    evidence = f"Echo 测试成功"
                    poc = f"curl 'http://target/{target_file}?{param_name}=echo+test'"
            else:
                if len(stdout) > 0:
                    is_vulnerable = True
                    evidence = f"命令可能执行成功，输出: {stdout[:200]}"
                    poc = f"curl 'http://target/{target_file}?{param_name}={test_command}'"

        if is_vulnerable:
            output_parts.append(f"\n\n🔴 **漏洞已确认!**")
            output_parts.append(f"证据: {evidence}")
            output_parts.append(f"\nPoC: `{poc}`")
        else:
            output_parts.append(f"\n\n🟡 未能确认漏洞")
            if result.get("stderr"):
                output_parts.append(f"可能原因: 执行错误或参数未正确传递")

        return ToolResult(
            success=True,
            data="\n".join(output_parts),
            metadata={
                "is_vulnerable": is_vulnerable,
                "evidence": evidence,
                "poc": poc,
                "exit_code": result["exit_code"],
            }
        )

    async def _test_php_injection(self, code: str, param_name: str, test_command: str) -> Dict[str, Any]:
        """测试 PHP 命令注入"""
        # 构建模拟环境
        wrapper = f"""<?php
$_GET['{param_name}'] = '{test_command}';
$_POST['{param_name}'] = '{test_command}';
$_REQUEST['{param_name}'] = '{test_command}';
"""
        # 移除原代码的 PHP 标签
        clean_code = code.strip()
        if clean_code.startswith("<?php"):
            clean_code = clean_code[5:]
        elif clean_code.startswith("<?"):
            clean_code = clean_code[2:]
        if clean_code.endswith("?>"):
            clean_code = clean_code[:-2]

        full_code = wrapper + clean_code + "\n?>"

        # 转义并执行
        escaped_code = full_code.replace("'", "'\"'\"'")
        command = f"php -r '{escaped_code}'"

        return await self.sandbox_manager.execute_command(command, timeout=30)

    async def _test_python_injection(self, code: str, param_name: str, test_command: str) -> Dict[str, Any]:
        """测试 Python 命令注入"""
        # 模拟 request.args.get
        wrapper = f"""
import sys
class MockArgs:
    def get(self, key, default=None):
        if key == '{param_name}':
            return '{test_command}'
        return default

class MockRequest:
    args = MockArgs()
    form = MockArgs()

request = MockRequest()
sys.argv = ['script.py', '{test_command}']

"""
        full_code = wrapper + code

        escaped_code = full_code.replace("'", "'\"'\"'")
        command = f"python3 -c '{escaped_code}'"

        return await self.sandbox_manager.execute_command(command, timeout=30)