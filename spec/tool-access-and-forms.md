# 工具接入机制 + 工具形式选型（深度分析）

> **状态**：分析完成，建议待采纳 ｜ **性质**：贯穿性，与 [tool-inventory-rationalization.md](./tool-inventory-rationalization.md) 互补——前者管"砍/并/留哪些工具"，本文件管"工具怎么接入、用什么形式" ｜ **对应诊断**：#3 #4 #18
>
> 本文件的"最佳实践"部分依据 Anthropic 官方工程指南（claude-api 技能 `shared/agent-design.md` / `shared/tool-use-concepts.md`）+ 通用 agent 工具研究；外部联网调研的补充引用见文末"引用"节（异步补全）。

---

## 第一部分：当前工具接入机制（逐层读码确认）

### 1.1 调用链全貌

```
agent_tasks.py:_initialize_tools()         ← 硬编码实例化 + 按 Agent 分组装配
  → 每个 Agent 拿到 dict{name: AgentTool}
ReAct 循环 (recon/analysis/verification.py)
  → stream_llm_call(messages)              ← 纯文本，不传 tools
  → LLM 输出文本 "Action: xxx\nAction Input: {...}"
  → _parse_llm_response() 正则抽取          ← 脆弱解析（#3）
  → execute_tool(name, input)  (base.py:1099)
      → tool.execute(**input)  (base.py:84) ← 计时/异常包装
      → ToolResult.to_string()              ← 转成 prose 塞回对话
```

### 1.2 已确认的机制级问题

| 层 | 现状 | 问题 |
|----|------|------|
| **暴露** | 两套并存：`get_tool_descriptions()`（base.py:890，标准 OpenAI JSON schema，**死代码**）vs `get_tools_description()`（base.py:1250，`"- name: desc"` 文本**粘进 prompt**，实际在用） | 模型看不到参数 schema → 只能靠 `_parse_llm_response` 正则兜参数；`args_schema`（Pydantic，每个工具都定义了）几乎白写（#4/#18） |
| **调用** | `stream_llm_call` 不传 `tools=`；走文本 ReAct | malformed-action 解析失败 → 丢工具调用/截断（#3） |
| **分发** | `execute_tool`（base.py:1099）按名字查 dict，硬编码 per-tool 超时（1127-1141），输出**截断到 6000 字符**（1212） | 名字与 LLM 自由文本耦合；超时表是工具名硬编码、易与装配漂移；6000 截断对 SARIF/大输出有损 |
| **返回** | `ToolResult.to_string()`（base.py:33）把 data 转 prose，再拼 metadata 里的 `issues`/`findings`（1206-1209） | 工具产出是**给人看的串**，模型要二次解析；结构化 metadata 被降格成 JSON 字符串塞进 prose |
| **桥接** | `get_langchain_tool()`（base.py:111）做了 LangChain StructuredTool 转换 | **未被使用**——又一处死/孤代码 |
| **装配真源** | 真正装配在 `agent_tasks.py:_initialize_tools` 硬编码；`config.py:get_agent_type_config` 那份 `tools=[...]` 名字对不上（死配置） | 两处脱节（详见 tool-inventory §5） |

**一句话**：接入机制停留在"LLM 吐文本→正则解析→prose 回灌"的最原始形态，而代码里其实**已经备好了结构化的半成品**（`args_schema`、`get_tool_descriptions`、`get_langchain_tool`），只是没接通——和 Phase 4a 的"原生工具调用是死代码"是同一处病根。

---

## 第二部分：工具形式选型——最佳实践与适配

四种工具形式，**不是互斥的，而是按场景分层**。下表给出"是什么 / 何时用 / DeepAudit 该不该用"。

### 2.1 原生 function/tool calling —— ✅ 应作为默认接入形式

- **是什么**：把工具以 JSON schema 通过 API 的 `tools=` 参数交给模型，模型返回结构化 `tool_calls`（name + 校验过的 input），而非自由文本。
- **为何更优**（Anthropic `tool-use-concepts.md` + 通用证据）：消除一整类解析失败；`strict: true` 可保证参数 schema 合法；`tool_choice` 可控制必用/禁用/指定工具。
- **DeepAudit 适配**：这正是 **Phase 4a/4c** 要打通的——`get_tool_descriptions()`（已生成 schema）+ `tool_call_loop()`。**接入形式的首选，地基。**
- **取舍**：LiteLLM 各 provider tool-calling 保真度不一 → 能力门控 + 文本 ReAct 兜底（见 2.5）。

### 2.2 Programmatic Tool Calling / Code-as-Action —— ✅ 高价值，强烈建议用于验证与扫描编排

