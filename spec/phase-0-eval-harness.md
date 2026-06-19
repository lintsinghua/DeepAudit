# Phase 0 — 评测与基准框架（记分牌）

> **状态**：未开始 ｜ **前置**：无（这是所有阶段的前置）｜ **对应诊断**：#6

## 1. 目标（独立闭环）

建立一套**离线、确定性、可进 CI**的评测框架，能对 DeepAudit 的真实审计流水线输出，按 CWE 给出 **precision / recall / F1 / FP 数 / FN 数**，并把基线指标固化、把回归变成 CI 门禁。

**闭环判据**：能对一个固定语料跑出一份带 per-CWE 指标的报告，并能对"两次运行"输出指标 diff。本阶段**不改任何检测逻辑**——它是度量仪器，独立交付、独立可用。

**为什么必须最先**：当前**零** precision/recall/F1 度量（诊断 #6），任何后续改动都无法证明是改善还是退化。先有记分牌，后面每个阶段才能用实测 delta 说话。

## 2. 范围

- ✅ 语料加载、流水线复用调用、打分、基线固化、CI 门禁、指标 diff 报告。
- ❌ 不动 `agents/`、`tools/`、`llm/` 任何检测逻辑。
- ❌ 不引入对生产运行时的依赖（评测代码独立于 `backend/app`，仅**调用**它）。

## 3. 实施步骤

### 3.1 目录与语料（`backend/eval/`，与 `backend/tests/` 平级）
- `corpus/` 语料加载器，**以标准合成基准为主**（用户已确认）：
  1. **OWASP Benchmark**（Java，~2740 用例，含 ground-truth）——主基准、干净 P/R 信号。
  2. **Juliet / SARD** 按 CWE 子集（C/Java/PHP）——CWE 覆盖广度。
  3. **小规模真实仓库集**（CVEfixes 或手工标注，含已知 CVE 行号范围）——**次要校准层**，观察真实代码上的 FP 行为。
- 统一标签格式 JSONL：`{repo, file, line_start, line_end, cwe, label: vuln|safe}`。
- 语料获取：可重分发的（OWASP Benchmark / Juliet）写**下载脚本**，不 vendoring 进仓库；真实仓库集用 `download_corpus.py` 拉取并转标签。

### 3.2 流水线复用调用（`runner.py`）
- `async def run_eval(corpus, config) -> EvalReport`：**直接复用真实流水线**——按 `backend/app/api/v1/endpoints/agent_tasks.py:508` 调用 `OrchestratorAgent.run(input_data)` 的同款入参，mock 掉 DB/event 层（SSE 不需要）。
- **固定 LLM 配置** + **回放/缓存模式**：按 `messages` 的 hash 缓存 `chat_completion` 响应到 `eval/cache/`，使评测确定性、低成本、可在 CI 离线跑。首次跑真实 LLM 落缓存，后续命中缓存。

### 3.3 打分（`scorer.py`）
- 匹配规则：**(归一化文件路径, 行范围重叠 ±N, CWE 家族匹配)** 把发现匹配到标签。
- `vulnerability_type → CWE` 映射以 `agent_tasks.py:1194` 的 `type_map` 为种子扩展为 `eval/cwe_map.py`（**此映射后续 Phase 1b 指纹、Phase 4d 定级 grounding 复用，须做成单一真源**）。
- 输出：per-CWE 与汇总的 precision / recall / F1 / FP 数 / FN 数 + 混淆表 + **逐条裁决日志**（每个发现判为 TP/FP，每个漏掉的标签判为 FN，附原因）。

### 3.4 基线与门禁（`baselines.json` / `gate.py` / `report.py`）
- `baselines.json`：提交当前流水线的基线指标（首次跑全量得到）。
- `gate.py`：F1 相对基线回退超过容差则 `exit(1)`，供 CI 调用。
- `report.py`：两次运行的指标 diff，输出如 `本次 +6 TP / -3 FP，recall 0.71→0.78`。

### 3.5 CI 接入
- PR 触发：跑**冒烟子集**（50-100 用例），输出**非阻塞**报告评论。
- 夜间触发：跑**全量**语料，`gate.py` 做**阻塞**门禁。

## 4. 验收标准

- [ ] `python -m backend.eval.runner --corpus owasp-benchmark --smoke` 能跑通并产出 `EvalReport`（含 per-CWE P/R/F1）。
- [ ] 回放缓存生效：同一语料 + 同一 LLM 配置**二次运行指标完全一致**（确定性验证）。
- [ ] `scorer.py` 的匹配规则有单测：构造"行号偏移 ±N 内/外""CWE 家族同/异"的样例，断言 TP/FP/FN 判定正确。
- [ ] `baselines.json` 已生成并提交；`gate.py` 在"人为注入一个 F1 回退"的 mock 运行下正确 `exit(1)`。
- [ ] `report.py` 能对两份 `EvalReport` 输出可读的指标 diff。
- [ ] CI 配置：PR 非阻塞报告 + 夜间阻塞门禁就位（可先在分支验证 workflow）。
- [ ] **不触碰** `backend/app` 检测逻辑（diff 仅限 `backend/eval/` 与 CI 配置）；既有 951 单测全绿。

## 5. 依赖与风险

- **依赖**：无（前置）。但 `cwe_map.py` 会被 Phase 1b/4d 复用，须设计为单一真源。
- **风险/取舍**：
  - 合成基准与真实分布有差距 → 用第 3 层真实仓库集校准，报告显式标注"OWASP Benchmark 模式化、易被规则过拟合"的局限。
  - LLM 成本 → 响应缓存 + 冒烟子集做 PR 门禁、全量夜间跑。
  - Java 重语料需先打通 Java 的 tree-sitter/Semgrep 路径 → 可先在系统最擅长的 Python/PHP/JS 上打分，再扩 Java。

## 6. 回滚

纯新增目录 `backend/eval/` + CI 配置，删除即回滚，对生产运行时零影响。
