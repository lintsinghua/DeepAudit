"""
文件操作工具
读取，搜索和写入代码文件
"""

import os
import re
import fnmatch
import asyncio
from typing import Optional, List, Dict, Any, Type
from pydantic import BaseModel, Field
import logging
logger = logging.getLogger(__name__)
from .base import AgentTool, ToolResult


class FileReadInput(BaseModel):
    """文件读取输入"""
    file_path: str = Field(description="文件路径（相对于项目根目录）")
    start_line: Optional[int] = Field(default=None, description="起始行号（从1开始）")
    end_line: Optional[int] = Field(default=None, description="结束行号")
    max_lines: int = Field(default=500, description="最大返回行数")


class FileReadTool(AgentTool):
    """
    文件读取工具
    读取项目中的文件内容
    """
    
    def __init__(
        self, 
        project_root: str,
        exclude_patterns: Optional[List[str]] = None,
        target_files: Optional[List[str]] = None,
    ):
        """
        初始化文件读取工具
        
        Args:
            project_root: 项目根目录
            exclude_patterns: 排除模式列表
            target_files: 目标文件列表（如果指定，只允许读取这些文件）
        """
        super().__init__()
        self.project_root = project_root
        self.exclude_patterns = exclude_patterns or []
        self.target_files = set(target_files) if target_files else None

    @staticmethod
    def _read_file_lines_sync(file_path: str, start_idx: int, end_idx: int) -> tuple:
        """同步读取文件指定行范围（用于 asyncio.to_thread）"""
        selected_lines = []
        total_lines = 0
        file_size = os.path.getsize(file_path)

        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= start_idx and i < end_idx:
                    selected_lines.append(line)
                elif i >= end_idx:
                    if i < end_idx + 1000:
                        continue
                    else:
                        remaining_bytes = file_size - f.tell()
                        avg_line_size = f.tell() / (i + 1)
                        estimated_remaining_lines = int(remaining_bytes / avg_line_size) if avg_line_size > 0 else 0
                        total_lines = i + 1 + estimated_remaining_lines
                        break

        return selected_lines, total_lines

    @staticmethod
    def _read_all_lines_sync(file_path: str) -> List[str]:
        """同步读取文件所有行（用于 asyncio.to_thread）"""
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.readlines()

    @property
    def name(self) -> str:
        return "read_file"
    
    @property
    def description(self) -> str:
        return """读取项目中的文件内容。

使用场景:
- 查看完整的源代码文件
- 查看特定行范围的代码
- 获取配置文件内容

输入:
- file_path: 文件路径（相对于项目根目录）
- start_line: 可选，起始行号
- end_line: 可选，结束行号
- max_lines: 最大返回行数（默认500）

注意: 为避免输出过长，建议指定行范围或使用 RAG 搜索定位代码。"""
    
    @property
    def args_schema(self):
        return FileReadInput
    
    def _should_exclude(self, file_path: str) -> bool:
        """检查文件是否应该被排除"""
        # 如果指定了目标文件，只允许读取这些文件
        if self.target_files and file_path not in self.target_files:
            return True
        
        # 检查排除模式
        for pattern in self.exclude_patterns:
            if fnmatch.fnmatch(file_path, pattern):
                return True
            # 也检查文件名
            if fnmatch.fnmatch(os.path.basename(file_path), pattern):
                return True
        
        return False
    
    async def _execute(
        self,
        file_path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        max_lines: int = 500,
        **kwargs
    ) -> ToolResult:
        """执行文件读取"""
        try: 
            # 检查是否被排除
            if self._should_exclude(file_path):
                return ToolResult(
                    success=False,
                    error=f"文件被排除或不在目标文件列表中: {file_path}",
                )
            
            # 安全检查：防止路径遍历
            # Security Fix: 使用 realpath 解析软链接，防止绕过项目根目录检查
            full_path = os.path.realpath(os.path.join(self.project_root, file_path))
            if not full_path.startswith(os.path.realpath(self.project_root)):
                return ToolResult(
                    success=False,
                    error="安全错误：不允许访问项目目录外的文件",
                )
            
            if not os.path.exists(full_path):
                return ToolResult(
                    success=False,
                    error=f"文件不存在: {file_path}",
                )
            
            if not os.path.isfile(full_path):
                return ToolResult(
                    success=False,
                    error=f"不是文件: {file_path}",
                )
            
            # 检查文件大小
            file_size = os.path.getsize(full_path)
            is_large_file = file_size > 1024 * 1024  # 1MB
            
            # 🔥 修复：如果指定了行范围，允许读取大文件的部分内容
            if is_large_file and start_line is None and end_line is None:
                return ToolResult(
                    success=False,
                    error=f"文件过大 ({file_size / 1024:.1f}KB)，请指定 start_line 和 end_line 读取部分内容",
                )
            
            # 🔥 对于大文件，使用流式读取指定行范围
            if is_large_file and (start_line is not None or end_line is not None):
                # 计算实际的起始和结束行
                start_idx = max(0, (start_line or 1) - 1)
                end_idx = end_line if end_line else start_idx + max_lines

                # 异步读取文件，避免阻塞事件循环
                selected_lines, total_lines = await asyncio.to_thread(
                    self._read_file_lines_sync, full_path, start_idx, end_idx
                )

                # 更新实际的结束索引
                end_idx = min(end_idx, start_idx + len(selected_lines))
            else:
                # 异步读取小文件，避免阻塞事件循环
                lines = await asyncio.to_thread(self._read_all_lines_sync, full_path)

                total_lines = len(lines)

                # 处理行范围
                if start_line is not None:
                    start_idx = max(0, start_line - 1)
                else:
                    start_idx = 0

                if end_line is not None:
                    end_idx = min(total_lines, end_line)
                else:
                    end_idx = min(total_lines, start_idx + max_lines)

                # 截取指定行
                selected_lines = lines[start_idx:end_idx]
            
            # 添加行号
            numbered_lines = []
            for i, line in enumerate(selected_lines, start=start_idx + 1):
                numbered_lines.append(f"{i:4d}| {line.rstrip()}")
            
            content = '\n'.join(numbered_lines)
            
            # 检测语言
            ext = os.path.splitext(file_path)[1].lower()
            language = {
                ".py": "python", ".js": "javascript", ".ts": "typescript",
                ".java": "java", ".go": "go", ".rs": "rust",
                ".cpp": "cpp", ".c": "c", ".cs": "csharp",
                ".php": "php", ".rb": "ruby", ".swift": "swift",
            }.get(ext, "text")
            
            output = f"📄 文件: {file_path}\n"
            output += f"行数: {start_idx + 1}-{end_idx} / {total_lines}\n\n"
            output += f"```{language}\n{content}\n```"
            
            if end_idx < total_lines:
                output += f"\n\n... 还有 {total_lines - end_idx} 行未显示"
            
            return ToolResult(
                success=True,
                data=output,
                metadata={
                    "file_path": file_path,
                    "total_lines": total_lines,
                    "start_line": start_idx + 1,
                    "end_line": end_idx,
                    "language": language,
                }
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"读取文件失败: {str(e)}",
            )


