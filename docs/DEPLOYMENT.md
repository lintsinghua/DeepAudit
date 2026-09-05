# 部署指南

> 本次升级新增独立审计 worker，需要运行数据库迁移并同步更新 API、worker 与前端。详见[运行与升级说明](OPERATIONS.md)。

本文档详细介绍 DeepAudit v3.0.0 的各种部署方式，包括 Docker Compose 一键部署、Agent 审计模式部署和本地开发环境搭建。

## 目录

- [快速开始](#快速开始)
- [Docker Compose 部署（推荐）](#docker-compose-部署推荐)
- [Agent 审计模式部署](#agent-审计模式部署)
- [生产环境部署](#生产环境部署)
- [本地开发部署](#本地开发部署)
- [常见部署问题](#常见部署问题)

---

## 快速开始

最快的方式是使用 Docker Compose 一键部署：

```bash
# 1. 克隆项目
git clone https://github.com/lintsinghua/DeepAudit.git
cd DeepAudit

# 2. 配置后端环境变量
cp backend/env.example backend/.env
# 编辑 backend/.env，配置 LLM API Key

# 3. 启动所有服务
docker compose up -d

# 4. 访问应用
# 前端: http://localhost:3000
# 后端 API: http://localhost:8000/docs
```

### 演示账户

默认不创建演示账户。仅在本地开发中同时设置 `ENVIRONMENT=development` 和
`DEMO_ENABLED=true` 后，系统才会创建以下演示账户及示例数据：

- 📧 邮箱：`demo@example.com`
- 🔑 密码：`demo123`

> 生产环境禁止启用演示账户，并要求配置至少 32 字符的随机 `SECRET_KEY`。
> 升级会禁用仍使用默认密码的旧演示账户。升级前请创建独立管理员或修改密码，
> 详情见[安全配置与迁移说明](CONFIGURATION.md#后端配置)。

---

## Docker Compose 部署（推荐）

完整的前后端分离部署方案，包含前端、后端、PostgreSQL 数据库以及 Agent 模式所需服务。

### 系统要求

| 资源 | 最低配置（含 Agent 模式） |
|------|---------------------------|
| 内存 | 4GB+                      |
| 磁盘 | 10GB+                     |
| Docker | 20.10+                 |
| Docker Compose | 2.0+           |

### 部署步骤

```bash
# 1. 克隆项目
git clone https://github.com/lintsinghua/DeepAudit.git
cd DeepAudit

# 2. 配置后端环境变量
cp backend/env.example backend/.env
```

编辑 `backend/.env` 文件，配置必要参数：

```env
# 数据库配置（Docker Compose 会自动处理）
POSTGRES_SERVER=db
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=deepaudit

# 安全配置（生产环境请修改）
# 使用 openssl rand -hex 32 生成随机值；已有部署保留原有安全密钥
SECRET_KEY=<填入随机密钥>

# LLM 配置（必填）
LLM_PROVIDER=openai
LLM_API_KEY=sk-your-api-key
LLM_MODEL=gpt-4o-mini

# 可选：API 中转站
# LLM_BASE_URL=https://your-proxy.com/v1
```

```bash
# 3. 启动所有服务
docker compose up -d

# 4. 查看服务状态
docker compose ps

# 5. 查看日志
docker compose logs -f
```

### 服务说明

| 服务 | 端口 | 说明 |
|------|------|------|
| `frontend` | 3000 | React 前端应用（生产构建） |
| `backend` | 8000 | FastAPI 后端 API |
| `db` | 5432 | PostgreSQL 15 数据库 |

### 访问地址

- 前端应用: http://localhost:3000
- 后端 API: http://localhost:8000
- API 文档 (Swagger): http://localhost:8000/docs
- API 文档 (ReDoc): http://localhost:8000/redoc

### 常用命令

```bash
# 停止所有服务
docker compose down

# 停止并删除数据卷（清除数据库）
docker compose down -v

# 重新构建镜像
docker compose build --no-cache

# 查看特定服务日志
docker compose logs -f backend

# 进入容器调试
docker compose exec backend sh
docker compose exec db psql -U postgres -d deepaudit
```

---

## Agent 审计模式部署

v3.0.0 新增的 Multi-Agent 深度审计功能，需要额外的服务支持。

### 功能特点

- 🤖 **Multi-Agent 架构**: Orchestrator/Analysis/Recon/Verification 多智能体协作
- 🧠 **RAG 知识库**: 代码语义理解 + CWE/CVE 漏洞知识库
- 🔒 **沙箱验证**: Docker 安全容器执行 PoC

### 部署步骤

```bash
# 1. 配置 Agent 相关参数
# 编辑 backend/.env，确保以下配置正确

# Agent 配置
AGENT_ENABLED=true
AGENT_MAX_ITERATIONS=5

# 嵌入模型配置
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_API_KEY=  # 留空则使用 LLM_API_KEY

# 向量数据库配置（使用 ChromaDB）
VECTOR_DB_TYPE=chroma

# 沙箱配置
SANDBOX_ENABLED=true
```

```bash
# 2. 启动包含 Agent 服务的完整部署
docker compose up -d
```

### Agent 模式服务说明

| 服务 | 端口 | 说明 |
|------|------|------|
| `redis` | 6379 | 任务队列（可选） |

### 构建安全沙箱镜像

沙箱用于安全地执行漏洞验证 PoC：

```bash
# 进入沙箱目录
cd docker/sandbox

# 构建沙箱镜像
./build.sh

# 验证镜像构建成功
docker images | grep deepaudit-sandbox
```

沙箱镜像包含：
- Python 3.11 + 安全工具 (Semgrep, Bandit, Safety)
- Node.js 20 + npm audit
- Go 1.21 + gosec
- Rust (cargo-audit)
- Gitleaks, TruffleHog, OSV-Scanner

### 验证 Agent 模式

```bash
# 检查所有服务状态
docker compose ps

# 查看 Agent 日志
docker compose logs -f backend | grep -i agent
```

---

## 生产环境部署

Docker Compose 默认配置已适用于生产环境：

- 前端：构建生产版本，使用 serve 提供静态文件服务
- 后端：使用 uv 管理依赖，镜像内包含所有依赖
- 数据库：使用 Docker Volume 持久化数据

### 生产环境安全建议

1. **修改默认密钥**：务必修改 `SECRET_KEY` 为随机字符串
2. **配置 HTTPS**：使用 Nginx 反向代理并配置 SSL 证书
3. **限制 CORS**：在生产环境配置具体的前端域名
4. **数据库安全**：修改默认数据库密码，限制访问 IP
5. **API 限流**：配置 Nginx 或应用层限流
6. **日志监控**：配置日志收集和监控告警
7. **删除演示账户**：生产环境请删除或禁用 demo 账户

### Nginx 反向代理配置（可选）

如需使用 Nginx 提供 HTTPS 和统一入口：

```nginx
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    # 前端
    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # API 代理
    location /api/ {
        proxy_pass http://localhost:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # SSE 事件流（Agent 审计日志）
    location /api/v1/agent-tasks/ {
        proxy_pass http://localhost:8000/api/v1/agent-tasks/;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400;
    }
}
```

---

## 本地开发部署

适合需要开发或自定义修改的场景。

### 环境要求

| 依赖 | 版本要求 | 说明 |
|------|---------|------|
| Node.js | 20+ | 前端运行环境 |
| Python | 3.11+ | 后端运行环境 |
| PostgreSQL | 15+ | 数据库 |
| pnpm | 8+ | 推荐的前端包管理器 |
| uv | 最新版 | 推荐的 Python 包管理器 |

### 数据库准备

```bash
# 方式一：使用 Docker 启动 PostgreSQL（推荐）
docker run -d \
  --name deepaudit-db \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=deepaudit \
  -p 5432:5432 \
  postgres:15-alpine

# 方式二：使用本地 PostgreSQL
createdb deepaudit
```

### 后端启动

```bash
# 1. 进入后端目录
cd backend

# 2. 安装 uv（如未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. 同步依赖
uv sync

# 4. 配置环境变量
cp env.example .env
# 编辑 .env 文件，配置数据库和 LLM 参数

# 5. 初始化数据库
uv run alembic upgrade head

# 6. 启动后端服务（开发模式，支持热重载）
uv run uvicorn app.main:app --reload --port 8000
# 另开终端，同目录启动审计 worker
uv run python -m app.worker
```

### 前端启动

```bash
# 1. 进入前端目录
cd frontend

# 2. 安装依赖
pnpm install

# 3. 配置环境变量（可选）
cp .env.example .env

# 4. 启动开发服务器
pnpm dev

# 5. 访问应用
# 浏览器打开 http://localhost:5173
```

### 开发工具

```bash
# 前端代码检查
cd frontend
pnpm lint
pnpm type-check

# 前端代码格式化
pnpm format

# 后端类型检查
cd backend
uv run mypy app

# 后端代码格式化
uv run ruff format app
```

---

## 数据存储

DeepAudit 采用前后端分离架构，所有数据存储在后端 PostgreSQL 数据库中。

### 数据管理

在 `/admin` 页面的"数据库管理"标签页中，可以：

- **导出数据**: 将所有数据导出为 JSON 文件备份
- **导入数据**: 从 JSON 文件恢复数据
- **清空数据**: 删除所有数据（谨慎操作）
- **健康检查**: 检查数据库连接状态和数据完整性

### 数据库备份

```bash
# 导出 PostgreSQL 数据
docker compose exec db pg_dump -U postgres deepaudit > backup.sql

# 恢复数据
docker compose exec -T db psql -U postgres deepaudit < backup.sql
```

---

## 常见部署问题

### Docker 相关

**Q: 容器启动失败，提示端口被占用**

```bash
# 检查端口占用
lsof -i :3000
lsof -i :8000
lsof -i :5432

# 停止占用端口的进程，或修改 docker-compose.yml 中的端口映射
```

**Q: 数据库连接失败**

```bash
# 检查数据库容器状态
docker compose ps db

# 查看数据库日志
docker compose logs db

# 确保数据库健康检查通过后再启动后端
docker compose up -d db
docker compose exec db pg_isready -U postgres
docker compose up -d backend
```

**Q: 构建时网络问题（代理相关）**

如果构建时遇到网络问题，检查 Docker Desktop 的代理设置：
1. 打开 Docker Desktop → Settings → Resources → Proxies
2. 关闭代理或配置正确的代理地址
3. 重启 Docker Desktop
4. 重新构建：`docker compose build --no-cache`

### Agent 模式相关

**Q: 沙箱镜像构建失败**

```bash
# 检查 Docker 服务状态
docker info

# 使用国内镜像源重新构建
cd docker/sandbox
# 编辑 Dockerfile，使用国内镜像源
./build.sh
```

### 后端相关

**Q: PDF 导出功能报错（WeasyPrint 依赖问题）**

Docker 镜像已包含 WeasyPrint 所需的系统依赖。本地开发时需要安装：

```bash
# macOS
brew install pango cairo gdk-pixbuf libffi

# Ubuntu/Debian
sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 libglib2.0-0

# Windows - 参见 FAQ.md 中的详细说明
```

**Q: LLM API 请求超时**

```env
# 增加超时时间
LLM_TIMEOUT=300

# 降低并发数
LLM_CONCURRENCY=1

# 增加请求间隔
LLM_GAP_MS=3000
```

### 前端相关

**Q: 前端无法连接后端 API**

Docker Compose 部署时，前端通过 `http://localhost:8000/api/v1` 访问后端。确保：
1. 后端容器正常运行：`docker compose ps backend`
2. 后端端口 8000 可访问：`curl http://localhost:8000/docs`

本地开发时，检查 `frontend/.env` 中的 API 地址配置：

```env
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

---

## 更多资源

- [配置说明](CONFIGURATION.md) - 详细的配置参数说明
- [Agent 审计](AGENT_AUDIT.md) - Multi-Agent 审计模块详解
- [LLM 平台支持](LLM_PROVIDERS.md) - 各 LLM 平台的配置方法
- [常见问题](FAQ.md) - 更多问题解答
- [贡献指南](../CONTRIBUTING.md) - 参与项目开发