- **是什么**（Anthropic `agent-design.md` §PTC）：让模型**写一段脚本**在代码执行容器里编排多个工具调用，中间结果留在脚本里、**只把最终输出回灌上下文**。普通 tool-use 是"每调一次一个 round trip + 中间结果全进 context"。
- **为何更优**：当需要**串很多次工具**或**中间结果很大**时，token 随"最终输出"而非"中间结果总量"增长；延迟也降。
- **DeepAudit 适配（关键）**：
  - **验证阶梯（Phase 3-V）天然契合**——"加载真实模块 → 喂 payload → 观测 canary/布尔差分"本就是一段脚本逻辑，用 code-as-action 表达远比 18 个独立 sandbox 工具自然，且与"坍缩 18→1~2"（tool-inventory §3.1）同向。
  - **扫描编排**——"跑 semgrep → 解析 SARIF → 对每条 dataflow 查可达性"也是脚本式编排，PTC 让中间的大块 SARIF 不必整体进 context。
- **取舍**：需要一个代码执行环境（DeepAudit 已有 `SandboxManager`，可复用）；安全上脚本本身要在沙箱里跑。

### 2.3 MCP（Model Context Protocol）—— ⚠️ 当前阶段多半 overkill，按需局部采用

- **是什么**：标准化的"工具/资源 client-server 协议"，让工具能跨 host（Claude Desktop、IDE、各家 agent）复用，而非绑死在一个进程里。
- **何时值得**：当工具要**被多个独立 host 复用**、或要**接第三方现成 MCP server**（如某安全厂商提供 MCP 工具）、或要把工具与主进程**解耦/独立部署**时。
- **DeepAudit 适配判断**：当前工具全是**进程内、单 host（自己的 FastAPI）独占**的——semgrep/sandbox/file 都在自己后端里跑。**为它们套 MCP 只增加协议层、延迟、运维与 prompt-injection 攻击面，不换来跨 host 复用收益**——典型 overkill。
  - **例外/未来**：若要接**外部 MCP 安全工具生态**，或把 sandbox 执行拆成独立服务供多 agent 复用，再局部引入 MCP（且注意 MCP 工具同样要走 2.4 的"工具搜索/分组"避免 context 膨胀，并审计其 prompt-injection 面）。
- **结论**：**不作为本轮改造目标**；记录为"未来若需跨 host/接外部工具生态再引入"。

### 2.4 Agent Skills（SKILL.md 渐进式披露）—— ◐ 用于"知识/流程"，非"可执行工具"

- **是什么**（Anthropic `agent-design.md` §Skills）：每个 skill 是一个含 `SKILL.md` 的文件夹，**简短描述常驻 context，完整内容按需加载**。用于把"任务特定的指令/知识"挡在基础系统提示之外，又不丢可发现性。
- **DeepAudit 适配**：
  - **不适合**当"可执行工具"（semgrep/sandbox 这些是要真执行的，归 function-calling/PTC）。
  - **适合**承载现在塞在系统提示里的**漏洞知识/框架知识/CWE 定级标准**（对应 #17 的 grounding、#12 退役的知识库 RAG）——把"SQLi 怎么判、Django 常见坑、CVSS 标准"做成按需加载的 skill，比常驻 prompt 或 embedding-RAG 都更省 context 且可发现。与 Phase 4d（CWE-grounded 注入）、Phase 4g（context 管理）同向。

### 2.5 纯文本粘贴工具描述（现状）—— ❌ 应废弃为兜底

- 仅在 provider 不支持原生 tool-calling 时作为**降级兜底**保留（Phase 4c 已如此设计），不再作主路径。

---

## 第三部分：工具数量与选择——最佳实践

Anthropic 与通用研究一致结论："**工具太多会让模型混淆，工具集要聚焦**"（`tool-use-concepts.md` §Tips #5 "Limit tool count"）。当前 Analysis 21 / Verification 23 个、且大量语义重叠，正是反面。对策（按 DeepAudit 优先级）：

1. **先做减法**（[tool-inventory-rationalization.md](./tool-inventory-rationalization.md)）：Verification 18→1~2、Analysis 21→≤12、删僵尸、按栈条件装配。**这是最直接的"降混淆"手段。**
2. **工具搜索（Tool Search）**（`agent-design.md` §Scaling）：工具多但每次只用少数时，让模型**按需检索并只加载相关工具 schema**，且**追加而非替换**（保 prompt cache）。DeepAudit 减法后若仍偏多（含按栈装配的扫描器变体），可叠加工具搜索。
3. **分组/命名空间 + 渐进披露**：按角色（已分）+ 按用途命名（`scan_*`/`sandbox_*`/`search_*`），配合 Skills 把"知识类"挪出工具集。
4. **прескриптив描述**（`tool-use-concepts.md`）：描述要写**"何时调用"**而非只写"做什么"（"当需要枚举所有 SQL sink 时用"），近期 Opus 模型对触发条件敏感，能显著提升 should-call 命中。

