# 工具集精简（Tool Inventory Rationalization）

> **状态**：未开始 ｜ **性质**：贯穿性——与 Phase 3（检索骨架）、Phase 3-V（验证阶梯）、Phase 4e（工具结构化/合并）高度重合，是它们的"工具清单视角" ｜ **对应诊断**：#1 #12 #14 #18

## 1. 目标（独立闭环）

把当前 **~50 个工具类 / 装配给 Agent 的 Recon 13 + Analysis 21 + Verification 23 个**，精简为**精瘦、单一职责、无语义重叠**的工具集。消除选择困难、判据不一致、伪能力、僵尸工具与噪音装配。

**闭环判据**：每个 Agent 的工具数显著下降（目标 Verification 23→≤8、Analysis 21→≤12）；每个保留工具有唯一职责、无重叠；记分牌不因精简而召回/精度下降（精简是去噪，不是减能力）。

**为什么"减法"有据（三方独立印证，见 [tool-access-and-forms.md](./tool-access-and-forms.md) 关键数据点）**：Anthropic 明示"工具**超过 30–50 个后选对工具的能力显著下降**"；OpenAI 建议"起始**<20 个**"；arXiv「How Many Tools」实测"自适应只呈现 ~7 个即逼近固定 50 个的覆盖率，且选择准确率 87.1%→93.1%"。当前 Analysis 21 / Verification 23 + 大量重叠 + 文本粘贴（token 膨胀）正落在退化区——**减法是直接的准确率手段，不只是整洁**。判定标尺（Anthropic）："**如果一个人类工程师都无法明确说出某情况该用哪个工具，模型更不可能做到**"——18 个同质执行工具、3 个重叠搜索工具均不通过此测试。

## 2. 现状盘点（实际装配，非理论清单）

真正装配在 `api/v1/endpoints/agent_tasks.py:_initialize_tools`（**不是** `config.py:get_agent_type_config`——后者的 `tools=[...]` 名字与现实不符，是**死配置**，见 §5）。

| Agent | 数量 | 工具 |
|-------|------|------|
| Recon | 13 | read_file, list_files, search_code, think, reflect, semgrep_scan, bandit_scan, gitleaks_scan, npm_audit, safety_scan, trufflehog_scan, osv_scan, rag_query |
| Analysis | 21 | base 5 + smart_scan, quick_audit, pattern_match, dataflow_analysis, 7 外部扫描器, query_security_knowledge, get_vulnerability_knowledge, rag_query, security_search, function_context |
| Verification | 23 | base 5 + sandbox_exec, sandbox_http, verify_vulnerability, php/python/javascript/java/go/ruby/shell/universal_code_test(8), test_command_injection/test_sql_injection/test_xss/test_path_traversal/test_ssti/test_deserialization/universal_vuln_test(7), run_code, extract_function, create_vulnerability_report |
| Orchestrator | 2 | think, reflect |

## 3. 决策表（keep / merge / drop）

### 3.1 验证执行工具：18 → 1~2（用户确认：坍缩为单一真实执行原语 + oracle 策略）

**问题**：`php_test/python_test/javascript_test/java_test/go_test/ruby_test/shell_test/universal_code_test`（8 个按语言切）+ `test_command_injection/test_sql_injection/test_xss/test_path_traversal/test_ssti/test_deserialization/universal_vuln_test`（7 个按漏洞类型切）+ `sandbox_exec/run_code/verify_vulnerability`（3 个沙箱）——**全部最终调同一个 `SandboxManager.execute_command`**，是同一能力被切成 18 个面孔，且都带 #14 演戏问题。LLM 面对 18 个语义重叠工具选择困难、判据不一致。

| 动作 | 工具 | 去向 |
|------|------|------|
| **MERGE→`run_in_sandbox`** | php/python/javascript/java/go/ruby/shell/universal_code_test (8), sandbox_exec, run_code | 坍缩为**1 个真实执行原语**（语言由参数/文件后缀决定，不是 8 个工具） |
| **MERGE→oracle 策略** | test_command_injection/test_sql_injection/test_xss/test_path_traversal/test_ssti/test_deserialization/universal_vuln_test (7), verify_vulnerability | 不再是 7+1 个工具，而是 **Phase 3-V 验证阶梯里按漏洞类型的 oracle 判定逻辑**（canary/布尔差分/带外回调…），由 `run_in_sandbox` + oracle 参数驱动 |
| **KEEP** | extract_function | Phase 3-V 需要它抽真实函数字节驱动"加载真实模块"（非誊抄） |
| **KEEP** | create_vulnerability_report | 产出工具，唯一职责 |
| **KEEP（可选）** | sandbox_http | L3 DAST 发真实 HTTP 时需要；可并入 `run_in_sandbox` 的网络模式参数，倾向保留为独立 1 个 |

