# Phase 3-V — 验证阶梯：从"仿制环境自证"改为"真实 oracle 观测"

> **状态**：未开始 ｜ **前置**：Phase 3a（ReachabilityTool 供 L1）、Phase 1c（消费 fidelity 做门禁）｜ **对应诊断**：#14（核心可信度问题）

## 1. 目标（独立闭环）

把"验证"从**在 LLM 捏造 / LLM mock / LLM 自定判据的仿制环境里自我盖章**，改为**用真实预言机（oracle）观测真实代码的真实副作用**。判定真伪的权力从 LLM 手里拿走，交给三样东西：**静态可达性引擎、真实依赖、可观测副作用**。LLM 退回它该干的：决定测什么、构造 payload、解释证据。

**闭环判据**：记分牌**伪确认计数→0**（被仿制环境盖章的假阳消失）；真实证据确认的发现带可复现工件；其余诚实降级而非伪装"已验证"。

**核心理念**：沙箱基建（`SandboxManager`）本身是真的（真起 Docker、隔离到位），保留不动——改的是"它验证的对象"。

## 2. 保真层级（fidelity，写入 finding，供 Phase 1c 门禁消费）

| 层级 | 含义 | 判定者 | 依赖 |
|------|------|--------|------|
| **L0 `static-only`** | 仅静态特征命中，无可达性证明 | 静态规则 | 无 |
| **L1 `reachable-unproven`** | 存在 source→sink 且中间无有效 sanitizer 的路径（漏洞为真的**必要条件**） | Semgrep taint / 调用图（确定性、不花 LLM、不依赖 Docker） | Phase 3a `ReachabilityTool` |
| **L2 `proven-exploited`** | 真实执行 + 语义 oracle 触发真实副作用 | 真实依赖 + 副作用观测 | Docker 沙箱 |
| **L3 `proven-exploited`** | 真应用 DAST：真起服务发真实恶意请求 | 运行中的真实应用 | `docker-compose`/`Dockerfile` |
| **`unverifiable`** | Docker/依赖不可用等 | —（诚实标注降级） | 无 |

**逐级升级、能到哪算哪**，不强求所有发现都到 L2/L3。

## 3. 实施步骤

### 3.1 L1 可达性门禁（先做，砍掉大批假阳）
- 复用 Phase 3a 的 `ReachabilityTool`：无 source→sink 路径的发现，**无论 harness 演出什么都降级**到 L0。

### 3.2 L2 真实执行 + 语义 oracle（重写 `tools/run_code.py` + `tools/sandbox_tool.py:435-518,999-1238`）
- **真实代码，非誊抄**：harness 必须 **import 项目真实模块 / `include` 真实文件**——用 `ExtractFunctionTool` 已有的 AST 抽真实函数字节去**驱动加载真实模块**，**禁止 LLM 把函数重写进 harness**。
- **mock 边界约束**：mock **只允许**用在"不改变真伪判定"的边界（stub 发邮件/付款/日志）；**严禁** mock 决定真伪的依赖——测 SQLi 不准 mock DB 驱动，测 XSS 不准 mock 转义函数，测命令注入不准用 `MockCursor`/`if "'" in query` 这种循环论证。
- **语义 oracle 替换"有输出≈有漏洞"**（新增沙箱原语）：
  - 命令注入 → `network=none` 只读沙箱里真执行 `; touch /tmp/canary_<rand>`，看 canary 是否真被创建。
  - SQLi → 沙箱里起**真实临时数据库**（sqlite/postgres）播种数据，用布尔差分（`1=1` vs `1=2` 行数不同）或真实驱动抛错当判据。
  - 路径遍历 → 目标目录外种 canary，看是否被读出。
  - SSRF → 真实带外回调监听器。
  - XSS → 对真实模板/转义函数喂 payload，检查输出字节（或 headless 浏览器）。

