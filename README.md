# DeepAudit-yasa

基于 [DeepAudit](https://github.com/lintsinghua/DeepAudit) v3 的分支，新增 **YASA 混合审计**：由 Agent 为目标项目编写
[YASA-Engine](https://github.com/antgroup/YASA-Engine) 污点规则并运行引擎，再在多个小上下文里分组复核引擎结果和残余危险调用；
同时用确定性的路由表做权限（访问控制）审计。整个审计有时间预算，默认 30 分钟内完成；超出预算没审到的候选会列出来。

原有的 Multi-Agent 审计、快速扫描、项目管理、报告等功能保持不变，和新模式并存。
上游 README 见 [README_EN.md](README_EN.md) / [README_JA.md](README_JA.md)（内容与上游一致，不包含本分支的改动）。

---

## 目录

- [两种审计引擎](#两种审计引擎)
- [实测结果](#实测结果)
- [从源码部署](#从源码部署)
- [使用](#使用)
- [配置](#配置)
- [已知限制](#已知限制)
- [开发与测试](#开发与测试)
- [许可证与致谢](#许可证与致谢)

## 两种审计引擎

| | Agent（上游） | YASA 混合（本分支） |
|---|---|---|
| 思路 | Orchestrator 调度 Recon / Analysis / Verification Agent 自主审计 | 固定流水线：建规则 → 引擎 → 分组复核；并行做权限审计 |
| 数据流 | Agent 自己沿 source → sink 追踪 | YASA 引擎找污点路径，Agent 只负责"写规则"和"判定" |
| 权限 | 依赖 Agent 自行发现 | 确定性路由表（Servlet/JSP、Spring、Express、Flask/FastAPI/Django、Laravel/普通 PHP 脚本）+ 同类入口对比 |
| 验证 | Docker 沙箱执行 PoC | 不执行，结论为静态判定（证据：文件:行 路径、引擎结果编号） |
| 时间 | 不固定 | 硬预算，默认 30 分钟 |
| 语言 | 不限 | Java（含 JSP）、JavaScript / TypeScript、Python、PHP（PHP 不用引擎，见下） |
| 依赖 | LLM、Embedding（RAG）、Docker（沙箱） | LLM（OpenAI 兼容、支持 tool calling）、YASA 工具，**不需要** RAG 和 Docker |

YASA 混合审计的流程（`backend/app/services/yasa_audit/`）：

```
            ┌─ 数据流 ─────────────────────────────────────────────────────────────┐
            │ build：Agent 读代码 + playbook → 写 ruleConfig → 运行 YASA（≤2 次）    │
 yasa-mcp   │ triage：引擎结果 + 残余危险调用（L0 清单 − 引擎已覆盖 − 常量参数）       │
 导航缓存 ──┤         按文件分组，每组一个新的小上下文，按严重程度优先调度              │
            ├─ 权限 ───────────────────────────────────────────────────────────────┤
            │ 路由表 + 全局守卫 → 每 3 个文件一组复核（每组都带完整路由表做对比）      │
            └──────────────────────────────────────────────────────────────────────┘
                         ↓ 结果写入 DeepAudit 任务（发现、事件流、报告）
```

## 实测结果

模型 deepseek-flash（temperature 0.1），YASA 0.2.30。基准、真值与评分脚本在 [`backend/benchmarks/yasa_audit/`](backend/benchmarks/yasa_audit/README.md)。

| 目标 | 代码量 | 数据流召回 | 权限召回 | 耗时 | Token |
|---|---|---|---|---|---|
| Hospital-Management-System（Java Servlet + JSP） | ~1.9k LOC | 13/13，负样本 0 命中 | 8/8 | 3.8 min | 1.2 M |
| OWASP Juice Shop 后端（TypeScript / Express） | ~10k LOC | 16/18，负样本 0 命中 | — | 11.3 min | 3.0 M |
| PowerJob v5.1.2（Java / Spring） | ~45k LOC | 见下 | 2/2 已知 CVE | ~21 min | 8.7 M |
| Vulnerable-Flask-App（Python / Flask） | 420 LOC | 5/5 | — | 3.6 min | 0.2 M |
| DVWA（PHP，无引擎） | ~13k LOC | SQLi、盲注、命令注入 9/9，`impossible` 级 0 误报 | — | 6 min | 3.3 M |

- HMS 一行经 DeepAudit 任务入口实测（数据流和权限两个阶段并行）。
- PowerJob：权限阶段复现了 CVE-2025-11580 / CVE-2025-11581；数据流阶段的报告经人工复核后有若干确认问题，
  按负责任披露流程处理，细节暂不公开。
- 对照组（同模型、同工具，只让单个 Agent 自己追踪 source → sink、不用引擎）：HMS 两次分别为 13/13、11/13，Juice 两次分别为 9/17、12/17。

## 从源码部署

以下命令在 Ubuntu 24.04（x86_64）上完整走过一遍：PostgreSQL 16、Node 22、Python 3.12。

### 1. 环境要求

| 组件 | 版本 | 用途 |
|---|---|---|
| Python | 3.11+（由 uv 管理） | 后端 |
| [uv](https://docs.astral.sh/uv/) | 最新 | Python 依赖管理 |
| Node.js | 20+ | 前端 |
| pnpm | 10（随 corepack 提供） | 前端依赖管理 |
| PostgreSQL | 15+ | 数据库 |
| curl、unzip、tar | — | 安装 YASA 工具（源码安装另需 git） |
| Redis | 可选 | 启动时检查，缺失不影响使用 |
| Docker | 可选 | 只有 Agent 模式的沙箱验证需要；YASA 模式不需要 |

YASA 混合审计支持 **Linux x86_64、macOS Apple Silicon（ARM64）和 macOS Intel（x86_64）**。
安装脚本和后端按本机平台选择官方工具包；macOS 不需要 Docker 或 Rosetta。
macOS 可用 Homebrew 安装 PostgreSQL 15+、Node.js 20+、uv 和 pnpm；数据库创建好后按下文配置和启动。
内存建议 16 GB 以上：在 8 GB 的机器上，
YASA 处理 2 万行以上的 Spring 项目会因内存不足被终止，这时流水线会退化为只做残余危险调用复核，仍在预算内完成。

```bash
# Ubuntu / Debian
sudo apt update
sudo apt install -y git curl unzip postgresql redis-server
curl -LsSf https://astral.sh/uv/install.sh | sh          # 安装 uv（装完重新打开终端）
# Node.js 20+ 请用 nvm 或 NodeSource 安装，然后启用 pnpm：
corepack enable
```

### 2. 获取代码

```bash
git clone https://github.com/Ka7arotto/DeepAudit-yasa.git
cd DeepAudit-yasa
```

### 3. 数据库

```bash
sudo systemctl start postgresql
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'postgres';"
sudo -u postgres createdb deepaudit
```

如果用了别的用户名、密码或主机，请对应修改下一步 `.env` 里的 `POSTGRES_*`。

### 4. 后端

```bash
cd backend
cp env.example .env
```

编辑 `backend/.env`，至少填写：

```ini
SECRET_KEY=<随机字符串，例如 openssl rand -hex 32 的输出>
LLM_PROVIDER=openai
LLM_API_KEY=<你的 Key>
LLM_MODEL=<模型名>
LLM_BASE_URL=<OpenAI 兼容地址，例如 https://api.openai.com/v1>
```

LLM 也可以之后在网页的"系统管理"里配置（按用户保存，优先于 `.env`）。安装依赖并初始化数据库：

```bash
uv sync --frozen                 # 安装依赖到 backend/.venv
uv run alembic upgrade head      # 建表；首次启动时会自动创建演示账户
```

### 5. YASA 工具（YASA 混合审计需要）

```bash
bash scripts/setup_yasa.sh       # 仍在 backend/ 目录下执行
```

脚本会把本机平台的 YASA 引擎安装到 `~/.yasamcp/tools/<平台>/`，把官方
[yasa-mcp v1.0.3](https://github.com/antgroup/YASA-Engine/releases/tag/yasamcp-v1.0.3)
完整发布包（含 `lib/`）安装到 `~/.yasamcp/mcp/<平台>/`，校验 MCP 包的 SHA256，并检查工具能否启动。
平台目录为 `linux-x86-64`、`darwin-aarch64` 或 `darwin-x86-64`。重复执行会复用已安装的引擎和同版本 MCP。
需要从源码安装 MCP 时可设置 `YASA_REF=<上游 tag/分支>`，仍使用独立的 `~/.yasamcp/venv`，
并按脚本输出设置 `YASAMCP_BIN`。原有 virtualenv 安装也继续兼容。
装在默认位置时后端会自动找到，不用设置环境变量。想换位置就用 `YASAMCP_HOME=/opt/yasamcp bash scripts/setup_yasa.sh`，
之后启动后端时也要带上同一个 `YASAMCP_HOME`。

### 6. 启动后端

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
# 开发时可加 --reload；检查：curl http://127.0.0.1:8000/health  →  {"status":"ok"}
```

API 文档：http://127.0.0.1:8000/docs

### 7. 前端（另开一个终端）

```bash
cd frontend
cp .env.example .env             # 默认 VITE_API_BASE_URL=/api/v1，由 Vite 代理到 127.0.0.1:8000
pnpm install --frozen-lockfile
pnpm dev                         # http://localhost:5173
```

后端如果不在本机 8000 端口，启动前端时设置 `VITE_API_TARGET=http://<host>:<port>`。

打开 http://localhost:5173 ，用演示账户 `demo@example.com` / `demo123` 登录（正式使用请注册新账户，或修改演示账户密码）。

## 使用

### 网页

1. "项目管理"里新建项目：Git 仓库地址，或者上传 ZIP。
2. 首页（Agent 审计）在终端里输入 `audit`，或者在"审计任务"页新建任务。
3. 引擎选 **YASA Hybrid**；"产品上下文"里写明哪些入口按设计公开、有哪些角色
   （例如"公开 /login、/search；角色 admin / user"），可以明显减少权限审计的误报。
4. 任务页实时显示阶段事件；完成后发现列表、状态流转和报告导出都和 Agent 任务一样使用。
   结论中的 confirmed / likely 换算为置信度（0.85 / 0.6，likely 严重度降一级），不会标成"已验证"。
5. 规则、SARIF、每个 Agent 的对话记录和未审清单（`not_reviewed`）保存在 `YASA_AUDIT_RUNS_DIR/<任务 ID>/`。

### API

```bash
curl -X POST http://127.0.0.1:8000/api/v1/agent-tasks/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"project_id": "<项目 ID>", "audit_mode": "yasa", "timeout_seconds": 1800,
       "audit_scope": {"product": "公开 /login；角色 admin/user", "deploy": "Linux, JDK 17",
                       "stages": ["dataflow", "authz"]}}'
```

`audit_scope` 里的字段都是可选的：`product` 产品上下文；`deploy` 部署环境（例如路径检查能否用反斜杠绕过要看操作系统）；
`stages` 默认两个阶段都跑；`workers` 并发数，默认 6。

### 命令行（不需要数据库和前端）

```bash
cd backend
export LLM_BASE_URL=... LLM_API_KEY=... LLM_MODEL=...
uv run python -m app.services.yasa_audit init  /path/to/project
uv run python -m app.services.yasa_audit run   /path/to/project --out out/ --deploy "Linux container"
uv run python -m app.services.yasa_audit authz /path/to/project --out out-authz/ \
       --product "Roles: user, admin. Public by design: /login, /search"
```

另有 `build` / `triage` / `trace` 子命令，以及 `--time-budget`（分钟）、`--workers`，详见
[`backend/app/services/yasa_audit/README.md`](backend/app/services/yasa_audit/README.md)。

## 配置

`backend/.env` 的完整说明见 [docs/CONFIGURATION.md](docs/CONFIGURATION.md)。YASA 模式相关的配置：

| 变量 | 默认 | 说明 |
|---|---|---|
| `LLM_*` | — | 和 DeepAudit 共用；网页里的用户配置优先。必须是 OpenAI 兼容并支持 tool calling 的接口 |
| `YASAMCP_HOME` | `~/.yasamcp` | `setup_yasa.sh` 的安装位置 |
| `YASA_BIN` / `YASAMCP_BIN` / `YASA_RG_BIN` / `YASAMCP_TOOLS_DIR` | 由 `YASAMCP_HOME` 推出 | 需要单独指定某个工具时才设置 |
| `YASA_AUDIT_RUNS_DIR` | `/tmp/deepaudit-yasa-runs` | 运行产物目录，建议换成持久目录 |

注意：上面这几个 `YASA*` 变量是在后端进程的环境变量里读取的，**不会**从 `.env` 读取。需要时在启动命令前设置，例如
`YASA_AUDIT_RUNS_DIR=/var/lib/deepaudit/yasa uv run uvicorn app.main:app --port 8000`。

## 已知限制

- 各语言的支持程度不同：

  | 语言 | 数据流 | 权限路由表 |
  |---|---|---|
  | Java（含 JSP） | 引擎 + 复核 | Servlet、JSP、Spring（注解 + 拦截器 + Security 规则） |
  | JS / TS | 引擎 + 复核 | Express（全局、前缀、内联中间件） |
  | Python | 引擎 + 复核 | Flask / FastAPI 装饰器（含 Blueprint/APIRouter 前缀、`Depends`）、Django `urls.py`（视图装饰器、Mixin、`MIDDLEWARE`） |
  | PHP | **只做危险调用复核**，不跑引擎 | Laravel `routes/*.php`（`->middleware`）；没有 Laravel 时每个脚本都是入口，开头的 include/session 检查作为守卫 |

  PHP 不跑引擎的原因：YASA 当前发布版对普通 PHP 脚本和 Laravel 收集不到任何入口（各种入口模式下入口数都是 0），
  只支持它内部的几个框架。PHP 的数据流因此只靠危险调用清单 + Agent 复核，跨文件的长链路比其他语言更容易漏。
- Go：YASA 引擎支持，但流水线还没有为 Go 写危险调用清单、路由提取和规则手册，请先用 Agent 模式。
- 结论是静态判定，没有执行验证；报告里附带了路径和证据，需要的话请人工复现。
- 大型 Spring 项目上引擎受内存限制（见上文），而且自定义入口方案还没跑通，这时数据流阶段主要靠残余危险调用复核。
- 时间预算优先：预算用完时剩下的候选不再复核，任务页会提示数量，清单在运行目录里。
- 和 Agent 模式一样遵守项目的排除规则（默认 `node_modules/**`、`.git/**`、`dist/**`、`build/**`、`*.log`）和"指定文件"。
  只选部分文件时，跨到未选文件的数据流和路由注册（例如 Express 的 `server.ts`）会看不到，召回会下降。

## 开发与测试

```bash
cd backend
uv run --with pytest pytest tests/test_yasa_audit.py      # YASA 模式单元测试（不需要 LLM 和 YASA）
uv run --with ruff ruff check app/services/yasa_audit
cd ../frontend
npx tsc --noEmit -p . && pnpm test
```

基准复现：`bash backend/benchmarks/yasa_audit/prepare_targets.sh /tmp/targets` 下载靶场，然后用
`backend/benchmarks/yasa_audit/eval.py` 评分。

代码位置：

```
backend/app/services/yasa_audit/     YASA 混合审计（pipeline / entrypoints / toolbox / prompts / kb）
  task.py                            DeepAudit 任务入口（agent_tasks.py 中 audit_mode=yasa 时调用）
backend/scripts/setup_yasa.sh        YASA 工具安装
backend/benchmarks/yasa_audit/       靶场、真值、评分、实验记录
frontend/src/components/agent/CreateAgentTaskDialog.tsx   引擎选择（首页）
frontend/src/components/audit/CreateTaskDialog.tsx        审计模式选择（审计任务页）
```

## 许可证与致谢

- 本项目沿用上游 DeepAudit 的 [AGPL-3.0](LICENSE) 许可证。
- [DeepAudit](https://github.com/lintsinghua/DeepAudit)（lintsinghua）提供了平台本身；
  [YASA-Engine](https://github.com/antgroup/YASA-Engine)（蚂蚁集团）提供了污点引擎和 yasa-mcp。
- 仅限对你有权测试的代码使用。安全与合规要求见 [SECURITY.md](SECURITY.md)、[DISCLAIMER.md](DISCLAIMER.md)。
  审计中发现的第三方漏洞，请通过项目方的安全渠道私下报告。
