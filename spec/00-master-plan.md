# DeepAudit 生产级硬化方案：提升准确率、降低误报/漏报

> **本文件是总方案（master plan）。** 按阶段拆解的详细实施文档（含独立闭环目标、实施步骤、验收标准、依赖与回滚）见同目录：索引 [README.md](./README.md)；阶段文档 `phase-0` ~ `phase-4` 与贯穿性 [agent-role-refactor.md](./agent-role-refactor.md)。本文件保留完整诊断（20 项）、分阶段设计与风险取舍，作为各实施文档的依据来源。

## Context（背景与目标）

DeepAudit 是一个基于 LLM 多 Agent（Orchestrator → Recon → Analysis → Verification）的代码安全审计系统，技术栈为 FastAPI + LiteLLM（50+ 提供商）+ ChromaDB RAG + tree-sitter + Docker 化外部工具（Semgrep/Bandit/Gitleaks/Kunlun-M）。

经过对核心代码的逐文件核验，系统**基础设施层成熟**（重试、熔断、限流、流式、加密、951 个单测），但**安全检测的"科学性"存在系统性短板**：没有真实数据流分析、没有评测基准、误报过滤只靠"文件是否存在"、验证只标注不门禁、ReAct 靠脆弱正则解析、置信度是 LLM 自报的固定值。这些直接导致误报率和漏报率都无法控制，也无法证明任何改动是改善还是退化。

**目标（用户已确认）**：准确率优先——**降误报与降漏报并重**；评测以**标准合成基准为主**（OWASP Benchmark / Juliet / SARD）；本次交付**完整诊断 + 分阶段实施计划**（不直接写代码）。

**总原则**：先能"度量"，再"降误报"，再"降漏报"，最后"硬化循环"。每个阶段独立可上线，并由第 0 阶段的评测框架验证其 FP/FN 变化。

**检索架构决策（已确认）**：RAG 从"首选检索骨架"**降级为 niche 工具**。理由——embedding top-k 对代码审计是错配：它按相似度*采样*而非按范围*枚举*，结构上就看不全所有 sink，本身即召回天花板（问题 #12）。新骨架 = **结构化检索**（Phase 3 的真实调用图 + sink 全量清单 + taint 可达性）；日常定位 = **agentic 探索**（ls/read/grep + AST，配合 Phase 4 原生工具调用）；**RAG 仅保留**两个 embedding 真正擅长的 niche：① 克隆/近重复检测（"这个漏洞模式在别处有没有复制版"），② 超大仓库（放不进上下文时）的**二级**辅助排序。Phase 3 的结构化检索是这一降级的前提，故 RAG 降级与 Phase 3 同步推进。

---

## 诊断：已验证的代码级问题（均经实际读码确认）

