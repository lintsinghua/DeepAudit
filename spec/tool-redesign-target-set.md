# 代码审计 Agent 工具重新设计与选型（目标工具集）

> **状态**：设计完成，待采纳 ｜ **性质**：正向设计（greenfield）——回答"代码审计 Agent **必须**有哪些工具" ｜ **与 [tool-inventory-rationalization.md](./tool-inventory-rationalization.md) 互补**：那份是"从现状 ~50 个减"，本份是"从能力本质正向定义目标态" ｜ **依据**：[tool-access-and-forms.md](./tool-access-and-forms.md)（形式选型 + 30–50 阈值证据）、[agent-role-refactor.md](./agent-role-refactor.md)（角色职责）、[phase-3v-verification-ladder.md](./phase-3v-verification-ladder.md)（验证阶梯）

## 0. 设计原则（前几轮已确立的结论收口）

1. **从能力本质出发，不修补旧工具**：先问"代码审计需要哪些能力"，再为每个能力选 1 个工具，而非保留 50 个面孔。
2. **单一职责、无重叠**：通过 Anthropic 判定标尺——"人类工程师能否明确说出某情况该用哪个工具"；不通过即合并。
3. **数量压到阈值内**：每 Agent ≤ ~10（证据：Anthropic 30–50 退化、OpenAI <20、arXiv 自适应 ~7）。
4. **形式分层**：可执行工具→原生 function-calling；多步编排/大输出→code-as-action（脚本）；知识/标准→Skills 渐进披露（非工具）；MCP 暂不引入。
5. **结构化检索骨架取代 RAG**：定位靠 call_graph + sink_inventory + grep/ast_grep，RAG 退为 niche。
6. **验证靠真实 oracle**：单一真实执行原语 + 按漏洞类型的 oracle 策略，非 18 个仿制工具。
7. **结构化输入输出**：schema 暴露、结构化返回、token 高效（大输出在 code-as-action 内过滤）。

---

## 1. 代码审计的能力域分解

一次安全审计 Agent 的完整工作流，本质只需要 **6 类能力**：

| # | 能力域 | 这一步在做什么 | 谁主要用 |
|---|--------|--------------|---------|
| A | **代码导航/检索** | 理解项目结构、精确定位代码 | 全部 |
| B | **危险点枚举** | 找出仓库中**全部** sink（保证覆盖、降漏报） | Recon→Analysis |
| C | **静态扫描（召回）** | 专业工具跑出候选漏洞 + 数据流路径 | Analysis |
| D | **可达性/数据流** | 判 source→sink 是否真的可达、sanitizer 是否有效 | Analysis + Verification |
| E | **真实验证（oracle）** | 用真实执行 + 副作用观测确认漏洞 | Verification |
| F | **产出/编排** | 报告发现、阶段调度、收尾 | Orchestrator + 全部 |

> 注意：能力域里**没有"漏洞知识/CWE 定级标准"**——那不是工具，是 **Skills 渐进披露**承载的知识（见 §4）。也没有"LLM 推理判断"——那是 Analysis 的本职思考，不需要工具。

---

## 2. 目标工具集（按能力域，MUST / SHOULD / OPTIONAL）

**必要性分级**：`MUST` = 没有它审计不成立 ｜ `SHOULD` = 显著提升召回/精度 ｜ `OPTIONAL` = 特定场景/可后置。

### A. 代码导航/检索

| 工具 | 级别 | 单一职责 | 形式 | 输入→输出 | 取代/来源 |
|------|------|---------|------|----------|----------|
| `read_file` | **MUST** | 读文件指定行范围的真实字节 | FC | path,start,end → 带行号代码 | 保留（现 FileReadTool） |
| `list_files` | **MUST** | 列目录结构（**仅结构，不遍历找内容**） | FC | dir,depth → 文件树 | 保留（现 ListFilesTool） |
| `grep` | **MUST** | 精确字符串/正则搜索（找确定符号） | FC | pattern,glob → 命中行 | 保留并正名（现 search_code/FileSearchTool） |
| `ast_grep` | **SHOULD** | 结构化语法搜索（"所有 `execute(` 调用"） | FC | ast_pattern,lang → 命中节点 | 新增（复用 `sgconfig.yml`/pattern_tool 实现底座） |
| `call_graph` | **SHOULD** | 查函数的 caller/callee（**真实 AST 调用图**） | FC | symbol,file → 调用边 | 新增（Phase 3b，取代伪 `function_context`/`retrieve_function_context`） |

