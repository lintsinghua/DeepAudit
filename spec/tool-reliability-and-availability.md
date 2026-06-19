# 工具可靠性与可用性保障

> **状态**：设计完成，待采纳 ｜ **优先级：最高**——工具选型再好，真实调用报错则等于零 ｜ **对应症状**：用户反馈"很多工具真实调用时都会报错" ｜ **依据**：2026-06-19 本机实测（见 §1）

## 0. 两类"可靠性"必须分开谈

| 类别 | 工具 | "可靠性"含义 | 能否保障 |
|------|------|------------|---------|
| **运行时可用性** | 可执行工具（semgrep/sandbox/外部扫描器） | 调用时不报错、依赖就位 | ✅ **工程问题，可保障**（本文件主体） |
| **分析完备性** | 分析工具（sink_inventory/reachability） | 枚举全部 sink、判定真实可达 | ❌ **理论上不可能 100%**，只能"尽量高 + 显式报告盲区 + oracle 裁决"（§4） |

用户已确认完备性立场：**要求尽量高的完备性**（多引擎交叉最大化覆盖/召回，成本换完备），但接受"100% 不可达"，故采用"多引擎 + 覆盖报告 + 候选 + 真实执行裁决 + ground-truth 度量"的组合。

---

## 1. 实测根因（2026-06-19 本机）——这不是偶发，是结构性单点

```
❌ Docker daemon 不可用/未运行
❌ deepaudit/sandbox:latest 镜像不存在（从未 build）
❌ 本地 CLI：semgrep/bandit/gitleaks/safety/osv-scanner/trufflehog 全部未安装
✅ 仅 npm、docker(二进制) 在
```

**读码确认的依赖链**（`external_tools.py` / `sandbox_*.py` / `run_code.py`）：

```
所有外部扫描 + 所有 sandbox/验证工具（占工具总数一大半）
  → SandboxManager.initialize() → docker.from_env().ping()
  → is_available?  ──否──► 整条链全部 ToolResult(success=False)
  → 镜像 deepaudit/sandbox:latest 起容器
  → semgrep 还需 network_mode="bridge" 联网下载规则
```

**结论**：当前能跑的只剩纯 Python、不碰 Docker 的工具（read_file/list_files/grep/pattern_match）。一大半工具的**唯一执行路径**押在"没起的 Docker + 没 build 的镜像 + 没装的 CLI"上——**这就是"很多工具报错"的全部原因**。这是**部署/依赖问题**，不是工具逻辑问题，但被现架构放大成全线崩溃。

**五个脆弱点**（读码定位）：
1. **Docker 单点**：`is_available=False` → 全线失败（最常见）。
2. **镜像单点**：重镜像（Python+Node+Go+Rust+Java+Ruby+7 安全工具），没 build/没 pull 即不可用。
3. **联网依赖**：Semgrep `network_mode="bridge"` 联网拉规则（external_tools.py:214），离线/内网即失败。
4. **路径/挂载**：`_smart_resolve_target_path` + host 挂载 + 容器内 `/workspace` 映射，一处错即失败。
5. **解析脆弱**：`stdout.find('{')` 找 JSON（external_tools.py:243），任何前置 warning 输出即解析失败。

---

## 2. 目标（独立闭环）

让**每个被装配给 Agent 的工具，在被调用时要么成功、要么返回明确的能力缺失信号**——杜绝"调了才发现底层依赖没有"的运行时崩溃；不可用的工具**在装配阶段就不出现在 Agent 工具集里**。

**闭环判据**：在"Docker 不可用 + 无本地 CLI"的最差环境下，审计仍能跑完（用可用工具的子集），且**无未捕获的工具崩溃**；每个工具有契约测试，CI 可证其可调用。

---

## 3. 实施步骤（运行时可用性）

### 3a. 启动预检 + 能力清单（治本第一步）
- 新增 `agent/tool_health.py` `probe_capabilities() -> CapabilityReport`：审计**启动前一次性**探测——
  - Docker：`docker info` 是否通；`deepaudit/sandbox` 镜像是否存在。
  - 本地 CLI：`semgrep`/`bandit`/`gitleaks`/... 各 `--version` 是否在 PATH。
  - 网络：规则源是否可达（决定 semgrep 联网/离线模式）。
