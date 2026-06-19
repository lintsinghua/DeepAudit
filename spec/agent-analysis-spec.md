# Analysis Agent 实施规格（分析层）

> **状态**：设计完成，待采纳 ｜ **性质**：补齐 [agent-role-refactor.md](./agent-role-refactor.md) 中 Analysis 的落地缺口（四角色里重构最不彻底的一个）｜ **对应诊断**：#1 #10 ｜ **依赖**：[agent-recon-spec.md](./agent-recon-spec.md)（输入来自 Recon 的 ProjectMap）

## 0. 为什么单独立此 spec

`agent-role-refactor.md` 的 Analysis 节只有三句"否定式"描述（去掉什么），**没定义新的正向契约**，导致三个悬空点 + 一处与 Recon spec 直接对撞：
1. **输入契约未定义**：代码现状（`analysis.py:410-416`）仍读 `recon_data["high_risk_areas"]`/`initial_findings`——**正是 Recon spec 要删的字段**。两份 spec 对撞。
2. **输出契约未重定义**：`_create_analysis_handoff`（:828）现在交"自己判过真伪的 findings"，但角色重构说"真伪判定移交 Verification"——那 Analysis 到底交什么？
3. **"聚焦推理"无规格**：推理产出什么结构、定级依据什么、怎么验收，全空。

本 spec 把这四点钉死。

---

## 1. Analysis 的单一职责：对候选做"上下文推理与定级"，不枚举、不扫描、不判真伪

**一句话**：Analysis 是**推理者**，不是扫描器编排器。它接收结构化骨架给出的**候选**，逐个判断"在真实代码上下文里这是不是一个值得验证的漏洞、属于哪类 CWE、初步严重度多少、source→sink 是否说得通"，产出**带推理依据的候选发现**交给 Verification 做真伪裁决。

| 该做 | 不该做（已移交） |
|------|----------------|
| ① 消费候选（sink + 可达性路径 + 上下文） | ❌ 枚举 sink（→ Recon 的 `sink_inventory`） |
| ② 读真实代码上下文（`read_file`/`grep`/`ast_grep`/`call_graph`） | ❌ 跑找漏洞的扫描器编排（semgrep 等结果由工具层/候选喂入，不由 Analysis"决定跑哪个"） |
| ③ 对候选做 CWE 归类 + 初步定级 + source→sink 推理 | ❌ **判定真伪/确认可利用**（→ Verification 的验证阶梯） |
| ④ 产出带推理依据的候选发现，交 Verification | ❌ 优先 Recon 高风险区、禁止全局扫描（删 #10/#16 钳制） |

---

## 2. 四个缺口的钉死方案

### 2.1 输入契约（缺口 1，消除与 Recon 对撞）：消费 `ProjectMap` + `Candidate` 列表

- **删** `analysis.py:410-416` 对 `high_risk_areas`/`initial_findings` 的读取。
- Analysis 的输入 = Recon 的 `ProjectMap`（`TaskHandoff.context_data["project_map"]`，见 agent-recon-spec §2.2）+ 由结构化骨架（Phase 3a/3b/3c）产出的 **`Candidate` 候选列表**：

```
Candidate（Analysis 的工作单元）:
  id:              稳定标识（file+line+sink_symbol 哈希）
  sink:            {file, line, symbol, category}      # 来自 sink_inventory
  source:          {file, line, kind} | null           # 来自 taint，可能未知
  dataflow_path:   [{file, line, note}] | null          # 来自 reachability/taint，可能为空
  reachability:    reachable | unknown                  # Phase 3a ReachabilityTool
  cwe_hint:        CWE-id | null                         # sink 类别推断的初步 CWE
```

- **来源**：Orchestrator 把 ProjectMap 的 sink 清单经 `reachability`/`call_graph` 加工成 Candidate 列表（或 Analysis 首步自行调这些工具把 sink → Candidate）。**覆盖保证**：Candidate 列表覆盖 sink 清单全集（未reachable 的标 `unknown` 仍入列，不丢——降漏报）。

### 2.2 输出契约（缺口 2）：交"带推理依据的候选"，不交"已确认漏洞"

- Analysis 产出 `AnalyzedFinding`，**明确标注"未经真实验证"**，交 Verification：

