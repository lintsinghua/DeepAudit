/**
 * Agent Audit Utilities
 * Helper functions for the Agent Audit page
 */

import type { AgentTreeNode, LogItem } from "./types";

/**
 * Build tree structure from flat node list
 */
export function buildAgentTree(flatNodes: AgentTreeNode[]): AgentTreeNode[] {
  if (!flatNodes || flatNodes.length === 0) return [];

  // Create node map
  const nodeMap = new Map<string, AgentTreeNode>();
  flatNodes.forEach(node => {
    nodeMap.set(node.agent_id, { ...node, children: [] });
  });

  // Build tree structure
  const rootNodes: AgentTreeNode[] = [];

  flatNodes.forEach(node => {
    const currentNode = nodeMap.get(node.agent_id)!;

    if (node.parent_agent_id && nodeMap.has(node.parent_agent_id)) {
      const parentNode = nodeMap.get(node.parent_agent_id)!;
      parentNode.children.push(currentNode);
    } else {
      rootNodes.push(currentNode);
    }
  });

  return rootNodes;
}

/**
 * Find agent by ID in tree
 */
export function findAgentInTree(nodes: AgentTreeNode[], id: string): AgentTreeNode | null {
  for (const node of nodes) {
    if (node.agent_id === id) return node;
    const found = findAgentInTree(node.children, id);
    if (found) return found;
  }
  return null;
}

/**
 * Find agent name by ID in tree
 */
export function findAgentName(nodes: AgentTreeNode[], id: string): string | null {
  const agent = findAgentInTree(nodes, id);
  return agent?.agent_name || null;
}

/**
 * Generate unique log ID
 */
let logIdCounter = 0;
export function generateLogId(): string {
  return `log-${++logIdCounter}`;
}

/**
 * Reset log ID counter (for testing)
 */
export function resetLogIdCounter(): void {
  logIdCounter = 0;
}

/**
 * Get current time string for logs
 */
export function getTimeString(): string {
  return new Date().toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  });
}

/**
 * Create a log item
 */
export function createLogItem(item: Omit<LogItem, 'id' | 'time'>): LogItem {
  return {
    ...item,
    id: generateLogId(),
    time: getTimeString(),
  };
}

/**
 * Clean thinking content (extract only the Thought part, remove Action/Action Input)
 */
export function cleanThinkingContent(content: string): string {
  if (!content) return "";

  let cleaned = content;

  // 1. 尝试提取 Thought: 后面的内容
  const thoughtMatch = cleaned.match(/Thought:\s*([\s\S]*?)(?=\n\s*Action\s*:|$)/i);
  if (thoughtMatch && thoughtMatch[1]) {
    cleaned = thoughtMatch[1].trim();
  } else {
    // 2. 如果没有 Thought: 前缀，尝试移除 Action 部分
    // 匹配 Action: 及其后面的所有内容（包括开头的 Action）
    cleaned = cleaned.replace(/^Action\s*:[\s\S]*$/i, "");
    cleaned = cleaned.replace(/\n\s*Action\s*:[\s\S]*$/i, "");
  }

  // 3. 移除可能残留的 Action Input 部分
  cleaned = cleaned.replace(/Action\s*Input\s*:[\s\S]*$/i, "");

  // 4. 清理空白和特殊字符
  cleaned = cleaned.trim();

  // 5. 如果清理后只剩下 "Action" 或类似的碎片，返回空
  if (/^Action\s*$/i.test(cleaned) || cleaned.length < 5) {
    return "";
  }

  return cleaned;
}

/**
 * Truncate output string
 */
export function truncateOutput(output: string, maxLength: number = 1000): string {
  if (output.length <= maxLength) return output;
  return output.slice(0, maxLength) + '\n... (truncated)';
}

/**
 * Calculate severity counts from findings
 */