---

## 第四部分：工具设计——最佳实践对照

| 维度 | 最佳实践（Anthropic/通用） | DeepAudit 现状 | 落点 |
|------|--------------------------|---------------|------|
| 粒度 | 少而可组合 > 多而专用；重叠工具合并 | 18 个执行工具同质、3 搜索重叠 | tool-inventory §3.1/3.2 |
| 命名 | 具体（`get_current_weather`>`weather`） | 尚可，但 `smart_scan`/`quick_audit` 含糊 | tool-inventory §3.2 |
| 描述 | 写"何时调用" + 触发条件 | 现为大段"做什么" + 反例堆砌 | Phase 4d |
| 入参 | JSON schema + enum + 必填标注 + 示例 | `args_schema` 已有但未用于暴露 | Phase 4a/4e |
| 出参 | **结构化** > prose；token 高效；大结果先过滤 | `to_string()` 转 prose + 6000 截断 | Phase 4e（结构化返回）+ 2.2 PTC（大结果不进 context） |
| 错误 | `is_error` + 可行动错误信息 | 已有较详尽错误串（base.py:1217） | 保留，结构化 |
| 网关 | 危险/不可逆动作才升级为 dedicated 工具并加 gating | 验证执行散成 18 工具而非 1 原语 + 策略 | tool-inventory §3.1 |

---

## 第五部分：结论与对既有 spec 的影响

**核心判断**：DeepAudit 的工具问题是**双重的**——既"选得多而杂"（tool-inventory 已覆盖），又"接得原始"（本文件）。两者根因相通：结构化能力（schema/原生调用/PTC）在代码里是半成品或死代码，系统退回最原始的文本粘贴 + 正则。

**形式选型结论（一句话）**：
- **默认形式 = 原生 function-calling**（Phase 4a/4c 打通），文本 ReAct 仅作弱 provider 兜底。
- **验证与扫描编排 = Programmatic Tool Calling / code-as-action**（复用 `SandboxManager`），与"18→1~2"坍缩同向。
- **知识/流程/CWE 标准 = Agent Skills 式渐进披露**（替代常驻 prompt 与知识库 RAG）。
- **MCP = 暂不引入**（进程内单 host，套 MCP 是 overkill），记录为"未来接外部工具生态/拆服务再议"。
- **工具数量 = 先减法（tool-inventory）+ 必要时叠加工具搜索**。

**不新增独立 Phase**，而是强化既有落点：
- Phase 4a/4c：原生 tool-calling 是"接入形式"的地基（已在计划）。
- Phase 4e：补充"**用 PTC/code-as-action 表达验证与扫描编排**"为工具结构化的一部分。
- Phase 3-V：明确验证阶梯**以 code-as-action 实现**，而非堆叠 sandbox 工具。
- Phase 4d/4g：知识类内容用 **Skills 式渐进披露**承载。
- tool-inventory：数量治理 + 必要时工具搜索。

---

## 关键数据点（外部调研交叉佐证）

> 以下数字直接支撑本文件结论，尤其是"工具太多"这一最初直觉——现已有**三方独立印证**。

**工具数量阈值（三方一致，强证据）**：
- **Anthropic（厂商、罕见地给了具体数字）**："Claude 选对工具的能力在**超过 30–50 个可用工具后显著下降**"；典型多 server 配置"在干活前就消耗 ~55k token 在工具定义上"。Tool Search 按需只加载 3–5 个、可扩到 1 万工具、定义 token **降 85%+**、且**追加不替换以保 prompt cache**（`defer_loading: true`）。
- **OpenAI**："起始可用函数**控制在 20 个以内**"（软建议）；大工具集"延迟加载罕用工具"。
- **arXiv「How Many Tools Should an LLM Agent See?」(2026, BoR 指标)**：BFCL 370 工具下，自适应"平均只呈现 ~7 个工具即逼近呈现 50 个的覆盖率（90.3% vs 90.8%）"；下游 Sonnet 上"短自适应列表把选择准确率从固定 5 个的 87.1% 提到 93.1%"，中等难度"76.8% vs 60.9%"。
→ **DeepAudit 的 Analysis 21 / Verification 23 个、且大量重叠 + 文本粘贴（token 膨胀），正落在 30–50 退化区**。先做减法（tool-inventory），catalog 仍大则叠加 Tool Search。

