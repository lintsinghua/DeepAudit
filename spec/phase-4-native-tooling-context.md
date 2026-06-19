# Phase 4 — 原生工具调用 + 结构化输出 + 提示词/工具/通信/上下文专项

> **状态**：未开始 ｜ **前置**：Phase 0（在稳定记分牌上度量）｜ **对应诊断**：#3 #4 #17 #18 #19 #20

## 总目标（独立闭环）

消除脆弱正则 ReAct 与提示"较劲"，把"状态/工具/通信/控制流全塞进自然语言对话流再用正则解析/压缩/补救"的根因，改造成**结构化状态 + 原生工具调用 + 结构化交接 + 可回派通信**。放最后，因其价值需在稳定记分牌上度量。

**闭环判据**：记分牌 **F1 ≥ 持平且 token/延迟↓**，malformed-action 解析失败日志显著减少。

**专项总纲（#17-20 同源）**：提示词（#17）、工具（#18）、通信（#19）、上下文（#20）是同一根因的四个投影。**4a-4c 是地基**（打通原生调用 + 结构化输出 + 迁移循环），**4d-4g 在其上分别修复四个面**。

子项依赖：`4a → 4b → 4c`（递进）；`4d/4e/4f/4g` 依赖 4a-4c；其中 **`4g` 的 `AuditRunState` 须先于 `4f`**（4f 引用结构化事实需要它做数据源）。

---

## 子目标 4a — 打通工具链（修死代码）

### 目标（闭环）
让 `chat_completion(tools=...)` 从"调用即 `TypeError`"变为真正可用的原生 function-calling。对应诊断 #4。

### 实施步骤
1. `llm/types.py`：给 `LLMRequest`（48-56）加 `tools`/`tool_choice`，给 `LLMResponse`（66-72）加 `tool_calls`。
2. `llm/adapters/litellm_adapter.py` `_send_request`（213-301）：转发 `tools`/`tool_choice` 进 `litellm.acompletion`，抽出 `choice.message.tool_calls`。
3. `llm/service.py` `chat_completion`（424-476）：字段补齐后即可用。
4. `strict: true`（provider 支持时）——把"工具调用严格符合 schema"从尽力而为变成构造保证，直接消除一整类正则解析失败。

> **provider 无关层用 LiteLLM 现成原语，不自造**（调研确认）：能力门控用 `litellm.supports_function_calling(model=...)`；弱 provider 兜底用 `litellm.add_function_to_prompt = True`（这正是把现有文本/正则路径**降级为门控兜底**的落点）；单一 schema 真源用 `litellm.utils.function_to_dict`（docstring 化函数→OpenAI schema，原生 + 兜底两条路径共用）。架构：归一化 OpenAI 形态工具注册表 → 逐调用能力探测 → {原生 FC + strict} 或 {prompt 注入 + 防御式解析}。

### 验收标准
- [ ] 单测：`chat_completion(tools=[...])` 在 mock LiteLLM 下正确传参并解析 `tool_calls`，不再 `TypeError`。
- [ ] 逐 provider 冒烟（OpenAI/Claude/Gemini）：原生 tool-calling 往返成功。
- [ ] 能力门控生效：`supports_function_calling` 为 False 的 provider 自动走 `add_function_to_prompt` 文本兜底（构造一个 Ollama/弱模型样例验证降级）。
- [ ] strict 模式在支持的 provider 上开启，schema 不符的工具调用被构造性拒绝。

---

## 子目标 4b — 结构化输出

### 目标（闭环）
finding 形状有唯一真源，LLM 输出经 schema 校验，取代多级 JSON 修复链。

### 实施步骤
- 新模块 `agent/schemas.py`：Pydantic `Finding`/`FindingList`/`Verdict`（取代散落在 analysis/verification/orchestrator/`_save_findings` 的多份定义）。作为 JSON-schema 用于 structured-output/response-format，并校验 LLM 输出，替换 `service.py:596-704` 的多级修复链。

