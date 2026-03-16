import asyncio
import os
import sys
import logging
import subprocess
import shutil
from typing import Any
import dotenv

# 将 backend 目录加入模块搜索路径，保证无论从哪里运行都能正确导入
_backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# 加载 backend/.env 中的环境变量（包含 LLM_API_KEY 等）
dotenv.load_dotenv(os.path.join(_backend_dir, ".env"))

# 日志配置：默认 WARNING，测试主逻辑使用 INFO
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("E2E_Test")
logger.setLevel(logging.INFO)

# ── 导入智能合约专用 Agent（smart_contract_* 版本）──────────────────────
from app.services.agent.agents.smart_contract_orchestrator import OrchestratorAgent
from app.services.agent.agents.smart_contract_recon import ReconAgent
from app.services.agent.agents.smart_contract_analysis import AnalysisAgent
from app.services.agent.agents.smart_contract_verification import VerificationAgent

# ── 工具 ──────────────────────────────────────────────────────────────
from app.services.agent.tools.file_tool import FileReadTool, ListFilesTool, FileSearchTool, FileWriteTool
from app.services.agent.knowledge import SecurityKnowledgeQueryTool,GetVulnerabilityKnowledgeTool
from app.services.agent.tools.foundry_tools import FoundryTestTool, FoundryCastTool
from app.services.agent.tools.thinking_tool import ThinkTool, ReflectTool
from app.services.agent.tools.sandbox_tool import SandboxManager, SandboxConfig

# ── LLM 服务 ──────────────────────────────────────────────────────────
from app.services.llm import LLMService


# ==========================================
# 1. 模拟前端流式事件输出
# ==========================================
class ConsoleEventEmitter:
    """将 Agent 事件实时打印到终端，方便调试 LLM 思考过程。"""

    # 每类事件的展示前缀和颜色码（ANSI）
    _PREFIX = {
        "llm_start":       ("🔵", ""),
        "llm_thought":     ("💭", "\033[36m"),       # 青色
        "thinking_start":  ("🤔", "\033[35m"),       # 紫色
        "thinking_token":  ("   ", "\033[35m"),      # 紫色，无换行累积显示
        "thinking_end":    ("✅", "\033[35m"),       # 紫色
        "llm_decision":    ("🎯", "\033[33m"),       # 黄色
        "llm_action":      ("⚡", "\033[33m"),       # 黄色
        "llm_observation": ("👁️ ", "\033[32m"),      # 绿色
        "llm_complete":    ("✔️ ", ""),
        "tool_call":       ("🔧", "\033[33m"),
        "tool_result":     ("📦", "\033[32m"),
        "tool_error":      ("💥", "\033[31m"),       # 红色
        "agent_start":     ("🚀", ""),
        "agent_complete":  ("🏁", ""),
        "finding":         ("🚨", "\033[31m"),
        "error":           ("❌", "\033[31m"),
        "warning":         ("⚠️ ", "\033[33m"),
    }
    _RESET = "\033[0m"

    # thinking_token 是流式 token，单独用行内刷新
    _last_thinking_line = False

    async def emit_info(self, message: str):
        print(f"\nℹ️  [系统] {message}")

    async def emit_warning(self, message: str):
        print(f"\n⚠️  [警告] {message}")

    async def emit_error(self, message: str):
        print(f"\n❌ [错误] {message}")

    async def emit(self, event_data: Any):
        event_type = getattr(event_data, "event_type", "UNKNOWN")
        msg        = getattr(event_data, "message", "") or ""
        metadata   = getattr(event_data, "metadata", {}) or {}

        icon, color = self._PREFIX.get(event_type, ("📢", ""))
        reset = self._RESET if color else ""

        # ── 特殊处理：流式 thinking_token（只显示进度点，不打印内容）──
        if event_type == "thinking_token":
            # 用 . 表示推理进行中，避免重复打印流式内容
            print(".", end="", flush=True)
            self._last_thinking_line = True
            return

        # 如果上一行是 thinking_token，先换行
        if self._last_thinking_line:
            print()
            self._last_thinking_line = False

        # ── llm_thought：打印完整思考内容（来自 metadata["thought"]）──
        if event_type == "llm_thought":
            full_thought = metadata.get("thought", msg)
            iteration    = metadata.get("iteration", "?")
            agent_name   = metadata.get("agent_name", "Agent")
            # 每行加缩进，方便阅读
            indented = "\n".join(f"  {line}" for line in full_thought.splitlines())
            print(f"\n{color}{icon} [{agent_name}] 第{iteration}轮思考:{reset}\n{color}{indented}{reset}")
            return

        # ── thinking_end：打印完整推理内容 ──
        if event_type == "thinking_end":
            full = metadata.get("accumulated", msg)
            if full:
                indented = "\n".join(f"  {line}" for line in full.splitlines())
                print(f"\n{color}{icon} [推理完毕]:{reset}\n{color}{indented}{reset}")
            return

        # ── llm_action：展示工具调用意图 ──
        if event_type == "llm_action":
            action = metadata.get("action", "")
            action_input = metadata.get("action_input", {})
            print(f"\n{color}{icon} [决策] 调用 `{action}` 参数: {str(action_input)[:300]}{reset}")
            return

        # ── llm_observation：展示工具返回结果 ──
        if event_type == "llm_observation":
            obs = metadata.get("observation", msg)
            preview = obs[:600] + ("..." if len(obs) > 600 else "")
            print(f"\n{color}{icon} [观察结果]:\n{preview}{reset}")
            return

        # ── 通用事件：截断 message 打印 ──
        print(f"\n{color}{icon} [{event_type.upper()}] {msg[:500]}{reset}")