**结果**：Verification 23 → **≤8**（base 精简后 + run_in_sandbox + sandbox_http + extract_function + create_vulnerability_report + reachability）。

### 3.2 Analysis 工具：去伪能力 + 去检索冗余 + 扫描器按栈装配

| 动作 | 工具 | 理由/去向 |
|------|------|----------|
| **DROP** | smart_scan, quick_audit | 大杂烩（LLM+正则混合），与 semgrep 职责重叠且更弱（#18） |
| **REPLACE** | pattern_match, dataflow_analysis | 伪能力（正则共现 #1）→ Phase 3d 改接真实引擎（call_graph + reachability）；保留名字但换实现，或并入新工具 |
| **MERGE→检索骨架** | rag_query, security_search, function_context | 检索冗余（#12）→ Phase 3b/3e：function_context 由真实 call_graph 取代；rag 仅留 clone_detection（见 3.4） |
| **DROP（默认）** | query_security_knowledge, get_vulnerability_knowledge | 知识库 RAG，前沿模型已超检索片段且自标幻觉源（#12）；默认关，Phase 0 评测定去留 |
| **CONDITIONAL** | bandit_scan, npm_audit, safety_scan, trufflehog_scan, osv_scan | 按 Recon 探明技术栈条件装配（见 3.3） |
| **KEEP** | semgrep_scan(+taint), gitleaks_scan | 通用必备；semgrep 升级 taint 模式（Phase 3a） |
| **ADD** | call_graph, sink_inventory, ast_grep, reachability | Phase 3 的结构化检索骨架 |

**结果**：Analysis 21 → **≤12**（base + semgrep + gitleaks + 条件扫描器 + 检索骨架 4 件 + clone_detection）。

### 3.3 外部扫描器：全量装配 → 按技术栈条件装配（用户确认）

**问题**：7 个扫描器无脑全给 Recon+Analysis，但 `npm_audit` 对 Python 项目、`safety` 对 JS 项目纯噪音，增加 LLM 选择负担与误用。

**动作**：Recon 探明技术栈后，`_initialize_tools` **按栈条件装配**：
- 通用：`semgrep_scan`、`gitleaks_scan`
- Python：`+ bandit_scan`、`+ safety_scan`
- Node.js：`+ npm_audit`
- 多语言/依赖：`+ osv_scan`（按 manifest 存在性）
- `trufflehog_scan`：仅"需验证密钥有效性"时（与 gitleaks 重叠，倾向**默认只留 gitleaks**，trufflehog 设为可选）

### 3.4 RAG 工具：仅留 1 个 niche

| 动作 | 工具 | 去向 |
|------|------|------|
| **KEEP→`clone_detection`** | retrieve_similar_code 包装 | embedding 真正强项（#12，Phase 3b-RAG） |
| **DROP** | rag_query（作主检索）, security_search, retrieve_security_related | 退役，由结构化检索骨架接管 |

### 3.5 僵尸工具：删除（用户确认）

类定义存在但 `_initialize_tools` **从未装配**——删除，消除维护与认知负担（git 历史可追溯）：

| 文件 | 删除的工具 |
|------|-----------|
| `code_analysis_tool.py` | `code_analysis`（CodeAnalysisTool）、`vulnerability_validation`（VulnerabilityValidationTool）— 均未装配 |
| `kunlun_tool.py` | `kunlun_scan`、`kunlun_list_rules`、`kunlun_plugin` — 三件套均未装配（如确需 Kunlun-M 再按栈条件接回，否则整文件删） |
| `agent_tools.py` | `create_sub_agent`、`run_sub_agents`、`send_message`、`wait_for_message`、`view_agent_graph`、`collect_sub_agent_results`、`agent_finish` — 多 Agent 通信族，审计主流程不用（与 Phase 4f 统一通信机制一并处理） |
| `finish_tool.py` | `finish_scan` — 未装配（Orchestrator 用硬编码骨架收尾，见角色重构） |

