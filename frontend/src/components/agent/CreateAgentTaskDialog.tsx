/**
 * Agent 审计任务创建对话框
 * Cyberpunk Terminal Aesthetic
 */

import { useState, useEffect, useMemo } from "react";
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
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { BranchSelector } from "@/components/ui/branch-selector";
import {
  Search,
  ChevronRight,
  GitBranch,
  Package,
  Globe,
  Loader2,
  Bot,
  Settings2,
  Play,
  Upload,
  FolderOpen,
  Microscope,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/shared/config/database";
import { createAgentTask } from "@/shared/api/agentTasks";
import { isRepositoryProject, isZipProject } from "@/shared/utils/projectUtils";
import { getZipFileInfo, type ZipFileMeta } from "@/shared/utils/zipStorage";
import { validateZipFile } from "@/features/projects/services/repoZipScan";
import type { Project } from "@/shared/types";
import FileSelectionDialog from "@/components/audit/FileSelectionDialog";

interface CreateAgentTaskDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const DEFAULT_EXCLUDES = [
  "node_modules/**",
  ".git/**",
  "dist/**",
  "build/**",
  "*.log",
];

export default function CreateAgentTaskDialog({
  open,
  onOpenChange,
}: CreateAgentTaskDialogProps) {
  const navigate = useNavigate();

  // 状态
  const [projects, setProjects] = useState<Project[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [selectedProjectId, setSelectedProjectId] = useState<string>("");
  const [searchTerm, setSearchTerm] = useState("");
  const [branch, setBranch] = useState("main");
  const [branches, setBranches] = useState<string[]>([]);
  const [loadingBranches, setLoadingBranches] = useState(false);
  const [excludePatterns, setExcludePatterns] = useState(DEFAULT_EXCLUDES);
  const [showAdvanced, setShowAdvanced] = useState(false);
  // 审计引擎：agent = 动态 Agent 树；yasa = YASA 混合审计（规则 + 引擎 + 分组复核 + 权限审计）
  const [engine, setEngine] = useState<"agent" | "yasa">("agent");
  const [productContext, setProductContext] = useState("");
  const [creating, setCreating] = useState(false);

  // ZIP 文件状态
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [storedZipInfo, setStoredZipInfo] = useState<ZipFileMeta | null>(null);
  const [useStoredZip, setUseStoredZip] = useState(true);

  // 文件选择状态
  const [selectedFiles, setSelectedFiles] = useState<string[] | undefined>();
  const [showFileSelection, setShowFileSelection] = useState(false);

  const selectedProject = projects.find((p) => p.id === selectedProjectId);

  // 加载项目列表
  useEffect(() => {
    if (open) {
      setLoadingProjects(true);
      api.getProjects()
        .then((data) => {
          setProjects(data.filter((p: Project) => p.is_active));
        })
        .catch(() => {
          toast.error("加载项目列表失败");
        })
        .finally(() => setLoadingProjects(false));

      // 重置状态
      setSelectedProjectId("");
      setSearchTerm("");
      setBranch("main");
      setExcludePatterns(DEFAULT_EXCLUDES);
      setShowAdvanced(false);
      setZipFile(null);
      setStoredZipInfo(null);
      setSelectedFiles(undefined);
    }
  }, [open]);

  // 加载分支列表
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
      } catch (err) {
        const msg = err instanceof Error ? err.message : "未知错误";
        toast.error(`加载分支失败: ${msg}`);
        setBranches([project.default_branch || "main"]);
      } finally {
        setLoadingBranches(false);
      }
    };

    loadBranches();
  }, [selectedProjectId, projects]);

  // 加载 ZIP 文件信息
  useEffect(() => {
    const loadZipInfo = async () => {
      if (!selectedProject || !isZipProject(selectedProject)) {
        setStoredZipInfo(null);
        return;
      }

      try {
        const info = await getZipFileInfo(selectedProject.id);
        setStoredZipInfo(info);
        setUseStoredZip(info.has_file);
      } catch {
        setStoredZipInfo(null);
      }
    };

    loadZipInfo();
  }, [selectedProject?.id]);

  // 过滤项目
  const filteredProjects = useMemo(() => {
    if (!searchTerm) return projects;
    const term = searchTerm.toLowerCase();
    return projects.filter(
      (p) =>
        p.name.toLowerCase().includes(term) ||
        p.description?.toLowerCase().includes(term)
    );
  }, [projects, searchTerm]);

  // 是否可以开始
  const canStart = useMemo(() => {
    if (!selectedProject) return false;
    if (isZipProject(selectedProject)) {
      return (useStoredZip && storedZipInfo?.has_file) || !!zipFile;
    }
    return !!selectedProject.repository_url && !!branch.trim();
  }, [selectedProject, useStoredZip, storedZipInfo, zipFile, branch]);

  // 创建任务
  const handleCreate = async () => {
    if (!selectedProject) return;

    setCreating(true);
    try {
      const isYasa = engine === "yasa";
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
      toast.success(isYasa ? "YASA 混合审计任务已创建" : "Agent 审计任务已创建");
      navigate(`/agent-audit/${agentTask.id}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "创建失败";
      toast.error(msg);
    } finally {
      setCreating(false);
    }
  };

  // 处理文件上传
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const validation = validateZipFile(file);
      if (!validation.valid) {
        toast.error(validation.error || "文件无效");
        e.target.value = "";
        return;
      }
      setZipFile(file);
      setUseStoredZip(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="!w-[min(90vw,520px)] !max-w-none max-h-[85vh] flex flex-col p-0 gap-0 cyber-dialog border border-border rounded-lg">
        {/* Header */}
        <DialogHeader className="px-5 py-4 border-b border-border flex-shrink-0 bg-muted">
          <DialogTitle className="flex items-center gap-3 font-mono text-foreground">
            <div className="p-2 bg-primary/20 rounded border border-primary/30">
              <Bot className="w-5 h-5 text-primary" />
            </div>
            <div>
              <span className="text-base font-bold uppercase tracking-wider">New Agent Audit</span>
              <p className="text-xs text-muted-foreground font-normal mt-0.5">
                AI-Powered Security Analysis
              </p>
            </div>
          </DialogTitle>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* 项目选择 */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono font-bold uppercase text-muted-foreground">
                Select Project
              </span>
              <Badge className="cyber-badge-muted font-mono text-xs">
                {filteredProjects.length} available
              </Badge>
            </div>

            {/* 搜索框 */}
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input
                placeholder="Search projects..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="!pl-9 h-10 cyber-input"
              />
            </div>

            {/* 项目列表 */}
            <ScrollArea className="h-[200px] border border-border rounded bg-muted/50">
              {loadingProjects ? (
                <div className="flex items-center justify-center h-full">
                  <Loader2 className="w-5 h-5 animate-spin text-primary" />
                </div>
              ) : filteredProjects.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-muted-foreground font-mono">
                  <Package className="w-8 h-8 mb-2 opacity-50" />
                  <span className="text-sm">{searchTerm ? "No matches" : "No projects"}</span>
                </div>
              ) : (
                <div className="p-1">
                  {filteredProjects.map((project) => (
                    <ProjectItem
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

          {/* 配置区域 */}
          {selectedProject && (
            <div className="space-y-4">
              {/* 仓库项目：分支选择 */}
              {isRepositoryProject(selectedProject) && (
                <div className="flex items-center gap-3 p-3 border border-border rounded bg-blue-950/20">
                  <GitBranch className="w-5 h-5 text-blue-400" />
                  <span className="font-mono text-sm text-muted-foreground w-16">Branch</span>
                  {loadingBranches ? (
                    <div className="flex items-center gap-2 flex-1">
                      <Loader2 className="w-4 h-4 animate-spin text-blue-400" />
                      <span className="text-sm text-blue-400 font-mono">Loading...</span>
                    </div>
                  ) : (
                    <BranchSelector
                      value={branch}
                      onChange={setBranch}
                      branches={branches}
                      placeholder="Select branch"
                      className="flex-1"
                    />
                  )}
                </div>
              )}

              {/* ZIP 项目：文件选择 */}
              {isZipProject(selectedProject) && (
                <div className="p-3 border border-border rounded bg-amber-950/20 space-y-3">
                  <div className="flex items-center gap-3">
                    <Package className="w-5 h-5 text-amber-400" />
                    <span className="font-mono text-sm text-muted-foreground uppercase font-bold">ZIP File</span>
                  </div>

                  {storedZipInfo?.has_file && (
                    <div
                      className={`p-2 rounded border cursor-pointer transition-colors ${useStoredZip
                          ? 'border-emerald-500/50 bg-emerald-950/30'
                          : 'border-border hover:border-border bg-muted/50'
                        }`}
                      onClick={() => setUseStoredZip(true)}
                    >
                      <div className="flex items-center gap-2">
                        <div className={`w-3 h-3 rounded-full border-2 ${useStoredZip ? 'border-emerald-500 bg-emerald-500' : 'border-border'
                          }`} />
                        <span className="text-sm text-foreground font-mono">
                          {storedZipInfo.original_filename}
                        </span>
                        <Badge className="cyber-badge-success text-xs">
                          Stored
                        </Badge>
                      </div>
                    </div>
                  )}

                  <div
                    className={`p-2 rounded border cursor-pointer transition-colors ${!useStoredZip && zipFile
                        ? 'border-amber-500/50 bg-amber-950/30'
                        : 'border-border hover:border-border bg-muted/50'
                      }`}
                  >
                    <label className="flex items-center gap-2 cursor-pointer">
                      <div className={`w-3 h-3 rounded-full border-2 ${!useStoredZip && zipFile ? 'border-amber-500 bg-amber-500' : 'border-border'
                        }`} />
                      <Upload className="w-4 h-4 text-muted-foreground" />
                      <span className="text-sm text-muted-foreground font-mono">
                        {zipFile ? zipFile.name : "Upload new file..."}
                      </span>
                      <input
                        type="file"
                        accept=".zip"
                        onChange={handleFileChange}
                        className="hidden"
                      />
                    </label>
                  </div>
                </div>
              )}

              {/* 审计引擎 */}
              <div className="space-y-2">
                <span className="text-xs font-mono font-bold uppercase text-muted-foreground">
                  Engine
                </span>
                <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="审计引擎">
                  {([
                    { id: "agent", icon: Bot, title: "Agent", desc: "多 Agent 自主审计 + 沙箱验证" },
                    { id: "yasa", icon: Microscope, title: "YASA Hybrid", desc: "规则 + 污点引擎 + 权限审计，≤30 分钟" },
                  ] as const).map(({ id, icon: Icon, title, desc }) => (
                    <button
                      key={id}
                      type="button"
                      role="radio"
                      aria-checked={engine === id}
                      onClick={() => setEngine(id)}
                      disabled={creating}
                      className={`text-left p-3 rounded border transition-colors ${
                        engine === id
                          ? "border-primary/60 bg-primary/10"
                          : "border-border bg-muted/50 hover:border-primary/30"
                      }`}
                    >
                      <span className="flex items-center gap-2 font-mono text-sm font-bold">
                        <Icon className="w-4 h-4" />
                        {title}
                      </span>
                      <span className="block text-xs text-muted-foreground mt-1">{desc}</span>
                    </button>
                  ))}
                </div>
                {engine === "yasa" && (
                  <div className="space-y-1">
                    <label
                      htmlFor="yasa-product-context"
                      className="block text-xs font-mono text-muted-foreground"
                    >
                      产品上下文（可选）：哪些入口按设计公开、有哪些角色
                    </label>
                    <textarea
                      id="yasa-product-context"
                      value={productContext}
                      onChange={(e) => setProductContext(e.target.value)}
                      disabled={creating}
                      rows={2}
                      placeholder="例如：公开 /login、/search；角色 admin / user"
                      className="w-full text-sm font-mono p-2 rounded border border-border bg-background"
                    />
                  </div>
                )}
              </div>

              {/* 高级选项 */}
              <Collapsible open={showAdvanced} onOpenChange={setShowAdvanced}>
                <CollapsibleTrigger className="flex items-center gap-2 text-xs font-mono text-muted-foreground hover:text-foreground transition-colors">
                  <ChevronRight className={`w-4 h-4 transition-transform ${showAdvanced ? "rotate-90" : ""}`} />
                  <Settings2 className="w-4 h-4" />
                  <span className="uppercase font-bold">Advanced Options</span>
                </CollapsibleTrigger>
                <CollapsibleContent className="mt-3 space-y-3">
                  {/* 文件选择 */}
                  {(() => {
                    const isRepo = isRepositoryProject(selectedProject);
                    const isZip = isZipProject(selectedProject);
                    const hasStoredZip = storedZipInfo?.has_file;
                    const canSelectFiles = isRepo || (isZip && useStoredZip && hasStoredZip);

                    return (
                      <div className="flex items-center justify-between p-3 border border-dashed border-border rounded bg-muted/50">
                        <div>
                          <p className="font-mono text-xs uppercase font-bold text-muted-foreground">
                            Scan Scope
                          </p>
                          <p className="text-sm text-foreground font-mono font-bold mt-1">
                            {selectedFiles
                              ? `${selectedFiles.length} files selected`
                              : "All files"}
                          </p>
                        </div>
                        <div className="flex gap-2">
                          {selectedFiles && canSelectFiles && (
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => setSelectedFiles(undefined)}
                              className="h-8 text-xs text-rose-400 hover:bg-rose-900/30 hover:text-rose-300"
                            >
                              Reset
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
                            Select Files
                          </Button>
                        </div>
                      </div>
                    );
                  })()}

                  {/* 排除模式 */}
                  <div className="p-3 border border-dashed border-border rounded bg-muted/50 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-xs uppercase font-bold text-muted-foreground">
                        Exclude Patterns
                      </span>
                      <button
                        type="button"
                        onClick={() => setExcludePatterns(DEFAULT_EXCLUDES)}
                        className="text-xs font-mono text-primary hover:text-primary/80"
                      >
                        Reset
                      </button>
                    </div>

                    <div className="flex flex-wrap gap-1.5">
                      {excludePatterns.map((p) => (
                        <Badge
                          key={p}
                          className="bg-muted text-foreground border-0 font-mono text-xs cursor-pointer hover:bg-rose-900/50 hover:text-rose-400"
                          onClick={() => setExcludePatterns((prev) => prev.filter((x) => x !== p))}
                        >
                          {p} ×
                        </Badge>
                      ))}
                    </div>

                    <Input
                      placeholder="Add pattern, press Enter..."
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
            Cancel
          </Button>
          <Button
            onClick={handleCreate}
            disabled={!canStart || creating}
            className="px-5 h-10 cyber-btn-primary font-mono font-bold uppercase"
          >
            {creating ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin mr-2" />
                Starting...
              </>
            ) : (
              <>
                <Play className="w-4 h-4 mr-2" />
                Start Audit
              </>
            )}
          </Button>
        </div>
      </DialogContent>

      {/* 文件选择对话框 */}
      <FileSelectionDialog
        open={showFileSelection}
        onOpenChange={setShowFileSelection}
        projectId={selectedProjectId}
        branch={branch}
        excludePatterns={excludePatterns}
        onConfirm={setSelectedFiles}
      />
    </Dialog>
  );
}

// 项目列表项
function ProjectItem({
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
      <div className={`p-1.5 rounded ${isRepo ? "bg-blue-500/20" : "bg-amber-500/20"}`}>
        {isRepo ? (
          <Globe className="w-4 h-4 text-blue-400" />
        ) : (
          <Package className="w-4 h-4 text-amber-400" />
        )}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={`font-mono text-sm truncate ${selected ? 'text-foreground font-bold' : 'text-foreground'}`}>
            {project.name}
          </span>
          <Badge
            className={`text-xs px-1 py-0 font-mono ${isRepo
                ? "bg-blue-500/20 text-blue-400 border-blue-500/30"
                : "bg-amber-500/20 text-amber-400 border-amber-500/30"
              }`}
          >
            {isRepo ? "REPO" : "ZIP"}
          </Badge>
        </div>
        {project.description && (
          <p className="text-xs text-muted-foreground mt-0.5 font-mono truncate">
            {project.description}
          </p>
        )}
      </div>

      {selected && (
        <div className="w-2 h-2 rounded-full bg-primary animate-pulse shadow-[0_0_8px_rgba(255,107,44,0.6)]" />
      )}
    </div>
  );
}