### 3.3 L3 真应用 DAST
- 仓库自带可运行 `docker-compose`/`Dockerfile` 时，**真起服务、发真实恶意 HTTP、观测真实响应**。对相当一部分 Web 仓库可达，应主动尝试。

### 3.4 诚实降级 + 工件存档
- 修 `run_code.py:147-152` 的静默降级：Docker/依赖不可用 → 标 `unverifiable` 并降级，**绝不**把静态臆测伪装成"已验证"。
- harness/PoC + 确切命令 + 捕获证据（canary 命中、回调日志、布尔差分）**存档为工件**；不能复现的"确认"不算确认。

### 3.5 verification agent 接线
- `agents/verification.py`：提示词与流程改为走验证阶梯，输出 `fidelity` 层级（供 Phase 1c）。

### 3.6 输入边界修正（补 Verification 角色落地缺口 V1/V2）
> 角色审计发现 Verification 有两处与"对进报告的每条负责"冲突的残留，在此钉死：
- **缺口 V1（分诊归属）**：Verification **不再自己挑子集**（删 `verification.py:496-523` 的"只验 critical/high 或 needs_verification"逻辑）。验证分诊归 **Orchestrator 的 D3 决策点**（见 [agent-orchestrator-spec.md](./agent-orchestrator-spec.md) §1.2）——Orchestrator 按 severity/fidelity/reachability 给每条发现打 `verify_tier`（`ladder_L2L3`/`cheap_judge`/`static_only`），Verification **执行**该分诊：L2/L3 走真实 oracle、cheap_judge 走 Phase 2 单次 judge、static_only 直接降级。Verification 对**每条都给结论**，无"未裁决"漏网。
- **缺口 V2（输入截断）**：Verification 从 `_incoming_handoff.key_findings` 取输入（`verification.py:485`），而 handoff 的 key_findings 现状被**截断为前 15 条**（#19 有损摘要）——与"对每条负责"矛盾。修：Verification 的输入改为引用 **`AuditRunState`（Phase 4g）里的完整 `AnalyzedFinding` 列表**，不经 handoff 的有损截断；handoff 只传引用/ID，全量数据从结构化状态读。

## 4. 验收标准

- [ ] **真实模块加载**：harness 生成逻辑能从真实文件 import 目标函数；注入"LLM 重写函数"的尝试被拒绝（测试断言 harness 引用的是真实模块路径）。
- [ ] **mock 边界**：单测断言"mock 了 DB 驱动/转义函数/命令执行"的 harness 被判非法（不可用于 L2 判定）。
- [ ] **语义 oracle**：命令注入样例——canary 文件真被创建才判 L2；构造"看似有输出但无副作用"的样例**不再误判**为漏洞。
- [ ] **SQLi 布尔差分**：真实临时库样例，`1=1`/`1=2` 行数差异驱动判定，无差异则不确认。
- [ ] **诚实降级**：Docker 不可用时，发现标 `unverifiable` 且严重度封顶，报告明示"未真实验证"——无任何 `confirmed` 出现。
- [ ] **工件**：每个 L2/L3 确认附可复现命令 + 捕获证据，能重放。
- [ ] 记分牌：**伪确认计数→0**；L2/L3 确认的发现精度极高；召回不因门禁下降（L1 仍保留为候选，只是降级展示）。

## 5. 依赖与回滚

- **依赖**：Phase 3a（`ReachabilityTool` 做 L1）；Phase 1c 消费 `fidelity`。
- **取舍（已与用户确认接受）**：真实确认只覆盖"能起真实依赖/真应用"的**子集**，其余诚实降级——**一个被真实证据确认的漏洞，价值远高于一百个被仿制环境盖章的"确认"**。起真实 DB/真应用增加沙箱镜像与时间成本，故按 L0→L3 逐级升级。
- **回滚**：新沙箱原语与重写的 harness 逻辑可开关切换；保留旧 `run_code` 路径作为应急兜底（但默认走新阶梯）。