### B. 危险点枚举

| 工具 | 级别 | 单一职责 | 形式 | 输入→输出 | 取代/来源 |
|------|------|---------|------|----------|----------|
| `sink_inventory` | **MUST** | **多引擎并集**枚举 sink（tree-sitter 签名库 ∪ Semgrep taint sink ∪ 可选 CodeQL），产出 `(file,line,sink_symbol)` 清单 + **覆盖报告 + 盲区标注** | FC | scope → sink 清单 + 覆盖率 | 新增（Phase 3c，取代 Recon 文件名启发式 `high_risk_areas` + 退役 `retrieve_security_related`） |

> 这是**降漏报的核心**：覆盖不再由 LLM 猜的"高风险区"钳死。**注意完备性边界**——静态无法枚举动态构造的 sink（反射/eval/运行时路由），故 sink_inventory **输出覆盖报告并显式标注盲区**，不假装"枚举全部"；详见 [tool-reliability-and-availability.md](./tool-reliability-and-availability.md) §4。

### C. 静态扫描（召回）

| 工具 | 级别 | 单一职责 | 形式 | 装配条件 | 取代/来源 |
|------|------|---------|------|---------|----------|
| `semgrep_scan` | **MUST** | 多语言静态分析 + **taint 模式 + SARIF dataflow** | FC（结果大→可经 code-as-action 过滤） | 通用 | 升级（Phase 3a，现 SemgrepTool 加 taint/SARIF） |
| `gitleaks_scan` | **MUST** | 密钥/凭证泄露 | FC | 通用 | 保留 |
| `bandit_scan` | SHOULD | Python 专项 | FC | **仅 Python 项目** | 保留 + 按栈条件装配 |
| `npm_audit` | SHOULD | Node 依赖漏洞 | FC | **仅 package.json** | 保留 + 条件装配 |
| `safety_scan` | SHOULD | Python 依赖漏洞 | FC | **仅 requirements.txt** | 保留 + 条件装配 |
| `osv_scan` | OPTIONAL | 多语言依赖漏洞 | FC | 按 manifest 存在 | 保留 + 条件装配 |
| `kunlun_scan` | OPTIONAL | PHP/Java 深度 | FC | 按栈、大项目 | 仅按需接回（否则随僵尸删） |

> **删**：`trufflehog_scan`（与 gitleaks 重叠，默认只留 gitleaks）。**全部按 Recon 探明技术栈条件装配**，不再无脑全给。

### D. 可达性/数据流

| 工具 | 级别 | 单一职责 | 形式 | 输入→输出 | 取代/来源 |
|------|------|---------|------|----------|----------|
| `reachability` | **MUST** | **多引擎交叉**判 source→sink 是否存在无有效 sanitizer 的路径（Semgrep taint ∪ 自建调用图 ∪ 可选 CodeQL，任一报可达即候选） | FC | finding/sink → reachable**候选** + 路径 | 新增（Phase 3a `ReachabilityTool`；同时是验证阶梯 L1 门禁） |

> **取代伪 `dataflow_analysis`**（正则共现 #1）。Analysis 用它发现（召回），Verification 用它门禁（精度）。**完备性边界**：静态可达性**理论上不可精确判定**，故 reachability 产出**只作候选**（`reachable-unproven`）——真伪由验证阶梯 L2/L3 **真实执行 oracle** 裁决，reachability 不假装"保证真实可达"；详见 [tool-reliability-and-availability.md](./tool-reliability-and-availability.md) §4。

### E. 真实验证（oracle）