class FileSearchInput(BaseModel):
    """文件搜索输入"""
    keyword: str = Field(description="搜索关键字或正则表达式")
    file_pattern: Optional[str] = Field(default=None, description="文件名模式，如 *.py, *.js")
    directory: Optional[str] = Field(default=None, description="搜索目录（相对路径）")
    case_sensitive: bool = Field(default=False, description="是否区分大小写")
    max_results: int = Field(default=50, description="最大结果数")
    is_regex: bool = Field(default=False, description="是否使用正则表达式")


class FileSearchTool(AgentTool):
    """
    文件搜索工具
    在项目中搜索包含特定内容的代码
    """
    
    # 排除的目录
    DEFAULT_EXCLUDE_DIRS = {
        "node_modules", "vendor", "dist", "build", ".git",
        "__pycache__", ".pytest_cache", "coverage", ".nyc_output",
        ".vscode", ".idea", ".vs", "target", "venv", "env",
    }
    
    def __init__(
        self, 
        project_root: str,
        exclude_patterns: Optional[List[str]] = None,
        target_files: Optional[List[str]] = None,
    ):
        super().__init__()
        self.project_root = project_root
        self.exclude_patterns = exclude_patterns or []
        self.target_files = set(target_files) if target_files else None

        # 从 exclude_patterns 中提取目录排除
        self.exclude_dirs = set(self.DEFAULT_EXCLUDE_DIRS)
        for pattern in self.exclude_patterns:
            if pattern.endswith("/**"):
                self.exclude_dirs.add(pattern[:-3])
            elif "/" not in pattern and "*" not in pattern:
                self.exclude_dirs.add(pattern)

    @staticmethod
    def _read_file_lines_sync(file_path: str) -> List[str]:
        """同步读取文件所有行（用于 asyncio.to_thread）"""
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.readlines()

    @property
    def name(self) -> str:
        return "search_code"
    
    @property
    def description(self) -> str:
        return """在项目代码中搜索关键字或模式。

使用场景:
- 查找特定函数的所有调用位置
- 搜索特定的 API 使用
- 查找包含特定模式的代码

输入:
- keyword: 搜索关键字或正则表达式
- file_pattern: 可选，文件名模式（如 *.py）
- directory: 可选，搜索目录
- case_sensitive: 是否区分大小写
- is_regex: 是否使用正则表达式

这是一个快速搜索工具，结果包含匹配行和上下文。"""
    
    @property
    def args_schema(self):
        return FileSearchInput
    
    async def _execute(
        self,
        keyword: str,
        file_pattern: Optional[str] = None,
        directory: Optional[str] = None,
        case_sensitive: bool = False,
        max_results: int = 50,
        is_regex: bool = False,
        **kwargs
    ) -> ToolResult:
        """执行文件搜索"""
        try:

            # 🔥 新增兜底逻辑：如果未指定目录或指定了根目录，强制改为 'src'
            if not directory or directory in [".", "./", "/", ""]:
                directory = "src"

            # 确定搜索目录
            if directory:
                # Security Fix: 使用 realpath 解析软链接，防止绕过项目根目录检查
                search_dir = os.path.realpath(os.path.join(self.project_root, directory))
                if not search_dir.startswith(os.path.realpath(self.project_root)):
                    return ToolResult(
                        success=False,
                        error="安全错误：不允许搜索项目目录外的内容",
                    )
            else:
                search_dir = self.project_root
            
            # 编译搜索模式
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                if is_regex:
                    pattern = re.compile(keyword, flags)
                else:
                    pattern = re.compile(re.escape(keyword), flags)
            except re.error as e:
                return ToolResult(
                    success=False,
                    error=f"无效的搜索模式: {e}",
                )
            
            results = []
            files_searched = 0
            
            # 遍历文件
            for root, dirs, files in os.walk(search_dir):
                # 排除目录
                dirs[:] = [d for d in dirs if d not in self.exclude_dirs]
                
                for filename in files:
                    # 检查文件模式
                    if file_pattern and not fnmatch.fnmatch(filename, file_pattern):
                        continue
                    
                    file_path = os.path.join(root, filename)
                    relative_path = os.path.relpath(file_path, self.project_root)
                    
                    # 检查是否在目标文件列表中
                    if self.target_files and relative_path not in self.target_files:
                        continue
                    
                    # 检查排除模式
                    should_skip = False
                    for excl_pattern in self.exclude_patterns:
                        if fnmatch.fnmatch(relative_path, excl_pattern) or fnmatch.fnmatch(filename, excl_pattern):
                            should_skip = True
                            break
                    if should_skip:
                        continue
                    
                    try:
                        # 异步读取文件，避免阻塞事件循环
                        lines = await asyncio.to_thread(
                            self._read_file_lines_sync, file_path
                        )

                        files_searched += 1

                        for i, line in enumerate(lines):
                            if pattern.search(line):
                                # 获取上下文
                                start = max(0, i - 1)
                                end = min(len(lines), i + 2)
                                context_lines = []
                                for j in range(start, end):
                                    prefix = ">" if j == i else " "
                                    context_lines.append(f"{prefix} {j+1:4d}| {lines[j].rstrip()}")
                                
                                results.append({
                                    "file": relative_path,
                                    "line": i + 1,
                                    "match": line.strip()[:200],
                                    "context": '\n'.join(context_lines),
                                })
                                
                                if len(results) >= max_results:
                                    break
                        
                        if len(results) >= max_results:
                            break
                            
                    except Exception:
                        continue
                
                if len(results) >= max_results:
                    break
            
            if not results:
                return ToolResult(
                    success=True,
                    data=f"没有找到匹配 '{keyword}' 的内容\n搜索了 {files_searched} 个文件",
                    metadata={"files_searched": files_searched, "matches": 0}
                )
            
            # 格式化输出
            output_parts = [f"🔍 搜索结果: '{keyword}'\n"]
            output_parts.append(f"找到 {len(results)} 处匹配（搜索了 {files_searched} 个文件）\n")
            
            for result in results:
                output_parts.append(f"\n📄 {result['file']}:{result['line']}")
                output_parts.append(f"```\n{result['context']}\n```")
            
            if len(results) >= max_results:
                output_parts.append(f"\n... 结果已截断（最大 {max_results} 条）")
            
            return ToolResult(
                success=True,
                data="\n".join(output_parts),
                metadata={
                    "keyword": keyword,
                    "files_searched": files_searched,
                    "matches": len(results),
                    "results": results[:10],  # 只在元数据中保留前10个
                }
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"搜索失败: {str(e)}",
            )


