# Phase 1 — 降误报：行号/片段校验 + 稳定指纹去重 + 验证即门禁

> **状态**：未开始 ｜ **前置**：Phase 0（验收需记分牌）｜ **对应诊断**：#7 #8 #9

## 总目标（独立闭环）

阻止**幻觉发现**（伪造行号/片段）与**未验证发现**进入报告，并修复脆弱的去重/合并。精度最高杠杆、低风险、无新基建。

**闭环判据**：Phase 0 记分牌显示**精度↑、召回≥持平**，且"幻觉过滤计数 > 0"。

本阶段含三个可独立验收的子目标：1a、1b 可与 Phase 0 并行开发并独立上线；1c 的"高保真分层"消费端依赖 Phase 3-V 的 `fidelity`，未上 3-V 前先用现有 `verdict` 分层。

---

## 子目标 1a — 行号/片段校验（杀掉伪造位置类误报）

### 目标（闭环）
任何引用了真实文件但**行号越界或 `code_snippet` 不在该位置**的发现，被判为幻觉丢弃；命中但行号有偏移的，吸附到正确行。对应诊断 #8（当前只校验"文件存在"）。

### 实施步骤
1. 新增纯函数 `validate_finding_location(project_root, file_path, line_start, code_snippet) -> (ok: bool, corrected_line: int|None)`：
   - 解析路径（复用 `_save_findings` 已有的相对/绝对路径解析逻辑）。
   - 读文件字节 → 校验 `line_start` 在文件行数范围内。
   - 把 `code_snippet` 与 `line_start` ±5 行窗口做**归一化（折叠空白）**比对；命中则返回 `corrected_line`（吸附），未命中且片段非空 → `ok=False`。
2. 接入两处：
   - `backend/app/api/v1/endpoints/agent_tasks.py` `_save_findings`：扩展 1270-1283 区块，文件存在检查后追加位置校验。
   - `backend/app/services/agent/agents/orchestrator.py` `_normalize_finding`（1201-1208）：把 `_validate_file_path` 升级为 `_validate_finding`，**在合并前**就过滤（早于持久化）。

### 验收标准
- [ ] 单测：构造"行号越界""片段不存在""片段存在但偏移 3 行"三类发现，分别断言 丢弃 / 丢弃 / 吸附到正确行。
- [ ] 记分牌：引用真实文件但伪造位置的 FP 减少（逐条裁决日志可见幻觉过滤计数 > 0）。
- [ ] 真实片段（仅行号偏移）不被误杀——召回不因此下降。

---

## 子目标 1b — 稳定发现指纹去重（修复过度/漏合并）

### 目标（闭环）
用稳定指纹替换子串匹配去重，消除 `sql_injection` 命中 `nosql_injection` 的**过度合并**与"描述前缀相同"的**漏合并**。对应诊断 #7。

### 实施步骤
1. `backend/app/services/agent/agents/orchestrator.py`：替换 931-997 的子串匹配块。
2. 新增 `_finding_fingerprint(f) -> str`：对 `(归一化相对路径, CWE 家族, 归一化 sink 符号, source 类别)` 取哈希。
   - `CWE 家族`由 Phase 0 的 `cwe_map.py` 推导（使 `sql_injection ≠ nosql_injection`）。
   - 按指纹**精确去重**；仅当结构化字段缺失时回退模糊匹配。
3. 保留现有"智能合并/保留更丰富字段"逻辑（968-988），但以指纹为键。

### 验收标准
- [ ] 单测：`sql_injection` 与 `nosql_injection` 同文件同行**不再合并**；同一指纹的两条**正确合并**且保留更丰富字段；描述前缀相同但 sink 不同的两条**不再误并**。
- [ ] 记分牌：去重导致的 FN（漏合并误删）下降；总 TP 不减。

---

## 子目标 1c — 验证即门禁 + 强制裁决

### 目标（闭环）
报告中的每条发现都必须带 `verdict`（+ Phase 3-V 落地后的 `fidelity`），未验证/误报发现不再以全置信度进入报告。对应诊断 #9（当前 `is_verified` 算了但不门禁，且只验 critical/high 子集）。

### 实施步骤
1. `backend/app/services/agent/agents/orchestrator.py` 最终返回处新增 `_finalize_findings()`，分层：
   - `proven-exploited`/`confirmed` → 正常报告；
   - `reachable-unproven`/`likely` → 降级展示（封顶严重度 + 标 `needs_review=True`）；
   - `static-only`/`uncertain`/未验证、`unverifiable`（Docker 不可用）→ 按配置 `report_unverified`（**默认降级**，明标"未真实验证"）；
   - `false_positive` → 排除。
   - **过渡**：Phase 3-V 未落地前，按现有 `verdict`/`is_verified`（verification.py:879）分层；3-V 落地后接入 `fidelity` 字段。
2. `backend/app/services/agent/agents/verification.py` 输入选择（481-549）：新增**强制裁决策略**——进报告的每条都必须带 verdict；低/中危走 Phase 2 的廉价单次 judge 而非跳过。
3. **删自证循环指标**：移除 verification.py:1030 的"验证准确率 = confirmed/总数"，替换为"按保真层级分布"。

### 验收标准
- [ ] 单测：构造 `confirmed`/`likely`/`uncertain`/`false_positive` 四类发现，断言 `_finalize_findings()` 的分层与 `report_unverified` 开关行为正确。
- [ ] 报告中不再出现 `false_positive`；未验证发现明确标注"未真实验证"且严重度被封顶。
- [ ] verification.py:1030 的自证指标已移除。
- [ ] 记分牌：精度↑（未验证 FP 不再满置信进报告），召回≥持平。

---

## 阶段级依赖与回滚

- **依赖**：Phase 0（验收用记分牌）；1c 低/中危裁决路径依赖 Phase 2 的 judge（未就绪前低/中危标 `uncertain` 降级，不阻塞 1c 上线）；1c 高保真分层依赖 Phase 3-V（过渡用 verdict）。
- **回滚**：1a/1b/1c 各自独立，均为局部函数替换 + 新增纯函数，可单独 revert。`report_unverified` 配置开关可一键回到"全部上报"行为做对照。