| # | 问题 | 证据（文件:行） | 影响 |
|---|------|----------------|------|
| 1 | **无真实污点/数据流分析**。`dataflow_analysis` 是 LLM 调用，唯一的非 LLM 兜底是正则检查"源样式"和"汇样式"是否**出现在同一段文本**，无过程间、无路径敏感 | `tools/code_analysis_tool.py:334-414` | 漏报（跨函数污点）+ 误报（同文件共现即判风险） |
| 2 | **"调用图"是伪造的**。callee 用 `re.findall(r'\b(\w+)\s*\(', ...)` 抓"任意标识符+左括号"再配 RAG，不是真实调用图 | `rag/retriever.py:413-479` | 跨函数可达性判断不可靠 |
| 3 | **ReAct 靠脆弱正则文本解析**，而非原生工具调用；系统提示在和模型"较劲"（"禁止使用 Markdown"） | `agents/analysis.py:307-383`、`158-174` | 解析失败→丢工具调用→分析截断→漏报 |
| 4 | **原生工具调用是死代码**。`LLMService.chat_completion` 传 `tools=`/读 `tool_calls`，但 `LLMRequest`/`LLMResponse` **根本没有这两个字段**，调用即 `TypeError`；适配器也未转发 | `llm/types.py:48-56, 66-72`；`llm/adapters/litellm_adapter.py:213-301` | 无法用原生 function-calling，被迫走正则 |
| 5 | **置信度未校准**，Analysis 默认写死 `0.7`；无集成、无自一致、无 LLM-as-judge | `agents/analysis.py:779` | 置信度无意义，门禁阈值无依据 |
| 6 | **完全没有评测/基准框架**。951 个后端测试全是基础设施单测（重试/熔断/限流/JSON 解析），**零** precision/recall/F1 度量 | `backend/tests/`（全目录核验） | 无法度量 FP/FN，无法判断改动好坏 |
| 7 | **去重/合并脆弱**。`same_type` 用包含匹配（`sql_injection` 命中 `nosql_injection`）；`similar_desc` 用前 100 字符子串 | `agents/orchestrator.py:931-997` | 既过度合并又漏合并 |
| 8 | **防幻觉只校验"文件存在"**，不校验行号在范围内、不校验 `code_snippet` 真的出现在该位置 | `agents/orchestrator.py:1080-1111`；持久化边界 `api/v1/endpoints/agent_tasks.py:1270-1283` | 引用真实文件但伪造行号/片段的发现可蒙混入库 |
| 9 | **验证只标注不门禁**。`is_verified` 已计算，但 `orchestrator.run()` 返回 `_all_findings` 未按 verdict 过滤；`_save_findings` 也不按 verdict 拦截；且只验证 critical/high 子集 | `agents/verification.py:879-882`；`orchestrator.py` 返回处；`agent_tasks.py:_save_findings` | 未验证/误报发现以全置信度进入报告 |
| 10 | **覆盖不足→漏报**。Analysis 被要求优先 Recon 的文件名启发式高风险区（`*auth*`/`*api*`），且"禁止全局扫描"；叠加迭代上限 + RAG top-k，大片代码可能从未被读 | `agents/analysis.py:447-476`；Recon 启发式 | 系统性漏报，无 sink 全量覆盖保证 |
| 11 | **外部工具能力未用满**。Semgrep 仅 `p/security-audit`，未用 taint 模式 / SARIF dataflow；工具产出与 LLM 发现仅靠上面的字符串去重对齐 | `tools/external_tools.py`（Semgrep 调用与 `metadata["findings"]`） | 既漏报（taint 路径）又难交叉验证 |
| 12 | **RAG 被当成"首选检索骨架"是场景错配**。embedding top-k 检索对审计是反的——按相似度采样而非按范围枚举，结构上看不全所有 sink；prompt 还把 `rag_query` 设为"🔥 首选"、`search_code` "严禁作主要搜索"，主动把 agent 从"精确完整枚举"推向"模糊采样"；知识库示例自身被标注为幻觉来源 | `system_prompts.py:199-213`；`analysis.py:89-96, 214-237`；`rag/retriever.py` 全局 | **放大漏报**（召回天花板）+ 运维负担（embedding provider/ChromaDB/逐仓索引/维度推断 `retriever.py:179-226`） |
| 13 | **向量索引无条件同步卡在审计关键路径上**。每次审计开始即对全仓库 embedding（先索引完才进分析），这是主要延迟来源；且配置开关 `rag_enabled`（`config.py:308`）是**死配置**——全后端无任何引用，开关实际不生效 | `api/v1/endpoints/agent_tasks.py:761-884`（无 `if rag_enabled` 守卫）；`config.py:308`（仅定义未使用） | **审计启动慢**；用户无法关闭这段耗时 |
| 14 | **"验证"在仿制环境里自我验证（核心问题）**。沙箱基建是真的（真起 Docker、隔离到位），但被验证的对象是 **LLM 誊抄/重写的函数 + LLM 自己写的 mock + LLM 自定的判据**。`run_code.py:1-13,90-119` 的 harness 示例明确写"目标函数（从项目代码复制）"；`MockCursor`/`MockArgs`（`sandbox_tool.py:1216-1234`）把决定真伪的依赖 mock 掉；判据是"有输出≈有漏洞"（`sandbox_tool.py:1017-1021`、`:1155`）。Docker 不可用时静默降级为静态臆测（`run_code.py:147-152`）。"验证准确率 = confirmed/总数"（`verification.py:1030`）是自证循环 | `tools/run_code.py`；`tools/sandbox_tool.py:435-518, 999-1238`；`agents/verification.py:751,879,1030` | **伪确认**（假阳被盖章 confirmed）；mock 替换了恰恰决定真伪的依赖；循环论证 |
| 15 | **Orchestrator 名为"大脑"实为固定管线**。提示词一边强调"你是大脑不是执行器"（`:91`），一边把路径写死"先 recon→再 analysis→再 verification，每个通常只调度一次"（`:84-95,101-103`）。用昂贵的 LLM 自主循环执行一条本可硬编码的固定管线；真正的规划职责（按 sink/可达性分配审计预算、决定哪些发现上 L2/L3 验证、覆盖不足回派）全缺失 | `agents/orchestrator.py:28-105` | **付自主 Agent 成本、只得固定管线能力**；规划决策空缺 |
| 16 | **Recon 用启发式猜测当了"范围闸门"，是漏报源头**。核心交付物 `high_risk_areas` 是文件名启发式 + 正则从 observation 抓文件名（`recon.py:748-758`），tech_stack 用 `if "django" in obs_lower` 子串猜（`:716-746`）；下游 Analysis 被要求**优先**这些区域且"禁止全局扫描"→ Recon 猜漏的文件后面再不会看。还越界报 `initial_findings`（侦察阶段就报漏洞，未经分析就进去重池） | `agents/recon.py:106-156, 672-771` | **系统性漏报**（范围被启发式钳死）+ 职责越界 + 关键词计数式"侦察" |
| 17 | **提示词工程是反模式为主**。四个 Agent 都花大段"禁止使用 Markdown"（`recon.py:83-104`、`analysis.py:158-174`）再用 `re.sub` 补救——在和模型较劲而非用原生工具调用让 API 保证结构；few-shot 几乎全是"❌错误/✅正确"反例，缺真实 source→sink 漏洞正例 + CoT 推理链；靠"必须/禁止/🔥首选"强调词堆叠且自相矛盾（既"宁可漏报"又"必须用满所有工具"）；CWE/CVSS 无结构化 grounding，定级凭模型记忆 | `prompts/system_prompts.py`；`agents/{recon,analysis,verification}.py` 系统提示 | 脆弱、互相冲突、定级不可靠 |
| 18 | **工具暴露机制割裂，好的那套是死代码**。`get_tool_descriptions`（`base.py:890-912`）已生成标准 OpenAI function schema 且 `call_llm` 传 `tools=`，但 ReAct Agent 全走 `stream_llm_call`（不传 tools），改用文本版 `get_tools_description` 把工具文档**当散文粘进 prompt**；工具粒度两极（伪能力 `dataflow_analysis` vs 大杂烩 `smart_scan`，且 `rag_query`/`security_search`/`search_code` 三搜索工具职责重叠）；工具返回是带 emoji 的**人类可读串**（`code_analysis_tool.py:121`）而非结构化数据 | `agents/base.py:857-912`；`tools/*`（返回格式） | 模型看不到 schema→参数错误靠正则兜（同 #4）；选择困难；结果需二次解析 |
| 19 | **Agent 通信：抽象最好但单向无回路 + 双机制并存**。`TaskHandoff`（`base.py:107-232`）是真结构化交接（优点），但只能 recon→analysis→verification **单向**传——Verification 发现 Analysis 漏看文件**无法回派重做**（放大 #10）；另有一套更完整的 `MessageBus`/`AgentMessage`（`core/message.py`，带 QUERY/INSTRUCTION/优先级/`to_xml`）但审计主流程不走它，两套并存职责不清；handoff 的 `key_findings`/`priority_areas` 是上游 LLM 自报的**有损摘要**；`confidence` 写死 0.8（`base.py:137`，同 #5 毛病） | `agents/base.py:107-232`；`core/message.py` | 无反馈回路→漏报；双机制冗余；二手有损信息 |
| 20 | **上下文管理：有损正则压缩 + 无 caching + 状态全塞文本流**。`MemoryCompressor._extract_key_info`（`memory_compressor.py:236-319`）压缩旧消息靠 `if "sql" in text` 抓类型、`re.search(r'action:\s*(\w+)')` 抓工具名，拼成摘要串——**真实代码片段/行号/数据流细节全丢**；单一阈值（100K/最近15条/90%）无内容分级、无 provider 感知；`prompt_cache.py` 存在但未接主循环，几千 token 系统提示每轮重发；根因是整个状态塞进一条 `_conversation_history` 文本流（`analysis.py:482`）才被迫有损压缩 | `llm/memory_compressor.py`；`agents/base.py:926-951`；`agents/*.py` 对话历史 | 压缩丢关键审计信息→漏报/上下文断裂；token 浪费 |

