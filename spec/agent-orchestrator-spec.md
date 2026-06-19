# Orchestrator Agent 实施规格（编排层）

> **状态**：设计完成，待采纳 ｜ **性质**：把 [agent-role-refactor.md](./agent-role-refactor.md) 中 Orchestrator 的"真规划"从**愿景**落成**规格** ｜ **对应诊断**：#15（假规划=固定管线伪自主）｜ **依赖**：Recon 的 coverage_report、Phase 3c 覆盖跟踪、Phase 1c 验证分诊、Phase 4f 回派通道

## 0. 为什么单独立此 spec

角色重构说 Orchestrator 做"预算分配、覆盖回派、验证分诊"，但这三个是**名词，不是机制**：
1. 代码现状（`orchestrator.py:46/79/390/630`）是 `dispatch_agent`/`summarize`/`finish` 的 LLM 文本自主循环——#15 的伪自主。
2. **三个"真规划"动作零实现规格**：预算怎么分、覆盖信号从哪读、回派怎么触发、分诊规则是什么——一行都没写。
3. **决策点的输入/输出 schema 未定义**：要让"LLM 只在真实决策点介入"成立，就得定义每个决策点喂什么、吐什么——否则要么退回文本自主循环（#15 没解决），要么硬编码死板。

本 spec 把"骨架硬编码 + LLM 在结构化决策点介入"定透。

---

## 1. Orchestrator 的单一职责：固定骨架 + 三个结构化决策点

**一句话**：审计的**流程骨架是确定性的**（不该花 LLM token 去"决定先 recon 还是先 analysis"），LLM 只在**三个真实需要判断的决策点**介入，且每个决策点有**结构化输入→结构化输出**。

### 1.1 骨架硬编码（去 #15 伪自主）
```
确定性流程（代码写死，非 LLM 自主循环）:
  Recon → [决策点 D1: 预算分配]
        → Analysis(候选列表) → [决策点 D2: 覆盖回派] ⟲
        → [决策点 D3: 验证分诊] → Verification
        → finalize（Phase 1c 门禁）→ 报告
```
- 删除 `orchestrator.py:28-105` 的"你是大脑、自主决定调度谁"提示词与文本 `dispatch_agent` 循环。
- 顺序、何时进下一阶段——**代码控制**，不问 LLM。

### 1.2 三个决策点（LLM 介入处，各有 schema）

**D1 — 预算分配**（Recon 后）：
```
输入:  {sink_total, reachable_count, file_count, token_budget_total, tech_stack}
输出:  {analysis_passes_max, per_file_depth, verify_budget_share}  # 如何在覆盖广度 vs 验证深度间分配
```
- 决策："这个仓库 500 个 sink、预算有限 → Analysis 优先 reachable 的、verify 只给 critical 留预算" vs "小仓库 → 全量深挖"。
- 可先用**确定性启发式**（sink 数/预算的简单公式）实现，LLM 仅在边界情况微调——不强求每次都问 LLM。

**D2 — 覆盖回派**（每轮 Analysis 后，⟲ 循环）：
```
输入:  {sinks_total, sinks_covered, sinks_uncovered[], iterations_left, budget_left}
输出:  {action: "re_dispatch" | "proceed", target_files[]}  # 是否回派 Analysis 补覆盖
```
- 消费 Recon 的 `coverage_report` + Phase 3c 的实时覆盖跟踪。未覆盖 sink + 有预算 → 回派 Analysis 定向分析这些文件（经 Phase 4f 通信通道）。**这是降漏报的闭环**——不再"Analysis 跑一遍就算完"。
- 收敛条件：覆盖达标 或 预算耗尽 或 连续 N 轮无新覆盖 → `proceed`。

**D3 — 验证分诊**（Verification 前，解决 Verification 缺口 V1 的归属）：
```
输入:  [{finding_id, severity_prelim, fidelity, reachability}]  # 来自 Analysis 的 AnalyzedFinding
输出:  [{finding_id, verify_tier: "ladder_L2L3" | "cheap_judge" | "static_only"}]
```
- 分诊规则（确定性优先，LLM 兜底边界）：critical/high + reachable → 完整验证阶梯（L2/L3）；low/medium → Phase 2 廉价 judge；reachability=unknown 且证据弱 → 标 static_only 降级。
- **归属定论**：分诊在 **Orchestrator**（它有全局视图 + 预算），Verification **执行**分诊结果，不自己挑子集（修 Verification 缺口 V1）。

---

## 2. 与各 Phase 的数据流闭环（缺口 O2）

```
Recon.coverage_report ─┐
                        ├─► D2 覆盖回派 ──(Phase 4f 通信通道)──► Analysis 补扫
Phase 3c 覆盖跟踪 ──────┘
Analysis.AnalyzedFinding ──► D3 验证分诊 ──► Verification 执行 ──► Phase 1c finalize 门禁
```
- **Phase 3c** 提供"哪些 sink 已被分析"的实时信号给 D2。
- **Phase 4f** 提供回派的通信机制（MessageBus）给 D2 落地。
- **Phase 1c** 在 Verification 后做最终 fidelity 门禁——Orchestrator 不重复判真伪，只分诊。

---

## 3. 验收标准

- [ ] **骨架确定性**：recon→analysis→verification 顺序由代码控制，不消耗 LLM 自主循环 token（对比改造前 token↓，#15 解除）。
- [ ] **D1 可观测**：预算分配输出 analysis/verify 的资源切分；大仓库 vs 小仓库行为不同。
- [ ] **D2 闭环**：构造"Analysis 首轮漏掉部分 sink"场景，Orchestrator 据覆盖率**回派 Analysis 补扫**，覆盖率上升（记分牌召回↑）；收敛条件生效（不无限回派）。
- [ ] **D3 分诊归属**：验证分诊在 Orchestrator 产出，Verification 执行而非自选子集（修 V1）；分诊结果与 severity/fidelity/reachability 一致。
- [ ] 三个决策点各有结构化输入/输出（非自由文本）；确定性启发式可跑，LLM 仅边界介入。

## 4. 需同步修正的既有 spec

| 文件 | 修正 |
|------|------|
| [agent-role-refactor.md](./agent-role-refactor.md) | Orchestrator 节链接本 spec，三动作补 schema 引用 |
| [phase-3-recall-taint.md](./phase-3-recall-taint.md) | 3c 覆盖跟踪明确为"喂 Orchestrator D2 决策点的信号源" |
| [phase-4-native-tooling-context.md](./phase-4-native-tooling-context.md) | 4f 回派通道明确为"D2 覆盖回派的落地机制" |
| [phase-1-fp-gating.md](./phase-1-fp-gating.md) | 1c 验证分诊归 Orchestrator D3（非 Verification 自选） |

## 5. 一句话总结

Orchestrator 应有作用 = **用确定性骨架省掉伪自主，把 LLM 的判断力集中到三个真正需要权衡的决策点（预算/覆盖/分诊），且每点有结构化输入输出**——从"假装规划的固定管线"变成"骨架确定、决策点智能"的真编排。