### 验收标准
- [ ] `Finding` 模型为唯一真源；各处构造 finding 改用它（grep 验证无平行字典定义残留）。
- [ ] 合法/非法 LLM 输出分别通过/被拒，且报错可定位字段。

---

## 子目标 4c — Agent 循环迁移到工具调用（开关控制）

### 目标（闭环）
ReAct 文本循环旁加原生工具调用循环，能力门控切换，正则解析器保留为兜底。对应诊断 #3。

### 实施步骤
1. `agents/base.py` 加 `tool_call_loop()`：把 `get_tool_descriptions()`（base.py:890）作为 `tools` 发出，收 `tool_calls`，经现有 `execute_tool`/`call_tool` 分发，结果作为 `role:"tool"` 消息回填。
2. `analysis.py`/`verification.py`/`orchestrator.py`：`config.use_native_tools` 为真时切到 `tool_call_loop()`；不支持的 provider 回退正则 ReAct。**保留正则解析器作为有文档的兜底，不删。**

### 验收标准
- [ ] `use_native_tools=True` 下三个 Agent 走原生循环，无 markdown 剥离/JSON 修复。
- [ ] `use_native_tools=False` 或弱 provider 下，正则兜底路径仍可用。
- [ ] 记分牌：malformed-action 导致的丢工具调用/截断减少；token/延迟↓；F1≥持平。

### 取舍
LiteLLM 各 provider tool-calling 保真度不一（OpenAI/Claude/Gemini 稳；部分国产端 + Ollama 弱）→ 能力门控 + 文本兜底，**绝不硬切**；切默认前在 Phase 0 框架逐 provider 验证。

---

## 子目标 4d — 提示词工程：从"较劲"转向"借力 + grounding"

### 目标（闭环）
删反模式（与模型较劲、反例堆砌），加 CWE-grounded 正例 + CoT。对应诊断 #17。

### 实施步骤
- `prompts/system_prompts.py`、`agents/{recon,analysis,verification}.py` 系统提示：
  - **删反模式**：4a/4c 落地后由 API 保证结构 → 删"禁止 Markdown"段与 `re.sub` 补救（仅文本兜底路径保留）；删"❌/✅"反例堆砌与强调词轰炸。
  - **加正例 + CoT**：注入少量高质量 source→sink 漏洞正例（含"为何可达、sanitizer 为何无效"推理链）。
  - **CWE/CVSS grounding**：漏洞类型/定级标准做成结构化注入（CWE 定义 + 判定 checklist + severity 标准），复用 Phase 0 `cwe_map.py` 作锚。
  - **消除自相矛盾**：统一"质量优先 vs 用满工具"的冲突表述（与 3e、角色重构一致）。

### 验收标准
- [ ] 原生路径的提示词中无"禁止 Markdown/❌✅ 反例"残留（文本兜底路径保留）。
- [ ] 定级有 CWE/severity checklist 依据（提示词可见结构化注入）。
- [ ] 记分牌：定级准确性↑（severity 与 ground-truth 一致率提升）；无自相矛盾导致的行为漂移。

---

## 子目标 4e — 工具设计：统一 schema 暴露 + 结构化返回 + 合并冗余

### 目标（闭环）
废弃文本版工具描述粘贴，统一走 schema；工具返回结构化；治理粒度。对应诊断 #18。

### 实施步骤
- **统一 schema**：4a 后统一用 `get_tool_descriptions()`（base.py:890 标准 function schema），废弃文本版 `get_tools_description` 粘贴（仅文本兜底保留）。
- **结构化返回**：`tools/*` 的 `ToolResult.data` 从带 emoji 的人类串改为结构化字段（`metadata` 已结构化，扩展为主返回），展示层（SSE/前端）再渲染。
- **粒度治理**：合并冗余搜索工具（`rag_query`/`security_search`/`search_code` → 结构化检索骨架，见 3b/3e）；伪能力 `dataflow_analysis` 改接真实引擎（见 3d）；拆/明确 `smart_scan`/`quick_audit`。
- 复用 `AgentTool`/`ToolResult` 基类与注册表（`agent/config.py:433-477`），只改返回内容与暴露路径。