**可复用资产**（避免重复造轮子）：`TreeSitterParser`（`rag/splitter.py:138`，多语言、异步、已含定义/导入节点类型）可建真实调用图；`SandboxManager.execute_tool_command`（`tools/sandbox_tool.py:222`）可跑 Docker 化引擎；`AgentTool`/`ToolResult` 基类 + 工具注册表（`agent/config.py:433-477`）可加工具而不动 Agent 循环；`AgentJsonParser`（`agent/json_parser.py`）可解析结构化输出。

---

## Agent 角色重构（贯穿性，统领 Phase 0-4）

**诊断结论**：四层"侦察→分析→验证→编排"的*划分维度*是对的（XBOW、Project Naptime 均类似分工），但**每个角色的实现都偏离了它本该承担的职责**（问题 #14/15/16 + 前述 #1/#10）。用户已确认：**保留四层，重划每层的单一职责边界**——不改 Agent 数量，让 Phase 0-4 的改动各自归位到正确角色。

| Agent | 现状（错位） | 重构后单一职责 | 归属改动 |
|-------|-------------|---------------|---------|
| **Recon** | 用文件名启发式产出 `high_risk_areas` 当范围闸门（漏报源头）；子串猜技术栈；越界报漏洞 | **纯客观事实采集**：① 从清单文件（`package.json`/`go.mod`/`requirements.txt` 等）**确定性**解析技术栈，不再子串猜；② 入口点枚举；③ 交出**完整 sink 清单**（不再是"高风险区"采样）。**不输出"高风险区"做闸门，不报漏洞** | Phase 3c（`SinkInventory` 接管 sink 枚举）；删 `initial_findings`/`high_risk_areas` 闸门语义 |
| **Analysis** | 一个 Agent 背"扫描器编排+数据流+跨文件推理+真伪判定"四件事，核心能力（过程间追踪）是假的 | **聚焦推理**：对结构化检索/可达性引擎给出的**候选**做上下文推理与定级。把"枚举 sink"交 Recon/SinkInventory、"跑外部工具"交工具层、"判真伪"交 Verification | Phase 3a/3b/3d（真实可达性/调用图喂候选）；Phase 3e（prompt 去"全局扫描禁令"） |
| **Verification** | 角色对（独立验证层是亮点），但在仿制环境演戏；只验 critical/high 子集；结果不门禁 | **对进报告的每条负责**：走验证阶梯（真实 oracle），输出 `fidelity` 层级；不再只挑子集 | Phase 3-V（验证阶梯）；Phase 1c（门禁消费） |
| **Orchestrator** | 假装规划，实为写死的固定管线 | **真规划**：按 sink 清单/可达性**分配审计预算**、跟踪**覆盖**并在不足时**回派** Analysis、决定**哪些发现值得上 L2/L3 验证**（验证分诊）。固定的"recon→analysis→verification"骨架可硬编码，LLM 只在这些**真实决策点**介入 | Phase 3c（覆盖跟踪/回派）；Phase 1c（验证分诊） |

**一句话**：Recon 退回"采集客观事实 + 全量 sink 清单"、Analysis 专注"对候选推理"、Verification "对每条负责"、Orchestrator 做"预算/覆盖/分诊"的真规划。这样 #10 漏报（范围闸门）、#1 伪数据流、#14 验证演戏、#15 假规划、#16 启发式闸门 都各自归位到对应 Phase 解决，而非散落修补。

---

## 改进方案（分阶段）

### Phase 0 — 评测与基准框架【必须最先落地】

**目标**：让"每个 CWE 的 precision/recall/F1"可度量，并变成回归门禁。没有它，后续一切无法证伪。

**新建 `backend/eval/`**（与 `backend/tests/` 平级，独立于单测套件，可离线/夜间跑）：
- `corpus/` 语料加载器，**以标准合成基准为主**（用户已确认）：
  1. **OWASP Benchmark**（Java，~2740 用例，含 ground-truth）——干净的 P/R 信号、主基准。
  2. **Juliet / SARD** 按 CWE 子集（C/Java/PHP）——CWE 覆盖广度。
  3. **小规模真实仓库集**（CVEfixes 或手工标注，含已知 CVE 行号范围）作为**次要校准层**，专门观察真实代码上的 FP 行为。
  - 标签统一为 JSONL：`{repo, file, line_start, line_end, cwe, label: vuln|safe}`。
- `runner.py`：`async def run_eval(corpus, config) -> EvalReport`，**直接复用真实流水线**——按 `agent_tasks.py:508` 的方式调用 `OrchestratorAgent.run(input_data)`（mock DB/event 层）。关键：固定 LLM 配置 + **回放/缓存模式**（按 message hash 缓存 `chat_completion` 响应），让评测确定性、低成本、可进 CI。
- `scorer.py`：按 **(归一化文件路径, 行范围重叠 ±N, CWE 家族匹配)** 把发现匹配到标签，输出 per-CWE 与汇总的 **precision / recall / F1 / FP数 / FN数** + 混淆表 + 逐条裁决日志。`vulnerability_type → CWE` 映射以 `agent_tasks.py:1194` 的 `type_map` 为种子扩展。
- `baselines.json`（提交基线指标）+ `gate.py`（F1 超容差回退则 CI 失败）+ `report.py`（两次运行的指标 diff：如"本次 +6 TP / -3 FP，recall 0.71→0.78"）。

**影响**：建立 FP/FN 记分牌；后续每阶段都用实测 delta 证明价值。**本阶段不动检测逻辑。**

