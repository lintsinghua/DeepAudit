# Recon Agent 实施规格（侦察层）

> **状态**：设计完成，待采纳 ｜ **性质**：补齐 [agent-role-refactor.md](./agent-role-refactor.md) 中 Recon 的落地缺口 ｜ **对应诊断**：#16（启发式范围闸门=漏报源头）｜ **用户已确认**：Recon 跑 sink_inventory 产出统一地图、Recon 不碰扫描器

## 0. 为什么单独立此 spec

`agent-role-refactor.md` 定了 Recon 的职责方向（采集事实 + sink 清单），但落地有**五个悬空/矛盾点**，导致 Recon 能"不作恶"却不能"充分发挥作用"：
1. `sink_inventory` 归属矛盾（角色重构说"移交 Phase 3c 模块"，工具选型说"装配给 Recon"）。
2. 交接契约（handoff）只说删旧字段，没定义新契约 → Recon 采的事实传不到下游。
3. Recon 与 Analysis 谁触发 sink_inventory 没定 → 重复扫描/清单不一致。
4. Recon 还留 semgrep/gitleaks，与"纯事实采集"冲突 → 可能滑回越界报漏洞。
5. 覆盖报告由谁产出没归位。

本 spec 把这五点钉死。

---

## 1. Recon 的单一职责：建立"项目地图"，不做危险判断

**一句话**：Recon 负责回答"**这个项目是什么样**"（客观事实），**不**回答"**哪里危险**"（那是下游基于真实调用图/可达性的事）。

| 该做（事实采集） | 不该做（已删） |
|----------------|---------------|
| ① **确定性**解析技术栈（读 manifest，不子串猜） | ❌ 输出 `high_risk_areas` 当范围闸门 |
| ② 枚举入口点 | ❌ 报 `initial_findings`（侦察阶段报漏洞） |
| ③ 调用 `sink_inventory` 产出**全量 sink 清单 + 覆盖报告** | ❌ 跑 semgrep/gitleaks 等**找漏洞**的扫描器 |
| ④ 把以上打包成统一"项目地图"交接下游 | ❌ 对"哪里最危险"下判断 |

---

## 2. 五个缺口的钉死方案

### 2.1 sink_inventory 归属（缺口 1+3）：**Recon 跑、产出地图、下游消费**（用户确认）

- `sink_inventory` 是**装配给 Recon 的工具**（不是 Recon 之外的独立 Phase 3c 模块）。`tool-redesign-target-set.md` 的装配为准；`agent-role-refactor.md` 里"移交 Phase 3c SinkInventory"的措辞**修正为**："sink 枚举能力由 `sink_inventory` 工具实现，**在 Recon 阶段调用**，产出纳入项目地图"。
- **触发时机**：Recon 在侦察末期跑一次 `sink_inventory`（技术栈已知 → 可按语言选 sink 签名），产出全量清单。
- **下游不重复扫描**：Analysis/Verification **消费**地图里的 sink 清单，不再各自重跑 sink 枚举（消除重复/不一致）。若下游因新读到文件需补充，走增量而非全量重扫。

### 2.2 交接契约（缺口 2）：定义 `ProjectMap` 作为 Recon→下游的结构化产物

现状 `TaskHandoff`（`base.py:107-232`）字段：`summary/work_completed/key_findings/insights/suggested_actions/attention_points/priority_areas/context_data/confidence`。**重新映射如下**（删旧闸门语义，注入事实地图）：

```
ProjectMap（放入 TaskHandoff.context_data["project_map"]）:
  tech_stack:        {languages[], frameworks[], databases[]}   # 确定性 manifest 解析
  entry_points:      [{type, file, line, method}]               # HTTP/API/WS/cron/MQ
  sink_inventory:    [{file, line, sink_symbol, category}]      # 全量 sink 清单
  coverage_report:   {files_scanned, sinks_found, files_skipped,
                      blind_spots[], engine_contributions{}}    # 见 2.5
  manifests:         [{path, type}]                             # 探测到的依赖清单文件
```

- `TaskHandoff.context_data` 承载 `ProjectMap`（已有 `context_data: Dict` 字段，天然适配）。
- **删除**：`high_risk_areas`/`priority_areas` 的"范围闸门"语义、`key_findings` 里的 `initial_findings`。`priority_areas` 若保留，仅作"reachability 加权排序的弱提示"，**不作硬闸门**（下游不得因此跳过未列文件）。
- `summary` 改为客观画像（"Python/Django 项目，N 个入口点，M 个 sink，覆盖率 X%"），不含危险判断。

### 2.3 扫描器边界（缺口 4）：**Recon 不碰扫描器**（用户确认）

- 从 Recon 工具集**移除 `semgrep_scan`/`gitleaks_scan`**——扫描器只归 Analysis。
- **Recon 最终工具集（6 个）**：`read_file`, `list_files`, `grep`, `ast_grep`, `sink_inventory`, `parse_manifest`（见 2.4）。比 `tool-redesign-target-set.md` 原列的 7 个去掉 semgrep/gitleaks、加 `parse_manifest`。
- 这彻底杜绝 #16 的越界老路——Recon 没有"找漏洞"的能力，只能采集事实。

