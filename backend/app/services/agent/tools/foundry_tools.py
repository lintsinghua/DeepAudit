"""
Foundry 沙箱工具集（终极优化版）
1. FoundryCastTool - 下载合约源码到文件
2. FoundryTestTool - 执行 PoC 攻击验证（JSON 输出解析与详尽错误透传）
"""
import json
import logging
import re
import os
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

from .base import AgentTool, ToolResult
from .sandbox_tool import SandboxManager, SandboxConfig

logger = logging.getLogger(__name__)


# ============================================================================
# ============ FoundryCast 工具（下载合约源码） ================================
# ============================================================================

class FoundryCastInput(BaseModel):
    """Foundry Cast 工具输入"""
    contract_address: str = Field(..., description="目标合约地址 (0x...)")
    chain: str = Field("mainnet", description="区块链网络: mainnet, polygon, bsc, arbitrum 等")
    block_number: Optional[int] = Field(None, description="指定区块号（可选，默认最新块）")
    output_dir: str = Field("src", description="输出目录（相对于 /workspace）")
    

class FoundryCastTool(AgentTool):
    """
    使用 Foundry Cast 下载真实的 Solidity 源码（而不是字节码）
    - 使用 cast source 而不是 cast code
    - 源码被保存到沙箱文件系统，避免填充 LLM 上下文
    - 只返回摘要信息给 LLM
    """
    
    def __init__(
        self,
        sandbox_manager: Optional[SandboxManager] = None,
        rpc_urls: Optional[Dict[str, str]] = None,
        etherscan_urls: Optional[Dict[str, str]] = None,
    ):
        super().__init__()
        self.rpc_urls = rpc_urls or {
            "mainnet": "https://eth.llamarpc.com",
            "polygon": "https://polygon-rpc.com",
            "bsc": "https://bsc-dataseed1.binance.org",
            "arbitrum": "https://arb1.arbitrum.io/rpc",
            "optimism": "https://mainnet.optimism.io",
            "base": "https://mainnet.base.org",
        }
        self.etherscan_urls = etherscan_urls or {
            "mainnet": "https://api.etherscan.io",
            "polygon": "https://api.polygonscan.com",
            "bsc": "https://api.bscscan.com",
            "arbitrum": "https://api.arbiscan.io",
            "optimism": "https://api-optimistic.etherscan.io",
            "base": "https://api.basescan.org",
        }
        self.sandbox_manager = sandbox_manager or SandboxManager(
            SandboxConfig(network_mode="bridge", timeout=60)
        )

    @property
    def name(self) -> str:
        return "foundry_cast"

    @property
    def description(self) -> str:
        return """从区块链浏览器下载智能合约的真实 Solidity 源码并保存到沙箱文件系统。

使用场景:
- 获取链上已部署合约的源码，供后续静态分析使用
- 在开始漏洞挖掘前拉取目标合约代码

输入:
- contract_address: 目标合约地址（0x 开头，必填）
- chain: 区块链网络，默认 "mainnet"，支持 polygon、bsc、arbitrum、optimism、base
- output_dir: 源码保存目录，默认 "src"（相对于 /workspace）

注意:
- 只返回文件摘要（路径、行数），不把源码内容直接填入上下文，避免超长
- 下载成功后请用 read_file 读取具体文件内容"""

    @property
    def args_schema(self):
        return FoundryCastInput
    
    async def _execute(
        self,
        contract_address: str,
        chain: str = "mainnet",
        block_number: Optional[int] = None,
        output_dir: str = "src",
        **kwargs
    ) -> ToolResult:
        try:

            etherscan_api_key = os.getenv("ETHERSCAN_API_KEY", "9AGF78FY7JGCABG7Q9D843IZH69DBW9KAE")  # 待检查修改！！

            await self.sandbox_manager.initialize()
            if not self.sandbox_manager.is_available:
                return ToolResult(success=False, error="Docker 沙箱不可用")
            
            contract_address = contract_address.strip()
            chain = chain.lower()
            etherscan_api_key = etherscan_api_key.strip()
            
            if not re.match(r"^0x[a-fA-F0-9]{40}$", contract_address):
                return ToolResult(success=False, error=f"非法的合约地址格式: {contract_address}")
            if chain not in self.rpc_urls:
                return ToolResult(success=False, error=f"不支持的链: {chain}")
            
            prepare_cmd = f"mkdir -p /workspace/{output_dir}"
            cast_source_cmd = (
                f"cast source {contract_address} "
                f"-d /workspace/{output_dir} --chain {chain} --etherscan-api-key {etherscan_api_key}"
            )
            verify_cmd = f"find /workspace/{output_dir}/ -name '*.sol' -type f | head -10"
            full_command = f"{prepare_cmd} && {cast_source_cmd} && {verify_cmd}"
            
            logger.info(f"[FoundryCast] 下载源码: {contract_address} on {chain}")
            
            result = await self.sandbox_manager.execute_command(full_command, timeout=60)
            
            exit_code = result.get("exit_code", -1)
            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")
            
            if exit_code != 0:
                error_msg = self._build_cast_error_report(exit_code, stdout, stderr, contract_address, chain)
                return ToolResult(
                    success=False,
                    error=error_msg,
                    data={"exit_code": exit_code, "raw_stderr": stderr[-500:] if stderr else ""}
                )
            
            file_lines = [line for line in stdout.split("\n") if line.strip().endswith(".sol")]
            if not file_lines:
                return ToolResult(success=False, error="未成功下载任何源码文件。请检查 API Key 和网络连接")
            
            file_count = len(file_lines)
            total_lines = 0
            
            count_lines_cmd = f"find /workspace/{output_dir}/ -name '*.sol' -type f -exec cat {{}} + | wc -l"
            count_result = await self.sandbox_manager.execute_command(count_lines_cmd, timeout=10)
            if count_result.get("exit_code") == 0:
                match = re.search(r"(\d+)", count_result.get("stdout", ""))
                if match: total_lines = int(match.group(1))
            
            return ToolResult(
                success=True,
                data={
                    "contract_address": contract_address,
                    "chain": chain,
                    "file_count": file_count,
                    "total_lines": total_lines,
                    "files": file_lines[:10],
                    "summary": f"✅ 成功下载 {file_count} 个文件（总计 {total_lines} 行代码）到 {output_dir}",
                },
                metadata={"tool_used": "foundry_cast"}
            )
        except Exception as e:
            logger.exception(f"[FoundryCast] 异常: {e}")
            return ToolResult(success=False, error=f"执行异常: {str(e)[:500]}")

    def _build_cast_error_report(self, exit_code: int, stdout: str, stderr: str, contract_address: str, chain: str) -> str:
        combined = (stderr + "\n" + stdout).lower()
        lines = [f"❌ foundry_cast 下载失败 (Exit: {exit_code})", f"合约: {contract_address}", f"链: {chain}"]
        if "invalid api key" in combined or "apikey" in combined:
            lines.append("原因: Etherscan API Key 无效或未授权")
        elif "not verified" in combined or "no source" in combined:
            lines.append("原因: 该合约在区块链浏览器上未验证（未开源），无法下载 Solidity 源码。")
        elif "does not exist" in combined or "not a contract" in combined:
            lines.append("原因: 该地址不是合约账户（可能是 EOA 或地址有误）")
        elif "timed out" in combined or "timeout" in combined:
            lines.append("原因: 网络连接超时")
        else:
            lines.append(f"【报错详情】:\n{stderr[-1000:] if stderr else stdout[-1000:]}")
        return "\n".join(lines)