**取舍**：合成基准与真实代码分布有差距——用第 3 层真实仓库集校准，且在报告中显式标注合成基准的局限（如 OWASP Benchmark 模式化、易被规则过拟合）。LLM 成本用响应缓存 + "冒烟子集（50-100 用例）"做 PR 门禁、全量夜间跑缓解。Java 重的语料需先打通 Java 的 tree-sitter/Semgrep 路径；可先在系统最擅长的 Python/PHP/JS 上打分再扩展。

---

### Phase 1 — 降误报：验证即门禁 + 行号/片段校验 + 稳定指纹

**目标**：阻止未验证与幻觉发现进入报告；修复去重。精度最高杠杆、低风险、无新基建。

**1a. 行号/片段校验（杀掉伪造位置类误报，问题 #8）**
- 文件：`api/v1/endpoints/agent_tasks.py` `_save_findings`（扩展 1270-1283 区块）；同样逻辑上移到 `orchestrator._normalize_finding`（1201-1208），把 `_validate_file_path` 升级为 `_validate_finding`，在合并前就过滤。
- 新增 `validate_finding_location(project_root, file_path, line_start, code_snippet)`：读文件字节 → 校验 `line_start` 在范围内 → 校验归一化（折叠空白）后的 `code_snippet` 确实出现在该行 ±5 行窗口内（命中则把 `line_start` 吸附到匹配行）。非空片段在全文件无匹配 → 判幻觉丢弃。复用该函数已有的路径解析逻辑。

**1b. 稳定发现指纹（修复去重，问题 #7）**
- 文件：`agents/orchestrator.py`，替换 931-997 的子串匹配块。
- 新增 `_finding_fingerprint(f)`：对 `(归一化相对路径, CWE家族, 归一化sink符号, source类别)` 取哈希。`CWE家族` 由 Phase 0 映射推导（使 `sql_injection ≠ nosql_injection`）。按指纹精确去重；仅当结构化字段缺失时才回退模糊匹配。保留现有"智能合并/保留更丰富字段"逻辑（968-988），但以指纹为键。
- 影响：既止住 `sql_injection↔nosql_injection` 的包含式过度合并，又止住"描述前缀相同"导致的漏合并（同时利好 FN）。

**1c. 验证即门禁（问题 #9）**
- 文件：`agents/orchestrator.py` 最终返回处，新增 `_finalize_findings()`，按**保真层级**（见 Phase 3-V 的验证阶梯）+ `verdict`/`is_verified`（`verification.py:879` 已置）分层：`proven-exploited`/`confirmed` → 正常报告；`reachable-unproven`/`likely` → 降级展示（封顶严重度 + 标 `needs_review=True`）；`static-only`/`uncertain`/未验证、`unverifiable`（Docker 不可用）→ 按配置 `report_unverified`（默认降级，明标"未真实验证"）；`false_positive` → 排除。
- 文件：`agents/verification.py` 输入选择（481-549）目前只取 critical/high 或 `needs_verification`。新增**强制裁决策略**：进报告的每条发现必须带 verdict + 保真层级；低/中危用 Phase 2 的廉价单次 judge 而非跳过。
- **删除自证循环指标**：`verification.py:1030` 的"验证准确率 = confirmed/总数"是自我盖章，移除或替换为"按保真层级分布"。
- **取舍**：验证更多发现增加延迟/token——用"低危走廉价 judge、高危才上验证阶梯"分层控制。

> 注：Phase 1c 只做"门禁与分层"的**消费端**；真正把"验证"从仿制环境改成真实 oracle 的是新增的 **Phase 3-V 验证阶梯**（核心问题 #14），与 Phase 3a 可达性引擎合流。

**验证标准**：Phase 0 应显示 **精度↑、召回持平**。

---

### Phase 2 — 降误报（续）：LLM-as-judge 集成 + 置信度校准

**目标**：替换写死的 `0.7` 与单次验证，用"怀疑式自一致性"做 FP 三角验证（参考 Semgrep Assistant 的 LLM 三角化思路）。

- 新工具：`tools/judge_tool.py` `VulnerabilityJudgeTool(AgentTool)`。输入：一条发现 + 其代码上下文（`line_start` 周围切片，复用 `FileReadTool`）。低温下跑 **N 次（默认 3）独立怀疑式复核**（对抗式提示："假设这是误报，请证明在这段代码里 source 确实未经净化到达 sink"），各返回结构化 `{verdict, reason, exploitable}`。多数投票 → verdict；一致率 → 校准置信度桶（3/3→0.95，2/3→0.7，分裂→uncertain）。
- 复用而非新循环：从 `verification.py` 调用——低/中危的廉价路径 + 高/危 agentic 验证后的终裁。注册进验证工具表（`agent/config.py:465`）。
- 置信度校准集中到 `agent/confidence.py`（桶→分数映射唯一来源），替换散落字面量（analysis 默认值、verification.py:879 阈值）。
- **取舍**：N× 调用——仅对"决策边界"（置信度 0.4-0.8）做集成投票；极高一致直接采纳、片段校验失败直接拒。Provider 无关（纯 `chat_completion`），无 LiteLLM 限制。

---

### Phase 3 — 降漏报 + 升召回：真实污点/可达性 + 调用图 + 覆盖【高价值高工作量】

放在记分牌与 FP 门禁之后，使其召回增益可度量、新候选被 Phase 1-2 过滤。

**3a. Semgrep taint 模式 + SARIF 作为召回引擎（问题 #11）**
- 文件：`tools/external_tools.py` `SemgrepTool`。新增 `taint` 模式：启用 taint 规则包 + `--sarif` 输出；解析 SARIF `codeFlows`/`threadFlows` 抽出 **source→sink 数据流路径**（不只是 sink 位置），放进 `ToolResult.metadata["dataflows"]`（该工具已暴露 `metadata["findings"]`，扩展即可）。
- 新工具：`tools/taint_query_tool.py` `ReachabilityTool`：给定候选发现，回答"是否存在从不可信源到该 sink 的 Semgrep taint 路径"。Analysis 用它**发现**（召回），Verification 用它**门禁**（精度）。后端设计成可插拔，便于日后接 CodeQL。
- 影响：taint 枚举 LLM 从未读到的 source→sink 对（FN↓）；无 taint 路径的发现降级（FP↓）。
- **取舍**：依赖 Docker（已是硬依赖，经 `SandboxManager` 管理）；taint 较慢——每次审计跑一次做发现 pass 并缓存。CodeQL 可选（镜像重、需建 DB），靠 `ReachabilityTool` 可插拔后端后置。

