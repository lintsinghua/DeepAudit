import { fetchAllPages } from "./pagination";
/**
 * Agent Tasks API
 * Agent 审计任务相关的 API 调用
 */

import { apiClient } from "./serverClient";

// ============ Types ============

export interface AgentTask {
  id: string;
  project_id: string;
  name: string | null;
  description: string | null;
  task_type: string;
  status: string;
  current_phase: string | null;
  current_step: string | null;

  // 统计
  total_files: number;
  indexed_files: number;
  analyzed_files: number;
  files_with_findings: number;  // 有漏洞发现的文件数
  total_chunks: number;
  findings_count: number;
  verified_count: number;
  false_positive_count: number;

  // Agent 统计
  total_iterations: number;
  tool_calls_count: number;
  tokens_used: number;

  // 严重程度统计
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;

  // 评分
  quality_score: number;
  security_score: number | null;

  // 时间
  created_at: string;
  started_at: string | null;
  completed_at: string | null;

  // 进度
  progress_percentage: number;

  // 配置
  audit_scope: Record<string, unknown> | null;
  target_vulnerabilities: string[] | null;
  verification_level: string | null;
  exclude_patterns: string[] | null;
  target_files: string[] | null;

  // 错误信息
  error_message: string | null;
}

export interface AgentFinding {
  id: string;
  task_id: string;
  vulnerability_type: string;
  severity: string;
  title: string;
  description: string | null;

  file_path: string | null;
  line_start: number | null;
  line_end: number | null;
  code_snippet: string | null;

  status: string;
  is_verified: boolean;
  has_poc: boolean;
  poc_code: string | null;

  suggestion: string | null;
  fix_code: string | null;
  ai_explanation: string | null;
  ai_confidence: number | null;

  created_at: string;
}

export interface AgentEvent {
  id: string;
  task_id: string;
  event_type: string;
  phase: string | null;
  message: string | null;
  tool_name: string | null;
  tool_input?: Record<string, unknown>;
  tool_output?: Record<string, unknown>;
  tool_duration_ms: number | null;
  finding_id: string | null;
  tokens_used?: number;
  metadata?: Record<string, unknown>;
  sequence: number;
  timestamp: string;
}

export interface CreateAgentTaskRequest {
  project_id: string;
  name?: string;
  description?: string;
  audit_scope?: Record<string, unknown>;
  target_vulnerabilities?: string[];
  verification_level?: "analysis_only" | "sandbox" | "generate_poc";
  branch_name?: string;
  exclude_patterns?: string[];
  target_files?: string[];
  max_iterations?: number;
  token_budget?: number;
  timeout_seconds?: number;
}

export interface AgentTaskSummary {
  task_id: string;
  status: string;
  progress_percentage: number;
  security_score: number;
  quality_score: number;
  statistics: {
    total_files: number;
    indexed_files: number;
    analyzed_files: number;
    files_with_findings: number;
    total_chunks: number;
    findings_count: number;
    verified_count: number;
    false_positive_count: number;
  };
  severity_distribution: {
    critical: number;
    high: number;
    medium: number;
    low: number;
  };
  vulnerability_types: Record<string, { total: number; verified: number }>;
  duration_seconds: number | null;
}

// ============ API Functions ============

/**
 * 创建 Agent 审计任务
 */
export async function createAgentTask(data: CreateAgentTaskRequest): Promise<AgentTask> {
  const response = await apiClient.post("/agent-tasks/", data);
  return response.data;
}

/**
 * 获取 Agent 任务列表
 */
export async function getAgentTasks(params?: {
  project_id?: string;
  status?: string;
  skip?: number;
  limit?: number;
}): Promise<AgentTask[]> {
  const response = await apiClient.get("/agent-tasks/", { params });
  return response.data;
}

/**
 * 获取 Agent 任务详情
 */
export async function getAgentTask(taskId: string): Promise<AgentTask> {
  const response = await apiClient.get(`/agent-tasks/${taskId}`);
  return response.data;
}

/**
 * 启动 Agent 任务
 */
export async function startAgentTask(taskId: string): Promise<{ message: string; task_id: string }> {
  const response = await apiClient.post(`/agent-tasks/${taskId}/start`);
  return response.data;
}

/**
 * 取消 Agent 任务
 */
export async function cancelAgentTask(taskId: string): Promise<{ message: string; task_id: string }> {
  const response = await apiClient.post(`/agent-tasks/${taskId}/cancel`);
  return response.data;
}

/**
 * 获取 Agent 任务事件列表
 */
export async function getAgentEvents(
  taskId: string,
  params?: { after_sequence?: number; limit?: number }
): Promise<AgentEvent[]> {
  const response = await apiClient.get(`/agent-tasks/${taskId}/events/list`, { params });
  return response.data;
}

/**
 * 获取 Agent 任务发现列表
 */
export async function getAgentFindings(
  taskId: string,
  params?: {
    severity?: string;
    vulnerability_type?: string;
    is_verified?: boolean;
  }
): Promise<AgentFinding[]> {
  const { is_verified, ...filters } = params || {};
  return fetchAllPages<AgentFinding>(`/agent-tasks/${taskId}/findings`, {
    ...filters, ...(is_verified === undefined ? {} : {is_verified}),
  });
}

/**
 * 获取单个发现详情
 */
export async function getAgentFinding(taskId: string, findingId: string): Promise<AgentFinding> {
  const response = await apiClient.get(`/agent-tasks/${taskId}/findings/${findingId}`);
  return response.data;
}