class ListFilesInput(BaseModel):
    """列出文件输入"""
    directory: str = Field(default=".", description="目录路径（相对于项目根目录）")
    pattern: Optional[str] = Field(default=None, description="文件名模式，如 *.py")
    recursive: bool = Field(default=False, description="是否递归列出子目录")
    max_files: int = Field(default=100, description="最大文件数")


class ListFilesTool(AgentTool):
    """
    列出文件工具
    列出目录中的文件
    """
    
    DEFAULT_EXCLUDE_DIRS = {
        "node_modules", "vendor", "dist", "build", ".git",
        "__pycache__", ".pytest_cache", "coverage",
    }
    
    def __init__(
        self, 
        project_root: str,
        exclude_patterns: Optional[List[str]] = None,
        target_files: Optional[List[str]] = None,
    ):
        super().__init__()
        self.project_root = project_root
        self.exclude_patterns = exclude_patterns or []
        self.target_files = set(target_files) if target_files else None
        
        # 从 exclude_patterns 中提取目录排除
        self.exclude_dirs = set(self.DEFAULT_EXCLUDE_DIRS)
        for pattern in self.exclude_patterns:
            # 如果是目录模式（如 node_modules/**），提取目录名
            if pattern.endswith("/**"):
                self.exclude_dirs.add(pattern[:-3])
            elif "/" not in pattern and "*" not in pattern:
                self.exclude_dirs.add(pattern)
    
    @property
    def name(self) -> str:
        return "list_files"
    
    @property
    def description(self) -> str:
        return """列出目录中的文件。

使用场景:
- 了解项目结构
- 查找特定类型的文件
- 浏览目录内容

输入:
- directory: 目录路径
- pattern: 可选，文件名模式
- recursive: 是否递归
- max_files: 最大文件数"""
    
    @property
    def args_schema(self):
        return ListFilesInput
    
    async def _execute(
        self,
        directory: str = ".",
        pattern: Optional[str] = None,
        recursive: bool = False,
        max_files: int = 100,
        **kwargs
    ) -> ToolResult:
        """执行文件列表"""
        try:
            # 🔥 兼容性处理：支持 path 参数作为 directory 的别名
            if "path" in kwargs and kwargs["path"]:
                directory = kwargs["path"]

            # 🔥 强制拦截：如果 LLM 传入了根目录，强转为 src
            if directory in [".", "./", "/", ""]:
                directory = "src"

            target_dir = os.path.normpath(os.path.join(self.project_root, directory))
            if not target_dir.startswith(os.path.normpath(self.project_root)):
                return ToolResult(
                    success=False,
                    error="安全错误：不允许访问项目目录外的目录",
                )
            
            if not os.path.exists(target_dir):
                return ToolResult(
                    success=False,
                    error=f"目录不存在: {directory}",
                )
            
            files = []
            dirs = []
            
            if recursive:
                for root, dirnames, filenames in os.walk(target_dir):
                    # 排除目录
                    dirnames[:] = [d for d in dirnames if d not in self.exclude_dirs]
                    
                    for filename in filenames:
                        if pattern and not fnmatch.fnmatch(filename, pattern):
                            continue
                        
                        full_path = os.path.join(root, filename)
                        relative_path = os.path.relpath(full_path, self.project_root)
                        
                        # 检查是否在目标文件列表中
                        if self.target_files and relative_path not in self.target_files:
                            continue
                        
                        # 检查排除模式
                        should_skip = False
                        for excl_pattern in self.exclude_patterns:
                            if fnmatch.fnmatch(relative_path, excl_pattern) or fnmatch.fnmatch(filename, excl_pattern):
                                should_skip = True
                                break
                        if should_skip:
                            continue
                        
                        files.append(relative_path)
                        
                        if len(files) >= max_files:
                            break
                    
                    if len(files) >= max_files:
                        break
            else:
                # 🔥 如果设置了 target_files，只显示目标文件和包含目标文件的目录
                if self.target_files:
                    # 计算哪些目录包含目标文件
                    dirs_with_targets = set()
                    for tf in self.target_files:
                        # 获取目标文件的目录部分
                        tf_dir = os.path.dirname(tf)
                        while tf_dir:
                            dirs_with_targets.add(tf_dir)
                            tf_dir = os.path.dirname(tf_dir)
                    
                    for item in os.listdir(target_dir):
                        if item in self.exclude_dirs:
                            continue
                        
                        full_path = os.path.join(target_dir, item)
                        relative_path = os.path.relpath(full_path, self.project_root)
                        
                        if os.path.isdir(full_path):
                            # 只显示包含目标文件的目录
                            if relative_path in dirs_with_targets or any(
                                tf.startswith(relative_path + "/") for tf in self.target_files
                            ):
                                dirs.append(relative_path + "/")
                        else:
                            if pattern and not fnmatch.fnmatch(item, pattern):
                                continue
                            
                            # 检查是否在目标文件列表中
                            if relative_path not in self.target_files:
                                continue
                            
                            files.append(relative_path)
                            
                            if len(files) >= max_files:
                                break
                else:
                    # 没有设置 target_files，正常列出
                    for item in os.listdir(target_dir):
                        if item in self.exclude_dirs:
                            continue
                        
                        full_path = os.path.join(target_dir, item)
                        relative_path = os.path.relpath(full_path, self.project_root)
                        
                        if os.path.isdir(full_path):
                            dirs.append(relative_path + "/")
                        else:
                            if pattern and not fnmatch.fnmatch(item, pattern):
                                continue
                            
                            # 检查排除模式
                            should_skip = False
                            for excl_pattern in self.exclude_patterns:
                                if fnmatch.fnmatch(relative_path, excl_pattern) or fnmatch.fnmatch(item, excl_pattern):
                                    should_skip = True
                                    break
                            if should_skip:
                                continue
                            
                            files.append(relative_path)
                            
                            if len(files) >= max_files:
                                break
            
            # 格式化输出
            output_parts = [f"📁 目录: {directory}\n"]
            
            # 🔥 如果设置了 target_files，显示提示信息
            if self.target_files:
                output_parts.append(f"⚠️ 注意: 审计范围限定为 {len(self.target_files)} 个指定文件\n")
            
            if dirs:
                output_parts.append("目录:")
                for d in sorted(dirs)[:20]:
                    output_parts.append(f"  📂 {d}")
                if len(dirs) > 20:
                    output_parts.append(f"  ... 还有 {len(dirs) - 20} 个目录")
            
            if files:
                output_parts.append(f"\n文件 ({len(files)}):")
                for f in sorted(files):
                    output_parts.append(f"  📄 {f}")
            elif self.target_files:
                # 如果没有文件但设置了 target_files，显示目标文件列表
                output_parts.append(f"\n指定的目标文件 ({len(self.target_files)}):")
                for f in sorted(self.target_files)[:20]:
                    output_parts.append(f"  📄 {f}")
                if len(self.target_files) > 20:
                    output_parts.append(f"  ... 还有 {len(self.target_files) - 20} 个文件")
            
            if len(files) >= max_files:
                output_parts.append(f"\n... 结果已截断（最大 {max_files} 个文件）")
            
            return ToolResult(
                success=True,
                data="\n".join(output_parts),
                metadata={
                    "directory": directory,
                    "file_count": len(files),
                    "dir_count": len(dirs),
                }
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"列出文件失败: {str(e)}",
            )


