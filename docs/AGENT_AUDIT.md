# DeepAudit Agent 审计模块 v3.0.0

## 概述

Agent 审计模块是 DeepAudit v3.0.0 的核心功能，基于 **Multi-Agent 架构** 实现自主代码安全分析和漏洞验证。

### 核心特性

- 🤖 **Multi-Agent 协作**: Orchestrator 编排决策，多智能体协作审计
- 🧠 **RAG 知识库增强**: 代码语义理解 + CWE/CVE 漏洞知识库
- 🔒 **沙箱漏洞验证**: Docker 安全容器自动执行 PoC
- 🛠️ **专业工具集成**: Semgrep、Bandit、Gitleaks、OSV-Scanner 等

---

## 架构设计

### Multi-Agent 工作流

```
┌─────────────────────────────────────────────────────────────────────┐
│                     DeepAudit Agent 审计工作流                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│    START                                                            │
│      │                                                              │
│      ▼                                                              │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │               Orchestrator Agent (编排决策)                      │ │
│  │  • 分析审计目标          • 制定审计策略                          │ │
│  │  • 分配子任务            • 汇总审计结果                          │ │
│  └────────────────────────────┬───────────────────────────────────┘ │
│                               │                                     │
│              ┌────────────────┼────────────────┐                    │
│              ▼                ▼                ▼                    │
│  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐    │
│  │   Recon Agent    │ │  Analysis Agent  │ │Verification Agent│    │
│  │  (信息收集)      │ │  (漏洞分析)      │ │  (漏洞验证)      │    │
│  │                  │ │                  │ │                  │    │
│  │ • 项目结构分析   │ │ • Semgrep 扫描   │ │ • 沙箱测试      │    │
│  │ • 技术栈识别     │ │ • RAG 语义搜索   │ │ • PoC 编写与迭代 │    │
│  │ • 入口点发现     │ │ • LLM 深度分析   │ │ • 误报过滤      │    │
│  │ • 依赖扫描       │ │ • 数据流追踪     │ │ • 置信度评估    │    │
│  └────────┬─────────┘ └────────┬─────────┘ └────────┬─────────┘    │
│           │                    │                    │               │
│           └────────────────────┴────────────────────┘               │
│                               │                                     │
│                               ▼                                     │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                     Report Generation                           │ │
│  │  • 漏洞汇总              • 安全评分                            │ │
│  │  • 修复建议              • 统计分析                            │ │
│  └────────────────────────────┬───────────────────────────────────┘ │
│                               │                                     │
│                               ▼                                     │
│                              END                                    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Agent 职责

| Agent | 职责 | 使用工具 |
|-------|------|----------|
| **Orchestrator** | 统筹编排，自主决策审计策略 | 任务分配、结果汇总 |
| **Recon** | 信息收集，识别技术栈和入口点 | list_files, npm_audit, safety_scan, gitleaks |
| **Analysis** | 深度分析，挖掘潜在安全漏洞 | semgrep, bandit, rag_query, code_analysis |
| **Verification** | 沙箱验证，确认漏洞真实有效，调用 PoC 编写子 Agent 生成攻击脚本 | sandbox_exec, vulnerability_validation, sandbox_attack |

---

## 快速开始

### 1. 部署 Agent 模式

```bash
# 配置环境变量
cp backend/env.example backend/.env
# 编辑 .env，设置 AGENT_ENABLED=true

# 启动完整服务
docker compose up -d
```

### 2. 构建沙箱镜像

```bash
cd docker/sandbox
./build.sh
```

### 3. 使用 Agent 审计

1. 在项目详情页点击 "Agent 审计"
2. 选择目标漏洞类型
3. 可选：上传知识库文件增强检测
4. 启动审计，实时查看 Agent 执行日志

---

## 工具集

### 内置工具

| 工具 | 功能 | Agent |
|------|------|-------|
| `list_files` | 目录浏览 | Recon |
| `read_file` | 文件读取 | All |
| `search_code` | 代码搜索 | Analysis |
| `rag_query` | 语义检索 | Analysis |
| `security_search` | 安全代码搜索 | Analysis |
| `function_context` | 函数上下文 | Analysis |
| `pattern_match` | 模式匹配 | Analysis |
| `code_analysis` | LLM 分析 | Analysis |
| `dataflow_analysis` | 数据流追踪 | Analysis |
| `vulnerability_validation` | 漏洞验证 | Verification |
| `sandbox_exec` | 沙箱执行 | Verification |
| `verify_vulnerability` | 自动验证 | Verification |

### 外部安全工具

| 工具 | 功能 | 适用场景 |
|------|------|----------|
| `semgrep_scan` | Semgrep 静态分析 | 多语言快速扫描 |
| `bandit_scan` | Bandit Python 扫描 | Python 安全分析 |
| `gitleaks_scan` | Gitleaks 密钥检测 | 密钥泄露检测 |
| `trufflehog_scan` | TruffleHog 扫描 | 深度密钥扫描 |
| `npm_audit` | npm 依赖审计 | Node.js 依赖漏洞 |
| `safety_scan` | Safety Python 审计 | Python 依赖漏洞 |
| `osv_scan` | OSV 漏洞扫描 | 多语言依赖漏洞 |

---

## RAG 系统

### 功能特点

- **代码分块**: 基于 Tree-sitter AST 的智能分块
- **向量存储**: ChromaDB 持久化
- **多语言支持**: Python, JavaScript, TypeScript, Java, Go, PHP, Rust 等
- **知识库增强**: 支持上传自定义漏洞知识库

### 配置

```env
# 嵌入模型配置
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small

