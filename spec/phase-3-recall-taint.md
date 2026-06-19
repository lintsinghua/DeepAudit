# Phase 3 — 降漏报 + 升召回：真实污点/可达性 + 调用图 + 覆盖 + RAG 降级

> **状态**：未开始 ｜ **前置**：Phase 0（度量）、Phase 1-2（FP 门禁过滤新候选）｜ **对应诊断**：#1 #2 #10 #11 #12 #13

## 总目标（独立闭环）

把"伪数据流 + 伪调用图 + 启发式范围闸门"换成**真实结构化检索骨架**（taint 可达性 + 真实调用图 + sink 全量清单），系统性消除漏报；同时把 RAG 从"首选骨架"降级为 niche，并把向量索引移出审计关键路径。

**闭环判据**：记分牌**召回↑**（taint/覆盖带来新 TP），精度由 Phase 1-2 门禁守住；审计启动不再有全仓库 embedding 等待。

**放在 Phase 1-2 之后的原因**：新召回出的候选会变多，必须先有 FP 门禁把它们过滤，否则召回↑会被精度↓抵消。

子项内部依赖：`3b-RAG-2`（提速）可**最先独立做**；`3a → 3b → 3c → 3d` 有递进依赖；`3e`（prompt）随 3a-3d 收尾；`3b-RAG`（降级）与 `3b` 同步。

---

## 子目标 3b-RAG-2 — 索引用户可选 + 移出关键路径【快赢，建议最先】

### 目标（闭环）
消除"每次审计开始即同步 embedding 全仓库"的启动延迟；把死配置 `rag_enabled` 接上，默认按需。对应诊断 #13。

### 实施步骤
1. **接上死开关**：`config.py:308` 的 `rag_enabled` 全后端无引用。在 `api/v1/endpoints/agent_tasks.py:761` 索引段外层加 `if rag_enabled:`，并把开关透出到用户配置（`user_config.otherConfig`，766-800 已读取 embedding 配置）+ 前端审计配置项。
2. **默认反转为按需**：审计**默认不索引**（`rag_enabled` 默认 False 或新增 `index_on_audit` 默认 False）。
3. **移出关键路径**：开启 RAG 时索引**不阻塞分析启动**——后台异步索引（复用 `smart_index_directory` 的增量/进度/取消，856-882），分析先用结构化检索跑，RAG 工具就绪后才可用。（倾向后台异步而非懒加载，进度事件已有。）
4. **复用**：`IndexUpdateMode.SMART` 增量、`include_patterns=target_files` 限范围、`cancel_check` 取消全部保留，只改"何时触发 + 是否阻塞"。

### 验收标准
- [ ] `rag_enabled=False` 时审计流程**完全不触发** embedding（日志/计时验证启动无索引段）。
- [ ] `rag_enabled=True` 时索引在后台进行，分析阶段不被阻塞（计时：到首个分析动作的时间不含全量 embedding）。
- [ ] 前端审计配置可见并可切换该开关。
- [ ] 记分牌：召回/精度不因此变化（纯性能改动）；审计端到端启动时延显著下降。

---

## 子目标 3a — Semgrep taint 模式 + SARIF 召回引擎

### 目标（闭环）
用 Semgrep taint 模式枚举 LLM 从未读到的 source→sink 数据流路径（召回），并提供 `ReachabilityTool` 供下游做可达性门禁（精度）。对应诊断 #11，并为 Phase 3-V 的 L1 门禁供能。

### 实施步骤
1. `tools/external_tools.py` `SemgrepTool`：新增 `taint` 模式——启用 taint 规则包 + `--sarif` 输出；解析 SARIF `codeFlows`/`threadFlows` 抽出 **source→sink 路径**（不只 sink 位置），放进 `ToolResult.metadata["dataflows"]`（扩展现有 `metadata["findings"]`）。
2. 新工具 `tools/taint_query_tool.py` `ReachabilityTool`：给定候选发现，回答"是否存在从不可信源到该 sink 的 taint 路径"。设计成**可插拔后端**，便于日后接 CodeQL。

### 验收标准
- [ ] 对一个已知 taint 漏洞样例，`SemgrepTool` taint 模式产出含 source→sink 路径的 `dataflows`。
- [ ] `ReachabilityTool` 对"有路径/无路径"样例分别返回 reachable / not-reachable。
- [ ] 记分牌：召回↑（出现 taint 带来的新 TP）。

---

## 子目标 3b — tree-sitter 真实调用图（替换伪图）

### 目标（闭环）
用真实 AST 调用图替换 `re.findall` 抓括号的伪调用图，支持过程间源→汇遍历。对应诊断 #2、#1（无过程间追踪）。

### 实施步骤
1. 新模块 `rag/call_graph.py` `CallGraphBuilder`：**复用 `TreeSitterParser`**（splitter.py:138，已含 `DEFINITION_TYPES`）抽取函数/方法定义与 AST 调用节点；用 import 语句解析过程内 callee，建邻接表 `{(file,symbol) -> [callee]}`。
2. 重写 `rag/retriever.py` `retrieve_function_context`（413-479）：用真实调用图取 caller/callee，仅跨模块/动态边回退 RAG。
3. 包成 `CallGraphTool` 供 Analysis 过程间遍历。
4. **结构化检索成骨架**：`CallGraphTool` + 3c 的 `SinkInventory` + 3a 的 `ReachabilityTool` 取代 RAG 作主路径；确保有精确 `grep`/`ast_grep` 工具（复用 `pattern_tool.py`/`sgconfig.yml`）供"枚举所有 `execute(` 调用"。

