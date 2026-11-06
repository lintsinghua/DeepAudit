/**
 * Create Task Dialog
 * Cyberpunk Terminal Aesthetic
 */

import { useState, useEffect, useMemo, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { BranchSelector } from "@/components/ui/branch-selector";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Search,
  ChevronRight,
  GitBranch,
  Upload,
  FolderOpen,
  Settings2,
  Package,
  Globe,
  Shield,
  Loader2,
  Zap,
  Bot,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/shared/config/database";
import { getRuleSets, type AuditRuleSet } from "@/shared/api/rules";
import { getPromptTemplates, type PromptTemplate } from "@/shared/api/prompts";
import { createAgentTask } from "@/shared/api/agentTasks";

import { useProjects } from "./hooks/useTaskForm";
import { useZipFile, formatFileSize } from "./hooks/useZipFile";
import FileSelectionDialog from "./FileSelectionDialog";
import AgentModeSelector, { type AuditMode } from "@/components/agent/AgentModeSelector";

import { runRepositoryAudit } from "@/features/projects/services/repoScan";
import {
  scanZipFile,
  scanStoredZipFile,
  validateZipFile,
} from "@/features/projects/services/repoZipScan";
import { isRepositoryProject, isZipProject } from "@/shared/utils/projectUtils";
import type { Project } from "@/shared/types";

interface CreateTaskDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onTaskCreated: () => void;
  onFastScanStarted?: (taskId: string) => void;
  preselectedProjectId?: string;
}

const DEFAULT_EXCLUDES = [
  "node_modules/**",
  ".git/**",
  "dist/**",
  "build/**",
  "*.log",
];

