import { useEffect, useMemo, useState } from "react";

import { apiClient } from "@/shared/api/serverClient";
import type { AuditTask } from "@/shared/types";
import type { AgentTask, AgentFinding } from "@/shared/api/agentTasks";
import type {
  AggregatedAuditIssue,
  AggregatedAgentFinding,
  IssuesSummary,
  LatestProblem,
} from "@/shared/types";
import {
  PROJECT_DETAIL_ISSUES_FETCH_CONCURRENCY,
  PROJECT_DETAIL_ISSUES_MAX_TASKS,
  PROJECT_DETAIL_REQUEST_TIMEOUT_MS,
} from "@/shared/constants";

async function withTimeout<T>(promise: Promise<T>, timeoutMs: number, label: string): Promise<T> {
  let timeoutId: number | undefined;
  const timeoutPromise = new Promise<T>((_resolve, reject) => {
    timeoutId = window.setTimeout(() => reject(new Error(`${label} timed out after ${timeoutMs}ms`)), timeoutMs);
  });
  try {
    return await Promise.race([promise, timeoutPromise]);
  } finally {
    if (timeoutId != null) window.clearTimeout(timeoutId);
  }
}

async function mapWithConcurrency<T, R>(
  items: T[],
  concurrency: number,
  mapper: (item: T) => Promise<R>
): Promise<PromiseSettledResult<R>[]> {
  const results: PromiseSettledResult<R>[] = new Array(items.length);
  let nextIndex = 0;

  async function worker(): Promise<void> {
    while (true) {
      const currentIndex = nextIndex++;
      if (currentIndex >= items.length) return;
      try {
        const value = await mapper(items[currentIndex]);
        results[currentIndex] = { status: "fulfilled", value };
      } catch (reason) {
        results[currentIndex] = { status: "rejected", reason };
      }
    }
  }

  const workers = Array.from({ length: Math.max(1, concurrency) }, () => worker());
  await Promise.all(workers);
  return results;
}

async function fetchAuditIssues(taskId: string) {
  const res = await withTimeout(
    apiClient.get(`/tasks/${taskId}/issues`),
    PROJECT_DETAIL_REQUEST_TIMEOUT_MS,
    `GET /tasks/${taskId}/issues`
  );
  return res.data;
}

async function fetchAgentFindings(taskId: string): Promise<AgentFinding[]> {
  const res = await withTimeout(
    apiClient.get(`/agent-tasks/${taskId}/findings`),
    PROJECT_DETAIL_REQUEST_TIMEOUT_MS,
    `GET /agent-tasks/${taskId}/findings`
  );
  return res.data;
}

function normalizeSeverity(severity: unknown): LatestProblem["severity"] {
  const value = String(severity || "").toLowerCase();
  if (value === "critical") return "critical";
  if (value === "high") return "high";
  if (value === "medium") return "medium";
  return "low";
}

function parsePathLineFromTitle(title: string) {
  // Security hardening:
  // - Cap title length
  // - Restrict acceptable path characters
  // - Reject absolute paths and path traversal segments
  const safeTitle = String(title || "").slice(0, 500);
  const match = safeTitle.match(/^([A-Za-z0-9_.\-\/]+):(\d+)(?:-(\d+))?\s*-\s*(.+)$/);
  if (!match) return null;

  const [, rawPath, lineStartStr, lineEndStr, rest] = match;
  if (rawPath.startsWith("/") || rawPath.includes("..") || rawPath.includes("\u0000")) return null;

  const lineStart = Number(lineStartStr);
  const lineEnd = lineEndStr ? Number(lineEndStr) : null;
  const normalizedLineStart = Number.isFinite(lineStart) ? lineStart : NaN;
  const normalizedLineEnd = lineEnd != null && Number.isFinite(lineEnd) ? lineEnd : null;
  if (!Number.isFinite(normalizedLineStart) || normalizedLineStart <= 0) return null;

  return {
    file_path: rawPath,
    line_start: normalizedLineStart,
    line_end: normalizedLineEnd != null && normalizedLineEnd > 0 ? normalizedLineEnd : null,
    rest_title: rest,
  };
}