```
AnalyzedFinding（Analysis → Verification）:
  candidate_id:        关联的 Candidate
  vulnerability_type:  CWE-grounded 类型（依据 Phase 4d 的 CWE 标准，非凭记忆）
  severity_prelim:     初步严重度（仅供分诊排序，非最终）
  source, sink:        污点两端（来自候选 + 代码确认）
  reasoning:           **结构化推理**：为何 source 能到 sink、sanitizer 为何无效/缺失
  code_context:        read_file 取的真实片段（供验证阶梯加载真实模块）
  fidelity:            static-only（Analysis 产出的天花板就是 L0/L1，真伪由 Verification 升级）
  needs_verification:  恒为 true（Analysis 不再自封"已确认"）
```

- **关键**：`_create_analysis_handoff`（:828）改为产 `AnalyzedFinding` 列表，**不再设 `is_verified`/不再自报终态 confidence**——这些是 Verification 的职责。`confidence` 字段删除或恒为"待验证"，由 Phase 2 judge + Phase 3-V oracle 后续填。

### 2.3 "聚焦推理"规格（缺口 3）：推理是结构化的，定级是 grounded 的

- **推理结构化**：每个 Candidate 的 `reasoning` 必须回答三问——① source 是否真不可信？② 到 sink 路径上有无有效 sanitizer？③ 这段真实代码是否构成可利用模式？（对应核心安全原则的 source→sink 分析）。这是 Analysis 的核心产出，不是散文。
- **定级 grounded**：`vulnerability_type`/`severity_prelim` 依据 Phase 4d 注入的 **CWE 定义 + CVSS 标准**（Skills 渐进披露），不凭模型记忆。复用 Phase 0 的 `cwe_map.py`。
- **不判真伪**：Analysis 可以说"这看起来是 SQLi 候选、推理如下"，但**不能**输出"已确认 SQLi"——确认权在 Verification。

### 2.4 提示词与工具（落实角色重构步骤 2）

- 提示词（`analysis.py:88-96, 447-476`）：去"禁止全局扫描"、去"优先 Recon 高风险区"、去扫描器编排职责；改为"消费候选列表，逐个读真实代码做 source→sink 推理与 grounded 定级"。
- 工具集（对齐 [tool-redesign-target-set.md](./tool-redesign-target-set.md)）：`read_file`, `grep`, `ast_grep`, `call_graph`, `reachability`, `report_finding` + 按栈条件装配的扫描器（semgrep+taint/bandit/npm_audit/safety/osv）。扫描器在此是**候选来源之一**，不是 Analysis"自主决定跑哪个"的编排对象。

---

## 3. 验收标准

- [ ] **输入对齐**：Analysis 不再读 `high_risk_areas`/`initial_findings`；消费 Recon ProjectMap + Candidate 列表（构造一个 ProjectMap 样例，断言 Analysis 正确解析 sink/路径）。
- [ ] **全覆盖输入**：Candidate 列表覆盖 sink 清单全集（含 reachability=unknown 的，不丢）——记分牌召回↑（#10 解除）。
- [ ] **输出不越界**：Analysis 产出的 `AnalyzedFinding` 恒 `needs_verification=true`、`fidelity=static-only`，无 `is_verified=true`（grep 验证 Analysis 不自封已确认）。
- [ ] **推理结构化**：每条发现的 `reasoning` 含 source/sanitizer/可利用性三问的回答（非散文）。
- [ ] **定级 grounded**：`vulnerability_type` 来自 CWE 标准注入，severity 有 CVSS 依据（不凭记忆）。
- [ ] 记分牌：Analysis 阶段产出的候选数 ≥ sink 数（无遗漏）；交 Verification 后精度由验证阶梯守住。

## 4. 需同步修正的既有 spec

| 文件 | 修正 |
|------|------|
| [agent-role-refactor.md](./agent-role-refactor.md) | Analysis 节补"输入=ProjectMap+Candidate、输出=AnalyzedFinding（不判真伪）"，链接本 spec |
| [phase-1-fp-gating.md](./phase-1-fp-gating.md) | 1c 的 verdict 分层明确：Analysis 出 `static-only`，Verification 升级 fidelity |
| [phase-4-native-tooling-context.md](./phase-4-native-tooling-context.md) | 4b 的 `Finding` schema 增补 `Candidate`/`AnalyzedFinding` 两个中间态模型 |

## 5. 一句话总结

Analysis 应有作用 = **把"结构化骨架找出的候选"转化为"带推理依据、CWE-grounded 定级、但明确未验证的发现"**，是连接"机器枚举的候选"与"真实验证的确认"之间的**推理桥**——不枚举、不扫描编排、不判真伪。
