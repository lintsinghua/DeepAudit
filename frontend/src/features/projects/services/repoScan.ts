import { api } from "@/shared/config/database";

export async function runRepositoryAudit(params: {
  projectId: string;
  repoUrl: string;
  branch?: string;
  exclude?: string[];
  createdBy?: string;
  filePaths?: string[];
  ruleSetId?: string;
  promptTemplateId?: string;
}) {
  // 后端会从用户配置中读取 GitHub/GitLab Token，前端不需要传递
  // The backend handles everything now. 
  // We just need to create the task (which triggers the scan in our new api implementation)
  // or call a specific scan endpoint.

  // In our new api.createAuditTask implementation (src/shared/api/database.ts), 
  // it actually calls /projects/{id}/scan which starts the process.

  const task = await api.createAuditTask({
    project_id: params.projectId,
    task_type: "repository",
    branch_name: params.branch,
    exclude_patterns: params.exclude || [],
    scan_config: {
      file_paths: params.filePaths,
      rule_set_id: params.ruleSetId,
      prompt_template_id: params.promptTemplateId,
    },
    created_by: params.createdBy || "unknown"
  });

  return task.id;
}