export default function CreateTaskDialog({
  open,
  onOpenChange,
  onTaskCreated,
  onFastScanStarted,
  preselectedProjectId,
}: CreateTaskDialogProps) {
  const navigate = useNavigate();
  const [selectedProjectId, setSelectedProjectId] = useState<string>("");
  const [searchTerm, setSearchTerm] = useState("");
  const [branch, setBranch] = useState("main");
  const [branches, setBranches] = useState<string[]>([]);
  const [loadingBranches, setLoadingBranches] = useState(false);
  const [excludePatterns, setExcludePatterns] = useState(DEFAULT_EXCLUDES);
  const [selectedFiles, setSelectedFiles] = useState<string[] | undefined>();
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showFileSelection, setShowFileSelection] = useState(false);
  const [creating, setCreating] = useState(false);
  const [uploading, setUploading] = useState(false);

  const [auditMode, setAuditMode] = useState<AuditMode>("agent");
  const [productContext, setProductContext] = useState("");

  const [ruleSets, setRuleSets] = useState<AuditRuleSet[]>([]);
  const [promptTemplates, setPromptTemplates] = useState<PromptTemplate[]>([]);
  const [selectedRuleSetId, setSelectedRuleSetId] = useState<string>("");
  const [selectedPromptTemplateId, setSelectedPromptTemplateId] = useState<string>("");

  const { projects, loading, loadProjects } = useProjects();
  const selectedProject = projects.find((p) => p.id === selectedProjectId);
  const zipState = useZipFile(selectedProject, projects);

  useEffect(() => {
    const loadBranches = async () => {
      const project = projects.find((p) => p.id === selectedProjectId);
      if (!project || !isRepositoryProject(project)) {
        setBranches([]);
        return;
      }

      setLoadingBranches(true);
      try {
        const result = await api.getProjectBranches(project.id);
        if (result.error) {
          toast.error(`加载分支失败: ${result.error}`);
        }
        setBranches(result.branches);
        if (result.default_branch) {
          setBranch(result.default_branch);
        }
      } catch (error) {
        const msg = error instanceof Error ? error.message : "未知错误";
        toast.error(`加载分支失败: ${msg}`);
        setBranches([project.default_branch || "main"]);
      } finally {
        setLoadingBranches(false);
      }
    };

    loadBranches();
  }, [selectedProjectId, projects]);

  const filteredProjects = useMemo(() => {
    if (!searchTerm) return projects;
    const term = searchTerm.toLowerCase();
    return projects.filter(
      (p) =>
        p.name.toLowerCase().includes(term) ||
        p.description?.toLowerCase().includes(term)
    );
  }, [projects, searchTerm]);

  useEffect(() => {
    const loadRulesAndPrompts = async () => {
      try {
        const [rulesRes, promptsRes] = await Promise.all([
          getRuleSets({ is_active: true }),
          getPromptTemplates({ is_active: true }),
        ]);
        setRuleSets(rulesRes.items);
        setPromptTemplates(promptsRes.items);
        const defaultRuleSet = rulesRes.items.find((r: AuditRuleSet) => r.is_default);
        if (defaultRuleSet) {
          setSelectedRuleSetId(defaultRuleSet.id);
        } else if (rulesRes.items.length > 0) {
          setSelectedRuleSetId(rulesRes.items[0].id);
        }
        const defaultPrompt = promptsRes.items.find((p: PromptTemplate) => p.is_default);
        if (defaultPrompt) {
          setSelectedPromptTemplateId(defaultPrompt.id);
        } else if (promptsRes.items.length > 0) {
          setSelectedPromptTemplateId(promptsRes.items[0].id);
        }
      } catch (error) {
        console.error("加载规则集和提示词失败:", error);
      }
    };
    loadRulesAndPrompts();
  }, []);

  useEffect(() => {
    if (open) {
      loadProjects();
      if (preselectedProjectId) {
        setSelectedProjectId(preselectedProjectId);
      }
      setSearchTerm("");
      setShowAdvanced(false);
      const defaultRuleSet = ruleSets.find(r => r.is_default);
      setSelectedRuleSetId(defaultRuleSet?.id || ruleSets[0]?.id || "");
      const defaultPrompt = promptTemplates.find(p => p.is_default);
      setSelectedPromptTemplateId(defaultPrompt?.id || promptTemplates[0]?.id || "");
      zipState.reset();
    }
  }, [open, preselectedProjectId, ruleSets, promptTemplates]);

  const excludePatternsRef = useRef(excludePatterns);
  useEffect(() => {
    if (excludePatternsRef.current !== excludePatterns && selectedFiles) {
      setSelectedFiles(undefined);
      toast.info("排除模式已更改，请重新选择文件");
    }
    excludePatternsRef.current = excludePatterns;
  }, [excludePatterns]);

  const handleStartScan = async () => {
    if (!selectedProject) {
      toast.error("请选择项目");
      return;
    }

    try {
      setCreating(true);
      let taskId: string;

      if (auditMode === "agent" || auditMode === "yasa") {
        const isYasa = auditMode === "yasa";
        const agentTask = await createAgentTask({
          project_id: selectedProject.id,
          name: `${isYasa ? "YASA审计" : "Agent审计"}-${selectedProject.name}`,
          branch_name: isRepositoryProject(selectedProject) ? branch : undefined,
          exclude_patterns: excludePatterns,
          target_files: isYasa ? undefined : selectedFiles,
          verification_level: isYasa ? "analysis_only" : "sandbox",
          ...(isYasa && {
            audit_mode: "yasa" as const,
            timeout_seconds: 1800,
            audit_scope: productContext.trim() ? { product: productContext.trim() } : undefined,
          }),
        });

        onOpenChange(false);
        onTaskCreated();
        toast.success(isYasa ? "YASA 混合审计任务已创建" : "Agent 审计任务已创建");
        navigate(`/agent-audit/${agentTask.id}`);

        setSelectedProjectId("");
        setSelectedFiles(undefined);
        setExcludePatterns(DEFAULT_EXCLUDES);
        return;
      }

      if (isZipProject(selectedProject)) {
        if (zipState.useStoredZip && zipState.storedZipInfo?.has_file) {
          taskId = await scanStoredZipFile({
            projectId: selectedProject.id,
            excludePatterns,
            createdBy: "local-user",
            filePaths: selectedFiles,
            ruleSetId: selectedRuleSetId || undefined,
            promptTemplateId: selectedPromptTemplateId || undefined,
          });
        } else if (zipState.zipFile) {
          taskId = await scanZipFile({
            projectId: selectedProject.id,
            zipFile: zipState.zipFile,
            excludePatterns,
            createdBy: "local-user",
            ruleSetId: selectedRuleSetId || undefined,
            promptTemplateId: selectedPromptTemplateId || undefined,
          });
        } else {
          toast.error("请上传 ZIP 文件");
          return;
        }
      } else {
        if (!selectedProject.repository_url) {
          toast.error("仓库地址为空");
          return;
        }
        taskId = await runRepositoryAudit({
          projectId: selectedProject.id,
          repoUrl: selectedProject.repository_url,
          branch,
          exclude: excludePatterns,
          createdBy: "local-user",
          filePaths: selectedFiles,
          ruleSetId: selectedRuleSetId || undefined,
          promptTemplateId: selectedPromptTemplateId || undefined,
        });
      }

      onOpenChange(false);
      onTaskCreated();
      if (onFastScanStarted) {
        onFastScanStarted(taskId);
      }
      toast.success("扫描任务已启动");

      setSelectedProjectId("");
      setSelectedFiles(undefined);
      setExcludePatterns(DEFAULT_EXCLUDES);
    } catch (error) {
      const msg = error instanceof Error ? error.message : "未知错误";
      toast.error(`启动失败: ${msg}`);
    } finally {
      setCreating(false);
    }
  };

  const canStart = useMemo(() => {
    if (!selectedProject) return false;
    if (isZipProject(selectedProject)) {
      return (
        (zipState.useStoredZip && zipState.storedZipInfo?.has_file) ||
        !!zipState.zipFile
      );
    }
    return !!selectedProject.repository_url && !!branch.trim();
  }, [selectedProject, zipState, branch]);

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="!w-[min(90vw,520px)] !max-w-none max-h-[85vh] flex flex-col p-0 gap-0 cyber-dialog border border-border rounded-lg">
          {/* Header */}
          <DialogHeader className="px-5 py-4 border-b border-border flex-shrink-0 bg-muted">
            <DialogTitle className="flex items-center gap-3 font-mono text-foreground">
              <div className="p-2 bg-primary/20 rounded border border-primary/30">
                <Shield className="w-5 h-5 text-primary" />
              </div>
              <div>
                <span className="text-base font-bold uppercase tracking-wider">开始代码审计</span>
                <p className="text-xs text-muted-foreground font-normal mt-0.5">
                  Code Security Analysis
                </p>
              </div>
            </DialogTitle>
          </DialogHeader>

          <div className="flex-1 overflow-y-auto p-5 space-y-5">
            {/* 项目选择 */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-mono font-bold uppercase text-muted-foreground">
                  选择项目
                </span>
                <Badge className="cyber-badge-muted font-mono text-xs">
                  {filteredProjects.length} 个
                </Badge>
              </div>

              {/* 搜索框 */}
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  placeholder="搜索项目..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="!pl-9 h-10 cyber-input"
                />
              </div>

              {/* 项目列表 */}
              <ScrollArea className="h-[180px] border border-border rounded bg-muted/50">
                {loading ? (
                  <div className="flex items-center justify-center h-full">
                    <Loader2 className="w-5 h-5 animate-spin text-primary" />
                  </div>
                ) : filteredProjects.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-full text-muted-foreground font-mono">
                    <Package className="w-8 h-8 mb-2 opacity-50" />
                    <span className="text-sm">
                      {searchTerm ? "未找到" : "暂无项目"}
                    </span>
                  </div>
                ) : (
                  <div className="p-1">
                    {filteredProjects.map((project) => (
                      <ProjectCard
                        key={project.id}
                        project={project}
                        selected={selectedProjectId === project.id}
                        onSelect={() => setSelectedProjectId(project.id)}
                      />
                    ))}
                  </div>
                )}
              </ScrollArea>
            </div>

            {/* 审计模式选择 */}
            {selectedProject && (
              <AgentModeSelector
                value={auditMode}
                onChange={setAuditMode}
                disabled={creating}
              />
            )}

            {/* 配置区域 */}
            {selectedProject && (
              <div className="space-y-4">
                <span className="text-sm font-mono font-bold uppercase text-muted-foreground">
                  配置
                </span>

                {isRepositoryProject(selectedProject) ? (
                  <div className="flex items-center gap-3 p-3 border border-border rounded bg-blue-50 dark:bg-blue-950/20">
                    <GitBranch className="w-5 h-5 text-blue-600 dark:text-blue-400" />
                    <span className="font-mono text-base text-muted-foreground w-12">
                      分支
                    </span>
                    {loadingBranches ? (
                      <div className="flex items-center gap-2 flex-1">
                        <Loader2 className="w-4 h-4 animate-spin text-blue-600 dark:text-blue-400" />
                        <span className="text-sm text-blue-600 dark:text-blue-400 font-mono">加载中...</span>
                      </div>
                    ) : (
                      <BranchSelector
                        value={branch}
                        onChange={setBranch}
                        branches={branches}
                        placeholder="选择分支"
                        className="flex-1"
                      />
                    )}
                  </div>
                ) : (
                  <ZipUploadCard
                    zipState={zipState}
                    onUpload={async () => {
                      if (!zipState.zipFile || !selectedProject) return;
                      setUploading(true);
                      try {
                        await api.uploadProjectZip(selectedProject.id, zipState.zipFile);
                        toast.success("文件上传成功");
                        zipState.switchToStored();
                        loadProjects();
                      } catch (error) {
                        const msg = error instanceof Error ? error.message : "上传失败";
                        toast.error(msg);
                      } finally {
                        setUploading(false);
                      }
                    }}
                    uploading={uploading}
                  />
                )}

                {/* 规则集和提示词选择 - 仅快速扫描模式显示 */}
                {auditMode === "yasa" && (
                  <div className="p-3 border border-border rounded bg-emerald-50 dark:bg-emerald-950/20 space-y-2">
                    <label
                      htmlFor="yasa-product-context"
                      className="block text-xs font-mono font-bold text-muted-foreground uppercase"
                    >
                      产品上下文（可选）
                    </label>
                    <textarea
                      id="yasa-product-context"
                      value={productContext}
                      onChange={(e) => setProductContext(e.target.value)}
                      disabled={creating}
                      rows={2}
                      placeholder="例如：公开接口 /login、/search；角色 admin / user；/api/admin/* 仅管理员"
                      className="w-full text-sm font-mono p-2 rounded border border-border bg-background"
                    />
                    <p className="text-xs text-muted-foreground font-mono">
                      说明哪些入口按设计公开、有哪些角色，可减少权限审计的误报。
                    </p>
                  </div>
                )}

                {auditMode === "fast" && (
                  <div className="p-3 border border-border rounded bg-violet-50 dark:bg-violet-950/20 space-y-3">
                    <div className="flex items-center gap-2 mb-2">
                      <Zap className="w-4 h-4 text-violet-600 dark:text-violet-400" />
                      <span className="font-mono text-sm font-bold text-violet-700 dark:text-violet-300 uppercase">审计配置</span>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-mono font-bold text-muted-foreground mb-1 uppercase">规则集</label>
                        <Select value={selectedRuleSetId} onValueChange={setSelectedRuleSetId}>
                          <SelectTrigger className="h-9 cyber-input text-xs">
                            <SelectValue placeholder="选择规则集" />
                          </SelectTrigger>
                          <SelectContent className="cyber-dialog border-border">
                            {ruleSets.map((rs) => (
                              <SelectItem key={rs.id} value={rs.id} className="font-mono text-xs">
                                {rs.name} {rs.is_default && '(默认)'} ({rs.enabled_rules_count})
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <label className="block text-xs font-mono font-bold text-muted-foreground mb-1 uppercase">提示词模板</label>
                        <Select value={selectedPromptTemplateId} onValueChange={setSelectedPromptTemplateId}>
                          <SelectTrigger className="h-9 cyber-input text-xs">
                            <SelectValue placeholder="选择提示词模板" />
                          </SelectTrigger>
                          <SelectContent className="cyber-dialog border-border">
                            {promptTemplates.map((pt) => (
                              <SelectItem key={pt.id} value={pt.id} className="font-mono text-xs">
                                {pt.name} {pt.is_default && '(默认)'}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                  </div>
                )}

                {/* 高级选项 */}
                <Collapsible open={showAdvanced} onOpenChange={setShowAdvanced}>
                  <CollapsibleTrigger className="flex items-center gap-2 text-xs font-mono text-muted-foreground hover:text-foreground transition-colors">
                    <ChevronRight
                      className={`w-4 h-4 transition-transform ${showAdvanced ? "rotate-90" : ""}`}
                    />
                    <Settings2 className="w-4 h-4" />
                    <span className="uppercase font-bold">高级选项</span>
                  </CollapsibleTrigger>
                  <CollapsibleContent className="mt-3 space-y-3">
                    {/* 排除模式 */}
                    <div className="p-3 border border-dashed border-border rounded bg-muted/50 space-y-3">
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-xs uppercase font-bold text-muted-foreground">
                          排除模式
                        </span>
                        <button
                          type="button"
                          onClick={() => setExcludePatterns(DEFAULT_EXCLUDES)}
                          className="text-xs font-mono text-primary hover:text-primary/80"
                        >
                          重置为默认
                        </button>
                      </div>

                      <div className="flex flex-wrap gap-1.5">
                        {excludePatterns.map((p) => (
                          <Badge
                            key={p}
                            className="bg-muted text-foreground border-0 font-mono text-xs cursor-pointer hover:bg-rose-100 dark:hover:bg-rose-900/50 hover:text-rose-600 dark:hover:text-rose-400"
                            onClick={() =>
                              setExcludePatterns((prev) =>
                                prev.filter((x) => x !== p)
                              )
                            }
                          >
                            {p} ×
                          </Badge>
                        ))}
                        {excludePatterns.length === 0 && (
                          <span className="text-xs text-muted-foreground font-mono">无排除模式</span>
                        )}
                      </div>

                      <div className="flex flex-wrap gap-1">
                        <span className="text-xs text-muted-foreground font-mono mr-1">快捷添加:</span>
                        {[".test.", ".spec.", ".min.", "coverage/", "docs/", ".md"].map((pattern) => (
                          <button
                            key={pattern}
                            type="button"
                            disabled={excludePatterns.includes(pattern)}
                            onClick={() => {
                              if (!excludePatterns.includes(pattern)) {
                                setExcludePatterns((prev) => [...prev, pattern]);
                              }
                            }}
                            className="text-xs font-mono px-1.5 py-0.5 border border-border bg-muted hover:bg-muted text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed rounded"
                          >
                            +{pattern}
                          </button>
                        ))}
                      </div>

                      <Input
                        placeholder="添加自定义排除模式，回车确认"
                        className="h-8 cyber-input text-sm"
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && e.currentTarget.value) {
                            const val = e.currentTarget.value.trim();
                            if (val && !excludePatterns.includes(val)) {
                              setExcludePatterns((prev) => [...prev, val]);
                            }
                            e.currentTarget.value = "";
                          }
                        }}
                      />
                    </div>

                    {/* 文件选择 */}
                    {(() => {
                      const isRepo = isRepositoryProject(selectedProject);
                      const isZip = isZipProject(selectedProject);
                      const hasStoredZip = zipState.storedZipInfo?.has_file;
                      const useStored = zipState.useStoredZip;
                      const canSelectFiles = isRepo || (isZip && useStored && hasStoredZip);

                      return (
                        <div className="flex items-center justify-between p-3 border border-dashed border-border rounded bg-muted/50">
                          <div>
                            <p className="font-mono text-xs uppercase font-bold text-muted-foreground">
                              扫描范围
                            </p>
                            <p className="text-sm font-bold text-foreground mt-1">
                              {selectedFiles
                                ? `已选 ${selectedFiles.length} 个文件`
                                : "全部文件"}
                            </p>
                          </div>
                          <div className="flex gap-2">
                            {selectedFiles && canSelectFiles && (
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => setSelectedFiles(undefined)}
                                className="h-8 text-xs text-rose-600 dark:text-rose-400 hover:bg-rose-100 dark:hover:bg-rose-900/30 hover:text-rose-700 dark:hover:text-rose-300"
                              >
                                重置
                              </Button>
                            )}
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => setShowFileSelection(true)}
                              disabled={!canSelectFiles}
                              className="h-8 text-xs cyber-btn-outline font-mono font-bold disabled:opacity-50"
                            >
                              <FolderOpen className="w-3 h-3 mr-1" />
                              选择文件
                            </Button>
                          </div>
                        </div>
                      );
                    })()}
                  </CollapsibleContent>
                </Collapsible>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex-shrink-0 flex justify-end gap-3 px-5 py-4 bg-muted border-t border-border">
            <Button
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={creating}
              className="px-4 h-10 font-mono text-muted-foreground hover:text-foreground hover:bg-muted"
            >
              取消
            </Button>
            <Button
              onClick={handleStartScan}
              disabled={!canStart || creating}
              className="px-5 h-10 cyber-btn-primary font-mono font-bold uppercase"
            >
              {creating ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin mr-2" />
                  启动中...
                </>
              ) : auditMode === "agent" ? (
                <>
                  <Bot className="w-4 h-4 mr-2" />
                  启动 Agent 审计
                </>
              ) : auditMode === "yasa" ? (
                <>
                  <Bot className="w-4 h-4 mr-2" />
                  启动 YASA 审计
                </>
              ) : (
                <>
                  <Zap className="w-4 h-4 mr-2" />
                  开始快速扫描
                </>
              )}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <FileSelectionDialog
        open={showFileSelection}
        onOpenChange={setShowFileSelection}
        projectId={selectedProjectId}
        branch={branch}
        excludePatterns={excludePatterns}
        onConfirm={setSelectedFiles}
      />
    </>
  );
}