- **装配阶段消费能力清单**：`_initialize_tools` 只装配**探测可用**的工具；不可用的**不进 Agent 工具集**（而非让 LLM 调了才报错）。能力清单透出到 Orchestrator 与前端（"本次审计：semgrep ✅ / sandbox ❌，PoC 验证降级为 reachable-unproven"）。

### 3b. 拆单点：本地优先 + Docker 兜底，且**扫描与执行分离**
- **关键区分**（决定要不要沙箱）：
  - **静态扫描（读代码，安全）**：semgrep/bandit/gitleaks 只**读**目标代码，不执行不可信代码——**根本不需要 Docker 隔离**。优先直接在宿主跑本地 CLI（快、无镜像依赖）。
  - **PoC 执行（跑不可信代码，危险）**：验证阶梯 L2/L3 才**必须**沙箱隔离。
- 每个外部工具改为**多后端可插拔**：`local CLI`（首选，若 §3a 探测到）→ `docker`（兜底，隔离执行 PoC 必走）→ `unavailable`（明确缺失）。复用现有 `SandboxManager` 作为 docker 后端之一。
- 这样：用户只要 `pip install semgrep bandit` 就能让扫描工作，**不必非得 build 重镜像/起 Docker**。

### 3c. 离线化规则
- Semgrep 规则包**预装/预缓存**（镜像内置 or 本地 `~/.semgrep`），`--config` 指向本地规则目录，去掉 `network_mode="bridge"` 的强制联网；联网仅作"更新规则"的可选项。消除脆弱点 #3。

### 3d. 健壮的结果解析
- 外部工具统一用 `--json` 输出到**文件**或用稳健的 JSON 提取（而非 `stdout.find('{')`），semgrep 的 stderr/warning 与 stdout 分离。消除脆弱点 #5。

### 3e. 结构化失败信号（不再塞 prose 让 LLM 猜）
- `ToolResult` 增加 `failure_kind` 枚举：`unavailable`（依赖缺失）/ `bad_input`（参数错）/ `timeout` / `target_error`（目标代码问题）/ `internal`。
- Agent 侧据此分流：`unavailable` → 不重试、走降级路径；`bad_input` → 修参重试；`timeout` → 缩范围。取代现在"在 prose 里 grep '失败'两字"的脆弱判断（analysis.py `_failed_tool_calls`）。

### 3f. 契约测试（CI 防回归）
- 每个工具一个**冒烟用例**：喂一个已知输入、断言关键输出字段（如 semgrep 对一段已知 SQLi 必报、reachability 对已知通路必判 reachable）。
- 两档：`@requires_docker` / `@requires_cli` 标记，CI 在装了依赖的 runner 上跑；本地最差环境跑"探测+降级"用例。
- 工具坏了**在 CI 暴露**，而非审计到一半才崩。

### 3g. 一键环境自检与修复指引
- `scripts/doctor.py`：跑 `probe_capabilities()` 并打印**可读的修复指引**（"Docker 未运行 → 启动 Docker"/"semgrep 未装 → pip install semgrep"/"镜像缺失 → bash docker/sandbox/build.sh"）。让部署问题**自诊断**，而非表现为"工具神秘报错"。

---

## 4. 分析完备性（sink_inventory / reachability）——"尽量高 + 诚实"

**认识论前提（必须承认）**：完整枚举所有 sink、判定精确可达性，在理论上**不可判定**（动态特性、反射、状态爆炸；Rice 定理层面）。任何声称"保证枚举全部 sink"的工具都不可信。用户已选"要求尽量高的完备性"，故：

### 4a. 多引擎交叉，最大化覆盖/召回（成本换完备）
- **sink_inventory**：不依赖单一来源——**并集**多个引擎的 sink：
  - 自建 tree-sitter + **结构化 sink 签名注册表**（每语言危险函数/方法，可审计、可扩充）；
  - Semgrep taint 规则里的 sink 定义；
  - （可选）CodeQL 的 sink 库。
  - 取并集 → 最大化覆盖；冲突/重复按 (file,line,symbol) 去重。