> **同步修正** `tool-redesign-target-set.md` §3 的 Recon 装配行（去 semgrep/gitleaks，加 parse_manifest）。

### 2.4 技术栈确定性解析（落实角色重构步骤 1）：新增 `parse_manifest` 工具

- 新增工具 `parse_manifest`：读 `package.json`/`go.mod`/`requirements.txt`/`pom.xml`/`composer.json`/`Gemfile`/`Cargo.toml` 等，**确定性**解析语言/框架/依赖，替换 `recon.py:716-746` 的 `if "django" in obs_lower` 子串猜。
- 一个用 Django 但代码无"django"字样的项目，靠 `requirements.txt` 里的 `Django==x` 也能准确识别。
- 框架识别优先级：manifest 声明 > import 语句（tree-sitter）> 文件名启发（最弱，仅兜底）。

### 2.5 覆盖报告产出（缺口 5）：Recon 是覆盖报告的**产出方**

- `sink_inventory` 的覆盖报告（[tool-reliability-and-availability.md](./tool-reliability-and-availability.md) §4b 要求）是 **Recon 项目地图的关键字段**（见 2.2 的 `coverage_report`）。
- Recon 产出后，覆盖率/盲区随地图传给 Orchestrator——**Orchestrator 据此做覆盖回派决策**（Phase 3c：未覆盖的 sink 是否需要补扫/补读）。这让"Recon 建的地图有多完整"成为可见、可决策的信号，而非黑盒。

---

## 3. Recon 重构后的执行流（ReAct → 事实采集）

```
1. list_files(根目录, 浅层)              → 项目结构
2. parse_manifest(探测到的清单文件)       → 技术栈（确定性）
3. grep/ast_grep                         → 入口点枚举（路由/API/WS/cron）
4. sink_inventory(scope=全仓, lang=已知)  → 全量 sink 清单 + 覆盖报告
5. 组装 ProjectMap → TaskHandoff.context_data → 交接 Analysis
```

- 全程**不报漏洞、不跑扫描器、不下危险判断**。
- 提示词同步改：去掉 `high_risk_areas`/`initial_findings`/`recommended_tools` 的产出要求与"猜高风险区"引导（`recon.py:106-156`）；改为"采集客观事实，产出项目地图"。

---

## 4. 验收标准

- [ ] **职责纯净**：Recon 工具集无任何扫描器（grep 确认 semgrep/gitleaks 不在 Recon 装配）；Recon 输出无 `initial_findings`、无作闸门的 `high_risk_areas`。
- [ ] **技术栈准确**：构造"用 Django 但代码无 'django' 字样"的样例，`parse_manifest` 仍从 `requirements.txt` 正确识别（旧子串法会漏）。
- [ ] **地图完整交接**：`ProjectMap` 五字段（tech_stack/entry_points/sink_inventory/coverage_report/manifests）经 `TaskHandoff.context_data` 完整传到 Analysis（下游能读到全量 sink 清单）。
- [ ] **不重复扫描**：Analysis/Verification 消费 Recon 的 sink 清单，不重跑全量 sink 枚举（日志验证 sink_inventory 每次审计仅 Recon 调一次）。
- [ ] **覆盖报告可用**：地图含覆盖率 + 盲区标注；Orchestrator 能据覆盖率做回派决策（Phase 3c）。
- [ ] **记分牌（Phase 0）**：相比现状（启发式闸门），新 Recon 下 **Analysis 覆盖面扩大、召回↑**（#16 漏报源头解除）；精度由 Phase 1-2 门禁守住。

---

## 5. 需同步修正的既有 spec（消除矛盾）

| 文件 | 修正 |
|------|------|
| [agent-role-refactor.md](./agent-role-refactor.md) | Recon 小节步骤 3"sink 枚举移交 Phase 3c SinkInventory" → "sink 枚举由 `sink_inventory` 工具在 **Recon 阶段**调用，产出纳入项目地图" |
| [tool-redesign-target-set.md](./tool-redesign-target-set.md) | §3 Recon 装配行：去 `semgrep_scan`/`gitleaks_scan`，加 `parse_manifest`（7→6 个工具） |
| [phase-3-recall-taint.md](./phase-3-recall-taint.md) | 3c `SinkInventory` 明确为"Recon 调用的 `sink_inventory` 工具"，非独立 Agent 外模块 |

---

## 6. 一句话总结

Recon 应有作用 = **为整个审计建立客观、可信、覆盖率可见的"项目地图"**（技术栈 + 入口点 + 全量 sink 清单 + 覆盖报告），作为下游分析的事实底座。本 spec 通过"Recon 跑 sink_inventory、不碰扫描器、用 ProjectMap 交接、产出覆盖报告"四件事，把它从"越权导航员"（猜高风险区、钳死覆盖面）拉回"可靠制图员"。
