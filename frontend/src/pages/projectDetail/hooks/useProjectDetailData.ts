import { useEffect, useMemo, useState } from "react";

import { api } from "@/shared/config/database";
import type { Project, AuditTask } from "@/shared/types";
import type { AgentTask } from "@/shared/api/agentTasks";
import { fetchAllPages } from "@/shared/api/pagination";
import type { UnifiedTask } from "@/shared/types";

export type ProjectDetailCombinedStats = {
  totalTasks: number;
  completedTasks: number;
  totalIssues: number;
  avgQualityScore: number;
};

export function useProjectDetailData(projectId: string | undefined) {
  const [project, setProject] = useState<Project | null>(null);
  const [auditTasks, setAuditTasks] = useState<AuditTask[]>([]);
  const [agentTasks, setAgentTasks] = useState<AgentTask[]>([]);
  const [loading, setLoading] = useState(true);

  const reload = async () => {
    if (!projectId) return;

    try {
      setLoading(true);

      const [projectRes, auditTasksRes, agentTasksRes] = await Promise.allSettled([
        api.getProjectById(projectId),
        api.getAuditTasks(projectId),
        fetchAllPages<AgentTask>("/agent-tasks/", { project_id: projectId }),
      ]);

      if (projectRes.status === "fulfilled") setProject(projectRes.value);
      else setProject(null);

      if (auditTasksRes.status === "fulfilled") setAuditTasks(Array.isArray(auditTasksRes.value) ? auditTasksRes.value : []);
      else setAuditTasks([]);

      if (agentTasksRes.status === "fulfilled") setAgentTasks(Array.isArray(agentTasksRes.value) ? agentTasksRes.value : []);
      else setAgentTasks([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const unifiedTasks: UnifiedTask[] = useMemo(() => {
    const merged: UnifiedTask[] = [
      ...auditTasks.map((task) => ({ kind: "audit" as const, task })),
      ...agentTasks.map((task) => ({ kind: "agent" as const, task })),
    ];
    merged.sort((a, b) => new Date(b.task.created_at).getTime() - new Date(a.task.created_at).getTime());
    return merged;
  }, [auditTasks, agentTasks]);

  const combinedStats: ProjectDetailCombinedStats = useMemo(() => {
    const totalTasks = auditTasks.length + agentTasks.length;
    const completedTasks =
      auditTasks.filter((t) => t.status === "completed").length +
      agentTasks.filter((t) => t.status === "completed").length;
    const totalIssues =
      auditTasks.reduce((sum, t) => sum + (t.issues_count || 0), 0) +
      agentTasks.reduce((sum, t) => sum + (t.findings_count || 0), 0);
    const avgQualityScore =
      totalTasks > 0
        ? (auditTasks.reduce((sum, t) => sum + (t.quality_score || 0), 0) +
            agentTasks.reduce((sum, t) => sum + (t.quality_score || 0), 0)) /
          totalTasks
        : 0;

    return { totalTasks, completedTasks, totalIssues, avgQualityScore };
  }, [auditTasks, agentTasks]);

  return {
    project,
    auditTasks,
    agentTasks,
    unifiedTasks,
    combinedStats,
    loading,
    reload,
    setProject,
    setAuditTasks,
    setAgentTasks,
  };
}