**3b. tree-sitter 真实调用图（替换 retriever.py:413-479 伪图，问题 #2）**
- 新模块：`rag/call_graph.py` `CallGraphBuilder`。**复用 `TreeSitterParser`**（splitter.py:138 已有 `DEFINITION_TYPES`）抽取函数/方法定义与 AST 调用节点（而非 `re.findall` 抓括号）；用 import 语句解析过程内 callee，建邻接表 `{(file,symbol) -> [callee]}`。
- 文件：`rag/retriever.py` 重写 `retrieve_function_context`（413-479），调用真实调用图取 caller/callee，仅对跨模块/动态边回退 RAG。
- 新工具：包成 `CallGraphTool` 供 Analysis 做**过程间**源→汇可达性遍历（修复问题 #1 的"无过程间追踪"）。
- **结构化检索成为骨架**：`CallGraphTool` + 3c 的 `SinkInventory` + 3a 的 `ReachabilityTool` 共同取代 RAG 作为代码定位的主路径。新增/确保有精确的 `grep`/`ast_grep` 工具（复用既有 `pattern_tool.py`/`sgconfig.yml`）供"枚举所有 `execute(` 调用"这类精确完整查询。

**3b-RAG. RAG 降级为 niche（问题 #12，与 3b 同步）**
- 文件：`rag/retriever.py`、`tools/rag_tool.py`、`agent/config.py` 工具注册表。保留 embedding/ChromaDB 基建，但把 RAG 的用途收窄为两项：① **克隆/近重复检测**——`retrieve_similar_code`（retriever.py:481-506）保留并包装成 `CloneDetectionTool`，用于"某确认漏洞模式在仓库别处是否有复制版"（embedding 真正的强项，AST/grep 不擅长）；② **超大仓库二级排序**——仅当 sink 清单 + 调用图产出的工作量超出迭代预算时，用 RAG 对剩余区域做相似度加权排序，且明确标注为弱信号。
- `retrieve_security_related`（retriever.py:379-411，按漏洞类型的固定查询串）**退役**——其职责由 `SinkInventory` 的精确 sink 枚举接管（精确且完整，无召回天花板）。
- 知识库 RAG（`agent/knowledge/rag_knowledge.py` 的 `query_security_knowledge`/`get_vulnerability_knowledge`）**默认关闭**：前沿模型对常见漏洞类型的理解已超过检索片段，且该工具自身被标注为幻觉来源（analysis.py:214-237）。保留为可选开关，默认 off，由 Phase 0 评测决定是否有正向贡献再定去留。

**3b-RAG-2. 索引用户可选 + 移出关键路径（问题 #13，优先做——直接解决"启动慢"）**
- **接上死开关**：`rag_enabled`（`config.py:308`）目前全后端无引用。在 `api/v1/endpoints/agent_tasks.py:761` 的索引段外层加 `if rag_enabled:` 守卫，并把开关透出到用户配置（`user_config` 的 `otherConfig`，与 embedding 配置同源，766-800 已读取）+ 前端审计配置项。
- **默认值反转为"按需"**：把审计**默认不索引**（`rag_enabled` 默认 False 或新增 `index_on_audit` 默认 False）。RAG 已降级为 niche，多数审计走结构化检索 + agentic 探索，不需要预先 embedding 全仓库。
- **移出关键路径**：当用户确实开启 RAG（克隆检测/超大仓辅助）时，索引**不再阻塞分析启动**——改为：① 后台任务异步索引（复用现有 `smart_index_directory` 的增量/进度/取消机制，856-882 已具备），分析阶段先用结构化检索跑起来，RAG 工具在索引就绪后才可用；或 ② 首次用到 RAG 工具时**懒加载**索引。二选一，倾向 ①（用户体验更平滑，进度事件已有）。
- **复用而非新写**：`smart_index_directory` 已支持 `IndexUpdateMode.SMART` 增量更新（仅变化文件重嵌）、`include_patterns=target_files` 限范围、`cancel_check` 取消——这些都保留，只改"何时触发 + 是否阻塞"。
- 影响：**直接消除审计启动时的全仓库 embedding 等待**（你反馈的核心痛点）；RAG 变成真正可选、可后台、可懒加载。

**3c. 覆盖策略（问题 #10）**
- 新模块：`agent/coverage.py` `SinkInventory`。分析前用 tree-sitter + 精选 sink 签名表（把 `code_analysis_tool.py:386-399` 的 sink 正则升级为结构化的、分语言的注册表）枚举**全部 sink**，产出 `(file, line, sink_symbol)` 工作清单，由 Orchestrator 保证每个 sink 至少被分析一次——不再只靠 Recon 的文件名启发式。
- 文件：`agents/orchestrator.py` 调度逻辑跟踪覆盖：sink 所在区域被分析即标记 visited；若还有迭代预算且有未访问 sink，定向派发分析（多 pass）。把 analysis.py:468 的"禁止全局扫描"放宽为"优先高风险，但 Orchestrator 保证 sink 覆盖"。
- **取舍**：大仓库多 pass→成本/延迟。用迭代预算 + 借 3b 调用图优先"从入口点可达的 sink"做**可达性加权**覆盖，而非盲扫。

**3d. 替换伪 dataflow 工具（问题 #1）**
- 文件：`tools/code_analysis_tool.py` `DataFlowAnalysisTool`/`_quick_pattern_analysis`（334-414）。非 LLM 路径改为调 `ReachabilityTool`（3a）+ `CallGraphBuilder`（3b）取真实路径，LLM 只做解释/定级。正则共现仅作"无引擎可用"时的最末兜底并明确标注低置信。

