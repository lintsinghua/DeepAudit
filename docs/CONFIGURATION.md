# 配置说明

> 本次升级新增独立审计 worker，需要运行数据库迁移并同步更新 API、worker 与前端。详见[运行与升级说明](OPERATIONS.md)。

本文档详细介绍 DeepAudit 的所有配置选项，包括后端环境变量、前端配置和运行时配置。

## 目录

- [配置方式概览](#配置方式概览)
- [后端配置](#后端配置)
- [前端配置](#前端配置)
- [运行时配置](#运行时配置)
- [API 中转站配置](#api-中转站配置)

---

## 配置方式概览

DeepAudit 采用前后端分离架构，数据存储在后端 PostgreSQL 数据库中。

配置优先级（从高到低）：

| 配置方式 | 适用场景 | 优先级 |
|---------|---------|--------|
| 运行时配置（浏览器 /admin） | 快速切换 LLM、调试 | 最高 |
| 后端环境变量 | 生产部署、团队共享 | 中 |
| 默认值 | 开箱即用 | 最低 |

---

## 后端配置

后端配置文件位于 `backend/.env`，首次使用请复制示例文件：

```bash
cp backend/env.example backend/.env
```

启动前，使用 `openssl rand -hex 32` 生成随机密钥，填写到 `backend/.env` 的
`SECRET_KEY` 中。密钥不能为空、不能使用旧的示例值，且至少需要 32 个字符。
使用生产 Compose 文件时，在项目根目录 `.env` 中设置相同变量，或通过
`docker compose --env-file backend/.env -f docker-compose.prod.yml up -d` 显式传入。
国内镜像配置 `docker-compose.prod.cn.yml` 使用相同方式。

默认 `ENVIRONMENT=production`、`DEMO_ENABLED=false`，不再自动创建演示管理员。
如需本地演示，必须同时设置 `ENVIRONMENT=development` 和 `DEMO_ENABLED=true`；
生产环境会拒绝启用演示账户。已有部署升级后，仍使用默认密码的原演示账户会被禁用，
其数据保留；升级前请创建独立管理员或修改原演示账户密码。

`SECRET_KEY` 也用于加密用户保存的 API Key 等配置。已有部署请保留安全的原密钥；
如果原来使用默认密钥，则必须更换，之后需要重新登录并重新保存加密配置。
生产环境数据库初始化失败时，应用会停止启动，请先完成数据库迁移。

同域反向代理部署可将 `BACKEND_CORS_ORIGINS` 设为 `[]`。前后端跨域时，
填写实际前端来源，例如 `["http://localhost:5173"]`，不支持通配符。

### 完整配置参考

```env
# =============================================
# DeepAudit Backend 配置文件
# =============================================

# ========== 数据库配置 ==========
POSTGRES_SERVER=localhost          # 数据库服务器地址
POSTGRES_USER=postgres             # 数据库用户名
POSTGRES_PASSWORD=postgres         # 数据库密码
POSTGRES_DB=deepaudit              # 数据库名称
# DATABASE_URL=                    # 完整数据库连接字符串（可选，会覆盖上述配置）

# ========== 安全配置 ==========
SECRET_KEY=                       # 必填，至少 32 字符的随机密钥
ENVIRONMENT=production
DEMO_ENABLED=false
BACKEND_CORS_ORIGINS=[]            # 跨域部署时填写实际前端来源
ALGORITHM=HS256                    # JWT 加密算法
ACCESS_TOKEN_EXPIRE_MINUTES=11520  # Token 过期时间（分钟），默认 8 天

# ========== LLM 通用配置 ==========
LLM_PROVIDER=openai                # LLM 提供商（见下方支持列表）
LLM_API_KEY=sk-your-api-key        # API 密钥
LLM_MODEL=                         # 模型名称（留空使用默认模型）
LLM_BASE_URL=                      # 自定义 API 端点（API 中转站）
LLM_TIMEOUT=150                    # 请求超时时间（秒）
LLM_TEMPERATURE=0.1                # 生成温度（0-1，越低越确定）
LLM_MAX_TOKENS=4096                # 最大生成 Token 数

# ========== 各平台独立配置（可选） ==========
# 如果需要同时配置多个平台，可以单独设置
# OPENAI_API_KEY=sk-xxx
# OPENAI_BASE_URL=https://api.openai.com/v1
# GEMINI_API_KEY=xxx
# CLAUDE_API_KEY=xxx
# QWEN_API_KEY=xxx
# DEEPSEEK_API_KEY=xxx
# ZHIPU_API_KEY=xxx
# MOONSHOT_API_KEY=xxx
# BAIDU_API_KEY=api_key:secret_key  # 百度格式特殊
# MINIMAX_API_KEY=xxx
# DOUBAO_API_KEY=xxx
# OLLAMA_BASE_URL=http://localhost:11434/v1

# ========== Git 仓库配置 ==========
GITHUB_TOKEN=                      # GitHub Personal Access Token
GITLAB_TOKEN=                      # GitLab Personal Access Token

# ========== 扫描配置 ==========
MAX_ANALYZE_FILES=0                # 单次扫描最大文件数，0表示无限制
MAX_FILE_SIZE_BYTES=204800         # 单文件最大大小（字节），默认 200KB
LLM_CONCURRENCY=3                  # LLM 并发请求数
LLM_GAP_MS=2000                    # 请求间隔（毫秒），避免限流

# ========== 存储配置 ==========
ZIP_STORAGE_PATH=./uploads/zip_files  # ZIP 文件存储目录

# ========== 输出配置 ==========
OUTPUT_LANGUAGE=zh-CN              # 输出语言：zh-CN（中文）| en-US（英文）
```

### 支持的 LLM 提供商

| Provider | 说明 | 适配器类型 |
|----------|------|-----------|
| `openai` | OpenAI GPT 系列 | LiteLLM |
| `gemini` | Google Gemini | LiteLLM |
| `claude` | Anthropic Claude | LiteLLM |
| `qwen` | 阿里云通义千问 | LiteLLM |
| `deepseek` | DeepSeek | LiteLLM |
| `zhipu` | 智谱 AI (GLM) | LiteLLM |
| `moonshot` | 月之暗面 Kimi | LiteLLM |
| `ollama` | Ollama 本地模型 | LiteLLM |
| `baidu` | 百度文心一言 | 原生适配器 |
| `minimax` | MiniMax | 原生适配器 |
| `doubao` | 字节豆包 | 原生适配器 |

### 配置示例

#### OpenAI

```env
LLM_PROVIDER=openai
LLM_API_KEY=sk-your-api-key
LLM_MODEL=gpt-4o-mini
```

#### 通义千问

```env
LLM_PROVIDER=qwen
LLM_API_KEY=sk-your-dashscope-key
LLM_MODEL=qwen-turbo
```

#### Ollama 本地模型

```env
LLM_PROVIDER=ollama
LLM_MODEL=llama3
LLM_BASE_URL=http://localhost:11434/v1
```

#### 百度文心一言

```env
LLM_PROVIDER=baidu
LLM_API_KEY=your_api_key:your_secret_key
LLM_MODEL=ernie-bot-4
```

---

## 前端配置

前端配置文件位于 `frontend/.env`，首次使用请复制示例文件：

```bash
cp frontend/.env.example frontend/.env
```

### 完整配置参考

```env
# ========== 后端 API 配置 ==========
VITE_API_BASE_URL=/api             # 后端 API 地址

# ========== 应用配置 ==========
VITE_APP_ID=deepaudit

# ========== 代码分析配置 ==========
VITE_MAX_ANALYZE_FILES=0           # 最大分析文件数，0表示无限制
VITE_LLM_CONCURRENCY=2             # LLM 并发数
VITE_LLM_GAP_MS=500                # 请求间隔（毫秒）
VITE_OUTPUT_LANGUAGE=zh-CN         # 输出语言
```

### 配置说明

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `VITE_API_BASE_URL` | 后端 API 地址，Docker 部署时使用 `/api` | `/api` |
| `VITE_MAX_ANALYZE_FILES` | 单次扫描最大文件数，0表示无限制 | `0` |
| `VITE_LLM_CONCURRENCY` | 前端 LLM 并发请求数 | `2` |
| `VITE_LLM_GAP_MS` | 前端请求间隔 | `500` |
| `VITE_OUTPUT_LANGUAGE` | 分析结果输出语言 | `zh-CN` |

---

## 运行时配置

DeepAudit 支持在浏览器中进行运行时配置，无需重启服务。

### 访问方式

1. 登录系统后，访问 `/admin` 系统管理页面
2. 或点击侧边栏的"系统管理"菜单

### 可配置项

#### LLM 配置

- LLM 提供商选择
- API Key 配置
- 模型选择
- 自定义 API 端点（中转站）
- 超时时间
- 温度参数
- 最大 Token 数

#### 分析参数

- 最大分析文件数
- 并发请求数
- 请求间隔时间
- 输出语言

#### Git 集成

- GitHub Token
- GitLab Token

### 配置优先级

运行时配置 > 后端环境变量 > 默认值

---

## 数据存储

DeepAudit 采用前后端分离架构，所有数据存储在后端 PostgreSQL 数据库中。

### 架构说明

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   前端      │────▶│   后端 API  │────▶│ PostgreSQL  │
│  (React)    │     │  (FastAPI)  │     │   数据库    │
└─────────────┘     └─────────────┘     └─────────────┘
```

### 特点

- ✅ 数据持久化存储
- ✅ 支持多用户
- ✅ 支持用户认证
- ✅ 数据导入/导出功能
- ✅ 团队协作

### 数据管理

在 `/admin` 页面的"数据库管理"标签页中，可以：

- **导出数据**: 将所有数据导出为 JSON 文件备份
- **导入数据**: 从 JSON 文件恢复数据
- **清空数据**: 删除所有数据（谨慎操作）
- **健康检查**: 检查数据库连接状态

---

## API 中转站配置

许多用户使用 API 中转服务来访问 LLM（更稳定、更便宜、解决网络问题）。

### 后端配置（推荐）

```env
LLM_PROVIDER=openai
LLM_API_KEY=中转站提供的Key
LLM_BASE_URL=https://your-proxy.com/v1
LLM_MODEL=gpt-4o-mini
```

### 运行时配置

1. 访问系统管理页面（`/admin`）
2. 在"系统配置"标签页中：
   - 选择 LLM 提供商
   - 填入中转站提供的 API Key
   - 设置自定义 API 基础 URL
3. 保存配置

### 常见中转站

| 中转站 | 说明 |
|--------|------|
| [OpenRouter](https://openrouter.ai/) | 支持多种模型 |
| [API2D](https://api2d.com/) | 国内访问友好 |
| [CloseAI](https://www.closeai-asia.com/) | 价格实惠 |

### 注意事项

1. 确保中转站支持你选择的模型
2. 中转站的 API 格式需要与 OpenAI 兼容
3. 部分中转站可能有请求限制

---

## 审计规则配置

DeepAudit 支持自定义审计规则集，可以根据团队需求定制检测规则。

### 访问方式

1. 登录系统后，访问 `/audit-rules` 审计规则页面
2. 或点击侧边栏的"审计规则"菜单

### 内置规则集

#### 1. OWASP Top 10（默认）

基于 OWASP Top 10 2021 的安全审计规则集，包含 10 条规则：

| 规则代码 | 名称 | 严重程度 | 检测提示词 |
|----------|------|----------|------------|
| A01 | 访问控制失效 | Critical | 检查是否存在访问控制失效问题：权限检查缺失、越权访问、IDOR（不安全的直接对象引用）、CORS配置错误 |
| A02 | 加密机制失效 | Critical | 检查是否存在加密问题：使用弱加密算法(MD5/SHA1/DES)、明文存储密码、硬编码密钥、不安全的随机数生成 |
| A03 | 注入攻击 | Critical | 检查是否存在注入漏洞：SQL注入、命令注入、LDAP注入、XPath注入、NoSQL注入、表达式语言注入 |
| A04 | 不安全设计 | High | 检查是否存在不安全的设计：缺少速率限制、业务逻辑漏洞、缺少输入验证、信任边界不清 |
| A05 | 安全配置错误 | High | 检查是否存在安全配置错误：默认凭证、不必要的功能启用、详细错误信息泄露、缺少安全头 |
| A06 | 易受攻击的组件 | High | 检查是否使用了已知漏洞的组件：过时的依赖库、未修补的漏洞、不安全的第三方组件 |
| A07 | 身份认证失效 | Critical | 检查是否存在身份认证问题：弱密码策略、会话固定、凭证明文存储、缺少多因素认证 |
| A08 | 数据完整性失效 | Critical | 检查是否存在完整性问题：不安全的反序列化、未验证的更新、CI/CD管道安全 |
| A09 | 日志监控失效 | Medium | 检查是否存在日志监控问题：缺少安全日志、敏感信息记录到日志、缺少告警机制 |
| A10 | SSRF | High | 检查是否存在SSRF漏洞：未验证的URL输入、内网资源访问、云元数据访问 |

#### 2. 代码质量规则

通用代码质量检查规则集，包含 8 条规则：

| 规则代码 | 名称 | 严重程度 | 检测提示词 |
|----------|------|----------|------------|
| CQ001 | 函数过长 | Medium | 检查函数是否过长（超过50行），是否应该拆分为更小的函数 |
| CQ002 | 重复代码 | Medium | 检查是否存在重复的代码块，可以提取为公共函数或类 |
| CQ003 | 嵌套过深 | Low | 检查代码嵌套是否过深（超过4层），影响可读性 |
| CQ004 | 魔法数字 | Low | 检查是否存在魔法数字或魔法字符串，应该定义为常量 |
| CQ005 | 缺少错误处理 | High | 检查是否缺少必要的错误处理，可能导致程序崩溃 |
| CQ006 | 未使用的变量 | Low | 检查是否存在声明但未使用的变量 |
| CQ007 | 命名不规范 | Low | 检查命名是否符合语言规范和最佳实践 |
| CQ008 | 注释缺失 | Low | 检查复杂逻辑是否缺少必要的注释说明 |

#### 3. 性能优化规则

性能问题检测规则集，包含 5 条规则：

| 规则代码 | 名称 | 严重程度 | 检测提示词 |
|----------|------|----------|------------|
| PERF001 | N+1查询 | High | 检查是否存在N+1查询问题，在循环中执行数据库查询 |
| PERF002 | 内存泄漏 | Critical | 检查是否存在内存泄漏：未关闭的资源、循环引用、大对象未释放 |
| PERF003 | 低效算法 | Medium | 检查是否存在低效算法，如O(n²)可优化为O(n)或O(nlogn) |
| PERF004 | 不必要的对象创建 | Medium | 检查是否在循环中创建不必要的对象，应该移到循环外 |
| PERF005 | 同步阻塞 | Medium | 检查是否存在同步阻塞操作，应该使用异步方式 |

### 自定义规则集

可以创建自定义规则集，每条规则包含：

- **规则代码**: 唯一标识符（如 SEC001）
- **规则名称**: 规则的简短描述
- **规则描述**: 详细说明
- **类别**: security / bug / performance / style / maintainability
- **严重程度**: critical / high / medium / low
- **自定义提示词**: 增强 LLM 检测的提示词（关键字段）
- **修复建议**: 问题修复模板
- **参考链接**: CWE/OWASP 等参考资料

### 规则集导入/导出

支持 JSON 格式的规则集导入导出，方便团队共享：

```json
{
  "name": "自定义安全规则",
  "description": "团队自定义的安全检测规则",
  "language": "all",
  "rule_type": "security",
  "rules": [
    {
      "rule_code": "CUSTOM001",
      "name": "敏感信息硬编码",
      "description": "检测代码中硬编码的敏感信息",
      "category": "security",
      "severity": "critical",
      "custom_prompt": "检查是否存在硬编码的密码、API Key、Token、私钥等敏感信息",
      "fix_suggestion": "使用环境变量或配置文件存储敏感信息"
    }
  ]
}
```

---

## 提示词模板配置

DeepAudit 支持自定义审计提示词模板，可以针对不同场景优化分析效果。

### 访问方式

1. 登录系统后，访问 `/prompts` 提示词管理页面
2. 或点击侧边栏的"提示词管理"菜单

### 内置模板

#### 1. 默认代码审计（默认）

全面的代码审计提示词，涵盖安全、性能、代码质量等多个维度：

```
你是一个专业的代码审计助手。请从以下维度全面分析代码：
- 安全漏洞（SQL注入、XSS、命令注入、路径遍历、SSRF、XXE、反序列化、硬编码密钥等）
- 潜在的 Bug 和逻辑错误
- 性能问题和优化建议
- 编码规范和代码风格
- 可维护性和可读性
- 最佳实践和设计模式

请尽可能多地找出代码中的所有问题，不要遗漏任何安全漏洞或潜在风险！
```

#### 2. 安全专项审计

专注于安全漏洞检测的提示词模板：

```
你是一个专业的安全审计专家。请专注于检测以下安全问题：

【注入类漏洞】
- SQL注入（包括盲注、时间盲注、联合查询注入）
- 命令注入（OS命令执行）
- LDAP注入、XPath注入、NoSQL注入

【跨站脚本（XSS）】
- 反射型XSS、存储型XSS、DOM型XSS

【认证与授权】
- 硬编码凭证、弱密码策略、会话管理问题、权限绕过

【敏感数据】
- 敏感信息泄露、不安全的加密、明文传输敏感数据

【其他安全问题】
- SSRF、XXE、反序列化漏洞、路径遍历、文件上传漏洞、CSRF

请详细说明每个漏洞的风险等级、利用方式和修复建议。
```

#### 3. 性能优化审计

专注于性能问题检测的提示词模板：

```
你是一个专业的性能优化专家。请专注于检测以下性能问题：

【数据库性能】
- N+1查询问题、缺少索引、不必要的全表扫描、大量数据一次性加载、未使用连接池

【内存问题】
- 内存泄漏、大对象未及时释放、缓存使用不当、循环中创建大量对象

【算法效率】
- 时间复杂度过高、不必要的重复计算、可优化的循环、递归深度过大

【并发问题】
- 线程安全问题、死锁风险、资源竞争、不必要的同步

【I/O性能】
- 同步阻塞I/O、未使用缓冲、频繁的小文件操作、网络请求未优化

请提供具体的优化建议和预期的性能提升。
```

#### 4. 代码质量审计

专注于代码质量和可维护性的提示词模板：

```
你是一个专业的代码质量审计专家。请专注于检测以下代码质量问题：

【代码规范】
- 命名不规范（变量、函数、类）、代码格式不一致、注释缺失或过时、魔法数字/字符串

【代码结构】
- 函数过长（超过50行）、类职责不单一、嵌套层级过深、重复代码

【可维护性】
- 高耦合低内聚、缺少错误处理、硬编码配置、缺少日志记录

【设计模式】
- 违反SOLID原则、可使用设计模式优化的场景、过度设计

【测试相关】
- 难以测试的代码、缺少边界条件处理、依赖注入问题

请提供具体的重构建议和代码示例。
```

### 自定义模板

可以创建自定义提示词模板：

- **模板名称**: 模板的简短名称
- **模板描述**: 模板用途说明
- **中文提示词**: 中文版本的系统提示词
- **英文提示词**: 英文版本的系统提示词
- **模板变量**: 可在提示词中使用的变量

### 提示词测试

在创建或编辑模板时，可以使用"测试"功能验证提示词效果：

1. 选择测试代码语言（支持 Python、JavaScript、Java、Go、Swift、Kotlin 等）
2. 输入测试代码片段（或使用内置示例代码）
3. 选择输出语言（中文/英文）
4. 点击"测试"按钮查看分析结果

### 在审计任务中使用

创建审计任务时，可以选择：

1. **规则集**: 选择要应用的审计规则集
2. **提示词模板**: 选择要使用的提示词模板

---

## 提示词架构详解

本节详细说明 DeepAudit 如何构建发送给 LLM 的完整提示词。

### 提示词组成结构

发送给 LLM 的提示词由以下部分组成：

```
┌─────────────────────────────────────────────────────────────┐
│                    System Prompt (系统提示词)                 │
├─────────────────────────────────────────────────────────────┤
│  ① 提示词模板内容 (来自数据库或默认模板)                        │
│     - 定义 AI 的角色和任务                                    │
│     - 指定分析维度和重点                                      │
├─────────────────────────────────────────────────────────────┤
│  ② 输出格式要求                                              │
│     - JSON Schema 定义                                       │
│     - 字段说明和约束                                          │
├─────────────────────────────────────────────────────────────┤
│  ③ 审计规则 (如果选择了规则集)                                 │
│     - 规则代码、名称、描述                                    │
│     - 每条规则的检测提示词                                    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    User Prompt (用户提示词)                   │
├─────────────────────────────────────────────────────────────┤
│  ④ 编程语言                                                  │
│  ⑤ 带行号的代码内容                                          │
└─────────────────────────────────────────────────────────────┘
```

### 完整系统提示词示例（中文版）

以下是使用默认模板 + OWASP Top 10 规则集时，发送给 LLM 的完整系统提示词：

```
你是一个专业的代码审计助手。请从以下维度全面分析代码：
- 安全漏洞（SQL注入、XSS、命令注入、路径遍历、SSRF、XXE、反序列化、硬编码密钥等）
- 潜在的 Bug 和逻辑错误
- 性能问题和优化建议
- 编码规范和代码风格
- 可维护性和可读性
- 最佳实践和设计模式

请尽可能多地找出代码中的所有问题，不要遗漏任何安全漏洞或潜在风险！

【输出格式要求】
1. 必须只输出纯JSON对象
2. 禁止在JSON前后添加任何文字、说明、markdown标记
3. 所有文本字段（title, description, suggestion等）必须使用中文输出
4. 输出格式必须符合以下 JSON Schema：

{
    "issues": [
        {
            "type": "security|bug|performance|style|maintainability",
            "severity": "critical|high|medium|low",
            "title": "string",
            "description": "string",
            "suggestion": "string",
            "line": 1,
            "column": 1,
            "code_snippet": "string",
            "rule_code": "string (optional, if matched a specific rule)"
        }
    ],
    "quality_score": 0-100,
    "summary": {
        "total_issues": number,
        "critical_issues": number,
        "high_issues": number,
        "medium_issues": number,
        "low_issues": number
    }
}

【审计规则】请特别关注以下规则：
- [A01] 访问控制失效: 检测权限绕过、越权访问、IDOR等访问控制问题
  检测要点: 检查是否存在访问控制失效问题：权限检查缺失、越权访问、IDOR（不安全的直接对象引用）、CORS配置错误
- [A02] 加密机制失效: 检测弱加密、明文传输、密钥管理不当等问题
  检测要点: 检查是否存在加密问题：使用弱加密算法(MD5/SHA1/DES)、明文存储密码、硬编码密钥、不安全的随机数生成
- [A03] 注入攻击: 检测SQL注入、命令注入、LDAP注入等注入漏洞
  检测要点: 检查是否存在注入漏洞：SQL注入、命令注入、LDAP注入、XPath注入、NoSQL注入、表达式语言注入
... (其他规则)
```

### 用户提示词示例

```
编程语言: Python

代码已标注行号（格式：行号| 代码内容），请根据行号准确填写 line 字段。

请分析以下代码:

1| import sqlite3
2| 
3| def get_user(user_id):
4|     conn = sqlite3.connect('users.db')
5|     cursor = conn.cursor()
6|     query = f"SELECT * FROM users WHERE id = {user_id}"
7|     cursor.execute(query)
8|     return cursor.fetchone()
```

### 不使用自定义模板时的默认提示词

当没有选择提示词模板时，系统使用硬编码的默认提示词（中文版）：

```
⚠️⚠️⚠️ 只输出JSON，禁止输出其他任何格式！禁止markdown！禁止文本分析！⚠️⚠️⚠️

你是一个专业的代码审计助手。你的任务是分析代码并返回严格符合JSON Schema的结果。

【最重要】输出格式要求：
1. 必须只输出纯JSON对象，从{开始，到}结束
2. 禁止在JSON前后添加任何文字、说明、markdown标记
3. 禁止输出```json或###等markdown语法
4. 如果是文档文件（如README），也必须以JSON格式输出分析结果

【内容要求】：
1. 所有文本内容必须统一使用简体中文
2. JSON字符串值中的特殊字符必须正确转义（换行用\n，双引号用\"，反斜杠用\\）
3. code_snippet字段必须使用\n表示换行

请从以下维度全面、彻底地分析代码，找出所有问题：
- 安全漏洞（SQL注入、XSS、命令注入、路径遍历、SSRF、XXE、反序列化、硬编码密钥等）
- 潜在的 Bug 和逻辑错误
- 性能问题和优化建议
- 编码规范和代码风格
- 可维护性和可读性
- 最佳实践和设计模式

【重要】请尽可能多地找出代码中的所有问题，不要遗漏任何安全漏洞或潜在风险！

输出格式必须严格符合以下 JSON Schema：

{
    "issues": [
        {
            "type": "security|bug|performance|style|maintainability",
            "severity": "critical|high|medium|low",
            "title": "string",
            "description": "string",
            "suggestion": "string",
            "line": 1,
            "column": 1,
            "code_snippet": "string",
            "ai_explanation": "string",
            "xai": {
                "what": "string",
                "why": "string",
                "how": "string",
                "learn_more": "string(optional)"
            }
        }
    ],
    "quality_score": 0-100,
    "summary": {
        "total_issues": number,
        "critical_issues": number,
        "high_issues": number,
        "medium_issues": number,
        "low_issues": number
    },
    "metrics": {
        "complexity": 0-100,
        "maintainability": 0-100,
        "security": 0-100,
        "performance": 0-100
    }
}

注意：
- title: 问题的简短标题（中文）
- description: 详细描述问题（中文）
- suggestion: 具体的修复建议（中文）
- line: 问题所在的行号（从1开始计数，必须准确对应代码中的行号）
- column: 问题所在的列号（从1开始计数，指向问题代码的起始位置）
- code_snippet: 包含问题的代码片段
- ai_explanation: AI 的深入解释（中文）
- xai.what: 这是什么问题（中文）
- xai.why: 为什么会有这个问题（中文）
- xai.how: 如何修复这个问题（中文）

【重要】关于行号和代码片段：
1. line 必须是问题代码的行号！代码左侧有"行号|"标注
2. column 是问题代码在该行中的起始列位置
3. code_snippet 应该包含问题代码及其上下文（前后各1-2行）
4. 如果代码片段包含多行，必须使用 \n 表示换行符
5. 如果无法确定准确的行号，不要填写line和column字段

【严格禁止】：
- 禁止在任何字段中使用英文，所有内容必须是简体中文
- 禁止在JSON字符串值中使用真实换行符，必须用\n转义
- 禁止输出markdown代码块标记（如```json）

⚠️ 重要提醒：line字段必须从代码左侧的行号标注中读取，不要猜测或填0！
```

### 提示词优先级

1. **用户选择的提示词模板** > **数据库默认模板** > **硬编码默认提示词**
2. 规则集是可选的，如果选择了规则集，规则会追加到系统提示词末尾

---

## 更多资源

- [部署指南](DEPLOYMENT.md) - 详细的部署说明
- [LLM 平台支持](LLM_PROVIDERS.md) - 各 LLM 平台的配置方法
- [常见问题](FAQ.md) - 配置相关问题解答