### 验收标准
- [ ] 单测：对多语言样例，`CallGraphBuilder` 正确解析 caller/callee 边（含 import 解析的过程内调用），不再把"任意标识符+左括号"当调用。
- [ ] `retrieve_function_context` 返回的 caller/callee 与 AST 真值一致（对比测试）。
- [ ] 记分牌：跨函数漏洞召回↑。

---

## 子目标 3c — sink 全量覆盖策略

### 目标（闭环）
保证仓库中**每个 sink 至少被分析一次**，消除"Recon 启发式钳死范围"的系统性漏报。对应诊断 #10。

### 实施步骤
1. 新模块 `agent/coverage.py` `SinkInventory`，包装为 **`sink_inventory` 工具，由 Recon 阶段调用**（非独立 Agent 外模块）：用 tree-sitter 签名库 ∪ Semgrep taint sink ∪ 可选 CodeQL **多引擎并集**枚举 sink（把 `code_analysis_tool.py:386-399` 的 sink 正则升级为结构化注册表），产出 `(file, line, sink_symbol)` 清单 + **覆盖报告 + 盲区标注**，纳入 Recon 的 ProjectMap 交接下游（详见 [agent-recon-spec.md](./agent-recon-spec.md)）。
2. `agents/orchestrator.py` 调度跟踪覆盖：消费 Recon 地图里的 sink 清单，sink 区域被分析即标记 visited；有迭代预算且有未访问 sink 则定向派发（多 pass）。把 `analysis.py:468` 的"禁止全局扫描"放宽为"优先高风险，但 Orchestrator 保证 sink 覆盖"。

### 验收标准
- [ ] 对一个含 N 个已知 sink 的样例仓库，审计结束后覆盖跟踪显示 **N 个 sink 全部 visited**（或明确记录未覆盖原因）。
- [ ] 记分牌：因"从未被读"导致的 FN 显著下降。
- [ ] 性能护栏：用调用图按"入口可达性加权"优先 sink，避免盲扫导致的成本爆炸（大仓库迭代数有上限且记录被截断的 sink）。

---

## 子目标 3d — 替换伪 dataflow 工具

### 目标（闭环）
`dataflow_analysis` 的非 LLM 路径从"源/汇文本共现"改为调真实引擎。对应诊断 #1。

### 实施步骤
- `tools/code_analysis_tool.py` `DataFlowAnalysisTool`/`_quick_pattern_analysis`（334-414）：非 LLM 路径改调 `ReachabilityTool`（3a）+ `CallGraphBuilder`（3b）取真实路径，LLM 只做解释/定级。正则共现仅作"无引擎可用"时最末兜底并明确标注低置信。

### 验收标准
- [ ] 对"源汇同文件但无真实数据流"的样例，新逻辑判**无路径**（旧逻辑会误报）。
- [ ] 对"跨函数真实污点"的样例，新逻辑借调用图判**有路径**（旧逻辑会漏）。
- [ ] 记分牌：该工具相关的 FP↓、FN↓。

---

## 子目标 3b-RAG — RAG 降级为 niche（与 3b 同步）

### 目标（闭环）
保留 embedding 基建但把 RAG 用途收窄为两项 niche，退役会制造召回天花板的固定查询串。对应诊断 #12。

### 实施步骤
1. `rag/retriever.py`、`tools/rag_tool.py`、`agent/config.py` 工具注册表：RAG 用途收窄为——① **克隆/近重复检测**（`retrieve_similar_code` retriever.py:481-506 包装成 `CloneDetectionTool`）；② **超大仓库二级排序**（仅当结构化骨架工作量超迭代预算时用，标注弱信号）。
2. `retrieve_security_related`（retriever.py:379-411，固定查询串）**退役**——职责由 `SinkInventory` 精确枚举接管。
3. 知识库 RAG（`agent/knowledge/rag_knowledge.py`）**默认关闭**：前沿模型理解已超检索片段，且该工具自标为幻觉来源（analysis.py:214-237）。保留开关，默认 off，由 Phase 0 评测定去留。

### 验收标准
- [ ] `retrieve_security_related` 不再被审计主流程调用；`CloneDetectionTool` 可用且仅用于克隆检测。
- [ ] 知识库 RAG 默认关闭；开/关两种配置的记分牌对比表明关闭不降召回（佐证降级合理）。

---

## 子目标 3e — 修正 prompt 检索取向

### 目标（闭环）
消除"被 prompt 推向模糊采样"的召回损失，引导用结构化/精确检索。对应诊断 #12。

### 实施步骤
- `prompts/system_prompts.py:196-223`、`agents/analysis.py:88-96`：去掉"`rag_query`/`security_search` 🔥首选"与"`search_code` 严禁作主要搜索"的偏向；改为"定位用 `call_graph`/`sink_inventory`/`grep`/`ast_grep`/`read_file`，RAG 仅用于克隆检测/超大仓辅助"。推荐流程从"RAG 搜关键逻辑"改为"先取 sink 清单 + 入口可达性，再逐个读真实代码"。

### 验收标准
- [ ] 提示词中不再有"RAG 首选/禁用精确搜索"的表述。
- [ ] 记分牌：Analysis 的检索行为转向结构化（工具调用日志可见 sink_inventory/call_graph 优先），召回↑或持平。

---

## 阶段级依赖与回滚

- **依赖**：Phase 0（度量）、Phase 1-2（过滤新候选）。3a 的 `ReachabilityTool` 同时供 Phase 3-V。
- **Docker 取舍**：taint 引擎依赖 Docker（已是硬依赖，经 `SandboxManager`）；taint 每审计跑一次并缓存；CodeQL 经可插拔后端后置。
- **回滚**：各子项独立。3b-RAG-2 是配置开关，可一键回到旧行为；3a-3d 为新增工具/模块 + 局部替换，可分别 revert；3b-RAG 的退役项与知识库开关可配置回退。