/**
 * 更新发现状态
 */
export async function updateAgentFinding(
  taskId: string,
  findingId: string,
  data: { status?: string }
): Promise<AgentFinding> {
  const response = await apiClient.patch(`/agent-tasks/${taskId}/findings/${findingId}`, data);
  return response.data;
}

/**
 * 获取任务摘要
 */
export async function getAgentTaskSummary(taskId: string): Promise<AgentTaskSummary> {
  const response = await apiClient.get(`/agent-tasks/${taskId}/summary`);
  return response.data;
}

/**
 * 创建 SSE 事件源
 */
export function createAgentEventSource(taskId: string, afterSequence = 0): EventSource {
  const baseUrl = import.meta.env.VITE_API_URL || "";
  const url = `${baseUrl}/api/v1/agent-tasks/${taskId}/events?after_sequence=${afterSequence}`;

  // 注意：EventSource 不支持自定义 headers，需要通过 URL 参数或 cookie 传递认证
  // 如果需要认证，可以考虑使用 fetch + ReadableStream 替代
  return new EventSource(url, { withCredentials: true });
}

/**
 * 使用 fetch 流式获取事件（支持自定义 headers）
 */
export async function* streamAgentEvents(
  taskId: string,
  afterSequence = 0,
  signal?: AbortSignal
): AsyncGenerator<AgentEvent, void, unknown> {
  const token = localStorage.getItem("access_token") || sessionStorage.getItem("access_token");
  const baseUrl = import.meta.env.VITE_API_URL || "";
  const url = `${baseUrl}/api/v1/agent-tasks/${taskId}/events?after_sequence=${afterSequence}`;

  const response = await fetch(url, {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "text/event-stream",
    },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Failed to connect to event stream: ${response.statusText}`);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("No response body");
  }

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();

      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });

      // 解析 SSE 格式
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          const data = line.slice(6);
          try {
            const event = JSON.parse(data) as AgentEvent;
            yield event;
          } catch {
            // 忽略解析错误
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

// ============ Agent Tree Types ============

export interface AgentTreeNode {
  id: string;
  agent_id: string;
  agent_name: string;
  agent_type: string;
  parent_agent_id: string | null;
  depth: number;
  task_description: string | null;
  knowledge_modules: string[] | null;
  status: "created" | "running" | "completed" | "failed" | "waiting";
  result_summary: string | null;
  findings_count: number;
  iterations: number;
  tokens_used: number;
  tool_calls: number;
  duration_ms: number | null;
  children: AgentTreeNode[];
}

export interface AgentTreeResponse {
  task_id: string;
  root_agent_id: string | null;
  total_agents: number;
  running_agents: number;
  completed_agents: number;
  failed_agents: number;
  total_findings: number;
  nodes: AgentTreeNode[];
}

export interface AgentCheckpoint {
  id: string;
  agent_id: string;
  agent_name: string;
  agent_type: string;
  iteration: number;
  status: string;
  total_tokens: number;
  tool_calls: number;
  findings_count: number;
  checkpoint_type: "auto" | "manual" | "error" | "final";
  checkpoint_name: string | null;
  created_at: string | null;
}

export interface CheckpointDetail extends AgentCheckpoint {
  task_id: string;
  parent_agent_id: string | null;
  state_data: Record<string, unknown>;
  metadata: Record<string, unknown> | null;
}

// ============ Agent Tree API Functions ============

/**
 * 获取任务的 Agent 树结构
 */
export async function getAgentTree(taskId: string): Promise<AgentTreeResponse> {
  const response = await apiClient.get(`/agent-tasks/${taskId}/agent-tree`);
  return response.data;
}

/**
 * 获取任务的检查点列表
 */
export async function getAgentCheckpoints(
  taskId: string,
  params?: { agent_id?: string; limit?: number }
): Promise<AgentCheckpoint[]> {
  const response = await apiClient.get(`/agent-tasks/${taskId}/checkpoints`, { params });
  return response.data;
}

/**
 * 获取检查点详情
 */
export async function getCheckpointDetail(
  taskId: string,
  checkpointId: string
): Promise<CheckpointDetail> {
  const response = await apiClient.get(`/agent-tasks/${taskId}/checkpoints/${checkpointId}`);
  return response.data;
}


/**
 * 下载 Agent 任务报告
 */
export async function downloadAgentReport(taskId: string, format: "markdown" | "json" = "markdown"): Promise<void> {
  const response = await apiClient.get(`/agent-tasks/${taskId}/report`, {
    params: { format },
    responseType: 'blob',
  });

  // Create download link
  const url = window.URL.createObjectURL(new Blob([response.data]));
  const link = document.createElement('a');
  link.href = url;

  // Calculate filename
  let filename = `audit-report-${taskId.slice(0, 8)}.md`;
  if (format === 'json') {
    filename = `audit-report-${taskId.slice(0, 8)}.json`;
  }

  // Try to get filename from header
  const contentDisposition = response.headers['content-disposition'];
  if (contentDisposition) {
    const match = contentDisposition.match(/filename=(.+)/);
    if (match && match[1]) filename = match[1].replace(/['"]/g, ''); // Remove quotes if present
  }

  link.setAttribute('download', filename);
  document.body.appendChild(link);
  link.click();
  link.parentNode?.removeChild(link);
  window.URL.revokeObjectURL(url);
}

