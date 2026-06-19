# Phase 2 — 降误报（续）：LLM-as-judge 集成 + 置信度校准

> **状态**：未开始 ｜ **前置**：Phase 0（验收）、Phase 1（门禁消费 judge 输出）｜ **对应诊断**：#5

## 1. 目标（独立闭环）

用**怀疑式自一致性**（N 次独立对抗复核 + 多数投票）替换写死的 `0.7`/`0.8` 置信度与单次验证，产出**校准的置信度**，作为 Phase 1c 门禁的可信输入（参考 Semgrep Assistant 的 LLM 三角化思路）。

**闭环判据**：边界发现（置信度 0.4-0.8）经 N 票投票后，记分牌显示**精度↑且召回≥持平**；置信度桶与实测正确率单调相关（校准检查）。

## 2. 实施步骤

### 2.1 新工具 `tools/judge_tool.py` — `VulnerabilityJudgeTool(AgentTool)`
- 输入：一条发现 + 其代码上下文（`line_start` 周围切片，**复用 `FileReadTool`**）。
- 行为：低温下跑 **N 次（默认 3）独立怀疑式复核**，对抗式提示——"假设这是误报，请证明在这段代码里 source 确实未经净化到达 sink"。
- 每次返回结构化 `{verdict, reason, exploitable}`（用 Phase 4b 的结构化输出；4b 未就绪前用 `AgentJsonParser` 解析）。
- 聚合：多数投票 → verdict；一致率 → 校准置信度桶。

### 2.2 置信度校准单一真源 `agent/confidence.py`
- 桶 → 分数映射（如 3/3→0.95，2/3→0.7，分裂→`uncertain`）集中于此。
- 替换散落字面量：`analysis.py:779` 的默认 0.7、`base.py:137` 的 0.8、`verification.py:879` 的阈值。

### 2.3 接入 verification
- 从 `verification.py` 调用 judge：**低/中危的廉价路径**（单/三票）+ **高/危 agentic 验证后的终裁**。
- 注册进验证工具表（`agent/config.py:465`）。

## 3. 成本控制（关键取舍）

- **仅对"决策边界"（置信度 0.4-0.8）做 N 票集成**；极高一致直接采纳、Phase 1a 片段校验失败的直接拒，不进 judge。
- Provider 无关（纯 `chat_completion`），无 LiteLLM 限制。

## 4. 验收标准

- [ ] 单测：构造投票结果 3/3、2/3、1/3、0/3，断言 `confidence.py` 映射出的桶/分数与 verdict 正确。
- [ ] 单测：judge 工具在 mock LLM 下对"明显误报"样例多数投 `false_positive`，对"明显真漏洞"多数投 `confirmed`。
- [ ] 散落的 0.7/0.8 字面量已全部改为引用 `confidence.py`（grep 验证无残留硬编码置信度）。
- [ ] 记分牌：边界发现精度↑、召回≥持平；置信度校准曲线（桶 vs 实测正确率）单调。
- [ ] 成本护栏生效：仅边界发现触发 N 票（日志可见跳过的高/低置信发现数）。

## 5. 依赖与回滚

- **依赖**：Phase 0（验收）；Phase 1c 消费 judge 输出做门禁；结构化输出最好有 Phase 4b（未就绪用 JSON 解析兜底）。
- **回滚**：judge 工具与 `confidence.py` 为新增；接入点可用开关 `judge_enabled` 关闭，回到 Phase 1 的纯 verdict 分层。
