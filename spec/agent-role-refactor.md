# Agent 角色重构（贯穿性）

> **状态**：未开始 ｜ **性质**：贯穿性——不单独成一个执行阶段，而是约束 Phase 1-4 各改动归位到正确角色 ｜ **对应诊断**：#14 #15 #16（+ #1 #10）

## 1. 目标（独立闭环）

四层"侦察→分析→验证→编排"的**划分维度是对的**（XBOW、Project Naptime 同类分工），问题是**每个角色的实现都偏离了它本该承担的职责**。本文件确立每层重构后的**单一职责边界**——**保留四层、不改 Agent 数量**（用户已确认），让 Phase 0-4 的改动各自归位。

**闭环判据**：四个 Agent 各自的职责边界在代码中体现为"只做该做的、不越界"，且每条对应改动可追溯到本表。

## 2. 角色职责对照

| Agent | 现状（错位） | 重构后单一职责 | 落地于 |
|-------|-------------|---------------|--------|
| **Recon** | 文件名启发式产出 `high_risk_areas` 当范围闸门（漏报源头 #16）；`if "django" in obs` 子串猜技术栈；越界报 `initial_findings` | **纯客观事实采集**：① 从清单文件（`package.json`/`go.mod`/`requirements.txt`）**确定性**解析技术栈；② 入口点枚举；③ 交出**完整 sink 清单**。**不输出"高风险区"做闸门，不报漏洞** | Phase 3c（`SinkInventory` 接管 sink 枚举）；删 `initial_findings`/`high_risk_areas` 闸门语义 |
| **Analysis** | 一个 Agent 背"扫描编排+数据流+跨文件+判真伪"四件事，核心能力（过程间追踪）是假的 | **聚焦推理**：对结构化检索/可达性引擎给出的**候选**做上下文推理与定级。枚举 sink 交 Recon/SinkInventory、跑外部工具交工具层、判真伪交 Verification | Phase 3a/3b/3d（真实可达性/调用图喂候选）；Phase 3e（去"全局扫描禁令"） |
| **Verification** | 角色对（独立验证层是亮点），但仿制环境演戏；只验 critical/high 子集；结果不门禁 | **对进报告的每条负责**：走验证阶梯（真实 oracle），输出 `fidelity`；不再只挑子集 | Phase 3-V（验证阶梯）；Phase 1c（门禁消费） |
| **Orchestrator** | 假装规划，实为写死的固定管线（#15） | **真规划**：按 sink/可达性**分配审计预算**、跟踪**覆盖**并在不足时**回派** Analysis、决定**哪些发现上 L2/L3 验证**（验证分诊）。固定"recon→analysis→verification"骨架可硬编码，LLM 只在**真实决策点**介入 | Phase 3c（覆盖跟踪/回派）；Phase 4f（回派通道）；Phase 1c（验证分诊） |

## 3. 实施步骤（按角色归集，避免散落修补）

### Recon
> 落地细节见 [agent-recon-spec.md](./agent-recon-spec.md)（ProjectMap 交接契约、触发时机、覆盖报告产出、验收标准）。
1. 技术栈解析：新增确定性 manifest 解析（`parse_manifest` 工具，读 `package.json`/`go.mod`/`requirements.txt`/`pom.xml` 等），替换 `recon.py:716-746` 的子串猜。
2. 删除 `high_risk_areas` 的"范围闸门"语义与 `initial_findings`（侦察阶段报漏洞）——`recon.py:106-156, 672-771`。
3. sink 枚举由 `sink_inventory` 工具在 **Recon 阶段**调用，产出纳入项目地图（ProjectMap），下游消费而非重扫——**非**独立 Agent 外模块。
4. **不碰扫描器**：Recon 工具集移除 semgrep/gitleaks，杜绝越界报漏洞（#16）。

### Analysis
> 落地细节见 [agent-analysis-spec.md](./agent-analysis-spec.md)（Candidate 输入契约、AnalyzedFinding 输出契约、结构化推理、grounded 定级、验收）。
1. **输入契约**：删 `analysis.py:410-416` 对 `high_risk_areas`/`initial_findings` 的读取；改为消费 Recon `ProjectMap` + `Candidate` 列表（覆盖 sink 全集）。
2. **输出契约**：产 `AnalyzedFinding`（恒 `needs_verification=true`、`fidelity=static-only`），**不自封已确认**、不设终态 confidence。
3. 提示词去"全局扫描禁令"与扫描器编排职责（Phase 3e、4d）；真伪判定完全移交 Verification。

### Verification
> 输入边界修正见 [phase-3v-verification-ladder.md](./phase-3v-verification-ladder.md) §3.6（V1 分诊归属、V2 输入截断）。
1. 走 Phase 3-V 验证阶梯，输出 `fidelity`。
2. **不自己挑子集**——执行 Orchestrator D3 的分诊结果（`verify_tier`），对进报告的每条负责（Phase 1c 强制裁决）。
3. 输入改读 `AuditRunState`（Phase 4g）完整 AnalyzedFinding，不经 handoff 有损截断。

### Orchestrator
> 落地细节见 [agent-orchestrator-spec.md](./agent-orchestrator-spec.md)（骨架硬编码 + D1/D2/D3 三决策点 schema 与数据流闭环）。
1. 骨架流程（recon→analysis→verification 顺序）**硬编码**，去掉"用 LLM 自主循环执行固定管线"的伪自主（`orchestrator.py:28-105`）。
2. LLM 只在三个**结构化决策点**介入：**D1 预算分配**、**D2 覆盖回派**（消费 Recon coverage_report + Phase 3c 跟踪，经 Phase 4f 回派）、**D3 验证分诊**（Phase 1c）。
3. 每个决策点有结构化输入/输出，非自由文本；确定性启发式优先，LLM 仅边界介入。

## 4. 验收标准

- [ ] **Recon 不越界**：审计产物中 Recon 不再输出"高风险区闸门"或漏洞；技术栈来自 manifest 确定性解析（构造一个无 `django` 字样但用 Django 的项目，仍能从 manifest 识别）。
- [ ] **Analysis 不被钳制**：移除"禁止全局扫描"后，Analysis 覆盖范围由 sink 清单决定而非 Recon 启发式（记分牌召回↑）。
- [ ] **Verification 全覆盖**：进报告的每条都带 `fidelity`/`verdict`，无"未裁决"漏网。
- [ ] **Orchestrator 真规划**：固定骨架不再消耗 LLM 自主循环 token（token↓）；覆盖不足时能观测到回派 Analysis 的行为。
- [ ] 每条改动可在第 2 节表中追溯到对应 Phase；记分牌整体：召回↑（#10/#16 解除）、精度由门禁守住。

## 5. 依赖

本文件是**约束**而非独立阶段，其验收随对应 Phase 完成而达成：Recon→Phase 3c、Analysis→Phase 3a/3b/3d/3e、Verification→Phase 3-V/1c、Orchestrator→Phase 3c/4f/1c。