**原生 FC vs 文本 ReAct**：BFCL 把二者明确区分为 "**FC**=原生工具调用" vs "**Prompt**=文本生成的 walk-around"，并记录文本路径"易生成 malformed function calls"——即当前正则解析的脆弱性。`strict: true`（OpenAI/Anthropic）"保证工具调用严格符合 schema，而非尽力而为"。

**Code-as-action 的量化收益**：Anthropic "Code execution with MCP" 的 Drive→Salesforce 例子**从 150,000 token 降到 2,000 token（省 98.7%）**；spreadsheet 过滤"模型只看 5 行而非 10,000 行"。直接对应"扫描器输出是 token firehose"——验证/扫描编排用脚本式更优。

**MCP 安全面（对安全产品尤其重要）**：MCP 规范本身列出 token passthrough 禁止（MUST NOT）、confused deputy、SSRF（169.254.169.254）、session hijacking、本地 server 需沙箱化；独立研究（Invariant Labs "tool poisoning"——工具描述里藏对模型可见、对用户不可见的恶意指令；Simon Willison "lethal trifecta"=私有数据+不可信指令+外泄通道）佐证"为进程内单 host 工具套 MCP 是净负担"。

**安全审计领域特别提示**：被审计的代码**本身就是不可信输入**（可含 prompt injection）→ lethal trifecta 全中。沙箱须 no-network 默认 + workspace-scoped FS + CPU/内存/墙钟上限（Anthropic code-execution 工具：5GiB/1CPU/90s/无网络，可直接照抄）；审计 agent 上下文不放密钥；外泄/破坏性动作需人工确认。

## 引用（URL 级，2026-06-19 调研已核实）

**基准/规范/同行评审**
- ReAct — arXiv:2210.03629 — https://arxiv.org/abs/2210.03629
- Gorilla — arXiv:2305.15334 — https://arxiv.org/abs/2305.15334
- ToolLLM/ToolBench — arXiv:2307.16789 — https://arxiv.org/abs/2307.16789
- Toolformer — arXiv:2302.04761 — https://arxiv.org/abs/2302.04761
- "How Many Tools Should an LLM Agent See?"（BoR）— arXiv:2605.24660 — https://arxiv.org/abs/2605.24660
- Berkeley Function-Calling Leaderboard（ICML 2025）— https://gorilla.cs.berkeley.edu/leaderboard.html ｜ https://gorilla.cs.berkeley.edu/blogs/8_berkeley_function_calling_leaderboard.html
- MCP intro/architecture/security — https://modelcontextprotocol.io/docs/getting-started/intro ｜ https://modelcontextprotocol.io/docs/learn/architecture ｜ https://modelcontextprotocol.io/specification/2025-06-18/basic/security_best_practices

**厂商工程/文档（自报指标已标注）**
- Anthropic, Writing effective tools for AI agents — https://www.anthropic.com/engineering/writing-tools-for-agents
- Anthropic, Code execution with MCP — https://www.anthropic.com/engineering/code-execution-with-mcp
- Anthropic, Equipping agents with Agent Skills — https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
- Anthropic, Effective context engineering — https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic, Multi-agent research system — https://www.anthropic.com/engineering/multi-agent-research-system
- Anthropic, Building effective agents — https://www.anthropic.com/engineering/building-effective-agents
- Anthropic docs — Tool use overview / Tool search tool / Code execution tool — https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview ｜ .../tool-search-tool ｜ .../code-execution-tool
- OpenAI, Function calling — https://developers.openai.com/api/docs/guides/function-calling
- LiteLLM, Function calling（`supports_function_calling()`、`add_function_to_prompt`、`function_to_dict`）— https://docs.litellm.ai/docs/completion/function_call

**独立实践/安全**
- Invariant Labs, MCP tool poisoning — https://invariantlabs.ai/blog/mcp-security-notification-tool-poisoning-attacks
- Simon Willison, MCP prompt injection / lethal trifecta — https://simonwillison.net/2025/Apr/9/mcp-prompt-injection/
- OWASP, MCP Tool Poisoning — https://owasp.org/www-community/attacks/MCP_Tool_Poisoning

> 注：LiteLLM 的 `supports_function_calling(model=...)` / `add_function_to_prompt=True` / `function_to_dict` 正是 Phase 4 "能力门控 + 文本兜底 + 单一 schema 真源"的现成实现路径——provider 无关层不必自造。