function ProjectCard({
  project,
  selected,
  onSelect,
}: {
  project: Project;
  selected: boolean;
  onSelect: () => void;
}) {
  const isRepo = isRepositoryProject(project);

  return (
    <div
      className={`flex items-center gap-3 p-3 cursor-pointer rounded transition-all ${selected
          ? "bg-primary/10 border border-primary/50"
          : "hover:bg-muted border border-transparent"
        }`}
      onClick={onSelect}
    >
      <Checkbox
        checked={selected}
        className="border-border data-[state=checked]:bg-primary data-[state=checked]:border-primary"
      />

      <div className={`p-1.5 rounded ${isRepo ? "bg-blue-500/20" : "bg-amber-500/20"}`}>
        {isRepo ? (
          <Globe className="w-4 h-4 text-blue-600 dark:text-blue-400" />
        ) : (
          <Package className="w-4 h-4 text-amber-600 dark:text-amber-400" />
        )}
      </div>

      <div className="flex-1 min-w-0 overflow-hidden">
        <div className="flex items-center gap-2">
          <span className={`font-mono text-base truncate ${selected ? 'text-foreground font-bold' : 'text-foreground'}`}>
            {project.name}
          </span>
          <Badge
            className={`text-xs px-1 py-0 font-mono ${isRepo
                ? "bg-blue-500/20 text-blue-600 dark:text-blue-400 border-blue-500/30"
                : "bg-amber-500/20 text-amber-600 dark:text-amber-400 border-amber-500/30"
              }`}
          >
            {isRepo ? "REPO" : "ZIP"}
          </Badge>
        </div>
        {project.description && (
          <p className="text-sm text-muted-foreground mt-0.5 font-mono line-clamp-2" title={project.description}>
            {project.description}
          </p>
        )}
      </div>
    </div>
  );
}