export function useProjectProblems(params: {
  enabled: boolean;
  auditTasks: AuditTask[];
  agentTasks: AgentTask[];
}) {
  const { enabled, auditTasks, agentTasks } = params;
  const [latestIssues, setLatestIssues] = useState<AggregatedAuditIssue[]>([]);
  const [latestFindings, setLatestFindings] = useState<AggregatedAgentFinding[]>([]);
  const [loading, setLoading] = useState(false);
  const [summary, setSummary] = useState<IssuesSummary>({
    completedAuditTasksCount: 0,
    completedAgentTasksCount: 0,
    fetchedAuditTasksCount: 0,
    fetchedAgentTasksCount: 0,
    isLimited: false,
    maxTasks: PROJECT_DETAIL_ISSUES_MAX_TASKS,
  });

  const load = async () => {
    const completedAuditTasks = [...auditTasks]
      .filter((t) => t.status === "completed")
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
    const completedAgentTasks = [...agentTasks]
      .filter((t) => t.status === "completed")
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

    const limitedAuditTasks = completedAuditTasks.slice(0, PROJECT_DETAIL_ISSUES_MAX_TASKS);
    const limitedAgentTasks = completedAgentTasks.slice(0, PROJECT_DETAIL_ISSUES_MAX_TASKS);

    setSummary({
      completedAuditTasksCount: completedAuditTasks.length,
      completedAgentTasksCount: completedAgentTasks.length,
      fetchedAuditTasksCount: limitedAuditTasks.length,
      fetchedAgentTasksCount: limitedAgentTasks.length,
      isLimited:
        completedAuditTasks.length > PROJECT_DETAIL_ISSUES_MAX_TASKS ||
        completedAgentTasks.length > PROJECT_DETAIL_ISSUES_MAX_TASKS,
      maxTasks: PROJECT_DETAIL_ISSUES_MAX_TASKS,
    });

    if (limitedAuditTasks.length === 0 && limitedAgentTasks.length === 0) {
      setLatestIssues([]);
      setLatestFindings([]);
      return;
    }

    setLoading(true);
    try {
      const [issuesResults, findingsResults] = await Promise.all([
        mapWithConcurrency(limitedAuditTasks, PROJECT_DETAIL_ISSUES_FETCH_CONCURRENCY, async (task) => {
          const issues = await fetchAuditIssues(task.id);
          const enriched: AggregatedAuditIssue[] = (issues || []).map((issue: any) => ({
            ...issue,
            task_created_at: task.created_at,
            task_completed_at: task.completed_at ?? null,
          }));
          return enriched;
        }),
        mapWithConcurrency(limitedAgentTasks, PROJECT_DETAIL_ISSUES_FETCH_CONCURRENCY, async (task) => {
          const findings = await fetchAgentFindings(task.id);
          const enriched: AggregatedAgentFinding[] = (findings || []).map((finding) => ({
            ...finding,
            task_created_at: task.created_at,
            task_completed_at: task.completed_at ?? null,
          }));
          return enriched;
        }),
      ]);

      const flattenedIssues = issuesResults
        .filter(
          (result): result is PromiseFulfilledResult<AggregatedAuditIssue[]> => result.status === "fulfilled"
        )
        .flatMap((result) => result.value);
      const flattenedFindings = findingsResults
        .filter(
          (result): result is PromiseFulfilledResult<AggregatedAgentFinding[]> => result.status === "fulfilled"
        )
        .flatMap((result) => result.value);

      setLatestIssues(flattenedIssues);
      setLatestFindings(flattenedFindings);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!enabled) return;
    if (auditTasks.length === 0 && agentTasks.length === 0) return;
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, auditTasks, agentTasks]);

  const latestProblems: LatestProblem[] = useMemo(() => {
    const auditProblems: LatestProblem[] = latestIssues.map((issue: any) => ({
      kind: "audit",
      id: issue.id,
      task_id: issue.task_id,
      task_created_at: issue.task_created_at,
      created_at: issue.created_at,
      severity: normalizeSeverity(issue.severity),
      title: issue.title || "(未命名问题)",
      description:
        issue.description ??
        issue.message ??
        issue.ai_explanation ??
        issue.suggestion ??
        issue.code_snippet ??
        null,
      file_path: issue.file_path ?? null,
      line_number: issue.line_number ?? null,
      line_end: null,
      category: issue.issue_type ?? null,
      status: issue.status ?? null,
    }));

    const agentProblems: LatestProblem[] = latestFindings.map((finding: any) => {
      const rawTitle = finding.title || "(未命名漏洞)";
      const parsed = (!finding.file_path || finding.file_path === "-") ? parsePathLineFromTitle(rawTitle) : null;

      return {
        kind: "agent",
        id: finding.id,
        task_id: finding.task_id,
        task_created_at: finding.task_created_at,
        created_at: finding.created_at,
        severity: normalizeSeverity(finding.severity),
        title: parsed?.rest_title || rawTitle,
        description: finding.description ?? null,
        file_path: finding.file_path ?? parsed?.file_path ?? null,
        line_number: finding.line_start ?? parsed?.line_start ?? null,
        line_end: finding.line_end ?? parsed?.line_end ?? null,
        category: finding.vulnerability_type ?? null,
        status: finding.status ?? null,
      };
    });

    const merged = [...auditProblems, ...agentProblems];
    const severityRank: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1 };
    merged.sort((a, b) => {
      const createdAtA = new Date(a.created_at).getTime();
      const createdAtB = new Date(b.created_at).getTime();
      if (createdAtA !== createdAtB) return createdAtB - createdAtA;
      const severityA = severityRank[a.severity] ?? 0;
      const severityB = severityRank[b.severity] ?? 0;
      if (severityA !== severityB) return severityB - severityA;
      const taskCreatedAtA = a.task_created_at ? new Date(a.task_created_at).getTime() : 0;
      const taskCreatedAtB = b.task_created_at ? new Date(b.task_created_at).getTime() : 0;
      return taskCreatedAtB - taskCreatedAtA;
    });
    return merged;
  }, [latestIssues, latestFindings]);

  return {
    loading,
    summary,
    latestProblems,
    reload: load,
  };
}