# ==========================================
# 2. 宿主机环境预置 (State Pre-provisioning)
# ==========================================
def setup_vulnerable_project(workspace_dir: str):
    """
    在宿主机创建一个包含 forge-std 依赖的完整 Foundry 项目。
    如果依赖（lib/forge-std）已存在，则跳过 forge init，只更新靶机合约。
    """
    lib_dir = os.path.join(workspace_dir, "lib", "forge-std")
    deps_exist = os.path.isdir(lib_dir)

    if deps_exist:
        print(f"⚡ 检测到依赖已存在，跳过 forge init，直接更新靶机合约...")
    else:
        print("⏳ 正在宿主机初始化真实 Foundry 靶场环境（首次运行，需拉取依赖）...")
        if os.path.exists(workspace_dir):
            shutil.rmtree(workspace_dir)

        # 1️⃣ 使用宿主机的 forge 创建基础项目 (使用 --force 覆盖空目录)
        # ⚠️ 注意：已移除最新版不支持的 --no-commit 参数
        init_cmd = f"forge init {workspace_dir} --force"
        try:
            subprocess.run(init_cmd, shell=True, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            print(f"❌ 初始化 Foundry 项目失败，请检查本机是否安装了 forge: {e.stderr}")
            raise

        # 2️⃣ 清理默认生成的无关合约
        for file in ["src/Counter.sol", "test/Counter.t.sol", "script/Counter.s.sol"]:
            path = os.path.join(workspace_dir, file)
            if os.path.exists(path):
                os.remove(path)

    # 3️⃣ 写入包含重入漏洞的真实靶机合约 (Violates CEI pattern)
    vulnerable_contract = """//SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract Vault {
    mapping(address => uint256) public balances;
    
    function deposit() public payable { 
        balances[msg.sender] += msg.value; 
    }
    
    function withdraw(uint256 amount) public {
        require(balances[msg.sender] >= amount, "Insufficient balance");
        
        // ⚠️ Vulnerability: External call before state update
        (bool success, ) = msg.sender.call{value: amount}("");
        require(success, "Transfer failed");
        
        // 使用 unchecked 绕过 0.8+ 的下溢出检查，让重入攻击能够成功结算
        unchecked {
            balances[msg.sender] -= amount;
        }
    }
    
    // 建议加一个 receive 函数，方便你在 setUp() 中直接给靶机塞 TVL (vm.deal)
    receive() external payable {}
}
"""
    with open(os.path.join(workspace_dir, "src/Vault.sol"), "w") as f:
        f.write(vulnerable_contract)
        
    print(f"🎯 靶机环境搭建完毕: {workspace_dir}")


# ==========================================
# 3. 最终报告生成器 (适配新版 Orchestrator 数据结构)
# ==========================================
def generate_markdown_report(findings: list, output_file: str):
    """生成最终的 Markdown 格式安全审计战报"""
    md = "# DeepAudit 智能合约安全审计战报\n\n"
    md += "---\n\n"
    
    if not findings:
        md += "🎉 **恭喜，本次审计未发现任何安全漏洞！**\n"
    else:
        # 统计数据
        confirmed_count = len([f for f in findings if f.get("is_verified") or f.get("verdict") == "confirmed"])
        total_profit = sum([f.get("profit_extracted", 0) for f in findings if isinstance(f.get("profit_extracted"), (int, float))])
        
        md += f"## 📊 审计总览\n"
        md += f"- **跟踪漏洞总数**: {len(findings)} 个\n"
        md += f"- **已确认真实漏洞**: {confirmed_count} 个 (通过沙箱动态验证)\n"
        md += f"- **累计沙箱获利**: {total_profit} ETH\n\n"
        md += "---\n\n"

        for i, f in enumerate(findings, 1):
            sev = str(f.get('severity', 'Unknown')).upper()
            title = f.get('title', '未命名漏洞')
            is_confirmed = f.get('is_verified') or f.get('verdict') == "confirmed"
            
            # 标题与基本状态
            status_icon = "🔴 [沙箱已利用]" if is_confirmed else "🟡 [静态疑似]"
            md += f"## {i}. {status_icon} [{sev}] {title}\n\n"
            
            # 基础信息表格
            md += "| 属性 | 详情 |\n"
            md += "|---|---|\n"
            md += f"| **漏洞类型** | `{f.get('vulnerability_type', 'N/A')}` |\n"
            md += f"| **漏洞位置** | `{f.get('file_path', 'N/A')}` (Line: {f.get('line_start', 'N/A')}) |\n"
            if f.get('target_function_signature'):
                md += f"| **目标函数** | `{f.get('target_function_signature')}` |\n"
            if f.get('profit_extracted'):
                md += f"| **榨取利润** | **{f.get('profit_extracted')} ETH** 💰 |\n"
            md += "\n"

            # 详细描述与理论分析 (来自 Analysis Agent)
            if f.get('description'):
                md += f"### 📝 漏洞描述\n{f.get('description')}\n\n"
                
            if f.get('source') or f.get('sink'):
                md += f"### 🔍 污点分析\n"
                md += f"- **Source (污染源)**: `{f.get('source', 'N/A')}`\n"
                md += f"- **Sink (执行点)**: `{f.get('sink', 'N/A')}`\n\n"

            if f.get('attack_strategy'):
                md += f"### ⚔️ 攻击策略\n{f.get('attack_strategy')}\n\n"

            # 目标合约切片
            if f.get('code_snippet'):
                md += f"### 🎯 脆弱代码片段\n```solidity\n{f.get('code_snippet')}\n```\n\n"

            # PoC 利用代码 (来自 Verification Agent)
            # 注意：适配新版 _normalize_finding 展平后的字段 poc_payload
            poc_code = f.get('poc_payload') or (f.get('poc', {})).get('payload') 
            if poc_code:
                poc_path = f.get('poc_file_path', 'test/Exploit.t.sol')
                md += f"### 💣 Foundry PoC 验证脚本 (`{poc_path}`)\n"
                md += f"```solidity\n{poc_code}\n```\n\n"
            elif is_confirmed:
                 md += f"### 💣 验证信息\n> 该漏洞已通过动态验证，但未提取到完整的 PoC 源码。\n\n"
            
            # 修复建议
            if f.get('suggestion') or f.get('recommendation'):
                md += f"### 🛡️ 修复建议\n{f.get('suggestion') or f.get('recommendation')}\n\n"

            md += "---\n\n"
            
    with open(output_file, "w", encoding="utf-8") as f: 
        f.write(md)
    
    logger.info(f"Markdown 审计报告已生成: {output_file}")


# ==========================================
# 4. 主系统流程与调度
# ==========================================
async def main():
    # 定义测试工作区绝对路径
    workspace = os.path.abspath("./test_workspace")
    
    # 1. 筑基：宿主机建项目拉依赖
    setup_vulnerable_project(workspace)
    
    emitter = ConsoleEventEmitter()
    llm_service = LLMService() 
    
    # 2. 基础文件工具：直接操作宿主机工作区
    base_tools = {
        "read_file": FileReadTool(project_root=workspace),
        "list_files": ListFilesTool(project_root=workspace),
        "search_code": FileSearchTool(project_root=workspace),
        "think": ThinkTool(),
        "reflect": ReflectTool()
    }
    
    # 3. 🔥 核心：配置 Docker Sandbox，全量挂载预置好的目录
    print("\n🐳 正在连接 Docker 沙箱引擎...")
    sandbox_config = SandboxConfig(
        workspace_dir=workspace,            # 👈 Docker 内部的 /workspace 就会直接映射为本机的 ./test_workspace
        image="deepaudit/sandbox:latest",   # 👈 你的专属 Web3 安全沙箱镜像
        network_mode="bridge",
        # Mac 环境下解决 Docker 写入挂载目录权限问题的终极杀招 (视情况解开注释)
        # user="root" 
    )
    sandbox_manager = SandboxManager(config=sandbox_config)
    await sandbox_manager.initialize()
    
    # 4. 组装Agent 的黑客工具箱
    recon_tools = {
        **base_tools,
        # 🔥 新增: 链上信息获取工具，用于下载合约源码/ABI
        "foundry_cast": FoundryCastTool(sandbox_manager),
    }
    analysis_tools = {
        **base_tools,
        # 安全知识查询 (防幻觉利器)
        "query_security_knowledge": SecurityKnowledgeQueryTool(),
        "get_vulnerability_knowledge": GetVulnerabilityKnowledgeTool(),
    }
    verify_tools = {
        **base_tools,
        "write_file": FileWriteTool(project_root=workspace),
        "foundry_test": FoundryTestTool(
            sandbox_manager=sandbox_manager, 
            project_root="/workspace" # 在 Docker 内部的视角，工作区就是根目录的 /workspace
        ) 
    }
    
    # 5. 实例化四大天王 Agent
    recon_agent = ReconAgent(llm_service, recon_tools, emitter)
    analysis_agent = AnalysisAgent(llm_service, base_tools, emitter)
    verification_agent = VerificationAgent(llm_service, verify_tools, emitter)
    orchestrator = OrchestratorAgent(llm_service, {"think": ThinkTool()}, emitter)
    
    orchestrator.register_sub_agent("recon", recon_agent)
    orchestrator.register_sub_agent("analysis", analysis_agent)
    orchestrator.register_sub_agent("verification", verification_agent)
    
    # 补齐独立测试环境的回调依赖
    for agent in [recon_agent, analysis_agent, verification_agent, orchestrator]:
        agent.set_cancel_callback(lambda: False)
        agent._timeout_config = {"sub_agent_timeout": 600, "tool_timeout": 60}
    
    input_data = {
        "project_root": workspace,
        "project_info": {"name": "VulnerableVault", "root": workspace},
        "config": {"target_vulnerabilities": ["reentrancy"], "verification_level": "sandbox"},
        "task": "完整审查代码，发现潜在的重入漏洞后，编写独立的 PoC 并在沙箱中爆破获取 Profit。"
    }
    
    print("\n🚀 [系统点火] 开始端到端多智能体安全审计！\n" + "="*60)
    result = await orchestrator.run(input_data)
    
    if result.success:
        findings = result.data.get("findings", [])
        
        # ==========================================
        # 🔥 终极战报去重逻辑 (Deduplication)
        # ==========================================
        unique_findings = {}
        for f in findings:
            if not isinstance(f, dict): continue
            
            # 尝试统一提取文件路径
            file_path = f.get("file_path") or f.get("file", "unknown")
            v_type = f.get("vulnerability_type", "unknown")
            
            # 过滤垃圾数据
            if file_path in ["?", "unknown", "", None] and v_type in ["unknown"]:
                continue
                
            key = f"{file_path}_{v_type}"
            
            # 优先级：已验证 (PoC 成功) > 分析推测 (Critical/High) > 侦察警告 (Medium/Low)
            is_confirmed = f.get("is_verified") or f.get("verdict") == "confirmed"
            
            if key not in unique_findings:
                unique_findings[key] = f
            else:
                # 只要新的 finding 确认成功了，或者带有更详细的 poc 代码，就无脑覆盖旧的理论发现
                if is_confirmed or (f.get("poc") and not unique_findings[key].get("poc")):
                    unique_findings[key] = f
                    
        final_findings = list(unique_findings.values())
        
        # 渲染 Markdown
        report_path = os.path.abspath("./audit_report.md")
        generate_markdown_report(final_findings, report_path)
        print(f"\n" + "="*60)
        print(f"✅ 审计完美结束！最终确认 {len(final_findings)} 个真实漏洞。")
        print(f"📄 请查看战报: {report_path}")
    else:
        print(f"\n❌ [执行失败] 编排器运行异常: {result.error}")

if __name__ == "__main__":
    asyncio.run(main())