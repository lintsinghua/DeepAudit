# 审计队列、资源限制与升级

## 运行方式

审计 API 只创建任务和数据库队列记录。独立 worker 从 PostgreSQL 领取任务，每个任务运行在单独的进程中。普通仓库、ZIP 和 Agent 审计均使用该队列；即时单段代码分析仍由请求直接处理。

源码部署需要同时启动 API 和 worker，工作目录均为 `backend`：

```bash
uv sync --frozen --group dev
uv run alembic upgrade head
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
# 在另一个终端中启动，使用相同 .env 和工作目录
uv run python -m app.worker
```

仓库中的三个 Compose 配置均已包含 worker。API、worker、数据库迁移必须使用包含此次改动的同一版本代码；旧的已发布镜像可能没有 worker 入口。测试本地改动时使用源码构建：

```bash
# 先配置 backend/.env 中的随机 SECRET_KEY、数据库和模型参数
# 首次部署的账户通过注册页面创建；默认不再生成演示管理员。
docker compose up -d --build
```

worker 默认每次处理一个任务。增加吞吐量可启动多个 worker，例如 `docker compose up -d --scale worker=3`。每个 worker 都必须访问同一数据库和共享上传目录，使用相同的 `SECRET_KEY`。跨主机部署需要共享文件存储，并确保沙箱所在的 Docker 主机能访问该存储。

## 升级步骤

1. 备份 PostgreSQL、上传目录和原有密钥；停止旧版本 API 与后台执行进程，防止旧任务与新 worker 同时运行。
2. 检查安全配置。生产环境禁止启用演示账户，`SECRET_KEY` 必须是至少 32 字符的随机值。保留原有安全密钥，否则旧的加密配置和队列配置快照无法解密。生产 Compose 还要求明确设置 `POSTGRES_PASSWORD`；对已有数据库，修改环境变量不会自动修改数据库用户密码，应与数据库实际密码保持一致。
3. 执行 `alembic upgrade head`，创建 `audit_jobs` 表和查询索引。迁移会把旧版本遗留的待执行、执行中任务加入队列，暂停任务保持暂停。
4. 启动新版 API、worker 和前端。检查 API `/ready` 与 worker 健康状态，然后提交一个小项目验证部署。

使用生产 Compose 时，在根目录 `.env` 或进程环境设置 `SECRET_KEY`、`POSTGRES_PASSWORD` 和模型配置。普通源码 Compose 从 `backend/.env` 读取应用配置，数据库仍采用其本地开发默认配置。

## 恢复与取消

任务创建与入队在同一数据库事务内提交。worker 持有 PostgreSQL 会话锁，租约过期也不会让第二个 worker 同时执行同一任务。进程退出或部署重启释放锁后，租约到期的任务可被重新领取；最多执行 3 次。

任务保留源码快照、加密的用户配置快照、逐文件分析缓存和已完成的 Agent 结果。恢复时复用已完成结果，未完成的分析步骤会重新执行，因此中断中的模型调用可能重复计费。尚未完成下载的仓库会重新下载；快照准备完成后，重试使用该快照。这里不提供模型生成到一半的逐 token 恢复。

取消请求写入数据库，worker 在心跳时检查并中止当前任务。部署停止与用户取消分别处理：部署中断的任务可以恢复。启动任务前，worker 会清理带有该任务标签的遗留沙箱容器。

完成、失败或取消的任务工作目录默认保留 7 天，worker 每小时清理一次到期目录。数据库中的报告和事件仍保留，项目原始 ZIP 存储独立保留。不要在运行中手动删除共享工作目录。

## 资源配置

以下参数放在 `backend/.env`；自定义生产 Compose 环境时应同时传给 API 和 worker。

| 参数 | 默认值 | 用途 |
| --- | --- | --- |
| `AUDIT_WORKSPACE_PATH` | `./uploads/audit_workspaces` | 源码快照、逐文件缓存、向量数据；Compose 使用 `/app/uploads/audit_workspaces` |
| `WORKER_POLL_SECONDS` | 1 | 队列轮询间隔 |
| `WORKER_HEARTBEAT_SECONDS` | 2 | 租约刷新与取消检查间隔 |
| `WORKER_LEASE_SECONDS` | 30 | 失联任务重新领取的等待时间；应大于心跳间隔 |
| `WORKER_MAX_ATTEMPTS` | 3 | 单任务最大执行次数 |
| `WORKER_TASK_TIMEOUT_SECONDS` | 3600 | 普通任务执行上限；Agent 使用任务自己的超时设置 |
| `WORKER_RETENTION_DAYS` | 7 | 终态任务工作目录保留天数 |
| `ZIP_MAX_UPLOAD_BYTES` | 524288000 | 压缩上传或下载大小上限，500 MiB |
| `ZIP_MAX_EXTRACTED_BYTES` | 2147483648 | ZIP 解压总量上限，2 GiB |
| `ZIP_MAX_FILE_BYTES` | 52428800 | 单个 ZIP 条目大小上限，50 MiB |
| `ZIP_MAX_ENTRIES` | 50000 | ZIP 最大条目数 |
| `ZIP_MAX_COMPRESSION_RATIO` | 200 | 单条目最大压缩比 |

上传和仓库归档下载按块读取。ZIP 在解压前校验所有条目，禁止路径穿越、符号链接、加密条目和重复路径；实际解压时再次计量。取消或校验失败时丢弃暂存内容。普通扫描逐个读取文件，另受 `MAX_FILE_SIZE_BYTES` 和扫描文件数量配置限制。

Docker socket 仅挂载给 worker。沙箱以任务标签标识，并将 worker 内的共享卷路径映射到 Docker 主机路径。API 无需访问 Docker socket。

## 事件、分页与健康检查

事件先写入数据库，再由 API 按序号读取。`/agent-tasks/{id}/events` 与 `/stream` 都支持 `after_sequence` 和 `Last-Event-ID`，多个客户端各自读取。高频思考 token 合并成块，最后一块由 worker 心跳或后续事件刷盘；尚未刷盘时进程崩溃可能丢失这一小段思考文本，不影响已保存的报告结果。

任务、问题与发现列表返回 `X-Total-Count`，支持 `skip`、`limit`，分页上限由各端点约束。任务页面按服务端状态和搜索条件分页；导出显式读取全部分页。统计面板由数据库聚合，避免逐任务拉取所有问题。页面通过按路由加载减少首屏下载量。

- `/health`：API 进程存活。
- `/ready`：数据库可访问，队列表已迁移。
- `python -m app.worker --health`：worker 最近 60 秒有活动心跳。容器健康检查持续失败时查看 worker 日志及数据库连接。

## 验证

```bash
cd backend
uv run --frozen pytest tests
# 设置独立测试数据库并先迁移，运行真实队列恢复、锁与事件测试
DATABASE_URL="$TEST_DATABASE_URL" uv run --frozen alembic upgrade head
TEST_DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@localhost/TEST_DB uv run --frozen pytest tests/test_durable_execution.py

cd ../frontend
pnpm type-check
pnpm lint
pnpm test
pnpm build
```

CI 自动启动独立 PostgreSQL、执行迁移、后端测试，以及前端类型检查、静态检查、测试和构建。发布工作流依赖这些检查。测试不调用外部模型；真实模型与 Docker 沙箱的端到端验证需要部署环境。
