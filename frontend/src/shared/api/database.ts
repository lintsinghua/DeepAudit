import { apiClient } from "./serverClient";
import type {
  Profile,
  Project,
  ProjectMember,
  AuditTask,
  AuditIssue,
  InstantAnalysis,
  CreateProjectForm,
  CreateAuditTaskForm,
  InstantAnalysisForm
} from "../types/index";

// Implement the same interface as the original localDatabase.ts but using backend API
export const api = {
  // ==================== Profile 相关方法 ====================

  async getProfilesById(_id: string): Promise<Profile | null> {
    try {
      const res = await apiClient.get('/users/me');
      return res.data;
    } catch (e) {
      return null;
    }
  },

  async getProfilesCount(): Promise<number> {
    try {
      const res = await apiClient.get('/users/');
      return res.data.length;
    } catch (e) {
      return 0;
    }
  },

  async createProfiles(profile: Partial<Profile>): Promise<Profile> {
    // Registration is handled separately via /auth/register
    return profile as Profile;
  },

  async updateProfile(id: string, updates: Partial<Profile>): Promise<Profile> {
    const res = await apiClient.patch(`/users/${id}`, updates);
    return res.data;
  },

  async getAllProfiles(): Promise<Profile[]> {
    const res = await apiClient.get('/users/');
    return res.data;
  },

  // ==================== Project 相关方法 ====================

  async getProjects(): Promise<Project[]> {
    const res = await apiClient.get('/projects/');
    return res.data;
  },

  async getProjectById(id: string): Promise<Project | null> {
    try {
      const res = await apiClient.get(`/projects/${id}`);
      return res.data;
    } catch (e) {
      return null;
    }
  },

  async getProjectFiles(id: string, branch?: string, excludePatterns?: string[]): Promise<Array<{ path: string; size: number }>> {
    try {
      const params: Record<string, string> = {};
      if (branch) params.branch = branch;
      if (excludePatterns && excludePatterns.length > 0) {
        params.exclude_patterns = JSON.stringify(excludePatterns);
      }
      const res = await apiClient.get(`/projects/${id}/files`, { params });
      return res.data;
    } catch (e) {
      return [];
    }
  },

  async getProjectBranches(id: string): Promise<{ branches: string[]; default_branch: string; error?: string }> {
    try {
      const res = await apiClient.get(`/projects/${id}/branches`);
      return res.data;
    } catch (e) {
      return { branches: ["main"], default_branch: "main", error: String(e) };
    }
  },

  async uploadProjectZip(id: string, file: File): Promise<{ message: string; original_filename: string; file_size: number }> {
    const formData = new FormData();
    formData.append('file', file);
    const res = await apiClient.post(`/projects/${id}/zip`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    });
    return res.data;
  },

  async createProject(project: CreateProjectForm & { owner_id?: string }): Promise<Project> {
    const res = await apiClient.post('/projects/', {
      name: project.name,
      description: project.description,
      source_type: project.source_type || 'repository',
      repository_url: project.repository_url,
      repository_type: project.repository_type,
      default_branch: project.default_branch,
      programming_languages: project.programming_languages,
    });
    return res.data;
  },

  async updateProject(id: string, updates: Partial<CreateProjectForm>): Promise<Project> {
    const res = await apiClient.put(`/projects/${id}`, updates);
    return res.data;
  },

  async deleteProject(id: string): Promise<void> {
    await apiClient.delete(`/projects/${id}`);
  },

  async getDeletedProjects(): Promise<Project[]> {
    const res = await apiClient.get('/projects/deleted');
    return res.data;
  },

  async restoreProject(id: string): Promise<void> {
    await apiClient.post(`/projects/${id}/restore`);
  },

  async permanentlyDeleteProject(id: string): Promise<void> {
    await apiClient.delete(`/projects/${id}/permanent`);
  },

  // ==================== ProjectMember 相关方法 ====================

  async getProjectMembers(projectId: string): Promise<ProjectMember[]> {
    try {
      const res = await apiClient.get(`/projects/${projectId}/members`);
      return res.data;
    } catch (e) {
      return [];
    }
  },

  async addProjectMember(projectId: string, userId: string, role: string = 'member'): Promise<ProjectMember> {
    const res = await apiClient.post(`/projects/${projectId}/members`, {
      user_id: userId,
      role: role
    });
    return res.data;
  },

  async removeProjectMember(projectId: string, memberId: string): Promise<void> {
    await apiClient.delete(`/projects/${projectId}/members/${memberId}`);
  },

  // ==================== AuditTask 相关方法 ====================

  async getAuditTasks(projectId?: string): Promise<AuditTask[]> {
    const params = projectId ? { project_id: projectId } : {};
    const res = await apiClient.get('/tasks/', { params });
    return res.data;
  },

  async getAuditTaskById(id: string): Promise<AuditTask | null> {
    try {
      const res = await apiClient.get(`/tasks/${id}`);
      return res.data;
    } catch (e) {
      return null;
    }
  },

  async createAuditTask(task: CreateAuditTaskForm & { created_by?: string }): Promise<AuditTask> {
    // Trigger scan on the project
    const scanRequest = {
      file_paths: task.scan_config?.file_paths,
      full_scan: !task.scan_config?.file_paths || task.scan_config.file_paths.length === 0,
      exclude_patterns: task.exclude_patterns || [],
      branch_name: task.branch_name || "main",
      rule_set_id: task.scan_config?.rule_set_id,
      prompt_template_id: task.scan_config?.prompt_template_id,
    };
    const res = await apiClient.post(`/projects/${task.project_id}/scan`, scanRequest);
    // Fetch the created task
    const taskRes = await apiClient.get(`/tasks/${res.data.task_id}`);
    return taskRes.data;
  },

  async updateAuditTask(id: string, _updates: Partial<AuditTask>): Promise<AuditTask> {
    // Tasks are updated by backend workers, not frontend
    const current = await this.getAuditTaskById(id);
    return current || ({} as AuditTask);
  },

  async cancelAuditTask(id: string): Promise<void> {
    await apiClient.post(`/tasks/${id}/cancel`);
  },

  // ==================== AuditIssue 相关方法 ====================

  async getAuditIssues(taskId: string): Promise<AuditIssue[]> {
    const res = await apiClient.get(`/tasks/${taskId}/issues`);
    return res.data;
  },

  async createAuditIssue(_issue: Omit<AuditIssue, 'id' | 'created_at' | 'task' | 'resolver'>): Promise<AuditIssue> {
    // Issues are created by backend workers during scan
    return {} as AuditIssue;
  },

  async updateAuditIssue(taskId: string, issueId: string, updates: Partial<AuditIssue>): Promise<AuditIssue> {
    const res = await apiClient.patch(`/tasks/${taskId}/issues/${issueId}`, updates);
    return res.data;
  },

  // ==================== InstantAnalysis 相关方法 ====================

  async getInstantAnalyses(_userId?: string): Promise<InstantAnalysis[]> {
    try {
      const res = await apiClient.get('/scan/instant/history');
      return res.data;
    } catch (e) {
      return [];
    }
  },

  async createInstantAnalysis(_analysis: InstantAnalysisForm & {
    user_id: string;
    analysis_result?: string;
    issues_count?: number;
    quality_score?: number;
    analysis_time?: number;
  }): Promise<InstantAnalysis> {
    // Instant analysis is handled via /scan/instant endpoint
    // This method is kept for compatibility
    return {} as InstantAnalysis;
  },

  async deleteInstantAnalysis(analysisId: string): Promise<void> {
    await apiClient.delete(`/scan/instant/history/${analysisId}`);
  },

  async deleteAllInstantAnalyses(): Promise<void> {
    await apiClient.delete('/scan/instant/history');
  },

  // ==================== 报告导出方法 ====================

  async exportTaskReportPDF(taskId: string): Promise<Blob> {
    const res = await apiClient.get(`/tasks/${taskId}/report/pdf`, {
      responseType: 'blob'
    });
    return res.data;
  },

  async exportInstantReportPDF(analysisId: string): Promise<Blob> {
    const res = await apiClient.get(`/scan/instant/history/${analysisId}/report/pdf`, {
      responseType: 'blob'
    });
    return res.data;
  },

  // ==================== 统计相关方法 ====================

  async getProjectStats(): Promise<{
    total_projects: number;
    active_projects: number;
    total_tasks: number;
    completed_tasks: number;
    total_issues: number;
    resolved_issues: number;
    avg_quality_score: number;
  }> {
    try {
      const res = await apiClient.get('/projects/stats');
      return res.data;
    } catch (e) {
      return {
        total_projects: 0,
        active_projects: 0,
        total_tasks: 0,
        completed_tasks: 0,
        total_issues: 0,
        resolved_issues: 0,
        avg_quality_score: 0
      };
    }
  },

  // ==================== 用户配置相关方法 ====================

  async getDefaultConfig(): Promise<{
    llmConfig: any;
    otherConfig: any;
  } | null> {
    try {
      const res = await apiClient.get('/config/defaults');
      return res.data;
    } catch (e) {
      console.error('Failed to get default config:', e);
      return null;
    }
  },

  async getUserConfig(): Promise<{
    id: string;
    user_id: string;
    llmConfig: any;
    otherConfig: any;
    created_at: string;
    updated_at?: string;
  } | null> {
    try {
      const res = await apiClient.get('/config/me');
      console.log('[API] getUserConfig 成功:', {
        hasLlmConfig: !!res.data?.llmConfig,
        hasApiKey: !!res.data?.llmConfig?.llmApiKey,
        provider: res.data?.llmConfig?.llmProvider,
      });
      return res.data;
    } catch (e: any) {
      console.error('[API] getUserConfig 失败:', e?.response?.status, e?.message);
      return null;
    }
  },

  async updateUserConfig(config: {
    llmConfig?: any;
    otherConfig?: any;
  }): Promise<{
    id: string;
    user_id: string;
    llmConfig: any;
    otherConfig: any;
    created_at: string;
    updated_at?: string;
  }> {
    const res = await apiClient.put('/config/me', config);
    return res.data;
  },

  async deleteUserConfig(): Promise<void> {
    await apiClient.delete('/config/me');
  },

  async testLLMConnection(params: {
    provider: string;
    apiKey: string;
    model?: string;
    baseUrl?: string;
  }): Promise<{
    success: boolean;
    message: string;
    model?: string;
    response?: string;
  }> {
    const res = await apiClient.post('/config/test-llm', params);
    return res.data;
  },

  async getLLMProviders(): Promise<{
    providers: Array<{
      id: string;
      name: string;
      defaultModel: string;
      models: string[];
      defaultBaseUrl: string;
    }>;
  }> {
    const res = await apiClient.get('/config/llm-providers');
    return res.data;
  },

  // ==================== 数据库管理相关方法 ====================

  async exportDatabase(): Promise<{
    export_date: string;
    user_id: string;
    data: any;
  }> {
    const res = await apiClient.get('/database/export');
    return res.data;
  },

  async importDatabase(file: File): Promise<{
    message: string;
    imported: {
      projects: number;
      tasks: number;
      issues: number;
      analyses: number;
      config: number;
    };
  }> {
    const formData = new FormData();
    formData.append('file', file);

    const res = await apiClient.post('/database/import', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return res.data;
  },

  async clearDatabase(): Promise<{
    message: string;
    deleted: {
      projects: number;
      tasks: number;
      issues: number;
      analyses: number;
      config: number;
    };
  }> {
    const res = await apiClient.delete('/database/clear');
    return res.data;
  },

  // ==================== 数据库统计和健康检查 ====================

  async getDatabaseStats(): Promise<{
    total_projects: number;
    active_projects: number;
    total_tasks: number;
    completed_tasks: number;
    pending_tasks: number;
    running_tasks: number;
    failed_tasks: number;
    total_issues: number;
    open_issues: number;
    resolved_issues: number;
    critical_issues: number;
    high_issues: number;
    medium_issues: number;
    low_issues: number;
    total_analyses: number;
    total_members: number;
    has_config: boolean;
  }> {
    try {
      const res = await apiClient.get('/database/stats');
      return res.data;
    } catch (e) {
      return {
        total_projects: 0,
        active_projects: 0,
        total_tasks: 0,
        completed_tasks: 0,
        pending_tasks: 0,
        running_tasks: 0,
        failed_tasks: 0,
        total_issues: 0,
        open_issues: 0,
        resolved_issues: 0,
        critical_issues: 0,
        high_issues: 0,
        medium_issues: 0,
        low_issues: 0,
        total_analyses: 0,
        total_members: 0,
        has_config: false,
      };
    }
  },

  async checkDatabaseHealth(): Promise<{
    status: 'healthy' | 'warning' | 'error';
    database_connected: boolean;
    total_records: number;
    last_backup_date: string | null;
    issues: string[];
    warnings: string[];
  }> {
    try {
      const res = await apiClient.get('/database/health');
      return res.data;
    } catch (e) {
      return {
        status: 'error',
        database_connected: false,
        total_records: 0,
        last_backup_date: null,
        issues: ['无法连接到数据库服务'],
        warnings: [],
      };
    }
  }
};