| 工具 | 级别 | 单一职责 | 形式 | 输入→输出 | 取代/来源 |
|------|------|---------|------|----------|----------|
| `run_in_sandbox` | **MUST** | **单一真实执行原语**：在隔离沙箱跑代码/命令，返回真实 stdout/exit/副作用 | **code-as-action**（模型写脚本，oracle 逻辑在脚本里） | code,lang,net_mode → 真实执行结果 + 工件 | **坍缩 18 个**（php/python/.../universal_test + test_sqli/xss/... + sandbox_exec + run_code + verify_vulnerability）→ 1 个 |
| `extract_function` | **MUST** | 从源文件抽**真实函数字节**（驱动"加载真实模块"，禁誊抄） | FC | file,func → 真实函数+依赖 | 保留（验证阶梯 L2 需要） |
| `sandbox_http` | SHOULD | 对**真起的服务**发真实 HTTP（L3 DAST） | FC（或并入 run_in_sandbox 的 net 参数） | method,url,payload → 真实响应 | 保留 1 个（现 SandboxHttpTool） |

> **oracle 策略不是工具**：命令注入查 canary、SQLi 布尔差分、SSRF 带外回调——这些是 `run_in_sandbox` 内 **code-as-action 脚本逻辑** + 验证阶梯（Phase 3-V）的判定规则，不再各开一个工具。`SandboxManager` 基建复用。

### F. 产出/编排

| 工具 | 级别 | 单一职责 | 形式 | 归属 | 取代/来源 |
|------|------|---------|------|------|----------|
| `report_finding` | **MUST** | 产出一条结构化发现（经行号/片段校验 + fidelity 层级） | FC | Finding schema → 入库 | 保留（现 CreateVulnerabilityReportTool，接 Phase 1a/4b） |
| `finish` | **MUST** | 显式结束当前 Agent/审计 | FC | conclusion → 终止信号 | 合并（现 `agent_finish`/`finish_scan` 二合一） |
| `clone_detection` | OPTIONAL | "某确认漏洞在别处有无复制版"（embedding niche） | FC | snippet → 相似位置 | RAG 唯一保留用途（Phase 3b-RAG） |

> **编排不靠工具**：角色重构已定 Orchestrator 的 recon→analysis→verification **骨架硬编码**，LLM 只在真实决策点（预算/覆盖回派/验证分诊）介入——不再有 `dispatch_agent` 这类伪工具，多 Agent 通信族（`create_sub_agent` 等 6 个）随僵尸删除。回派走 Phase 4f 的通信通道。

> **think/reflect**：Phase 0 记分牌 A/B 后多半移除（源码自承"不执行任何操作"）。不列入目标必须集。

---

## 3. 按 Agent 的最终装配（数量进阈值）

| Agent | 目标工具集 | 数量 | 对比现状 |
|-------|-----------|------|---------|
| **Recon**（采集事实 + sink 清单） | read_file, list_files, grep, ast_grep, `sink_inventory`, `parse_manifest` | **6** | 13 → 6 |
| **Analysis**（对候选推理） | read_file, grep, ast_grep, `call_graph`, `reachability`, semgrep_scan(+taint) + 按栈{bandit/npm_audit/safety/osv}, `report_finding` | **~8–10** | 21 → ≤10 |
| **Verification**（对每条负责） | `run_in_sandbox`, `extract_function`, `reachability`, sandbox_http, `report_finding`, finish | **6** | 23 → 6 |
| **Orchestrator**（真规划） | finish（+ 回派走通信通道，非工具） | **1**（+硬编码骨架） | 2 → 1 |

> 每个 Agent 都落在"人类能明确说出该用哪个工具"的可判定范围，且远低于 30–50 退化阈值。按栈条件装配下，单个 Python 项目的 Analysis 实际只见到相关扫描器（≈8 个），不会同时背 npm_audit 等噪音。
>
> **Recon = 6 个工具、不含任何扫描器**（用户确认）：semgrep/gitleaks 只归 Analysis，Recon 纯事实采集（technique 栈/入口/sink/覆盖报告），杜绝越界报漏洞（#16）。Recon 跑 `sink_inventory` 产出统一"项目地图"经 `TaskHandoff.context_data` 交接，下游消费不重扫——完整契约见 [agent-recon-spec.md](./agent-recon-spec.md)。

---

## 4. 形式选型总表（每个能力用什么形式承载）

