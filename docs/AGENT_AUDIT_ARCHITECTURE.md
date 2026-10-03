# DeepAudit 项目架构文档

## 目录

1. [系统概述](#1-系统概述)
2. [核心设计理念](#2-核心设计理念)
3. [后端架构](#3-后端架构)
   - [Agent层级结构](#31-agent层级结构)
   - [核心基础设施](#32-核心基础设施)
   - [工具生态系统](#33-工具生态系统)
   - [知识库与提示词](#34-知识库与提示词)
4. [前端架构](#4-前端架构)
5. [API接口](#5-api接口)
6. [审计任务执行流程](#6-审计任务执行流程)
7. [事件流与遥测](#7-事件流与遥测)
8. [配置与部署](#8-配置与部署)
9. [关键设计模式](#9-关键设计模式)
10. [安全与健壮性](#10-安全与健壮性)
11. [扩展指南](#11-扩展指南)
12. [项目整体架构](#12-项目整体架构)
13. [核心业务流程](#13-核心业务流程)
14. [数据模型与存储](#14-数据模型与存储)

---

## 1. 系统概述

DeepAudit Agent 审计系统是一个基于大语言模型(LLM)驱动的自主化安全代码分析系统。该系统采用**动态多Agent层级架构**，实现了从代码侦察、漏洞分析到验证确认的完整安全审计流程。

### 核心特性

| 特性 | 描述 |
|------|------|
| **LLM中心化决策** | LLM作为系统的"大脑"，在各个层级自主做出决策 |
| **动态Agent树** | 根据任务需求动态构建层级化的多Agent系统 |
| **ReAct模式** | 实现思考-行动-观察(Thought-Action-Observation)循环 |
| **事件驱动架构** | 通过SSE实时推送事件到前端 |
| **丰富的工具生态** | 20+专业工具覆盖代码分析、模式匹配、漏洞验证 |

### 技术栈

- **后端**: Python 3.11+, FastAPI, LangChain/LiteLLM
- **前端**: React 18, TypeScript, Ant Design
- **数据库**: PostgreSQL (Supabase)
- **通信**: SSE (Server-Sent Events), REST API

---

## 2. 核心设计理念

### 2.1 LLM自主决策

与传统的规则驱动自动化不同，本系统中**LLM做出所有战略决策**：

```
传统方式: 规则 → 固定流程 → 结果
DeepAudit: LLM分析 → 自主决策 → 动态调整 → 结果
```

LLM负责决定：
- 何时派发哪个子Agent
- 使用哪些工具进行分析
- 何时认为分析已足够充分
- 如何解读和关联发现的问题

### 2.2 ReAct模式实现

每个Agent的执行遵循ReAct（Reasoning + Acting）模式：

```
┌─────────────────────────────────────────────────┐
│                  LLM 输出                        │
├─────────────────────────────────────────────────┤
│ Thought: 我应该先了解项目结构...                  │
│ Action: list_files                              │
│ Action Input: {"directory": ".", "pattern": "*"}│
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│                系统执行工具                       │
├─────────────────────────────────────────────────┤
│ Observation: [找到 app/, config/, tests/...]     │
└─────────────────────────────────────────────────┘
                      ↓
         反馈给LLM，继续下一轮循环
```

### 2.3 层级化Agent协作

```
                    ┌───────────────────┐
                    │  OrchestratorAgent │
                    │    (策略编排者)     │
                    └─────────┬─────────┘
                              │
            ┌─────────────────┼─────────────────┐
            ↓                 ↓                 ↓
    ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
    │  ReconAgent   │ │ AnalysisAgent │ │VerificationAgent│
    │  (情报收集)    │ │  (漏洞猎手)    │ │   (验证确认)   │
    └───────────────┘ └───────────────┘ └───────────────┘
```

---

## 3. 后端架构

### 3.1 Agent层级结构

所有Agent代码位于 `backend/app/services/agent/agents/` 目录。

#### 3.1.1 BaseAgent 基类

**文件**: `base.py`

BaseAgent是所有Agent的抽象基类，提供核心功能：

```python
class BaseAgent:
    """Agent基类 - 提供通用功能"""

    # 核心配置
    config: AgentConfig  # 名称、类型、模式、最大token数、最大迭代次数
    state: AgentState    # 状态管理(status, messages, findings)

    # 关键方法
    async def run(self, input_data: dict) -> AgentResult  # 抽象方法
    async def stream_llm_call()    # 统一的LLM调用(支持流式+自动压缩)
    async def execute_tool()       # 工具执行(带错误处理)

    # 事件发射
    def emit_thinking_token()      # 流式输出LLM思考过程
    def emit_thinking_start/end()  # 思考生命周期
    def emit_tool_call/result()    # 工具执行生命周期
    def emit_finding()             # 漏洞发现事件
```

**关键特性**：
- 消息历史压缩（超过100k token时自动截断）
- 取消支持（`is_cancelled`属性）
- 知识模块动态加载
- 动态父子关系管理

#### 3.1.2 OrchestratorAgent 编排器

**文件**: `orchestrator.py`
**角色**: 战略编排与动态任务调度
**最大迭代次数**: 20

```python
class OrchestratorAgent(BaseAgent):
    """编排器Agent - 协调整体审计流程"""

    async def run(self, input_data: dict) -> AgentResult:
        """主ReAct循环 - LLM决定下一步行动"""
        # dispatch_agent: 派发子Agent
        # summarize: 汇总当前进度
        # finish: 完成审计

    async def _dispatch_agent(self, agent_name: str, task: str):
        """派发ReconAgent、AnalysisAgent或VerificationAgent"""

    def _parse_llm_response(self, response: str):
        """从LLM输出中提取Thought/Action/Action Input"""
```

**决策点**：
- 决定派发哪个子Agent
- 判断何时完成审计
- 汇总所有子Agent的发现

#### 3.1.3 ReconAgent 侦察员

**文件**: `recon.py`
**角色**: 项目分析与情报收集
**最大迭代次数**: 15

**主要任务**：
- 发现项目结构
- 识别技术栈和框架
- 定位入口点
- 标记高风险区域

**可用工具**: `list_files`, `read_file`, `search_code`

**输出格式**：
```json
{
  "project_structure": {...},
  "tech_stack": {"languages": ["Python"], "frameworks": ["Django"]},
  "entry_points": ["app/views.py", "api/routes.py"],
  "high_risk_areas": ["auth/", "payment/"],
  "initial_findings": [...]
}
```

#### 3.1.4 AnalysisAgent 分析员

**文件**: `analysis.py`
**角色**: 深度代码漏洞分析
**最大迭代次数**: 30

**主要工具**：

| 工具 | 描述 | 优先级 |
|------|------|--------|
| `smart_scan` | 智能批量安全扫描 | **推荐首选** |
| `quick_audit` | 快速文件审计 | 二级 |
| `pattern_match` | 危险模式检测 | 三级 |
| `dataflow_analysis` | 数据流追踪 | 深度分析 |
| `semgrep_scan` | Semgrep静态分析 | 外部工具 |
| `bandit_scan` | Python安全检测 | 外部工具 |
| `gitleaks_scan` | 密钥泄露检测 | 外部工具 |

**关注的漏洞类型**：
- SQL注入
- XSS跨站脚本
- 命令注入
- 路径遍历
- SSRF服务端请求伪造

#### 3.1.5 VerificationAgent 验证员

**文件**: `verification.py`
**角色**: 确认发现并生成PoC
**最大迭代次数**: 15

**主要职责**：
- 减少误报
- 验证可利用性
- 生成概念验证(PoC)

**输出格式**：
```json
{
  "is_verified": true,
  "poc": {
    "description": "...",
    "steps": [...],
    "payload": "..."
  },
  "exploitability": "high",
  "confidence": 0.95
}
```

#### 3.1.6 TaskHandoff 任务交接协议

Agent之间通过结构化的`TaskHandoff`进行协作：

```python
@dataclass
class TaskHandoff:
    """Agent间的结构化通信协议"""
    work_completed: str          # 已完成的工作
    key_findings: List[dict]     # 关键发现
    insights: List[str]          # 洞察
    suggested_actions: List[str] # 建议行动
    attention_points: List[str]  # 需要关注的点
    priority_areas: List[str]    # 优先区域
    context_data: dict           # 上下文数据

    def to_prompt_context(self) -> str:
        """转换为LLM可读格式"""
```

---

### 3.2 核心基础设施

核心基础设施位于 `backend/app/services/agent/core/` 目录。

#### 3.2.1 状态管理 (state.py)

```python
class AgentState:
    """Agent状态跟踪"""
    status: Literal["created", "running", "waiting", "completed", "failed"]
    messages: List[Message]  # 对话历史
    findings: List[Finding]  # 发现列表
    iterations: int          # 当前迭代次数
    tool_calls: int          # 工具调用次数
```

#### 3.2.2 执行上下文 (context.py)

```python
class ExecutionContext:
    """分布式追踪的执行上下文"""
    task_id: str           # 任务ID
    agent_id: str          # Agent ID
    trace_path: str        # 追踪路径 (如: Orchestrator > Analysis)
    depth: int             # 嵌套深度
    iteration: int         # 当前迭代
    metadata: dict         # 附加元数据

    def child_context(self, agent_id: str) -> ExecutionContext:
        """创建子上下文"""

    def with_iteration(self, iteration: int) -> ExecutionContext:
        """带迭代信息的上下文"""
```

#### 3.2.3 熔断器 (circuit_breaker.py)

```python
class CircuitBreaker:
    """熔断器 - 防止级联故障"""

    # 状态转换: CLOSED -> OPEN -> HALF_OPEN -> CLOSED

    failure_threshold: int = 5     # 失败阈值
    recovery_timeout: float = 30.0 # 恢复超时(秒)

    async def call(self, func: Callable) -> Any:
        """受保护的调用"""
        if self.state == CircuitState.OPEN:
            raise CircuitOpenError()
        try:
            result = await func()
            self._record_success()
            return result
        except Exception as e:
            self._record_failure()
            raise
```

#### 3.2.4 重试机制 (retry.py)

```python
class RetryStrategy:
    """指数退避重试"""
    base_delay: float = 1.0   # 基础延迟(秒)
    max_delay: float = 60.0   # 最大延迟(秒)
    max_retries: int = 3      # 最大重试次数

    def get_delay(self, attempt: int) -> float:
        """计算延迟: min(base * (2 ** attempt) + jitter, max)"""
```

#### 3.2.5 速率限制器 (rate_limiter.py)

```python
class RateLimiter:
    """令牌桶算法速率限制"""

    # 预设限制:
    # - 外部工具: 0.2 calls/second (每5秒1次)
    # - LLM调用: 60 calls/minute
    # - 突发支持: 最多3个并发调用

    async def acquire(self, tool_name: str):
        """获取执行许可"""
```

#### 3.2.6 输入验证 (validation.py)

```python
class InputValidator:
    """输入安全验证"""

    def validate_file_path(self, path: str) -> bool:
        """文件路径安全检查"""
        # - 检查路径遍历攻击
        # - 验证文件扩展名
        # - 检查符号链接

    def validate_file_size(self, path: str, max_size: int = 10_000_000):
        """文件大小限制(默认10MB)"""
```

#### 3.2.7 错误处理 (errors.py)

```python
# 自定义异常层级
class AgentError(Exception): pass
class CircuitOpenError(AgentError): pass      # 熔断器打开
class AgentExecutionError(AgentError): pass   # Agent执行失败
class ToolExecutionError(AgentError): pass    # 工具执行失败
class ValidationError(AgentError): pass       # 输入验证失败
class TokenLimitError(AgentError): pass       # Token超限
```

---

### 3.3 工具生态系统

工具代码位于 `backend/app/services/agent/tools/` 目录。

#### 3.3.1 文件操作工具

| 工具 | 文件 | 描述 |
|------|------|------|
| `FileReadTool` | - | 读取文件内容(支持行范围) |
| `ListFilesTool` | - | 列出目录内容(支持glob模式) |
| `FileSearchTool` | - | 按关键词搜索代码 |

#### 3.3.2 代码分析工具

**SmartScanTool** (`smart_scan_tool.py`)
```python
class SmartScanTool:
    """智能批量安全扫描 - 推荐首选工具"""

    # 功能:
    # - 自动检测漏洞模式
    # - 聚焦高风险文件
    # - 批量处理提高效率

    async def execute(self, target: str) -> dict:
        return {
            "vulnerabilities": [...],
            "risk_areas": [...],
            "recommendations": [...]
        }
```

**PatternMatchTool** (`pattern_tool.py`)
```python
class PatternMatchTool:
    """基于正则的模式检测"""

    # 内置模式:
    # - SQL注入模式
    # - XSS模式
    # - 命令注入模式
    # - 可作为Semgrep的后备
```

**DataFlowAnalysisTool** (`code_analysis_tool.py`)
```python
class DataFlowAnalysisTool:
    """数据流分析工具"""

    # 功能:
    # - 源点到汇点追踪
    # - 变量污点分析
    # - LLM辅助的数据流理解
```

#### 3.3.3 外部安全工具

**文件**: `external_tools.py`

| 工具 | 描述 | 超时 | 后备方案 |
|------|------|------|----------|
| `SemgrepTool` | 静态分析规则引擎 | 120s | PatternMatchTool |
| `BanditTool` | Python安全linter | 60s | PatternMatchTool |
| `GitleaksTool` | 密钥/凭证检测 | 60s | - |

#### 3.3.4 完成工具

**FinishTool** (`finish_tool.py`)
```python
class FinishTool:
    """任务完成工具"""

    async def execute(self, conclusion: str, findings: List[dict]):
        """标记任务完成并返回最终结果"""
```

---

### 3.4 知识库与提示词

#### 3.4.1 漏洞知识库

位于 `backend/app/services/agent/knowledge/vulnerabilities/`

**按漏洞类型组织**：

| 文件 | 漏洞类型 |
|------|----------|
| `sql_injection.py` | SQL注入 |
| `xss.py` | 跨站脚本 |
| `csrf.py` | 跨站请求伪造 |
| `auth.py` | 认证漏洞 |
| `ssrf.py` | 服务端请求伪造 |
| `path_traversal.py` | 路径遍历 |
| `deserialization.py` | 不安全反序列化 |
| `xxe.py` | XML外部实体注入 |
| `race_condition.py` | 竞态条件 |
| `crypto.py` | 弱加密 |
| `injection.py` | 代码/命令注入 |
| `business_logic.py` | 业务逻辑漏洞 |
| `open_redirect.py` | 开放重定向 |

**框架特定知识**：

| 文件 | 框架 |
|------|------|
| `FastAPI.py` | FastAPI安全模式 |
| `Django.py` | Django安全问题 |
| `Flask.py` | Flask漏洞 |
| `Express.js` | Node.js/Express模式 |
| `React.js` | 前端安全 |
| `Supabase.py` | BaaS安全 |

#### 3.4.2 系统提示词

**文件**: `backend/app/services/agent/prompts/system_prompts.py`

```python
# 核心安全原则
CORE_SECURITY_PRINCIPLES = """
- 深度分析优于广度覆盖
- 重视数据流追踪
- 上下文感知分析
- 假阳性需验证确认
"""

# 漏洞优先级
VULNERABILITY_PRIORITIES = {
    "critical": ["sql_injection", "command_injection", "code_injection"],
    "high": ["path_traversal", "ssrf", "auth_bypass"],
    "medium": ["xss", "information_disclosure", "xxe"],
    "low": ["csrf", "weak_crypto", "unsafe_transport"]
}

# 多Agent协作规则
MULTI_AGENT_RULES = """
- 避免重复工作
- 共享上下文信息
- 聚焦自身职责
- 及时交接发现
"""
```

---

## 4. 前端架构

前端代码位于 `frontend/src/pages/AgentAudit/` 目录。

### 4.1 目录结构

```
AgentAudit/
├── index.tsx              # 主页面组件
├── types.ts               # TypeScript类型定义
├── utils.ts               # 工具函数
├── constants.tsx          # 常量配置
├── hooks/
│   ├── useAgentAuditState.ts  # 状态管理(useReducer)
│   ├── useResilientStream.ts  # SSE流式连接
│   └── index.ts
└── components/
    ├── Header.tsx             # 标题、状态、控制按钮
    ├── StatsPanel.tsx         # 统计面板
    ├── AgentTreeNode.tsx      # Agent树节点渲染
    ├── AgentDetailPanel.tsx   # Agent详情侧边栏
    ├── LogEntry.tsx           # 单条日志条目
    ├── ConnectionStatus.tsx   # 连接状态指示器
    ├── StatusBadge.tsx        # 状态徽章
    ├── SplashScreen.tsx       # 初始屏幕
    ├── AgentErrorBoundary.tsx # 错误边界
    ├── ReportExportDialog.tsx # 导出对话框
    └── index.ts
```

### 4.2 状态管理

**文件**: `hooks/useAgentAuditState.ts`

```typescript
interface AgentAuditState {
  task: AgentTask | null;              // 当前任务
  findings: AgentFinding[];            // 发现列表
  agentTree: AgentTreeResponse | null; // Agent树
  logs: LogItem[];                     // 日志列表
  selectedAgentId: string | null;      // 选中的Agent
  connectionStatus: ConnectionStatus;   // 连接状态
  isAutoScroll: boolean;               // 自动滚动
  expandedLogIds: Set<string>;         // 展开的日志ID
}

type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

// Reducer Actions
type Action =
  | { type: 'SET_TASK'; payload: AgentTask }
  | { type: 'SET_FINDINGS'; payload: AgentFinding[] }
  | { type: 'ADD_LOG'; payload: LogItem }
  | { type: 'UPDATE_LOG'; payload: { id: string; updates: Partial<LogItem> } }
  | { type: 'SET_CONNECTION_STATUS'; payload: ConnectionStatus }
  | { type: 'SELECT_AGENT'; payload: string | null }
  | { type: 'TOGGLE_LOG_EXPANDED'; payload: string }
  | { type: 'RESET' };
```

### 4.3 事件流处理

**文件**: `hooks/useResilientStream.ts`

```typescript
function useResilientStream(taskId: string, options: StreamOptions) {
  // 功能:
  // - 弹性SSE连接(自动重连)
  // - Thinking token逐字符流式更新
  // - 按类型过滤事件
  // - 组件卸载时自动清理

  // 事件处理器
  onThinkingToken: (token: string) => void;  // 累积thinking内容
  onToolStart: (tool: ToolEvent) => void;    // 工具开始
  onToolEnd: (tool: ToolEvent) => void;      // 工具结束
  onFinding: (finding: Finding) => void;     // 新发现
  onComplete: () => void;                     // 任务完成
  onError: (error: Error) => void;           // 错误处理
}
```

### 4.4 日志类型

```typescript
type LogType =
  | 'thinking'  // LLM思考过程(支持流式)
  | 'tool'      // 工具执行(含耗时和状态)
  | 'phase'     // 工作流阶段
  | 'finding'   // 漏洞发现
  | 'info'      // 信息消息
  | 'error'     // 错误消息
  | 'dispatch'  // 子Agent派发
  | 'user';     // 用户操作

interface LogItem {
  id: string;
  type: LogType;
  timestamp: Date;
  content: string;
  metadata?: Record<string, any>;
  isExpanded?: boolean;
  isStreaming?: boolean;  // thinking类型专用
}
```

### 4.5 实时更新流程

```
SSE Stream → useResilientStream → dispatch() → reducer → UI更新
     ↓
thinking_token事件
     ↓
onThinkingToken回调
     ↓
dispatch({type: 'ADD_LOG', payload: {type: 'thinking', content: accumulated}})
     ↓
UI渲染LogEntry(流式效果)
```

---

## 5. API接口

API端点位于 `backend/app/api/v1/endpoints/agent_tasks.py`

### 5.1 任务管理

| 方法 | 端点 | 描述 |
|------|------|------|
| POST | `/agent-tasks/` | 创建并启动审计任务 |
| GET | `/agent-tasks/` | 列出任务(支持过滤) |
| GET | `/agent-tasks/{task_id}` | 获取任务详情 |
| POST | `/agent-tasks/{task_id}/cancel` | 取消运行中的任务 |

### 5.2 事件流

| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/agent-tasks/{task_id}/events` | 基础事件轮询(SSE) |
| GET | `/agent-tasks/{task_id}/stream` | 增强事件流(含thinking tokens) |

**查询参数**：
- `include_thinking`: 是否包含thinking token
- `include_tool_calls`: 是否包含工具调用
- `after_sequence`: 从指定序列号后开始

### 5.3 结果查询

| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/agent-tasks/{task_id}/findings` | 获取发现列表(支持分页) |
| GET | `/agent-tasks/{task_id}/summary` | 任务摘要与统计 |
| PATCH | `/agent-tasks/{task_id}/findings/{finding_id}/status` | 更新发现状态 |
| GET | `/agent-tasks/{task_id}/report` | 生成报告(markdown/json) |

### 5.4 高级功能

| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/agent-tasks/{task_id}/agent-tree` | Agent层级与执行统计 |
| GET | `/agent-tasks/{task_id}/checkpoints` | 执行检查点列表 |
| GET | `/agent-tasks/{task_id}/checkpoints/{checkpoint_id}` | 检查点详情 |

### 5.5 创建任务Schema

```python
class AgentTaskCreate(BaseModel):
    project_id: str                    # 项目ID
    name: Optional[str]                # 任务名称
    target_vulnerabilities: List[str] = [
        "sql_injection", "xss", "command_injection",
        "path_traversal", "ssrf"
    ]
    verification_level: str = "sandbox"  # 验证级别
    exclude_patterns: List[str] = [      # 排除模式
        "node_modules", "venv", "__pycache__", ".git"
    ]
    target_files: Optional[List[str]]    # 限定扫描文件
    max_iterations: int = 50             # 最大迭代(1-200)
    timeout_seconds: int = 1800          # 超时(60-7200秒)
```

---

## 6. 审计任务执行流程

### 6.1 完整流程图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        1. 任务创建                                   │
│  用户 → POST /agent-tasks/ → 创建AgentTask(PENDING) → 入队后台任务    │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                        2. 初始化                                     │
│  加载项目 → 收集项目信息 → 初始化工具 → 创建子Agent → 创建Orchestrator │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                   3. Orchestrator循环 (最多20轮)                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ 迭代 N:                                                       │   │
│  │  a) 调用LLM获取下一步决策                                      │   │
│  │  b) 解析: Thought / Action / Action Input                    │   │
│  │  c) 执行Action:                                              │   │
│  │     - dispatch_agent → 派发子Agent                           │   │
│  │     - finish → 完成审计                                       │   │
│  │  d) 发射事件到前端                                            │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                   4. 子Agent执行 (以Analysis为例)                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ 循环 (最多30轮):                                              │   │
│  │  a) LLM思考下一步                                             │   │
│  │  b) 选择并执行工具 (smart_scan, pattern_match, ...)          │   │
│  │  c) 将观察结果加入历史                                        │   │
│  │  d) 检测是否输出"Final Answer" → 解析发现，返回               │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                        5. 结果汇总                                   │
│  合并所有发现 → 去重 → 更新验证结果 → 构建findings列表               │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                        6. 持久化                                     │
│  更新AgentTask状态 → 保存到AgentFinding表 → 计算安全评分              │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                        7. 前端展示                                   │
│  实时SSE事件 → 日志累积 → Agent树生长 → 统计更新 → 最终结果展示        │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.2 详细执行示例

**场景**: 用户上传Python项目，执行Agent审计

```
1. 用户请求: POST /agent-tasks/
   {
     "project_id": "123",
     "target_files": ["app/views.py"]
   }

2. Orchestrator迭代1 - LLM输出:
   Thought: 我应该先用recon了解项目结构
   Action: dispatch_agent
   Action Input: {"agent": "recon", "task": "分析项目结构"}

3. ReconAgent执行:
   迭代1: list_files → 找到 app/views.py, models.py...
   迭代2: read_file → 读取app/views.py内容
   迭代N: Final Answer → 返回项目结构信息

4. Orchestrator迭代2 - LLM输出:
   Thought: 这是一个Django项目，让我派发Analysis进行漏洞分析
   Action: dispatch_agent
   Action Input: {"agent": "analysis", "task": "深度漏洞分析"}

5. AnalysisAgent执行:
   迭代1: smart_scan → 发现第42行可能存在SQL注入
   迭代2: read_file → 确认问题代码
   迭代M: Final Answer → 返回结构化的漏洞发现

6. Orchestrator迭代3 - LLM输出:
   Thought: 发现高危SQL注入，需要验证
   Action: dispatch_agent
   Action Input: {"agent": "verification", "task": "验证SQL注入"}

7. VerificationAgent确认:
   返回: {"is_verified": true, "poc": {...}}

8. Orchestrator完成:
   Thought: 审计完成，共发现1个已验证漏洞
   Action: finish
   Action Input: {"conclusion": "...", "findings": [...]}

9. 后端持久化:
   - AgentTask.status = COMPLETED
   - 写入AgentFinding表

10. 前端实时展示:
    - 日志流式更新
    - Agent树动态生长
    - 统计数据刷新
    - 最终展示发现列表
```

---

## 7. 事件流与遥测

### 7.1 事件管理器

**文件**: `backend/app/services/agent/event_manager.py`

```python
class EventManager:
    """事件管理器 - 内存队列 + 流式迭代"""

    max_events: int = 1000  # 最大事件数

    async def emit(self, event_type: str, message: str, **metadata):
        """发射事件"""

    async def stream_events(self):
        """异步迭代器: async for event in manager.stream_events()"""
```

### 7.2 事件类型

| 类型 | 描述 |
|------|------|
| `thinking_start` | LLM开始思考 |
| `thinking_token` | 思考token(逐字符) |
| `thinking_end` | LLM思考结束 |
| `tool_call` | 工具调用开始 |
| `tool_result` | 工具执行结果 |
| `finding` | 漏洞发现 |
| `phase_start` | 阶段开始 |
| `phase_complete` | 阶段完成 |
| `dispatch` | 子Agent派发 |
| `llm_thought` | LLM思考内容 |
| `llm_decision` | LLM决策 |
| `error` | 错误 |
| `warning` | 警告 |
| `info` | 信息 |

### 7.3 遥测追踪

**文件**: `backend/app/services/agent/telemetry/tracer.py`

```python
class Tracer:
    """分布式追踪"""

    def create_span(self, name: str, parent_span: Span = None) -> Span:
        """创建追踪Span"""

    # 追踪路径示例: Orchestrator > Analysis > (Verification)

    # 记录的指标:
    # - 执行时间
    # - Token使用量
    # - 工具调用次数
    # - 关联ID
```

---

## 8. 配置与部署

### 8.1 Agent配置

**文件**: `backend/app/services/agent/config.py`

```python
class AgentConfig:
    """Agent配置 (环境变量前缀: AGENT_)"""

    # LLM设置
    llm_max_retries: int = 3
    llm_retry_base_delay: float = 1.0
    llm_timeout_seconds: int = 120
    llm_max_tokens_per_call: int = 4096
    llm_temperature: float = 0.1
    llm_stream_enabled: bool = True

    # Agent迭代限制
    orchestrator_max_iterations: int = 20
    recon_max_iterations: int = 15
    analysis_max_iterations: int = 30
    verification_max_iterations: int = 15

    # 工具设置
    tool_timeout_seconds: int = 60
    tool_max_retries: int = 2
    semgrep_enabled: bool = True
    bandit_enabled: bool = True
    gitleaks_enabled: bool = True

    # 资源限制
    max_file_size_bytes: int = 10_000_000  # 10MB
    max_files_per_scan: int = 1000
    max_total_findings: int = 500
    max_context_messages: int = 50

    # 熔断器
    circuit_breaker_enabled: bool = True
    circuit_failure_threshold: int = 5
    circuit_recovery_timeout_seconds: float = 30.0

    # 检查点
    checkpoint_enabled: bool = True
    checkpoint_interval_iterations: int = 5
    max_checkpoints_per_task: int = 50
```

### 8.2 环境预设

```python
def apply_development_preset():
    """开发环境预设"""
    # 更宽松的限制，更多日志

def apply_production_preset():
    """生产环境预设"""
    # 更严格的限制，优化性能

def apply_testing_preset():
    """测试环境预设"""
    # 快速迭代，最小资源
```

---

## 9. 关键设计模式

### 9.1 LLM中心化决策

```
┌─────────────────────────────────────────────┐
│              传统自动化                      │
│  规则引擎 → 固定流程 → 预定义行为           │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│              DeepAudit                       │
│  LLM分析 → 自主决策 → 动态适应 → 智能输出   │
└─────────────────────────────────────────────┘
```

### 9.2 ReAct模式

```
Loop:
  1. Thought: LLM思考当前状态和下一步
  2. Action: 选择要执行的动作/工具
  3. Action Input: 提供参数
  4. Observation: 获取执行结果
  5. 重复直到达成目标或Final Answer
```

### 9.3 任务交接协议

```python
# Agent A完成工作后
handoff = TaskHandoff(
    work_completed="扫描了10个文件，发现3个可疑点",
    key_findings=[finding1, finding2, finding3],
    suggested_actions=["验证SQL注入", "检查认证逻辑"],
    priority_areas=["auth/", "api/"]
)

# 转换为下一个Agent的输入
context = handoff.to_prompt_context()
# Agent B使用此上下文继续工作
```

### 9.4 优雅降级

```
┌───────────────────────────────────────────────────┐
│                 优雅降级策略                       │
├───────────────────────────────────────────────────┤
│ • 工具失败不中断执行 (continue_on_tool_failure)   │
│ • 后备工具链 (Semgrep → PatternMatch)             │
│ • 超时时返回部分结果                              │
│ • 熔断器防止级联故障                              │
│ • 消息压缩避免token超限                           │
└───────────────────────────────────────────────────┘
```

### 9.5 范围限定审计

```python
# 支持的范围限定:
AgentTaskCreate(
    exclude_patterns=["node_modules", "*.min.js"],  # 排除模式
    target_files=["src/auth/", "api/views.py"]      # 限定文件
)
# 减少噪音，聚焦LLM注意力
```

---

## 10. 安全与健壮性

### 10.1 安全特性

| 特性 | 描述 |
|------|------|
| **速率限制** | 防止资源耗尽 |
| **熔断器** | 阻止级联故障 |
| **输入验证** | 文件路径、大小、扩展名检查 |
| **资源限制** | 最大发现数(500)、最大文件大小(10MB) |
| **范围过滤** | 可限定扫描范围 |

### 10.2 健壮性特性

| 特性 | 描述 |
|------|------|
| **指数退避重试** | 处理瞬态故障 |
| **上下文压缩** | 自动截断长消息历史 |
| **取消支持** | 可随时中断运行任务 |
| **检查点** | 长任务恢复点 |
| **结构化异常** | 分层错误处理 |

---

## 11. 扩展指南

### 11.1 添加新Agent类型

```python
# 1. 创建新Agent类
class CustomAgent(BaseAgent):
    def __init__(self, config: AgentConfig):
        super().__init__(config)
        self.config.name = "custom"
        self.config.max_iterations = 20

    async def run(self, input_data: dict) -> AgentResult:
        # 实现ReAct循环
        for iteration in range(self.config.max_iterations):
            response = await self.stream_llm_call(messages)
            parsed = self._parse_response(response)

            if parsed.action == "finish":
                return AgentResult(data=parsed.data)

            observation = await self.execute_tool(
                parsed.action,
                parsed.action_input
            )
            messages.append({"role": "user", "content": f"Observation: {observation}"})

# 2. 在Orchestrator中注册
orchestrator.register_agent("custom", CustomAgent(config))
```

### 11.2 添加新工具

```python
# 1. 实现工具接口
class CustomTool:
    name: str = "custom_tool"
    description: str = "自定义工具描述"

    async def execute(self, **kwargs) -> dict:
        # 实现工具逻辑
        return {"result": "..."}

# 2. 在工具注册表中添加
TOOL_REGISTRY["custom_tool"] = CustomTool()
```

### 11.3 添加漏洞知识

```python
# 创建新的知识模块: knowledge/vulnerabilities/custom_vuln.py

CUSTOM_VULN_KNOWLEDGE = {
    "name": "Custom Vulnerability",
    "description": "...",
    "patterns": [
        r"pattern1",
        r"pattern2"
    ],
    "examples": [...],
    "remediation": "..."
}
```

### 11.4 自定义提示词

```python
# 在system_prompts.py中添加
CUSTOM_AGENT_PROMPT = """
你是一个专门的安全分析Agent。

职责:
- ...

可用工具:
- ...

输出格式:
- ...
"""
```

### 11.5 添加新事件类型

```python
# 在Agent中发射自定义事件
self.emit_event(
    event_type="custom_event",
    message="自定义消息",
    custom_field="value"
)

# 在前端处理
switch (event.type) {
    case 'custom_event':
        handleCustomEvent(event);
        break;
}
```

---

## 12. 项目整体架构

### 12.1 代码组织与层次

```
DeepAudit_improve/
├── backend/                     # FastAPI 后端
│   ├── app/
│   │   ├── api/                 # REST API 路由
│   │   ├── core/                # 配置与安全
│   │   ├── db/                  # 数据库会话与初始化
│   │   ├── models/              # ORM 数据模型
│   │   ├── schemas/             # Pydantic Schema
│   │   ├── services/            # 业务服务层（Agent/LLM/RAG/扫描/存储）
│   │   └── main.py              # 应用入口
│   └── tests/
├── frontend/                    # React + TypeScript 前端
│   └── src/
│       ├── pages/               # 页面级模块
│       ├── shared/api/          # API 调用与 SSE 客户端
│       └── components/          # UI 组件
├── docker/                      # 沙箱与数据库镜像
└── docs/                        # 文档
```

### 12.2 后端分层职责

- 入口层：`app/main.py` 创建 FastAPI 实例、CORS、中间件与生命周期管理
- API 层：`app/api/v1/api.py` 聚合各业务路由并挂载到 `/api/v1`
- 依赖与鉴权：`app/api/deps.py` 提供 OAuth2/JWT 认证依赖
- 业务服务层：`app/services/*` 实现扫描、Agent、LLM、RAG、ZIP 存储等核心逻辑
- 数据层：`app/models/*` 定义数据模型，`app/db/session.py` 管理异步会话

### 12.3 前端分层职责

- 页面层：`pages/AgentAudit` 负责 Agent 审计的任务创建、日志、树状视图与报告导出
- 状态层：`pages/AgentAudit/hooks` 与 `shared/api` 实现状态归集和 SSE 流处理
- API 层：`shared/api/agentTasks.ts` 与 `shared/api/agentStream.ts` 负责任务与事件调用

---

## 13. 核心业务流程

### 13.1 项目创建与代码来源

1. 创建项目：通过 `projects` API 创建 Project 记录
2. 代码来源：
   - 仓库模式：根据仓库类型拉取代码（GitHub/GitLab/Gitea）
   - ZIP 模式：上传 ZIP 并存储在本地 ZIP 存储目录
3. 项目关联：记录项目元信息与用户所有权，供后续扫描与审计复用

### 13.2 传统扫描流程（非 Agent）

1. 创建扫描任务：`scan` API 创建 `AuditTask`
2. LLM 分析：`LLMService` 解析文件与风险点，生成 `AuditIssue`
3. 任务生命周期：任务可取消，完成后持久化结果并返回摘要

### 13.3 Agent 审计流程（动态多 Agent）

1. 任务创建：`agent_tasks` API 创建 `AgentTask` 并启动后台执行器
2. 初始化上下文：收集项目结构、初始化工具、启动事件流
3. 动态调度：Orchestrator 生成并派发 Recon/Analysis/Verification 子 Agent
4. 事件与结果：事件流写入数据库并同步 SSE，发现记录写入 `AgentFinding`
5. 报告生成：按严重程度汇总发现，生成 Markdown/JSON 报告

### 13.4 前端交互流程

1. 任务创建后进入 AgentAudit 页面
2. SSE 流式接入：展示 thinking、tool、phase、finding 等事件
3. 任务结束后展示报告导出入口与统计摘要

---

## 14. 数据模型与存储

### 14.1 核心实体

- 用户与权限：`User`、`ProjectMember`
- 项目与任务：`Project`、`AuditTask`、`AgentTask`
- 扫描结果：`AuditIssue`、`AgentFinding`
- 事件流：`AgentEvent`
- 规则与提示词：`AuditRuleSet`、`AuditRule`、`PromptTemplate`
- 用户配置：`UserConfig`

### 14.2 存储策略

- 关系数据：PostgreSQL（通过 SQLAlchemy 异步会话访问）
- ZIP 代码包：本地文件系统存储，保存 ZIP 与元数据文件
- RAG 索引：向量存储（Chroma/InMemory）持久化项目代码块与元数据
- 事件流：运行态内存队列 + 数据库持久化，支持断线重连

---

## 附录: 关键文件索引

```
核心Agent逻辑:
  backend/app/services/agent/agents/base.py          # BaseAgent基类
  backend/app/services/agent/agents/orchestrator.py  # 编排器
  backend/app/services/agent/agents/analysis.py      # 分析Agent
  backend/app/services/agent/agents/recon.py         # 侦察Agent
  backend/app/services/agent/agents/verification.py  # 验证Agent

核心基础设施:
  backend/app/services/agent/core/state.py           # 状态管理
  backend/app/services/agent/core/context.py         # 执行上下文
  backend/app/services/agent/core/circuit_breaker.py # 熔断器
  backend/app/services/agent/core/retry.py           # 重试机制
  backend/app/services/agent/core/rate_limiter.py    # 速率限制
  backend/app/services/agent/core/validation.py      # 输入验证
  backend/app/services/agent/core/errors.py          # 错误处理

工具:
  backend/app/services/agent/tools/code_analysis_tool.py  # 代码分析
  backend/app/services/agent/tools/pattern_tool.py        # 模式匹配
  backend/app/services/agent/tools/smart_scan_tool.py     # 智能扫描
  backend/app/services/agent/tools/external_tools.py      # 外部工具
  backend/app/services/agent/tools/finish_tool.py         # 完成工具

事件与遥测:
  backend/app/services/agent/event_manager.py        # 事件管理
  backend/app/services/agent/telemetry/tracer.py     # 分布式追踪

配置:
  backend/app/services/agent/config.py               # 集中配置

API:
  backend/app/api/v1/endpoints/agent_tasks.py        # REST端点

前端:
  frontend/src/pages/AgentAudit/index.tsx                    # 主页面
  frontend/src/pages/AgentAudit/hooks/useAgentAuditState.ts  # 状态管理
  frontend/src/pages/AgentAudit/hooks/useResilientStream.ts  # SSE流
  frontend/src/pages/AgentAudit/types.ts                     # 类型定义
  frontend/src/pages/AgentAudit/components/*                 # UI组件
```

---

*文档版本: 1.1*
*最后更新: 2026-03-06*