**3e. 修正 prompt 的检索取向（问题 #12）**
- 文件：`prompts/system_prompts.py:196-223`（`TOOL_USAGE_GUIDE` 的"辅助工具/代码搜索对比"段）、`agents/analysis.py:88-96`（Analysis 自带的工具优先级段）。
- 去掉"`rag_query`/`security_search` 🔥 首选"与"`search_code` 严禁作主要搜索手段"的偏向；改为引导：**定位用结构化检索/精确搜索**（`call_graph`/`sink_inventory`/`grep`/`ast_grep`/`read_file`），**RAG 仅用于克隆检测和超大仓库辅助**。把推荐流程从"RAG 搜关键逻辑"改为"先取 sink 清单 + 入口可达性，再逐个读真实代码"。
- 影响：直接消除"被 prompt 推向模糊采样"的召回损失；与 3a-3c 的结构化骨架一致。

**3-V. 验证阶梯：从"仿制环境自证"改为"真实 oracle 观测"（核心问题 #14）**

核心理念：**判定真伪的权力从 LLM 手里拿走，交给三样东西——静态可达性引擎、真实依赖、可观测的副作用**。沙箱基建（`SandboxManager`）保留不动，但改用它来"用真实预言机观测真实代码的真实副作用"，而非"验证 LLM 的想法"。LLM 退回它该干的活：决定测什么、构造 payload、解释证据——不再给自己的猜测盖章。

按保真度从低到高分级，**每条发现记录它达到的最高层级**（写入 finding 的 `fidelity` 字段，供 1c 门禁消费）：

- **L0 `static-only`**：仅静态特征命中，无可达性证明。最低，默认降级。
- **L1 `reachable-unproven`（可达性门禁，确定性、不花 LLM、不依赖 Docker）**：用 Phase 3a 的 `ReachabilityTool`（Semgrep taint / 调用图）证明"存在 source→sink 且中间无有效 sanitizer 的路径"。**这是漏洞为真的*必要条件***——无此路径的发现，无论 harness 演出什么都降级。先用它砍掉大批假阳。
- **L2 `proven-exploited`（真实执行 + 语义 oracle）**：要执行就执行**真实代码**——
  - harness 必须 **import 项目真实模块 / `include` 真实文件**（用 `ExtractFunctionTool` 已有的 AST 抽真实函数字节去*驱动加载真实模块*，**禁止 LLM 把函数重写进 harness**）。
  - **mock 只允许出现在"不改变真伪判定"的边界**（stub 掉发邮件/付款/日志）；**严禁 mock 掉决定真伪的依赖**——测 SQLi 不准 mock DB 驱动，测 XSS 不准 mock 转义函数，测命令注入不准用 `MockCursor`/`if "'" in query` 这种循环论证。
  - **判据是真实可观测副作用，不是"有输出≈有漏洞"**：命令注入→在 `network=none` 只读沙箱里真执行 `; touch /tmp/canary_<rand>` 看 canary 是否真被创建（隔离让"真打一发"变安全）；SQLi→沙箱里起**真实临时数据库**（sqlite/postgres）播种数据，用布尔差分（`1=1` vs `1=2` 行数不同）或真实驱动抛错当判据；路径遍历→目标目录外种 canary 看是否被读出；SSRF→真实带外回调监听器；XSS→对真实模板/转义函数喂 payload 检查输出字节（或 headless 浏览器）。
- **L3 `proven-exploited`（真应用 DAST，最高保真）**：仓库自带可运行 `docker-compose`/`Dockerfile` 时，**真起服务、发真实恶意 HTTP、观测真实响应**。对相当一部分 Web 仓库实际可达，应主动尝试。
- **`unverifiable`**：Docker/依赖不可用等——**诚实标注**为此层级并降级，**绝不**把静态臆测伪装成"已验证"（修 `run_code.py:147-152` 的静默降级）。

工件与可复现：把 harness/PoC + 确切命令 + 捕获证据（canary 命中、回调日志、布尔差分）**存档为工件**；不能复现的"确认"不算确认。

- 文件：重写 `tools/run_code.py`（强制真实模块加载 + mock 边界约束）、`tools/sandbox_tool.py:435-518,999-1238`（语义 oracle 替换"有输出即漏洞"、新增 DB/canary/带外回调原语）、`agents/verification.py`（提示词与流程改为走验证阶梯，输出 `fidelity` 层级）；可达性门禁复用 Phase 3a `ReachabilityTool`。
- 影响：**杜绝伪确认**（FP↓，且是当前最严重的可信度问题）；真实证据确认的发现可直接高置信报告；其余诚实降级。
- **取舍（已与用户确认接受）**：真实确认只覆盖"能起真实依赖/真应用"的**子集**，其余诚实降级——**一个被真实证据确认的漏洞，价值远高于一百个被仿制环境盖章的"确认"**。起真实 DB/真应用增加沙箱镜像与时间成本，故按 L0→L3 阶梯**逐级升级、能到哪算哪**，不强求所有发现都到 L2/L3。

---

### Phase 4 — 原生工具调用 + 结构化输出 + 通信与上下文专项【最后做】

**目标**：消除脆弱正则 ReAct（问题 #3）与提示"较劲"，砍掉一整类失败并降延迟。放最后，因其价值需在稳定记分牌上度量。

> **专项总纲（问题 #17-20 同源）**：提示词工程（#17）、工具设计（#18）、Agent 通信（#19）、上下文管理（#20）**不是四个独立问题，而是同一根因的四个投影**——系统把"状态、工具、通信、控制流"全压进一条自然语言对话流，再用正则解析/压缩/补救。最佳实践方向高度一致：**结构化状态 + 原生工具调用 + 结构化交接 + 可回派通信**。4a-4c 解决原生工具调用与结构化输出（地基），4d-4g 在其上分别修复四个面。

**4a. 打通工具链（修死代码，问题 #4）**
- `llm/types.py`：给 `LLMRequest` 加 `tools`/`tool_choice`，给 `LLMResponse` 加 `tool_calls`。
- `llm/adapters/litellm_adapter.py` `_send_request`（213-301）：转发 `tools`/`tool_choice` 进 `litellm.acompletion`，抽出 `choice.message.tool_calls`。LiteLLM 跨提供商归一化 tool-calling。
- `llm/service.py` `chat_completion`（424-476）：字段补齐后即从"调用即报错"变为可用。