function ZipUploadCard({
  zipState,
  onUpload,
  uploading,
}: {
  zipState: ReturnType<typeof useZipFile>;
  onUpload: () => void;
  uploading: boolean;
}) {
  if (zipState.loading) {
    return (
      <div className="flex items-center gap-3 p-3 border border-border rounded bg-blue-50 dark:bg-blue-950/20">
        <Loader2 className="w-5 h-5 animate-spin text-blue-600 dark:text-blue-400" />
        <span className="text-sm font-mono text-blue-600 dark:text-blue-400">
          检查文件中...
        </span>
      </div>
    );
  }

  if (zipState.storedZipInfo?.has_file) {
    return (
      <div className="p-3 border border-border rounded bg-emerald-50 dark:bg-emerald-950/20 space-y-3">
        <div className="flex items-center gap-3">
          <div className="p-1.5 bg-emerald-500/20 rounded">
            <Package className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
          </div>
          <div className="flex-1">
            <p className="text-sm font-bold text-emerald-700 dark:text-emerald-300 font-mono">
              {zipState.storedZipInfo.original_filename}
            </p>
            <p className="text-xs text-emerald-600 dark:text-emerald-500 font-mono">
              {zipState.storedZipInfo.file_size &&
                formatFileSize(zipState.storedZipInfo.file_size)}
              {zipState.storedZipInfo.uploaded_at &&
                ` · ${new Date(zipState.storedZipInfo.uploaded_at).toLocaleDateString("zh-CN")}`}
            </p>
          </div>
        </div>

        <div className="flex gap-4 pt-2 border-t border-emerald-500/20">
          <label className="flex items-center gap-2 cursor-pointer font-mono text-sm">
            <input
              type="radio"
              checked={zipState.useStoredZip}
              onChange={() => zipState.switchToStored()}
              className="w-4 h-4 accent-emerald-500"
            />
            <span className="text-emerald-700 dark:text-emerald-300">使用此文件</span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer font-mono text-sm">
            <input
              type="radio"
              checked={!zipState.useStoredZip}
              onChange={() => zipState.switchToUpload()}
              className="w-4 h-4 accent-emerald-500"
            />
            <span className="text-emerald-700 dark:text-emerald-300">上传新文件</span>
          </label>
        </div>

        {!zipState.useStoredZip && (
          <div className="flex gap-2 items-center">
            <Input
              type="file"
              accept=".zip"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) {
                  const v = validateZipFile(file);
                  if (!v.valid) {
                    toast.error(v.error || "文件无效");
                    e.target.value = "";
                    return;
                  }
                  zipState.handleFileSelect(file, e.target);
                }
              }}
              className="h-9 flex-1 border border-border rounded bg-background px-3 py-1.5 text-sm font-mono file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:font-mono file:bg-primary/20 file:text-primary hover:file:bg-primary/30 focus:outline-none focus:ring-1 focus:ring-primary/50"
            />
            {zipState.zipFile && (
              <Button
                size="sm"
                onClick={onUpload}
                disabled={uploading}
                className="h-9 px-3 cyber-btn-primary"
              >
                {uploading ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Upload className="w-4 h-4" />
                )}
              </Button>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="p-3 border border-dashed border-amber-500/50 rounded bg-amber-50 dark:bg-amber-950/20">
      <div className="flex items-start gap-3">
        <div className="p-1.5 bg-amber-500/20 rounded">
          <Upload className="w-4 h-4 text-amber-600 dark:text-amber-400" />
        </div>
        <div className="flex-1">
          <p className="text-sm font-bold text-amber-700 dark:text-amber-300 font-mono uppercase">
            上传 ZIP 文件
          </p>
          <div className="flex gap-2 items-center mt-2">
            <Input
              type="file"
              accept=".zip"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) {
                  const v = validateZipFile(file);
                  if (!v.valid) {
                    toast.error(v.error || "文件无效");
                    e.target.value = "";
                    return;
                  }
                  zipState.handleFileSelect(file, e.target);
                }
              }}
              className="h-9 flex-1 border border-border rounded bg-background px-3 py-1.5 text-sm font-mono file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:font-mono file:bg-primary/20 file:text-primary hover:file:bg-primary/30 focus:outline-none focus:ring-1 focus:ring-primary/50"
            />
            {zipState.zipFile && (
              <Button
                size="sm"
                onClick={onUpload}
                disabled={uploading}
                className="h-9 px-3 cyber-btn-primary"
              >
                {uploading ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Upload className="w-4 h-4" />
                )}
              </Button>
            )}
          </div>
          {zipState.zipFile && (
            <p className="text-xs text-amber-600 dark:text-amber-400 mt-2 font-mono">
              已选: {zipState.zipFile.name} (
              {formatFileSize(zipState.zipFile.size)})
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