| 内容 | 形式 | 理由 |
|------|------|------|
| 所有可执行工具（read/grep/scan/report…） | **原生 function-calling**（Phase 4a/4c） | schema 暴露、strict 保证、消除正则解析失败 |
| 验证执行 + 扫描结果编排（跑 semgrep→解析 SARIF→逐条查可达性；加载真实模块→喂 payload→观测 oracle） | **code-as-action**（脚本，复用 `SandboxManager`） | 多步编排 + 大输出（SARIF/扫描）在脚本内过滤，只回灌结论（Anthropic 实测 150k→2k token） |
| 漏洞知识 / 框架坑 / **CWE 定义与 CVSS 定级标准** | **Agent Skills 渐进披露**（非工具） | 按需加载、省 context、可发现；取代常驻 prompt 散文 + 退役的知识库 RAG |
| 跨 host 复用 / 第三方工具生态 | **MCP（暂不引入）** | 进程内单 host 套 MCP 是净负担 + 注入/SSRF 面；记为未来 |

---

## 5. 从现状到目标的映射（删 / 并 / 留 / 新增 / 升级）

| 处置 | 现状工具 | 目标 |
|------|---------|------|
| **坍缩** | php/python/javascript/java/go/ruby/shell/universal_code_test(8) + test_command_injection/sql/xss/path/ssti/deserialization/universal_vuln(7) + sandbox_exec + run_code + verify_vulnerability | → `run_in_sandbox`(1) + oracle 策略 |
| **删（僵尸/重叠）** | code_analysis, vulnerability_validation, kunlun_list_rules, kunlun_plugin, create_sub_agent, run_sub_agents, send_message, wait_for_message, view_agent_graph, collect_sub_agent_results, agent_finish/finish_scan(并为 finish), smart_scan, quick_audit, trufflehog_scan, dataflow_analysis(伪), pattern_match(伪) | 删除或并入 |
| **降级** | rag_query, security_search, function_context, retrieve_security_related, query/get_vulnerability_knowledge | → `clone_detection`(1, OPTIONAL) + 知识转 Skills |
| **留** | read_file, list_files, gitleaks_scan, extract_function, create_vulnerability_report(→report_finding), sandbox_http | 保留（部分正名） |
| **升级** | search_code→`grep`正名; SemgrepTool→加 taint/SARIF; FunctionContextTool→真实`call_graph` | 升级实现 |
| **新增** | `ast_grep`, `sink_inventory`, `reachability` | Phase 3 结构化骨架 |

**净效果**：~50 个工具类 → **约 15 个去重后的工具** + oracle 策略（脚本）+ 知识 Skills。每 Agent 装配从 13/21/23/2 降到 7/≤10/6/1。

---

## 6. 验收标准

- [ ] 每个 Agent 的工具数 ≤ 目标（Recon 6 / Analysis ≤10 / Verification 6 / Orchestrator 1）。
- [ ] 通过"人类可判定"测试：对每个 Agent，任给一个审计子任务，能唯一指出该用哪个工具（无重叠歧义）。
- [ ] 6 类能力域全覆盖：导航/枚举/扫描/可达性/验证/产出各至少 1 个 MUST 工具就位。
- [ ] 验证执行只剩 `run_in_sandbox` 一个真实执行原语；18 个旧执行工具删除且 `grep` 确认无运行时引用。
- [ ] 扫描器按技术栈条件装配（Py 项目不出现 npm_audit，反之亦然）——Py/JS 两样例验证装配差异。
- [ ] 知识类内容由 Skills 承载，不再占常驻 prompt / 不再有知识库 RAG 工具。
- [ ] 记分牌（Phase 0）：精简后**召回/精度不下降**（证明砍的是噪音不是能力），LLM 工具选择错误率↓、token↓。

---

## 7. 与既有 spec 的关系（不重复，各司其职）

- **本文件**：正向定义"目标该有哪些工具"（选型结论）。
- [tool-inventory-rationalization.md](./tool-inventory-rationalization.md)：reduction 视角的 keep/merge/drop 决策表（如何从现状达到本目标）。
- [tool-access-and-forms.md](./tool-access-and-forms.md)：工具**怎么接入**（形式/数量证据/引用）。
- [phase-3-recall-taint.md](./phase-3-recall-taint.md) / [phase-3v-verification-ladder.md](./phase-3v-verification-ladder.md) / [phase-4-native-tooling-context.md](./phase-4-native-tooling-context.md)：新工具（call_graph/sink_inventory/reachability/run_in_sandbox）的**实现落点**。
- [agent-role-refactor.md](./agent-role-refactor.md)：工具装配差异背后的**角色职责**依据。