# ============================================================================
# ============ FoundryTest 工具（执行 PoC 验证） ===============================
# ============================================================================

class FoundryTestInput(BaseModel):
    """Foundry Test 工具输入"""
    test_file: str = Field(..., description="PoC 测试文件路径（相对于 /workspace）")
    # 🔥 这里改成了默认 "local"，防止本地靶场因连接主网超时而崩溃
    chain: str = Field("local", description="目标链。填 'local' 表示纯本地测试；填 'mainnet' 等表示分叉主网测试")
    fork_block: Optional[int] = Field(None, description="分叉区块号（可选）")


class FoundryTestTool(AgentTool):
    """
    使用 Foundry Forge test 执行 PoC 攻击验证
    """
    
    def __init__(
        self,
        sandbox_manager: Optional[SandboxManager] = None,
        rpc_urls: Optional[Dict[str, str]] = None,
        project_root: str = "/workspace",
    ):
        super().__init__()
        self.rpc_urls = rpc_urls or {
            "mainnet": "https://eth.llamarpc.com",
            "polygon": "https://polygon-rpc.com",
            "bsc": "https://bsc-dataseed1.binance.org",
        }
        self.sandbox_manager = sandbox_manager or SandboxManager(
            SandboxConfig(network_mode="bridge", timeout=180)
        )
        self.project_root = project_root

    @property
    def name(self) -> str:
        return "foundry_test"

    @property
    def description(self) -> str:
        return """在沙箱中编译并执行 Foundry PoC 测试脚本，验证漏洞利用是否成功。

使用场景:
- 运行已编写好的 Solidity 漏洞利用测试（PoC）
- 验证重入、整数溢出等漏洞是否真实可利用
- 解析测试执行结果（通过/失败、Gas 消耗、Profit 日志）

输入:
- test_file: PoC 测试文件路径（相对于 /workspace，必填），例如 "test/RealExploit.t.sol"
- chain: 链模式，默认 "local"（本地脱机），真实链填 "mainnet"/"polygon"/"bsc" 等
- fork_block: 分叉历史区块号（可选，仅 chain 非 local 时有效）

注意:
- 本地靶场测试（无链上合约）必须保持 chain="local"，否则会尝试连接外部 RPC 导致超时
- 若测试失败，返回结果包含详细的 EVM 错误信息和智能诊断提示，请仔细阅读后修改 PoC 重试
- 示例: {"test_file": "test/RealExploit.t.sol", "chain": "local"}"""
    
    @property
    def args_schema(self):
        return FoundryTestInput
    
    async def _execute(
        self,
        test_file: str,
        chain: str = "local",
        fork_block: Optional[int] = None,
        **kwargs
    ) -> ToolResult:
        try:
            await self.sandbox_manager.initialize()
            if not self.sandbox_manager.is_available:
                return ToolResult(success=False, error="Docker 沙箱不可用")
            
            test_file = test_file.strip()
            chain = chain.lower()
            
            if chain != "local" and chain not in self.rpc_urls:
                return ToolResult(success=False, error=f"不支持的链: {chain}")
            
            # 1. 检查文件是否存在
            check_file_cmd = f"test -f {self.project_root}/{test_file} && echo 'File exists' || echo 'File not found'"
            check_result = await self.sandbox_manager.execute_command(check_file_cmd, timeout=5)
            if "not found" in check_result.get("stdout", ""):
                return ToolResult(success=False, error=f"测试文件不存在: {test_file}")
            
            # 2. 构建命令 (宿主机已预置好环境，直接 build 和 test 即可)
            compile_cmd = f"cd {self.project_root} && forge build 2>&1"
            test_cmd = f"cd {self.project_root} && forge test {test_file}"
            env_vars = {} # 你的 deepaudit 镜像内已配置好全局 PATH
            
            if chain != "local":
                rpc_url = self.rpc_urls[chain]
                test_cmd += f" --fork-url {rpc_url}"
                env_vars["FOUNDRY_ETH_RPC_URL"] = rpc_url
                if fork_block is not None: test_cmd += f" --fork-block-number {fork_block}"
            
            test_cmd += " -vv --json"
            
            full_command = " && ".join([compile_cmd, test_cmd])
            logger.info(f"[FoundryTest] 执行测试: {test_file}on {chain} fork={fork_block}")
            
            # 3. 在沙箱执行
            result = await self.sandbox_manager.execute_command(full_command, timeout=120, env=env_vars)
            
            exit_code = result.get("exit_code", -1)
            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")
            test_passed = exit_code == 0

            # =========================================================================
            # 🔥 核心防御体系：全方位解析并暴露编译器和虚拟机的报错给 LLM！
            # =========================================================================
            if not test_passed:
                json_results = self._extract_json_results(stdout, stderr)
                failure_summary = self._extract_failure_summary(json_results)
                
                # 判断是否是语法/编译错误
                is_compile_error = (not json_results and ("error" in stderr.lower() or "error" in stdout.lower()[:2000]))
                
                if is_compile_error:
                    error_msg = f"❌ 编译失败 (Exit code: {exit_code})\n"
                    # 从 stdout 提取具体的 "Error (XXXX):" 信息
                    error_lines = [l for l in stdout.split('\n') if 'Error' in l or 'error' in l or '-->' in l]
                    if error_lines:
                        error_msg += f"【提取的编译错误】:\n" + "\n".join(error_lines)[:1500] + "\n\n"
                    if stderr:
                        error_msg += f"【标准错误】:\n{stderr[-1500:]}\n"
                elif failure_summary:
                    # 测试执行了但失败了（包含具体的 Trace 分析）
                    error_msg = failure_summary
                else:
                    # 未知执行失败降级处理
                    error_msg = f"❌ 测试执行失败 (Exit code: {exit_code})\n"
                    error_msg += f"【标准错误】:\n{stderr[-2000:]}\n"
                    # 去掉 JSON 乱码
                    text_lines = [l for l in stdout.split("\n") if l.strip() and not l.strip().startswith("{") and len(l) < 300]
                    if text_lines:
                        error_msg += f"【关键输出】:\n" + "\n".join(text_lines[-60:])
                
                # 将最详细的 error_msg 赋值给 error，保证 LLM 能看清错在哪！
                return ToolResult(
                    success=False,
                    error=error_msg,
                    data={"exit_code": exit_code, "raw_stderr": stderr[-1000:]}
                )
            
            # 4. 成功执行，解析数据
            json_results = self._extract_json_results(stdout, stderr)
            analysis = self._analyze_json_results(json_results, test_passed)
            
            
            return ToolResult(
                success=True, # 只有真正通过测试才返回 True
                data={
                    "test_passed": True,
                    "test_file": test_file,
                    "analysis": analysis,
                    "exit_code": exit_code,
                },
                metadata={
                    "exit_code": exit_code,
                    "test_passed": True,
                    "profit": analysis.get("profit"),
                    "tool_used": "foundry_test",
                }
            )
        except Exception as e:
            logger.exception(f"[FoundryTest] 异常: {e}")
            return ToolResult(success=False, error=f"执行异常: {str(e)[:500]}")
    
    def _extract_json_results(self, stdout: str, stderr: str) -> Dict[str, Any]:
        output = stdout + stderr
        lines = output.split("\n")
        json_text = ""
        in_json = False
        brace_count = 0
        
        for line in lines:
            line_clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
            if "{" in line_clean and not in_json:
                in_json = True
            if in_json:
                json_text += line_clean + "\n"
                brace_count += line_clean.count("{") - line_clean.count("}")
                if brace_count == 0 and json_text.count("{") > 0:
                    try:
                        return json.loads(json_text)
                    except json.JSONDecodeError:
                        json_text, in_json, brace_count = "", False, 0
        return {}

    def _extract_failure_summary(self, json_results: Dict[str, Any]) -> str:
        if not json_results: return ""

        lines = ["❌ forge test 失败报告（Execution Reverted）"]
        found_any = False

        for contract_key, contract_data in json_results.items():
            if not isinstance(contract_data, dict): continue
            test_results_dict = contract_data.get("test_results", {})
            if not test_results_dict: continue

            for func_name, test_result in test_results_dict.items():
                if not isinstance(test_result, dict): continue

                status = test_result.get("status", "Unknown")
                reason = test_result.get("reason", None)
                
                lines.append(f"\n合约: {contract_key} | 函数: {func_name}")
                lines.append(f"状态: {status}")
                if reason: lines.append(f"失败原因 (Reason): {reason}")
                
                found_any = True

                # 提取 Execution Trace
                traces = test_result.get("traces", [])
                for trace_pair in traces:
                    if not isinstance(trace_pair, list) or len(trace_pair) < 2: continue
                    if trace_pair[0] != "Execution": continue
                    
                    call_lines = []
                    for node in trace_pair[1].get("arena", [])[:8]:
                        td = node.get("trace", {})
                        depth = td.get("depth", 0)
                        kind = td.get("kind", "CALL")
                        address = td.get("address", "?")[-10:]
                        t_status = td.get("status", "?")
                        indent = "  " * (depth + 1)
                        call_lines.append(f"{indent}[{depth}] {kind} → ...{address} [{t_status}]")
                        
                        if t_status == "OutOfFunds":
                            call_lines.append(f"{indent}  ↑ OutOfFunds: 余额不足以发送 value")
                        elif t_status in ("Revert", "Halt") and td.get("output", ""):
                            # 尝试解析常见 Error string
                            out_hex = td.get("output", "")
                            if out_hex.startswith("0x08c379a0") and len(out_hex) >= 138:
                                try:
                                    raw = bytes.fromhex(out_hex[2:])
                                    str_len = int.from_bytes(raw[36:68], 'big')
                                    msg = raw[68:68+str_len].decode('utf-8', 'ignore')
                                    call_lines.append(f"{indent}  ↑ Revert: \"{msg}\"")
                                except: pass
                                
                    if call_lines:
                        lines.append(f"\n调用栈 (Execution Trace):")
                        lines.extend(call_lines)

        if not found_any: return ""

        # 智能诊断提示
        all_reasons = str(json_results).lower()
        hint_lines = ["\n💡 智能诊断提示:"]
        if "insufficient balance" in all_reasons:
            hint_lines.append(
                "- 错误 'Insufficient balance': Attacker 在 balances mapping 里没有余额。"
                "根本原因: vm.deal() 只改 ETH 余额，不改合约内部的 balances mapping！"
                "必须修改 attack() 函数，先调用 vault.deposit{value: amount}() 在账本里登记，再调 vault.withdraw(amount) 触发重入。"
                "禁止直接调用 withdraw 而不先 deposit！"
            )
        if "outoffunds" in all_reasons or "out of funds" in all_reasons:
            hint_lines.append(
                "- 错误 'OutOfFunds': 发起调用的合约（VaultTest 或 Attacker）自身没有 ETH。"
                "修复: 在 setUp() 中用 vm.deal(address(this), 11 ether) 给测试合约本身充值，"
                "然后通过 attacker.attack{value: 1 ether}() 传入子弹，不要只给 attacker 地址 deal。"
            )
        if "transfer failed" in all_reasons:
            hint_lines.append("- 错误 'Transfer failed': Attacker 合约没有能够接收 ETH 的函数。修复: 添加 `receive() external payable {}`。")
        
        lines.extend(hint_lines)
        return "\n".join(lines)

    def _analyze_json_results(self, json_results: Dict[str, Any], test_passed: bool) -> Dict[str, Any]:
        analysis = {"test_passed": test_passed, "gas_used": None, "profit": None, "summary": ""}
        for contract_key, contract_data in json_results.items():
            if isinstance(contract_data, dict) and "test_results" in contract_data:
                for func_name, test_result in contract_data["test_results"].items():
                    if isinstance(test_result, dict):
                        analysis["gas_used"] = test_result.get("kind", {}).get("Unit", {}).get("gas")
                        logs = test_result.get("decoded_logs", [])
                        for log_str in logs:
                            profit_match = re.search(r'Profit.*?([\d.]+)', str(log_str), re.IGNORECASE)
                            if profit_match: analysis["profit"] = float(profit_match.group(1))
                        break
                break
                
        if test_passed:
            if analysis["profit"] is not None:
                analysis["summary"] = f"✅ 测试成功！获利 {analysis['profit']} ETH (Gas: {analysis['gas_used']})"
            else:
                analysis["summary"] = f"✅ 测试通过，成功执行"
        return analysis