### 验收标准
- [ ] 原生路径下工具以 schema 暴露（模型看得到参数定义）；工具参数错误率↓。
- [ ] 至少核心工具返回结构化数据，前端渲染不依赖解析散文串。
- [ ] 冗余搜索工具已合并；`dataflow_analysis` 走真实引擎。

---

## 子目标 4f — Agent 通信：加回派/质询通道 + 统一机制

### 目标（闭环）
给单向流水线加反馈回路，统一两套通信机制，去 LLM 自报摘要。对应诊断 #19。

### 实施步骤
- **回派回路**：给 `TaskHandoff` 流程加回派——Verification 判定某发现因上游漏看上下文而无法验证时，向 Orchestrator 发起"回派 Analysis 重看 X"；Orchestrator 真规划（角色重构）消费它。
- **统一两套机制**：`TaskHandoff`（顺向交接）与 `MessageBus`/`AgentMessage`（`core/message.py`，点对点/质询）职责划清——倾向 MessageBus 承载回派、handoff 承载顺向交接。
- **去自报摘要**：handoff 的 `key_findings`/`priority_areas` 改为引用 `AuditRunState`（4g）的可追溯事实。
- `confidence` 写死 0.8（base.py:137）→ 接 Phase 2 校准置信度。

### 验收标准
- [ ] 端到端：构造"Analysis 漏看某文件"场景，Verification 触发回派 → Orchestrator 重派 Analysis → 该文件被重新分析（召回↑）。
- [ ] 两套机制职责文档化且无重叠调用路径。
- [ ] handoff 内容引用 `AuditRunState` 事实，非 LLM 主观摘要；`confidence` 来自 `confidence.py`。

---

## 子目标 4g — 上下文管理：结构化状态外置 + 接 caching

### 目标（闭环）
把审计状态从对话文本流外置为结构化对象，压缩改为无损，接上 prompt caching。对应诊断 #20。**须先于 4f。**

### 实施步骤
- **状态外置（核心）**：新增 `agent/run_state.py` `AuditRunState`——findings、已读文件集、sink 清单与覆盖、handoff 事实存为结构化对象；`_conversation_history` 只承载推理。
- **压缩改造**：`MemoryCompressor` 不再正则抠关键词（memory_compressor.py:236-319）——关键事实已在 `AuditRunState` 无损保存，压缩只摘要"近期推理"，旧推理可安全丢弃。
- **接 prompt caching**：系统提示（安全原则 + 工具指南）接上 `llm/prompt_cache.py`，避免每轮重发；按 provider 能力开启（Claude/OpenAI）。
- **阈值分级 + provider 感知**：压缩阈值按内容重要性分级、按模型窗口动态调整，替代单一 100K/15/90%。

### 验收标准
- [ ] 压缩后 `AuditRunState` 中的 findings/已读文件/sink 覆盖**零丢失**（构造长对话触发压缩，断言结构化事实完整）。
- [ ] prompt cache 命中：多轮审计的系统提示 token 不重复计费（缓存命中率/ token 节省可见）。
- [ ] 压缩阈值随 provider 窗口调整（不同模型不同触发点）。
- [ ] 记分牌：token/延迟↓；不再有"压缩丢代码片段/行号"导致的上下文断裂/漏报。

---

## 阶段级依赖与回滚

- **依赖**：Phase 0（度量）。4d-4g 依赖 4a-4c 地基，且同受 `use_native_tools` 能力门控；不支持原生调用的 provider 走文本兜底时，4d 反模式提示词与 4g 有损压缩需保留。`AuditRunState`（4g）须先于 4f。
- **回滚**：4a-4c 由 `use_native_tools` 开关控制，可整体回退到正则 ReAct；4d-4g 各自独立，提示词/工具返回/通信/状态改造可分别 revert，正则与文本兜底路径全程保留。