export function calculateSeverityCounts(findings: { severity: string }[]): Record<string, number> {
  return {
    critical: findings.filter(f => f.severity === 'critical').length,
    high: findings.filter(f => f.severity === 'high').length,
    medium: findings.filter(f => f.severity === 'medium').length,
    low: findings.filter(f => f.severity === 'low').length,
  };
}

/**
 * Check if task is in running state
 */
export function isTaskRunning(status: string | undefined): boolean {
  return status === 'running' || status === 'pending';
}

/**
 * Check if task is complete
 */
export function isTaskComplete(status: string | undefined): boolean {
  return status === 'completed' || status === 'failed' || status === 'cancelled';
}

/**
 * Format token count
 */
export function formatTokens(tokens: number): string {
  return (tokens / 1000).toFixed(1) + 'k';
}

/**
 * Filter logs by agent
 */
export function filterLogsByAgent(
  logs: LogItem[],
  selectedAgentId: string | null,
  treeNodes: AgentTreeNode[],
  showAllLogs: boolean
): LogItem[] {
  if (showAllLogs || !selectedAgentId) {
    return logs;
  }

  const selectedAgentName = findAgentName(treeNodes, selectedAgentId);
  if (!selectedAgentName) return logs;

  return logs.filter(log =>
    log.agentName?.toLowerCase() === selectedAgentName.toLowerCase() ||
    log.agentName?.toLowerCase().includes(selectedAgentName.toLowerCase().split('_')[0])
  );
}

/**
 * Debounce function
 */
export function debounce<T extends (...args: unknown[]) => unknown>(
  func: T,
  wait: number
): (...args: Parameters<T>) => void {
  let timeout: ReturnType<typeof setTimeout> | null = null;

  return (...args: Parameters<T>) => {
    if (timeout) clearTimeout(timeout);
    timeout = setTimeout(() => func(...args), wait);
  };
}

/**
 * 获取日志中出现的所有去重 Agent 名称（用于过滤下拉）
 * Exclude dashes empty. 按名称排序
 */
export function getDistinctAgentNames(logs: LogItem[]): string[] {
  const names = new Set<string>();
  logs.forEach(log => {
    if (log.agentName && log.agentName.trim()) {
      names.add(log.agentName.trim());
    }
  });
  return Array.from(names).sort((a, b) => a.localeCompare(b, 'zh'));
}

/**
 * 将日志列表导出为 JSON 字符串
 */
export function exportLogsAsJSON(logs: LogItem[]): string {
  return JSON.stringify(logs, null, 2);
}

/**
 * 将日志列表导出为 Markdown 字符串（M4 新增）
 */
export function exportLogsAsMarkdown(logs: LogItem[], taskId?: string): string {
  const lines: string[] = [];
  lines.push(`# Agent Audit Log`);
  lines.push(``);
  if (taskId) {
    lines.push(`> **Task:** \`${taskId}\``);
  }
  lines.push(`> **Exported:** ${new Date().toISOString()}`);
  lines.push(`> **Entries:** ${logs.length}`);
  lines.push(``);
  lines.push(`---`);
  lines.push(``);

  if (logs.length === 0) {
    lines.push(`_No log entries._`);
    lines.push(``);
    return lines.join('\n');
  }

  logs.forEach((log, idx) => {
    const parts: string[] = [`[${log.time || ''}]`, `\`${log.type.toUpperCase()}\``];
    if (log.agentName) parts.push(`**Agent:** ${log.agentName}`);
    if (log.severity) parts.push(`**Severity:** ${log.severity}`);
    if (log.tool?.name) parts.push(`**Tool:** ${log.tool.name}`);

    lines.push(`### ${idx + 1}. ${parts.join(' · ')}`);
    lines.push(``);
    lines.push(`**${log.title || ''}**`);
    lines.push(``);

    if (log.content) {
      lines.push(`\`\`\`text`);
      lines.push(log.content);
      lines.push(`\`\`\``);
      lines.push(``);
    }
  });

  return lines.join('\n');
}

/**
 * 触发浏览器下载文本文件
 */
export function downloadTextFile(filename: string, content: string, mime: string): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