class FileWriteInput(BaseModel):
    """文件写入工具输入参数"""
    file_path: str = Field(..., description="要写入的文件相对路径，如 'test/RealExploit.t.sol'")
    content: str = Field(..., description="要写入的文件完整内容（代码或文本）")


class FileWriteTool(AgentTool):
    """
    文件写入工具
    
    用于将 Agent 生成的 PoC 代码、利用脚本或配置文件安全地写入到工作区。
    如果文件已存在，它将被覆盖；如果上级目录不存在，将自动创建。
    """
    
    def __init__(self, project_root: str):
        super().__init__()
        # 记录并规范化项目的根目录，用于后续的安全沙箱校验
        self.project_root = os.path.abspath(project_root)
    
    @property
    def name(self) -> str:
        return "write_file"
    
    @property
    def description(self) -> str:
        return """将完整的文本或代码内容写入到指定文件中。

使用场景：
- 编写并保存 Foundry/Hardhat 测试用例 (PoC)
- 创建或修改合约配置文件
- 写入恶意的输入载荷 (Payload) 文件

输入：
- file_path: 要写入的文件相对路径，如 'test/RealExploit.t.sol'
- content: 要写入的文件完整内容（代码或文本）

注意：
1. 文件路径必须是相对路径。
2. 如果文件已存在，原内容将被完全覆盖。
3. 不需要手动创建目录，工具会自动处理。"""
    
    @property
    def args_schema(self) -> Type[BaseModel]:
        return FileWriteInput
    
    async def _execute(
        self,
        file_path: str,
        content: str,
        **kwargs
    ) -> ToolResult:
        """执行文件写入"""
        try:
            # 1. 路径清洗与安全检查 (防止大模型尝试写入 /etc/passwd 等系统文件)
            # 移除前导的斜杠，强制变为相对路径
            clean_path = file_path.lstrip('/')
            full_path = os.path.abspath(os.path.join(self.project_root, clean_path))
            
            # 防路径遍历 (Path Traversal) 检查
            if not full_path.startswith(self.project_root):
                logger.warning(f"[FileWriteTool] 检测到越权写入尝试: {file_path}")
                return ToolResult(
                    success=False,
                    error=f"安全限制：禁止向项目根目录之外的路径写入文件 ({file_path})"
                )
            
            # 2. 自动创建所需的父级目录
            target_dir = os.path.dirname(full_path)
            if target_dir:
                os.makedirs(target_dir, exist_ok=True)
            
            # 3. 执行写入操作
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
                
            logger.info(f"[FileWriteTool] 成功写入文件: {clean_path} ({len(content)} bytes)")
            
            # 4. 封装标准化返回结果
            return ToolResult(
                success=True,
                data=f"✅ 成功将 {len(content)} 个字符的内容写入到文件: {clean_path}",
                metadata={
                    "file_path": clean_path,
                    "content_length": len(content),
                    "action": "write"
                }
            )
            
        except Exception as e:
            logger.error(f"[FileWriteTool] 文件写入异常: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=f"文件写入失败: {str(e)}",
            )