> 注：删除前用 `grep -rn "工具名"` 全仓确认无运行时引用（仅类定义/导出/测试），避免误删活引用。

### 3.6 思考工具：评估后多半移除（用户确认）

**证据**：`thinking_tool.py` 的 `think._execute` 注释明写"**实际上这个工具不执行任何操作，只是记录思考内容**"；`reflect` 仅回显入参。原生工具调用（Phase 4a/4c）下模型自带推理，二者多为占位空操作、徒增轮次与 token。

**动作**：在 Phase 0 记分牌上做 A/B（带/不带 think·reflect）——
- 若移除后 F1 与召回不降 → **DROP** think、reflect（Orchestrator 改由硬编码骨架 + 真规划决策点，不靠"思考工具"占位）。
- 若某弱 provider 下结构化思考确有增益 → 仅在该 provider 保留，文本兜底路径可留。

## 4. 目标工具集（精简后）

```
检索/定位:  read_file, list_files, grep(精确), ast_grep, call_graph, sink_inventory
静态扫描:   semgrep(+taint), gitleaks  [+ 按栈: bandit/safety/npm_audit/osv]
可达性:     reachability
验证:       run_in_sandbox(+oracle 策略), sandbox_http, extract_function
产出:       create_vulnerability_report, finish
RAG(niche): clone_detection
(评估去留)  think, reflect
```

## 5. 顺带修复：死配置对齐（#18 衍生）

`config.py:get_agent_type_config` 的 `tools=[...]` 列了 `dispatch_agent`/`finish`/`validate_vulnerability`/`sandbox_execute` 等**不存在的工具名**（真名 `agent_finish`/`vulnerability_validation`/`sandbox_exec`），证明它**没被用**——真正装配硬编码在 `_initialize_tools`。两处脱节是 bug 温床。

**动作**：二选一——① 让 `_initialize_tools` 真正消费 `get_agent_type_config` 的工具清单（配置驱动装配，单一真源）；或 ② 删除 `get_agent_type_config` 里的 `tools` 字段，明确装配只在 `_initialize_tools`。倾向 ①（配置驱动更清晰，便于按栈条件装配）。

## 6. 验收标准

- [ ] Verification 工具数 23 → ≤8；18 个执行/测试工具坍缩为 `run_in_sandbox`(+oracle) + sandbox_http + extract_function。
- [ ] Analysis 工具数 21 → ≤12；smart_scan/quick_audit 移除，pattern/dataflow 改接真实引擎，检索冗余收敛。
- [ ] 外部扫描器按技术栈条件装配（Python 项目不再出现 npm_audit，反之亦然）——构造 Py/JS 两个样例验证装配差异。
- [ ] 僵尸工具已删除且 `grep` 确认无运行时引用；既有 951 单测全绿（删除测试对应僵尸工具的用例或迁移）。
- [ ] think/reflect 的 A/B 评测结论已记录；按结论 DROP 或条件保留。
- [ ] `config.py` 与 `_initialize_tools` 的工具清单不再脱节（单一真源）。
- [ ] 记分牌：精简后召回/精度**不下降**（证明砍的是噪音不是能力）；LLM 工具选择错误率↓、token↓。

## 7. 依赖与回滚

- **依赖**：与 Phase 3（call_graph/sink_inventory/reachability/clone_detection 新工具）、Phase 3-V（run_in_sandbox + oracle）、Phase 4e（结构化返回/统一暴露）、Phase 4f（通信族删除）**强耦合**——本文件是这些 Phase 的"工具清单总账"，应与它们同步推进，而非孤立先删。
- **顺序**：僵尸工具删除（3.5）+ 死配置对齐（5）+ 扫描器条件装配（3.3）可**先行独立做**（低风险、即时降噪）；验证工具坍缩（3.1）随 Phase 3-V；检索冗余收敛（3.2/3.4）随 Phase 3。
- **回滚**：删除类工具 git 可恢复；条件装配与工具集变更由 `_initialize_tools` 集中控制，可灰度按 Agent 回退。