**4b. 结构化输出**
- 新模块：`agent/schemas.py`：Pydantic `Finding`/`FindingList`/`Verdict`（finding 形状的唯一真源，取代散落在 analysis/verification/orchestrator/`_save_findings` 的多份定义）。作为 JSON-schema 用于 structured-output/response-format，并校验 LLM 输出，替换 `service.py:596-704` 的多级 JSON 修复链。

**4c. Agent 循环迁移到工具调用（增量、开关控制）**
- `agents/base.py`：在现有文本循环旁加 `tool_call_loop()`——把 `get_tool_descriptions()`（base.py:890 已实现）作为 `tools` 发出，收 `tool_calls`，经现有 `execute_tool`/`call_tool` 分发，结果作为 `role:"tool"` 消息回填。复用全部既有工具接线。
- `analysis.py`/`verification.py`/`orchestrator.py`：当 `config.use_native_tools` 为真时切到 `tool_call_loop()`（按提供商能力门控；不支持的提供商/模型回退正则 ReAct）。**保留正则解析器作为有文档的兜底，不删。**
- 影响：消除 malformed-action 解析失败导致的丢工具调用/截断/漏报（间接但真实利好 FP/FN）；减少重试往返与 markdown 剥离/JSON 修复，降 token 与延迟。
- **关键取舍**：LiteLLM 各提供商 tool-calling 保真度不一（OpenAI/Claude/Gemini 稳；部分 OpenAI 兼容国产端 + Ollama 较弱）——故能力门控 + 保留文本兜底，**绝不硬切**。切默认前先在 Phase 0 框架上逐提供商验证。

**4d. 提示词工程：从"较劲"转向"借力 + grounding"（问题 #17）**
- 文件：`prompts/system_prompts.py`、`agents/{recon,analysis,verification}.py` 系统提示。
- **删反模式**：4a/4c 落地后，原生工具调用由 API 保证结构 → **删掉"禁止 Markdown"段与 `re.sub` 补救**（保留在文本兜底路径里即可）；删"❌错误/✅正确"反例堆砌与强调词轰炸。
- **加正例 + CoT**：注入**少量高质量 source→sink 漏洞正例**（含"为何可达、sanitizer 为何无效"的推理链），替代散文式漏洞清单。
- **CWE/CVSS grounding**：把漏洞类型/定级标准做成**结构化注入**（CWE 定义 + 判定 checklist + severity 标准），定级有据可依而非凭记忆。复用 Phase 0 的 `vulnerability_type→CWE` 映射作为锚。
- **消除自相矛盾**：统一"质量优先 vs 用满工具"的冲突表述（与 3e 的检索取向、角色重构的 Analysis 职责一致）。

**4e. 工具设计：统一 schema 暴露 + 结构化返回 + 合并冗余（问题 #18）**
- **统一走 schema**：4a 打通后，ReAct/工具调用循环统一用 `get_tool_descriptions()`（`base.py:890` 的标准 function schema），**废弃文本版 `get_tools_description` 粘贴**（仅文本兜底保留）。
- **工具返回结构化**：`tools/*` 的 `ToolResult.data` 从带 emoji 的人类可读串改为**结构化字段**（JSON/dataclass），展示层（SSE/前端）再渲染。`metadata` 已是结构化，扩展为主返回。
- **粒度治理**：合并语义重叠的搜索工具（`rag_query`/`security_search`/`search_code` → 结构化检索骨架，见 3b/3e）；伪能力工具（`dataflow_analysis`）改接真实引擎（见 3d）；拆解大杂烩 `smart_scan`/`quick_audit` 为单一职责小工具或明确其定位。
- 复用：`AgentTool`/`ToolResult` 基类与工具注册表（`agent/config.py:433-477`）不动，只改返回内容与暴露路径。

**4f. Agent 通信：加回派/质询通道 + 统一机制（问题 #19）**
- **加反馈回路**：给 `TaskHandoff` 流程加**回派**能力——Verification 判定某发现因上游漏看上下文而无法验证时，可向 Orchestrator 发起"回派 Analysis 重看 X"；Orchestrator 的真规划（角色重构）消费它。支撑 Verification→Analysis 的双向闭环，直接利好 #10 漏报。
- **统一两套机制**：`TaskHandoff`（顺向结构化交接）与 `MessageBus`/`AgentMessage`（`core/message.py`，点对点/质询）**职责划清**——handoff 做阶段交接，MessageBus 做回派/质询；二选一为主干，避免并存冗余。倾向以 MessageBus 承载回派、handoff 承载顺向交接。
- **去 LLM 自报摘要**：handoff 的 `key_findings`/`priority_areas` 改为引用**结构化状态对象**（见 4g）中的可追溯事实，而非上游 LLM 主观挑选的有损摘要。
- `confidence` 写死 0.8（`base.py:137`）→ 接 Phase 2 的校准置信度（与 #5 一并修）。

**4g. 上下文管理：结构化状态外置 + 接 caching（问题 #20）**
- **状态外置（核心）**：新增 `agent/run_state.py` `AuditRunState`——把 **findings、已读文件集、sink 清单与覆盖、handoff 事实**存为**结构化对象**，不再让 `_conversation_history` 文本流承载这些。对话历史只承载**推理过程**。
- **压缩改造**：`MemoryCompressor` 不再用正则抠关键词（`memory_compressor.py:236-319`）——关键事实已在 `AuditRunState` 里无损保存，压缩只需对"近期推理"做摘要，旧推理可安全丢弃。消除"压缩丢代码片段/行号"的漏报风险。
- **接 prompt caching**：把几千 token 的系统提示（安全原则 + 工具指南）接上已存在的 `llm/prompt_cache.py`，避免每轮重发；按 provider 能力开启（Claude/OpenAI 支持）。
- **阈值分级 + provider 感知**：压缩阈值按内容重要性分级、按模型上下文窗口动态调整，替代单一 100K/15 条/90%。
- 影响：消除有损压缩导致的上下文断裂与漏报；降 token/延迟；为 4f 的"引用结构化事实"提供数据源。