- **reachability**：多引擎交叉——Semgrep taint dataflow ∪ 自建调用图可达性（∪ 可选 CodeQL dataflow）；**任一引擎报可达即列为候选**（高召回），多引擎一致则置信度更高。

### 4b. 显式覆盖报告 + 盲区标注（把不完备摆上台面）
- sink_inventory **必须输出覆盖报告**：`扫描 N 文件 / 命中签名库内 sink M 个 / X 文件因解析失败跳过 / 各引擎贡献占比`。
- **盲区显式标注**：动态构造（反射/eval/动态 import/字符串拼函数名/运行时路由）**老实列为"静态不可见区"**，不假装覆盖。这些区域可提示走 §4d 的运行时辅助。

### 4c. 静态结论只作候选，真伪由 oracle 裁决（接 Phase 3-V）
- reachability 的产出**永远是候选**（`reachable-unproven`），不是定论。**唯一"保证为真"的一档是验证阶梯 L2/L3 的真实执行**（canary/布尔差分/带外回调）。即：reachability 负责**高召回找候选**，验证阶梯负责**确定性裁真伪**——职责分离，谁都不假装做不到的事。

### 4d. 可达性的运行时增强（可选，进一步提完备）
- 对静态盲区（动态特性），可选地用**运行时辅助**补充：若仓库可起服务（Phase 3-V L3），用真实流量/插桩观测实际触达的 sink——把动态构造的路径捞回来。成本高，作为"尽量高完备性"的上限手段。

### 4e. 完备性靠 ground-truth 度量，不靠声明
- sink 覆盖率、reachability 的 recall/precision，**在 Phase 0 评测框架的 OWASP Benchmark / 已知 CVE 上量出真实数字**。可靠性是**测出来的指标**（"sink 覆盖率 92%、reachability recall 0.85"），不是承诺。每次改动看这些数字升降。

---

## 5. 验收标准

**运行时可用性**：
- [ ] 最差环境（Docker 关、无本地 CLI）下审计**能跑完**，仅用可用工具子集，**无未捕获崩溃**；能力清单正确反映"哪些工具可用/降级"。
- [ ] 装了本地 semgrep/bandit（未起 Docker）时，静态扫描**走本地 CLI 成功**——证明扫描不再绑死 Docker。
- [ ] Semgrep 离线（无网络）能跑——证明规则离线化生效。
- [ ] 每个工具有契约冒烟用例，CI 绿；故意卸载某依赖 → 该工具标 `unavailable` 且不进 Agent 工具集（不报崩）。
- [ ] `scripts/doctor.py` 对当前残缺环境打印正确修复指引。
- [ ] `ToolResult.failure_kind` 就位，Agent 按类型分流（unavailable 不重试）。

**分析完备性**：
- [ ] sink_inventory 输出覆盖报告 + 盲区标注；多引擎并集生效（移除任一引擎可见覆盖下降）。
- [ ] reachability 多引擎交叉，产出仅为候选；真伪由验证阶梯裁决（无静态结论被直接当"已确认"）。
- [ ] Phase 0 量出 sink 覆盖率与 reachability recall/precision 的**具体数字**并入基线。

---

## 6. 与既有 spec 的关系

- **本文件**：工具**能不能跑**（运行时）+ 分析工具完备性的**诚实边界**。是 [tool-redesign-target-set.md](./tool-redesign-target-set.md)（该有哪些工具）的**前置**——工具得先能跑，选型才有意义。
- **多后端可插拔 / 本地优先**与 [tool-access-and-forms.md](./tool-access-and-forms.md) 的"扫描读代码无需沙箱、PoC 执行才需隔离"一致。
- **覆盖报告 + 候选 + oracle 裁决**接 [phase-3v-verification-ladder.md](./phase-3v-verification-ladder.md) 的 fidelity 分级。
- **完备性度量**接 [phase-0-eval-harness.md](./phase-0-eval-harness.md) 的 ground-truth 评测。
- **结构化失败信号**接 [phase-4-native-tooling-context.md](./phase-4-native-tooling-context.md) 4e 的工具结构化返回。

> **顺序提示**：§3a 预检 + §3b 本地优先 + §3g doctor 是**最高优先、最低风险的止血项**——直接解决"现在很多工具报错"，应先于一切工具选型/重设计落地。
