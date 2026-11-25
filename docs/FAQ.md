# 常见问题 (FAQ)

本文档收集了 DeepAudit 使用过程中的常见问题和解决方案。

## 目录

- [快速入门](#快速入门)
- [LLM 配置](#llm-配置)
- [网络问题](#网络问题)
- [功能使用](#功能使用)
- [部署问题](#部署问题)
- [性能优化](#性能优化)

---

## 快速入门

### Q: 如何快速开始使用？

最快的方式是使用 Docker Compose：

```bash
# 1. 克隆项目
git clone https://github.com/lintsinghua/DeepAudit.git
cd DeepAudit

# 2. 配置 LLM API Key
cp backend/env.example backend/.env
# 编辑 backend/.env，填写管理员初始化配置和 LLM API Key

# 3. 启动服务
docker-compose up -d

# 4. 访问 http://localhost:5173
```

### Q: 首次登录使用哪个账户？

使用部署者通过 `BOOTSTRAP_ADMIN_EMAIL` 和 `BOOTSTRAP_ADMIN_PASSWORD` 创建的管理员账户。公开注册会创建普通成员。旧版演示账户的升级步骤见[部署指南](DEPLOYMENT.md#初始化管理员)。

### Q: 不想用 Docker，如何本地运行？

参见 [部署指南 - 本地开发部署](DEPLOYMENT.md#本地开发部署)。

### Q: 支持哪些编程语言？

DeepAudit 支持所有主流编程语言的代码分析，包括但不限于：

- **Web**: JavaScript, TypeScript, HTML, CSS
- **后端**: Python, Java, Go, Rust, C/C++, C#
- **移动端**: Swift, Kotlin, Dart
- **脚本**: Shell, PowerShell, Ruby, PHP
- **其他**: SQL, YAML, JSON, Markdown

---

## LLM 配置

### Q: 如何快速切换 LLM 平台？

**方式一：浏览器运行时配置（推荐）**

1. 访问 `http://localhost:5173/admin` 系统管理页面
2. 在"系统配置"标签页选择不同的 LLM 提供商
3. 填入对应的 API Key
4. 保存即可，无需重启

**方式二：修改后端环境变量**

编辑 `backend/.env`：

```env
# 切换到 OpenAI
LLM_PROVIDER=openai
LLM_API_KEY=sk-your-key

# 切换到通义千问
LLM_PROVIDER=qwen
LLM_API_KEY=sk-your-dashscope-key

# 切换到 DeepSeek
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-your-key
```

修改后需要重启后端服务。

### Q: 百度文心一言的 API Key 格式是什么？

百度需要同时提供 API Key 和 Secret Key，用冒号分隔：

```env
LLM_PROVIDER=baidu
LLM_API_KEY=your_api_key:your_secret_key
LLM_MODEL=ernie-bot-4
```

获取地址：https://console.bce.baidu.com/qianfan/

### Q: 如何使用 Ollama 本地大模型？

```bash
# 1. 安装 Ollama
curl -fsSL https://ollama.com/install.sh | sh  # macOS/Linux
# Windows: 访问 https://ollama.com/download

# 2. 拉取模型
ollama pull llama3  # 或 codellama、qwen2.5、deepseek-coder

# 3. 确保 Ollama 服务运行
ollama serve

# 4. 配置后端
# 在 backend/.env 中设置：
LLM_PROVIDER=ollama
LLM_MODEL=llama3
LLM_BASE_URL=http://localhost:11434/v1
```

**推荐模型**：
- `llama3` - 综合能力强
- `codellama` - 代码专用
- `qwen2.5` - 中文支持好
- `deepseek-coder` - 代码分析强

### Q: 哪个 LLM 平台性价比最高？

| 场景 | 推荐 | 原因 |
|------|------|------|
| 免费使用 | Gemini / 智谱 GLM-4-Flash | 有免费配额 |
| 低成本 | DeepSeek | 价格仅为 GPT-4 的 1/10 |
| 最佳性能 | GPT-4o / Claude Sonnet | 代码理解能力最强 |
| 敏感代码 | Ollama 本地模型 | 完全本地化 |

---

## 网络问题

### Q: 遇到请求超时怎么办？

**方案一：增加超时时间**

```env
LLM_TIMEOUT=300  # 增加到 300 秒
```

**方案二：使用 API 中转站**

```env
LLM_PROVIDER=openai
LLM_API_KEY=中转站提供的Key
LLM_BASE_URL=https://your-proxy.com/v1
```

**方案三：切换到国内平台**

通义千问、DeepSeek、智谱 AI 等国内平台访问更稳定。

**方案四：降低并发**

```env
LLM_CONCURRENCY=1  # 降低并发数
LLM_GAP_MS=3000    # 增加请求间隔
```

### Q: 如何配置 API 中转站？

```env
LLM_PROVIDER=openai
LLM_API_KEY=中转站提供的Key
LLM_BASE_URL=https://your-proxy.com/v1
LLM_MODEL=gpt-4o-mini
```

常见中转站：
- [OpenRouter](https://openrouter.ai/)
- [API2D](https://api2d.com/)
- [CloseAI](https://www.closeai-asia.com/)

### Q: 提示 "API Key 无效" 怎么办？

1. 检查 API Key 是否正确复制（注意前后空格）
2. 确认 API Key 未过期或被禁用
3. 检查 LLM_PROVIDER 是否与 API Key 匹配
4. 如果使用中转站，确认 LLM_BASE_URL 配置正确

---

## 功能使用

### Q: 如何分析 GitHub/GitLab 仓库？

1. 在"项目管理"页面点击"添加项目"
2. 选择"GitHub 仓库"或"GitLab 仓库"
3. 输入仓库 URL（如 `https://github.com/user/repo`）
4. 如果是私有仓库，需要配置 Token：
   - GitHub: 在 `backend/.env` 中设置 `GITHUB_TOKEN`
   - GitLab: 在 `backend/.env` 中设置 `GITLAB_TOKEN`

### Q: 如何上传 ZIP 文件分析？

1. 在"项目管理"页面点击"添加项目"
2. 选择"上传 ZIP"
3. 选择本地 ZIP 文件上传
4. 系统会自动解压并分析

### Q: 如何使用即时分析功能？

1. 访问"即时分析"页面
2. 直接粘贴代码片段
3. 选择编程语言
4. 点击"分析"按钮

### Q: 如何导出审计报告？

1. 完成代码分析后，进入"审计报告"页面
2. 点击"导出"按钮
3. 选择导出格式：
   - **JSON**: 结构化数据，适合程序处理
   - **PDF**: 专业报告，适合交付

### Q: 分析结果不准确怎么办？

1. **切换更强的模型**：如 GPT-4o、Claude Sonnet
2. **调整温度参数**：降低 `LLM_TEMPERATURE` 到 0.1 以下
3. **增加上下文**：确保代码文件完整
4. **人工复核**：AI 分析结果仅供参考，建议结合人工审查

---

## 部署问题

### Q: Docker 容器启动失败？

**端口被占用**：

```bash
# 检查端口占用
lsof -i :5173
lsof -i :8000
lsof -i :5432

# 停止占用进程或修改 docker-compose.yml 中的端口
```

**数据库连接失败**：

```bash
# 确保数据库先启动
docker-compose up -d db
docker-compose exec db pg_isready -U postgres
docker-compose up -d backend
```

### Q: Windows 导出 PDF 报错怎么办？

PDF 导出功能使用 WeasyPrint 库，在 Windows 系统上需要安装 GTK 依赖。

**方法一：使用 MSYS2 安装（推荐）**

```bash
# 1. 下载并安装 MSYS2: https://www.msys2.org/
# 2. 打开 MSYS2 终端，执行：
pacman -S mingw-w64-x86_64-pango mingw-w64-x86_64-gtk3

# 3. 将 MSYS2 的 bin 目录添加到系统 PATH：
# C:\msys64\mingw64\bin
```

**方法二：使用 GTK3 Runtime**

1. 下载 GTK3 Runtime: https://github.com/nickvidal/gtk3-runtime/releases
2. 安装后将安装目录添加到系统 PATH

**方法三：使用 Docker 部署（最简单）**

```bash
docker-compose up -d backend
```

Docker 镜像已包含所有依赖，无需额外配置。

### Q: macOS 上 PDF 导出报错？

```bash
# 安装依赖
brew install pango cairo gdk-pixbuf libffi

# 重启后端服务
```

### Q: 前端无法连接后端 API？

检查 `frontend/.env` 中的 API 地址配置：

```env
# 本地开发
VITE_API_BASE_URL=http://localhost:8000/api/v1

# Docker Compose 部署
VITE_API_BASE_URL=/api
```

### Q: 数据库迁移失败？

```bash
cd backend
source .venv/bin/activate

# 查看当前迁移状态
alembic current

# 重新执行迁移
alembic upgrade head

# 如果有问题，可以回滚
alembic downgrade -1
```

---

## 性能优化

### Q: 分析速度太慢怎么办？

**1. 增加并发数**

```env
LLM_CONCURRENCY=5  # 增加并发（注意 API 限流）
LLM_GAP_MS=500     # 减少请求间隔
```

**2. 限制分析文件数**（默认无限制）

```env
MAX_ANALYZE_FILES=30  # 设置单次分析文件数限制
```

**3. 使用更快的模型**

- `gpt-4o-mini` 比 `gpt-4o` 快
- `qwen-turbo` 比 `qwen-max` 快
- `glm-4-flash` 比 `glm-4` 快

**4. 使用本地模型**

Ollama 本地模型没有网络延迟，适合大量文件分析。

### Q: 如何减少 API 调用费用？

1. **使用便宜的模型**：DeepSeek、通义千问 Turbo
2. **减少分析文件数**：设置 `MAX_ANALYZE_FILES`
3. **过滤不必要的文件**：排除测试文件、配置文件等
4. **使用本地模型**：Ollama 完全免费

### Q: 内存占用过高？

1. **减少并发数**：`LLM_CONCURRENCY=1`
2. **限制文件大小**：`MAX_FILE_SIZE_BYTES=102400`（100KB）
3. **使用更小的本地模型**：如 `deepseek-coder:1.3b`

---

## 数据管理

### Q: 如何备份数据？

在 `/admin` 页面的"数据库管理"标签页中，点击"导出数据"按钮，可以将所有数据导出为 JSON 文件。

也可以直接备份 PostgreSQL 数据库：

```bash
# 导出数据
docker-compose exec db pg_dump -U postgres deepaudit > backup.sql

# 恢复数据
docker-compose exec -T db psql -U postgres deepaudit < backup.sql
```

### Q: 如何恢复数据？

在 `/admin` 页面的"数据库管理"标签页中，点击"导入数据"按钮，选择之前导出的 JSON 文件即可恢复。

### Q: 如何清空所有数据？

在 `/admin` 页面的"数据库管理"标签页中，点击"清空数据"按钮。

⚠️ **警告**：此操作不可恢复，请先备份重要数据！

---

## 其他问题

### Q: 如何更新到最新版本？

```bash
# 拉取最新代码
git pull origin main

# 重新构建镜像
docker-compose build --no-cache

# 重启服务
docker-compose up -d
```

### Q: 如何参与贡献？

参见 [贡献指南](../CONTRIBUTING.md)。

---

## 还有问题？

如果以上内容没有解决你的问题，欢迎：

- 提交 [GitHub Issue](https://github.com/lintsinghua/DeepAudit/issues)
- 发送邮件至 lintsinghua@qq.com

提问时请提供：
1. 操作系统和版本
2. 部署方式（Docker/本地）
3. 错误日志或截图
4. 复现步骤