---

## 验证 / 评测策略（持续）

- **每个阶段后**跑 `backend/eval/runner.py` 冒烟子集，对 `baselines.json` 做 diff；夜间跑全量。各阶段验收：
  - Phase 1-2：**精度↑、召回≥持平**，幻觉过滤计数 > 0。
  - Phase 3：**召回↑**（taint/覆盖带来新 TP），精度由 Phase 1-2 门禁守住。
  - Phase 4：**F1≥持平且延迟/token↓**，解析失败日志减少；4d-4g 额外看：工具参数错误率↓、上下文压缩不再丢失结构化事实（findings/已读文件在 `AuditRunState` 中可追溯）、prompt cache 命中带来的 token↓、回派回路触发后召回↑。
- `backend/eval/gate.py` 接 CI：PR 上做非阻塞报告，夜间做阻塞门禁。
- 既有 951 个基础设施单测保持不动；为每个新纯函数（`_finding_fingerprint`、`validate_finding_location`、`CallGraphBuilder` 边、SARIF 解析）在 `backend/tests/` 加聚焦单测。

---

## 风险与取舍（汇总）

- **Provider 无关性 vs 原生工具调用（Phase 4）**：能力门控 + 保留正则兜底，永不硬切。
- **集成与验证的成本/延迟（1c、2）**：分层——低危单 judge、边界才 N 票集成、高/危才 agentic 验证 + 评测响应缓存。
- **taint 引擎的 Docker 依赖（Phase 3）**：已是硬依赖（`SandboxManager`）；taint 每审计跑一次并缓存；CodeQL 经可插拔后端后置。
- **合成基准的代表性（Phase 0）**：以真实仓库层校准，报告中显式标注合成基准过拟合风险；先在已支持语言打分再扩 Java。
- **增量性**：所有改动叠加在既有类（`AgentTool`、工具注册表、`LLMService`、`TreeSitterParser`、`SandboxManager`）之上——非重写。两处结构性重构（指纹去重、原生工具调用）相互隔离且开关保护。
- **通信与上下文专项（4d-4g）依赖 4a-4c 地基**：提示词去反模式、工具结构化返回、回派回路、状态外置都建立在原生工具调用打通之上——故 4d-4g 紧随 4a-4c，且同受 `use_native_tools` 能力门控；不支持原生调用的 provider 走文本兜底时，4d 的反模式提示词与有损压缩需保留。`AuditRunState`（4g）是 4f"引用结构化事实"的数据源，须先于 4f 落地。

---

## 关键文件清单

| 阶段 | 文件 | 动作 |
|------|------|------|
| 0 | `backend/eval/`（新建 runner/scorer/corpus/gate/baselines） | 评测记分牌（前置） |
| 1a | `api/v1/endpoints/agent_tasks.py:1270-1283`；`agents/orchestrator.py:1080-1210` | 行号/片段校验 + 升级 `_validate_finding` |
| 1b | `agents/orchestrator.py:931-997` | 稳定指纹去重替换子串匹配 |
| 1c | `agents/orchestrator.py` 返回处；`agents/verification.py:481-549` | `_finalize_findings()` 验证门禁 + 强制裁决 |
| 2 | `tools/judge_tool.py`（新）；`agent/confidence.py`（新）；`agent/config.py:465` | LLM-as-judge 集成 + 置信度校准 |
| 3a | `tools/external_tools.py`（Semgrep taint+SARIF）；`tools/taint_query_tool.py`（新） | 污点召回引擎 + 可达性门禁 |
| 3b | `rag/call_graph.py`（新，复用 `rag/splitter.py:138`）；`rag/retriever.py:413-479` | 真实调用图替换伪图；结构化检索成骨架 |
| 3b-RAG | `rag/retriever.py:379-506`；`tools/rag_tool.py`；`agent/knowledge/rag_knowledge.py`；`agent/config.py` | RAG 降级为 niche：保留克隆检测/超大仓辅助，退役固定查询串，知识库默认关 |
| 3b-RAG-2 | `api/v1/endpoints/agent_tasks.py:761-884`；`agent/config.py:308`；前端审计配置 | **索引用户可选 + 移出关键路径**：接上死开关 `rag_enabled`，默认按需，后台异步/懒加载索引 |
| 3c | `agent/coverage.py`（新）；`agents/orchestrator.py` 调度 | sink 全量覆盖保证 |
| 3d | `tools/code_analysis_tool.py:334-414` | 伪 dataflow 改接真实引擎 |
| 3e | `prompts/system_prompts.py:196-223`；`agents/analysis.py:88-96` | 修正 prompt 检索取向：结构化/精确优先，RAG 退辅助 |
| 3-V | `tools/run_code.py`；`tools/sandbox_tool.py:435-518,999-1238`；`agents/verification.py:751,1030` | **验证阶梯**：真实模块加载 + mock 边界约束 + 语义 oracle（canary/真实DB/带外回调/DAST）+ 保真层级，替换仿制环境自证 |
| 4a | `llm/types.py:48-56,66-72`；`llm/adapters/litellm_adapter.py:213-301` | 补 `tools`/`tool_calls` 字段，打通原生调用 |
| 4b | `agent/schemas.py`（新） | 结构化 Finding 模型 |
| 4c | `agents/base.py`；`analysis.py`/`verification.py`/`orchestrator.py` | `tool_call_loop()`（开关 + 兜底） |
| 4d | `prompts/system_prompts.py`；`agents/{recon,analysis,verification}.py` 系统提示 | 提示词去反模式 + CWE-grounded 正例/CoT |
| 4e | `agents/base.py:857-912`；`tools/*` 返回格式；`agent/config.py:433-477` | 统一 schema 暴露 + 工具结构化返回 + 合并冗余搜索工具 |
| 4f | `agents/base.py:107-232`；`core/message.py` | TaskHandoff 加回派/质询通道 + 统一通信机制 + 接校准置信度 |
| 4g | `agent/run_state.py`（新）；`llm/memory_compressor.py`；`llm/prompt_cache.py`（接入主循环） | 结构化状态外置 + 无损压缩 + prompt caching + 分级阈值 |
