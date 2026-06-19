# DeepAudit 生产级硬化 — 实施规格（spec）

本目录把总方案拆解为**可独立执行、可独立验收**的实施文档。每份阶段文档都包含：**目标（独立闭环）→ 实施步骤 → 验收标准 → 依赖与回滚**。

## 文档索引

| 文档 | 内容 | 对应总方案 |
|------|------|-----------|
| [00-master-plan.md](./00-master-plan.md) | 总方案：背景、20 项已验证诊断、分阶段改进、风险取舍、关键文件清单 | 全部 |
| [agent-role-refactor.md](./agent-role-refactor.md) | **贯穿性**：四层 Agent 职责重划（Recon/Analysis/Verification/Orchestrator） | Agent 角色重构 |
| [agent-recon-spec.md](./agent-recon-spec.md) | Recon 侦察层落地规格（ProjectMap 交接契约、sink_inventory 归属、不碰扫描器、覆盖报告产出） | Recon 充分发挥作用 |
| [agent-analysis-spec.md](./agent-analysis-spec.md) | Analysis 分析层落地规格（Candidate 输入契约、AnalyzedFinding 输出契约、结构化推理、grounded 定级、不判真伪） | Analysis 充分发挥作用 |
| [agent-orchestrator-spec.md](./agent-orchestrator-spec.md) | Orchestrator 编排层落地规格（骨架硬编码 + 三个结构化决策点 D1预算/D2覆盖回派/D3验证分诊） | Orchestrator 充分发挥作用 |
| [tool-reliability-and-availability.md](./tool-reliability-and-availability.md) | **🔥 最高优先**：工具运行时可用性（预检/能力清单/本地优先+Docker兜底/离线规则/契约测试）+ 分析完备性的诚实边界 | 一切工具工作的前置 |
| [tool-redesign-target-set.md](./tool-redesign-target-set.md) | **贯穿性**：工具正向重设计（按 6 类能力域定义"必须有哪些工具"；~50→约 15；每 Agent 7/≤10/6/1） | Phase 3 / 3-V / 4 的工具选型结论 |
| [tool-inventory-rationalization.md](./tool-inventory-rationalization.md) | **贯穿性**：工具集精简（~50 类 / 装配 13·21·23 → 精瘦集；keep/merge/drop 决策表） | Phase 3 / 3-V / 4e 的工具清单视角 |
| [tool-access-and-forms.md](./tool-access-and-forms.md) | **贯穿性**：工具接入机制分析 + 形式选型（function-calling / PTC code-as-action / MCP / Skills / 文本粘贴） | Phase 4a/4c/4e、Phase 3-V 的"工具怎么接"视角 |
| [phase-0-eval-harness.md](./phase-0-eval-harness.md) | 评测与基准框架（记分牌，**前置**） | Phase 0 |
| [phase-1-fp-gating.md](./phase-1-fp-gating.md) | 降误报：行号/片段校验 + 稳定指纹去重 + 验证即门禁 | Phase 1 |
| [phase-2-judge-calibration.md](./phase-2-judge-calibration.md) | 降误报续：LLM-as-judge 集成 + 置信度校准 | Phase 2 |
| [phase-3-recall-taint.md](./phase-3-recall-taint.md) | 降漏报：真实污点/可达性 + 调用图 + sink 覆盖 + RAG 降级/移出关键路径 | Phase 3（3a-3e, 3b-RAG, 3b-RAG-2） |
| [phase-3v-verification-ladder.md](./phase-3v-verification-ladder.md) | **核心**：验证阶梯（仿制自证 → 真实 oracle 观测） | Phase 3-V |
| [phase-4-native-tooling-context.md](./phase-4-native-tooling-context.md) | 原生工具调用 + 结构化输出 + 提示词/工具/通信/上下文专项 | Phase 4（4a-4g） |

## 实施顺序与依赖（关键）

```
Phase 0（评测记分牌）  ← 必须最先，否则无法证明任何改动是改善
   │
   ├─► Phase 1（FP 门禁：1a/1b 即可独立上线）
   │      └─ 1c 验证门禁的"高保真层级"消费端，依赖 Phase 3-V 提供 fidelity；
   │         未上 3-V 前 1c 先用现有 verdict 分层，3-V 落地后接入 fidelity
   │
   ├─► Phase 2（judge/校准） ← 1c 的低/中危廉价裁决路径依赖它
   │
   ├─► Phase 3（召回）  ← 放在 Phase 1-2 之后，新候选才会被 FP 门禁过滤
   │      ├─ 3b-RAG-2（索引移出关键路径）可**最先独立做**，立竿见影提速
   │      ├─ 3a（taint）→ 3b（调用图）→ 3c（覆盖）→ 3d（替换伪 dataflow）有内部依赖
   │      └─ 3a 的 ReachabilityTool 同时供 Phase 3-V 的 L1 门禁
   │
   ├─► Phase 3-V（验证阶梯，核心）  ← 复用 3a 的 ReachabilityTool 做 L1
   │
   └─► Phase 4（原生工具调用 + 专项）  ← 放最后，在稳定记分牌上度量
          ├─ 4a→4b→4c（地基：打通原生调用 + 结构化输出 + 迁移循环）
          └─ 4d/4e/4f/4g 依赖 4a-4c；其中 4g 的 AuditRunState 须先于 4f
```

**可并行/可提前的独立子项**（不阻塞主线）：
- **3b-RAG-2**（索引用户可选 + 移出关键路径）：纯提速、低风险，可作为"快赢"最先落地。
- **Phase 1a + 1b**：纯函数级 FP 修复，无新基建，可与 Phase 0 并行开发（但验收需 Phase 0 就绪）。
- **工具精简的"先行项"**（[tool-inventory-rationalization.md](./tool-inventory-rationalization.md) §3.5/§5/§3.3）：删僵尸工具 + 死配置对齐 + 扫描器按栈条件装配，低风险即时降噪；其余（验证工具坍缩、检索冗余收敛）随 Phase 3-V/Phase 3 同步。

## 全局验收门槛

1. **每个阶段**完成后，跑 `backend/eval/runner.py` 冒烟子集（50-100 用例），对 `baselines.json` 做 diff，指标满足该阶段文档的"验收标准"。
2. **回归保护**：既有 951 个基础设施单测全绿；新增纯函数有聚焦单测。
3. **方向性指标**（贯穿全程）：
   - Phase 1-2：精度（precision）↑，召回（recall）≥ 持平。
   - Phase 3 / 3-V：召回↑（taint/覆盖带来新 TP），精度由 Phase 1-2 门禁守住；伪确认计数→0。
   - Phase 4：F1 ≥ 持平且 token/延迟↓，解析失败日志显著减少。

## 术语

- **FP/FN**：误报（false positive）/ 漏报（false negative）。
- **fidelity（保真层级）**：L0 static-only / L1 reachable-unproven / L2·L3 proven-exploited / unverifiable，见 [phase-3v](./phase-3v-verification-ladder.md)。
- **source→sink**：污点源（不可信输入）到危险汇（敏感操作）的数据流路径。
- **记分牌**：Phase 0 的评测框架，所有改动以它度量 FP/FN delta。