# 向量数据库配置
VECTOR_DB_TYPE=chroma
```

---

## 安全沙箱

### 功能特点

- **Docker 隔离**: 安全容器执行 PoC
- **资源限制**: 内存、CPU 限制
- **网络隔离**: 可配置网络访问
- **seccomp 策略**: 系统调用白名单

### 配置

```env
SANDBOX_ENABLED=true
SANDBOX_IMAGE=deepaudit-sandbox:latest
SANDBOX_MEMORY_LIMIT=512m
SANDBOX_CPU_LIMIT=1.0
SANDBOX_NETWORK_DISABLED=true
```

### 沙箱镜像内置工具

- Python 3.11 + Semgrep, Bandit, Safety
- Node.js 20 + npm audit
- Go 1.21 + OSV-Scanner
- Rust + cargo-audit
- Gitleaks, TruffleHog

---

## API 接口

### 创建任务

```http
POST /api/v1/agent-tasks/
Content-Type: application/json

{
  "project_id": "xxx",
  "name": "安全审计",
  "target_vulnerabilities": ["sql_injection", "xss"],
  "verification_level": "sandbox",
  "max_iterations": 3
}
```

### 事件流

```http
GET /api/v1/agent-tasks/{task_id}/events
Accept: text/event-stream
```

### 获取发现

```http
GET /api/v1/agent-tasks/{task_id}/findings?verified_only=true
```

### 任务摘要

```http
GET /api/v1/agent-tasks/{task_id}/summary
```

### 导出报告

```http
GET /api/v1/agent-tasks/{task_id}/report?format=markdown
```

---

## 支持的漏洞类型

| 类型 | 说明 |
|------|------|
| `sql_injection` | SQL 注入 |
| `xss` | 跨站脚本 |
| `command_injection` | 命令注入 |
| `path_traversal` | 路径遍历 |
| `ssrf` | 服务端请求伪造 |
| `xxe` | XML 外部实体 |
| `insecure_deserialization` | 不安全反序列化 |
| `hardcoded_secret` | 硬编码密钥 |
| `weak_crypto` | 弱加密 |
| `authentication_bypass` | 认证绕过 |
| `authorization_bypass` | 授权绕过 |
| `idor` | 不安全直接对象引用 |

---

## 目录结构

```
backend/app/services/agent/
├── __init__.py              # 模块导出
├── event_manager.py         # 事件管理
├── agents/                  # Agent 实现
│   ├── __init__.py
│   ├── base.py             # Agent 基类
│   ├── recon.py            # 信息收集 Agent
│   ├── analysis.py         # 漏洞分析 Agent
│   ├── verification.py     # 漏洞验证 Agent
│   └── orchestrator.py     # 编排 Agent
├── tools/                   # Agent 工具
│   ├── __init__.py
│   ├── base.py             # 工具基类
│   ├── rag_tool.py         # RAG 工具
│   ├── pattern_tool.py     # 模式匹配工具
│   ├── code_analysis_tool.py
│   ├── file_tool.py        # 文件操作
│   ├── sandbox_tool.py     # 沙箱工具
│   └── external_tools.py   # 外部安全工具
└── prompts/                 # 系统提示词
    ├── __init__.py
    └── system_prompts.py
```

---

## 故障排除

### 常见问题

**Q: Agent 审计启动失败**

```bash
# 检查服务状态
docker compose ps

# 查看后端日志
docker compose logs backend | grep -i agent
```

**Q: RAG 初始化失败**

```bash
# 检查嵌入模型配置
# 确保 EMBEDDING_API_KEY 正确设置
```

**Q: 沙箱执行失败**

```bash
# 检查沙箱镜像
docker images | grep deepaudit-sandbox

# 重新构建沙箱
cd docker/sandbox && ./build.sh
```

**Q: 外部工具不可用**

```bash
# 检查工具安装（本地开发时）
which semgrep bandit gitleaks

# 或使用 Docker 沙箱执行
```

### 日志查看

```bash
# 查看 Agent 日志
docker compose logs -f backend | grep -E "(agent|Agent)"

# 查看详细日志
tail -f logs/agent.log
```

---

## 更多资源

- [部署指南](DEPLOYMENT.md) - 完整部署说明
- [配置说明](CONFIGURATION.md) - 详细配置参数
- [架构详解](AGENT_AUDIT_ARCHITECTURE.md) - 深度架构文档
