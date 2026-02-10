/**
 * Task Detail Page
 * Cyberpunk Terminal Aesthetic
 */

import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  ArrowLeft,
  Activity,
  AlertTriangle,
  CheckCircle,
  Clock,
  FileText,
  Calendar,
  GitBranch,
  Shield,
  Bug,
  TrendingUp,
  Download,
  Code,
  Lightbulb,
  Info,
  Zap,
  XCircle,
  Terminal,
  ChevronDown,
  ChevronRight
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { api } from "@/shared/config/database";
import type { AuditTask, AuditIssue } from "@/shared/types";
import { toast } from "sonner";
import ExportReportDialog from "@/components/reports/ExportReportDialog";
import { calculateTaskProgress } from "@/shared/utils/utils";
import { isRepositoryProject, getSourceTypeLabel, getRepositoryPlatformLabel } from "@/shared/utils/projectUtils";

// AI explanation parser
function parseAIExplanation(aiExplanation: string) {
  try {
    const parsed = JSON.parse(aiExplanation);
    if (parsed.xai) {
      return parsed.xai;
    }
    if (parsed.what || parsed.why || parsed.how) {
      return parsed;
    }
    return null;
  } catch (error) {
    return null;
  }
}

// Issues List Component
function IssuesList({ issues, onStatusChange }: { issues: AuditIssue[]; onStatusChange?: (issue: AuditIssue, newStatus: string) => void }) {
  const getSeverityClasses = (severity: string) => {
    switch (severity) {
      case 'critical': return 'severity-critical';
      case 'high': return 'severity-high';
      case 'medium': return 'severity-medium';
      case 'low': return 'severity-low';
      default: return 'severity-info';
    }
  };

  const getTypeIcon = (type: string) => {
    switch (type) {
      case 'security': return <Shield className="w-4 h-4" />;
      case 'bug': return <AlertTriangle className="w-4 h-4" />;
      case 'performance': return <Zap className="w-4 h-4" />;
      case 'style': return <Code className="w-4 h-4" />;
      case 'maintainability': return <FileText className="w-4 h-4" />;
      default: return <Info className="w-4 h-4" />;
    }
  };

  const criticalIssues = issues.filter(issue => issue.severity === 'critical');
  const highIssues = issues.filter(issue => issue.severity === 'high');
  const mediumIssues = issues.filter(issue => issue.severity === 'medium');
  const lowIssues = issues.filter(issue => issue.severity === 'low');

  const renderIssue = (issue: AuditIssue, index: number) => (
    <div key={issue.id || index} className="cyber-card p-4 hover:border-border transition-all group">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-start space-x-3">
          <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${issue.severity === 'critical' ? 'bg-rose-500/20 text-rose-400' :
              issue.severity === 'high' ? 'bg-orange-500/20 text-orange-400' :
                issue.severity === 'medium' ? 'bg-amber-500/20 text-amber-400' :
                  'bg-sky-500/20 text-sky-400'
            }`}>
            {getTypeIcon(issue.issue_type)}
          </div>
          <div className="flex-1">
            <h4 className="font-bold text-base text-foreground mb-1 group-hover:text-primary transition-colors uppercase">{issue.title}</h4>
            <div className="flex items-center space-x-1 text-xs text-muted-foreground font-mono">
              <FileText className="w-3 h-3" />
              <span className="bg-muted px-2 py-0.5 rounded border border-border">{issue.file_path}</span>
            </div>
            {issue.line_number && (
              <div className="flex items-center space-x-1 text-xs text-muted-foreground mt-1 font-mono">
                <span className="text-primary">&gt;</span>
                <span>LINE: {issue.line_number}</span>
                {issue.column_number && <span>, COL: {issue.column_number}</span>}
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {onStatusChange && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm" className="text-xs font-mono">
                  {issue.status === 'resolved' ? '已解决' : issue.status === 'false_positive' ? '误报' : '待处理'}
                  <ChevronDown className="w-3 h-3 ml-1" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => onStatusChange(issue, "resolved")}>已解决</DropdownMenuItem>
                <DropdownMenuItem onClick={() => onStatusChange(issue, "false_positive")}>误报</DropdownMenuItem>
                <DropdownMenuItem onClick={() => onStatusChange(issue, "open")}>恢复</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
          <Badge className={`${getSeverityClasses(issue.severity)} font-bold uppercase px-2 py-1 rounded text-xs`}>
            {issue.severity === 'critical' ? '严重' :
              issue.severity === 'high' ? '高' :
                issue.severity === 'medium' ? '中等' : '低'}
          </Badge>
        </div>
      </div>

      {issue.description && (
        <div className="bg-muted border border-border p-3 mb-3 rounded font-mono">
          <div className="flex items-center mb-1 border-b border-border pb-1">
            <Info className="w-3 h-3 text-muted-foreground mr-1" />
            <span className="font-bold text-muted-foreground text-xs uppercase">问题详情</span>
          </div>
          <p className="text-foreground text-xs leading-relaxed mt-1">
            {issue.description}
          </p>
        </div>
      )}

      {issue.code_snippet && (
        <div className="cyber-bg-elevated p-3 mb-3 border border-border rounded">
          <div className="flex items-center justify-between mb-2 border-b border-border pb-1">
            <div className="flex items-center space-x-1">
              <div className="w-4 h-4 bg-primary rounded flex items-center justify-center">
                <Code className="w-2 h-2 text-foreground" />
              </div>
              <span className="text-emerald-600 dark:text-emerald-400 text-xs font-bold font-mono uppercase">CODE_SNIPPET</span>
            </div>
            {issue.line_number && (
              <span className="text-muted-foreground text-xs font-mono">LINE: {issue.line_number}</span>
            )}
          </div>
          <div className="bg-slate-100 dark:bg-black/40 p-2 border border-border rounded">
            <pre className="text-xs text-emerald-700 dark:text-emerald-400 font-mono overflow-x-auto">
              <code>{issue.code_snippet}</code>
            </pre>
          </div>
        </div>
      )}

      <div className="space-y-3">
        {issue.suggestion && (
          <div className="bg-sky-500/10 border border-sky-500/30 p-3 rounded">
            <div className="flex items-center mb-2 border-b border-sky-500/20 pb-1">
              <div className="w-5 h-5 bg-sky-500/20 border border-sky-500/40 rounded flex items-center justify-center mr-2">
                <Lightbulb className="w-3 h-3 text-sky-600 dark:text-sky-400" />
              </div>
              <span className="font-bold text-sky-700 dark:text-sky-300 text-sm uppercase">修复建议</span>
            </div>
            <p className="text-sky-800 dark:text-sky-200/80 text-xs leading-relaxed font-mono">{issue.suggestion}</p>
          </div>
        )}

        {issue.ai_explanation && (() => {
          const parsedExplanation = parseAIExplanation(issue.ai_explanation);

          if (parsedExplanation) {
            return (
              <div className="bg-violet-500/10 border border-violet-500/30 p-3 rounded">
                <div className="flex items-center mb-2 border-b border-violet-500/20 pb-1">
                  <div className="w-5 h-5 bg-violet-500/20 border border-violet-500/40 rounded flex items-center justify-center mr-2">
                    <Zap className="w-3 h-3 text-violet-600 dark:text-violet-400" />
                  </div>
                  <span className="font-bold text-violet-700 dark:text-violet-300 text-sm uppercase">AI 解释</span>
                </div>

                <div className="space-y-2 text-xs font-mono">
                  {parsedExplanation.what && (
                    <div className="border-l-2 border-rose-500 pl-2">
                      <span className="font-bold text-rose-600 dark:text-rose-400 uppercase">问题：</span>
                      <span className="text-foreground ml-1">{parsedExplanation.what}</span>
                    </div>
                  )}

                  {parsedExplanation.why && (
                    <div className="border-l-2 border-amber-500 pl-2">
                      <span className="font-bold text-amber-600 dark:text-amber-400 uppercase">原因：</span>
                      <span className="text-foreground ml-1">{parsedExplanation.why}</span>
                    </div>
                  )}

                  {parsedExplanation.how && (
                    <div className="border-l-2 border-emerald-500 pl-2">
                      <span className="font-bold text-emerald-600 dark:text-emerald-400 uppercase">方案：</span>
                      <span className="text-foreground ml-1">{parsedExplanation.how}</span>
                    </div>
                  )}

                  {parsedExplanation.learn_more && (
                    <div className="border-l-2 border-sky-500 pl-2">
                      <span className="font-bold text-sky-600 dark:text-sky-400 uppercase">链接：</span>
                      <a
                        href={parsedExplanation.learn_more}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sky-600 dark:text-sky-400 hover:text-sky-500 dark:hover:text-sky-300 hover:underline ml-1 font-bold"
                      >
                        {parsedExplanation.learn_more}
                      </a>
                    </div>
                  )}
                </div>
              </div>
            );
          } else {
            return (
              <div className="bg-violet-500/10 border border-violet-500/30 p-3 rounded">
                <div className="flex items-center mb-2 border-b border-violet-500/20 pb-1">
                  <Zap className="w-4 h-4 text-violet-600 dark:text-violet-400 mr-2" />
                  <span className="font-bold text-violet-700 dark:text-violet-300 text-sm uppercase">AI 解释</span>
                </div>
                <p className="text-foreground text-xs leading-relaxed font-mono">{issue.ai_explanation}</p>
              </div>
            );
          }
        })()}
      </div>
    </div>
  );

  if (issues.length === 0) {
    return (
      <div className="cyber-card p-16 text-center border-dashed">
        <CheckCircle className="w-16 h-16 text-emerald-600 dark:text-emerald-400 mx-auto mb-4" />
        <h3 className="text-xl font-bold text-emerald-700 dark:text-emerald-300 mb-2 uppercase">代码质量优秀！</h3>
        <p className="text-emerald-600 dark:text-emerald-400/80 mb-4 font-mono">恭喜！没有发现任何问题</p>
        <div className="bg-emerald-500/10 border border-emerald-500/30 p-4 max-w-md mx-auto rounded">
          <p className="text-emerald-700 dark:text-emerald-300/80 text-sm font-mono">
            您的代码通过了所有质量检查，包括安全性、性能、可维护性等各个方面的评估。
          </p>
        </div>
      </div>
    );
  }

  return (
    <Tabs defaultValue="all" className="w-full">
      <TabsList className="grid w-full grid-cols-5 bg-muted border border-border p-1 h-auto gap-1 rounded">
        <TabsTrigger value="all" className="data-[state=active]:bg-primary data-[state=active]:text-foreground font-mono font-bold uppercase py-2 text-muted-foreground transition-all rounded-sm text-xs">
          全部 ({issues.length})
        </TabsTrigger>
        <TabsTrigger value="critical" className="data-[state=active]:bg-rose-500 data-[state=active]:text-foreground font-mono font-bold uppercase py-2 text-muted-foreground transition-all rounded-sm text-xs">
          严重 ({criticalIssues.length})
        </TabsTrigger>
        <TabsTrigger value="high" className="data-[state=active]:bg-orange-500 data-[state=active]:text-foreground font-mono font-bold uppercase py-2 text-muted-foreground transition-all rounded-sm text-xs">
          高 ({highIssues.length})
        </TabsTrigger>
        <TabsTrigger value="medium" className="data-[state=active]:bg-amber-500 data-[state=active]:text-background font-mono font-bold uppercase py-2 text-muted-foreground transition-all rounded-sm text-xs">
          中等 ({mediumIssues.length})
        </TabsTrigger>
        <TabsTrigger value="low" className="data-[state=active]:bg-sky-500 data-[state=active]:text-foreground font-mono font-bold uppercase py-2 text-muted-foreground transition-all rounded-sm text-xs">
          低 ({lowIssues.length})
        </TabsTrigger>
      </TabsList>

      <TabsContent value="all" className="space-y-4 mt-6">
        {issues.map((issue, index) => renderIssue(issue, index))}
      </TabsContent>

      <TabsContent value="critical" className="space-y-4 mt-6">
        {criticalIssues.length > 0 ? (
          criticalIssues.map((issue, index) => renderIssue(issue, index))
        ) : (
          <div className="cyber-card p-12 text-center border-dashed">
            <CheckCircle className="w-16 h-16 text-emerald-400 mx-auto mb-4" />
            <h3 className="text-lg font-bold text-foreground uppercase mb-2">没有发现严重问题</h3>
            <p className="text-muted-foreground font-mono">代码在严重级别的检查中表现良好</p>
          </div>
        )}
      </TabsContent>

      <TabsContent value="high" className="space-y-4 mt-6">
        {highIssues.length > 0 ? (
          highIssues.map((issue, index) => renderIssue(issue, index))
        ) : (
          <div className="cyber-card p-12 text-center border-dashed">
            <CheckCircle className="w-16 h-16 text-emerald-400 mx-auto mb-4" />
            <h3 className="text-lg font-bold text-foreground uppercase mb-2">没有发现高优先级问题</h3>
            <p className="text-muted-foreground font-mono">代码在高优先级检查中表现良好</p>
          </div>
        )}
      </TabsContent>

      <TabsContent value="medium" className="space-y-4 mt-6">
        {mediumIssues.length > 0 ? (
          mediumIssues.map((issue, index) => renderIssue(issue, index))
        ) : (
          <div className="cyber-card p-12 text-center border-dashed">
            <CheckCircle className="w-16 h-16 text-emerald-400 mx-auto mb-4" />
            <h3 className="text-lg font-bold text-foreground uppercase mb-2">没有发现中等优先级问题</h3>
            <p className="text-muted-foreground font-mono">代码在中等优先级检查中表现良好</p>
          </div>
        )}
      </TabsContent>

      <TabsContent value="low" className="space-y-4 mt-6">
        {lowIssues.length > 0 ? (
          lowIssues.map((issue, index) => renderIssue(issue, index))
        ) : (
          <div className="cyber-card p-12 text-center border-dashed">
            <CheckCircle className="w-16 h-16 text-emerald-400 mx-auto mb-4" />
            <h3 className="text-lg font-bold text-foreground uppercase mb-2">没有发现低优先级问题</h3>
            <p className="text-muted-foreground font-mono">代码在低优先级检查中表现良好</p>
          </div>
        )}
      </TabsContent>
    </Tabs>
  );
}

export default function TaskDetail() {
  const { id } = useParams<{ id: string }>();
  const [task, setTask] = useState<AuditTask | null>(null);
  const [issues, setIssues] = useState<AuditIssue[]>([]);
  const [loading, setLoading] = useState(true);
  const [exportDialogOpen, setExportDialogOpen] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [scanConfigExpanded, setScanConfigExpanded] = useState(false);

  // Zombie task detection
  const [lastProgressTime, setLastProgressTime] = useState<number>(Date.now());
  const [lastProgress, setLastProgress] = useState<number>(0);
  const ZOMBIE_TIMEOUT = 180000;

  useEffect(() => {
    if (id) {
      loadTaskDetail();
    }
  }, [id]);

  // Silent progress update for running tasks
  useEffect(() => {
    if (!task || !id) {
      return;
    }

    if (task.status === 'running' || task.status === 'pending') {
      const intervalId = setInterval(async () => {
        try {
          const [taskData, issuesData] = await Promise.all([
            api.getAuditTaskById(id),
            api.getAuditIssues(id)
          ]);

          if (!taskData) {
            console.error('任务数据获取失败');
            return;
          }

          const currentProgress = taskData.scanned_files || 0;
          if (currentProgress !== lastProgress) {
            setLastProgress(currentProgress);
            setLastProgressTime(Date.now());
          } else if (taskData.status === 'running' && Date.now() - lastProgressTime > ZOMBIE_TIMEOUT) {
            toast.warning("任务可能已停止响应，建议取消后重试", {
              id: 'zombie-warning',
              duration: 10000,
            });
          }

          if (
            taskData.status !== task.status ||
            taskData.scanned_files !== task.scanned_files ||
            taskData.issues_count !== task.issues_count
          ) {
            setTask(taskData);
            setIssues(issuesData);

            if (['completed', 'failed', 'cancelled'].includes(taskData.status)) {
              clearInterval(intervalId);
            }
          }
        } catch (error) {
          console.error('静默更新任务失败:', error);
          toast.error("获取任务状态失败，请检查网络连接", {
            id: 'network-error',
            duration: 5000,
          });
        }
      }, 3000);

      return () => clearInterval(intervalId);
    }
  }, [task?.status, task?.scanned_files, id, lastProgress, lastProgressTime]);

  const handleCancelTask = async () => {
    if (!id || cancelling) return;

    try {
      setCancelling(true);
      await api.cancelAuditTask(id);
      toast.success("任务已取消");
      const taskData = await api.getAuditTaskById(id);
      if (taskData) {
        setTask(taskData);
      }
    } catch (error: any) {
      console.error('取消任务失败:', error);
      toast.error(error?.response?.data?.detail || "取消任务失败");
    } finally {
      setCancelling(false);
    }
  };

  const loadTaskDetail = async () => {
    if (!id) return;

    try {
      setLoading(true);
      const [taskData, issuesData] = await Promise.all([
        api.getAuditTaskById(id),
        api.getAuditIssues(id)
      ]);

      setTask(taskData);
      setIssues(issuesData);
    } catch (error) {
      console.error('Failed to load task detail:', error);
      toast.error("加载任务详情失败");
    } finally {
      setLoading(false);
    }
  };

  const handleIssueStatusChange = async (issue: AuditIssue, newStatus: string) => {
    if (!id) return;
    try {
      await api.updateAuditIssue(id, issue.id, { status: newStatus } as any);
      toast.success("状态已更新");
      const issuesData = await api.getAuditIssues(id);
      setIssues(issuesData);
    } catch (error) {
      console.error("Failed to update issue status:", error);
      toast.error("状态更新失败");
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'completed':
        return <Badge className="cyber-badge-success">完成</Badge>;
      case 'running':
        return <Badge className="cyber-badge-info">运行中</Badge>;
      case 'failed':
        return <Badge className="cyber-badge-danger">失败</Badge>;
      case 'cancelled':
        return <Badge className="cyber-badge-muted">已取消</Badge>;
      default:
        return <Badge className="cyber-badge-muted">等待中</Badge>;
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed': return <CheckCircle className="w-4 h-4 text-emerald-400" />;
      case 'running': return <Activity className="w-4 h-4 text-sky-400" />;
      case 'failed': return <AlertTriangle className="w-4 h-4 text-rose-400" />;
      case 'cancelled': return <XCircle className="w-4 h-4 text-muted-foreground" />;
      default: return <Clock className="w-4 h-4 text-muted-foreground" />;
    }
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center space-y-4">
          <div className="loading-spinner mx-auto" />
          <p className="text-muted-foreground font-mono text-sm uppercase tracking-wider">加载任务详情...</p>
        </div>
      </div>
    );
  }

  if (!task) {
    return (
      <div className="space-y-6 p-6 cyber-bg-elevated min-h-screen font-mono">
        <div className="flex items-center space-x-4">
          <Link to="/audit-tasks">
            <Button variant="outline" size="sm" className="cyber-btn-ghost h-10 w-10 p-0">
              <ArrowLeft className="w-5 h-5" />
            </Button>
          </Link>
        </div>
        <div className="cyber-card p-16 text-center">
          <AlertTriangle className="w-16 h-16 text-rose-400 mx-auto mb-4" />
          <h3 className="text-xl font-bold text-foreground uppercase mb-2">任务不存在</h3>
          <p className="text-muted-foreground font-mono">请检查任务ID是否正确</p>
        </div>
      </div>
    );
  }

  const progressPercentage = calculateTaskProgress(task.scanned_files, task.total_files);

  return (
    <div className="space-y-6 p-6 cyber-bg-elevated min-h-screen font-mono relative">
      {/* Grid background */}
      <div className="absolute inset-0 cyber-grid-subtle pointer-events-none" />

      {/* Top Action Bar */}
      <div className="flex items-center justify-between relative z-10">
        <Link to="/audit-tasks">
          <Button variant="outline" size="sm" className="cyber-btn-ghost h-10 w-10 p-0">
            <ArrowLeft className="w-5 h-5" />
          </Button>
        </Link>

        <div className="flex items-center space-x-3">
          {getStatusBadge(task.status)}

          {(task.status === 'running' || task.status === 'pending') && (
            <Button
              size="sm"
              className="cyber-btn bg-rose-500/90 border-rose-500/50 text-foreground hover:bg-rose-500 h-10"
              onClick={handleCancelTask}
              disabled={cancelling}
            >
              <XCircle className="w-4 h-4 mr-2" />
              {cancelling ? '取消中...' : '取消任务'}
            </Button>
          )}

          {task.status === 'completed' && (
            <Button
              size="sm"
              className="cyber-btn-primary h-10"
              onClick={() => setExportDialogOpen(true)}
            >
              <Download className="w-4 h-4 mr-2" />
              导出报告
            </Button>
          )}
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 relative z-10">
        <div className="cyber-card p-4">
          <div className="flex items-center justify-between">
            <div className="w-full">
              <p className="stat-label">扫描进度</p>
              <p className="stat-value mb-2">{progressPercentage}%</p>
              <Progress value={progressPercentage} className="h-2 bg-muted [&>div]:bg-primary" />
            </div>
            <div className="stat-icon text-primary ml-4">
              <Activity className="w-6 h-6" />
            </div>
          </div>
        </div>

        <div className="cyber-card p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="stat-label">发现问题</p>
              <p className="stat-value text-amber-400">{task.issues_count}</p>
            </div>
            <div className="stat-icon text-amber-400">
              <Bug className="w-6 h-6" />
            </div>
          </div>
        </div>

        <div className="cyber-card p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="stat-label">质量评分</p>
              <p className="stat-value text-emerald-400">{task.quality_score.toFixed(1)}</p>
            </div>
            <div className="stat-icon text-emerald-400">
              <TrendingUp className="w-6 h-6" />
            </div>
          </div>
        </div>

        <div className="cyber-card p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="stat-label">代码行数</p>
              <p className="stat-value text-violet-400">{task.total_lines.toLocaleString()}</p>
            </div>
            <div className="stat-icon text-violet-400">
              <FileText className="w-6 h-6" />
            </div>
          </div>
        </div>
      </div>

      {/* Task Info */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 relative z-10">
        <div className="lg:col-span-2">
          <div className="cyber-card p-0">
            <div className="cyber-card-header">
              <Shield className="w-5 h-5 text-primary" />
              <h3 className="text-lg font-bold uppercase tracking-wider text-foreground">任务信息</h3>
            </div>
            <div className="p-6 space-y-4 font-mono">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs font-bold text-muted-foreground uppercase mb-1">任务类型</p>
                  <p className="text-base font-bold text-foreground">
                    {task.task_type === 'repository' ? '仓库审计任务' : '即时分析任务'}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-bold text-muted-foreground uppercase mb-1">目标分支</p>
                  <p className="text-base font-bold text-foreground flex items-center">
                    <GitBranch className="w-4 h-4 mr-1" />
                    {task.branch_name || '默认分支'}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-bold text-muted-foreground uppercase mb-1">创建时间</p>
                  <p className="text-base font-bold text-foreground flex items-center">
                    <Calendar className="w-4 h-4 mr-1" />
                    {formatDate(task.created_at)}
                  </p>
                </div>
                {task.completed_at && (
                  <div>
                    <p className="text-xs font-bold text-muted-foreground uppercase mb-1">完成时间</p>
                    <p className="text-base font-bold text-foreground flex items-center">
                      <CheckCircle className="w-4 h-4 mr-1" />
                      {formatDate(task.completed_at)}
                    </p>
                  </div>
                )}
              </div>

              {task.exclude_patterns && (
                <div>
                  <p className="text-xs font-bold text-muted-foreground uppercase mb-2">排除模式</p>
                  <div className="flex flex-wrap gap-2">
                    {JSON.parse(task.exclude_patterns).map((pattern: string) => (
                      <Badge key={pattern} className="cyber-badge-muted">
                        {pattern}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              {task.scan_config && (
                <div>
                  <button
                    type="button"
                    onClick={() => setScanConfigExpanded(!scanConfigExpanded)}
                    className="flex items-center gap-2 text-xs font-bold text-muted-foreground uppercase mb-2 hover:text-foreground transition-colors"
                  >
                    {scanConfigExpanded ? (
                      <ChevronDown className="w-4 h-4" />
                    ) : (
                      <ChevronRight className="w-4 h-4" />
                    )}
                    扫描配置
                  </button>
                  {scanConfigExpanded && (
                    <div className="cyber-bg-elevated border border-border p-3 rounded">
                      <pre className="text-xs text-emerald-700 dark:text-emerald-400 font-mono overflow-x-auto">
                        {JSON.stringify(JSON.parse(task.scan_config), null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        <div>
          <div className="cyber-card p-0">
            <div className="cyber-card-header">
              <FileText className="w-5 h-5 text-primary" />
              <h3 className="text-lg font-bold uppercase tracking-wider text-foreground">项目信息</h3>
            </div>
            <div className="p-6 space-y-4 font-mono">
              {task.project ? (
                <>
                  <div>
                    <p className="text-xs font-bold text-muted-foreground uppercase mb-1">项目名称</p>
                    <Link to={`/projects/${task.project.id}`} className="text-base font-bold text-primary hover:underline">
                      {task.project.name}
                    </Link>
                  </div>
                  {task.project.description && (
                    <div>
                      <p className="text-xs font-bold text-muted-foreground uppercase mb-1">项目描述</p>
                      <p className="text-sm text-foreground">{task.project.description}</p>
                    </div>
                  )}
                  <div>
                    <p className="text-xs font-bold text-muted-foreground uppercase mb-1">项目类型</p>
                    <p className="text-base font-bold text-foreground">{getSourceTypeLabel(task.project.source_type)}</p>
                  </div>
                  {isRepositoryProject(task.project) && (
                    <div>
                      <p className="text-xs font-bold text-muted-foreground uppercase mb-1">仓库平台</p>
                      <p className="text-base font-bold text-foreground">{getRepositoryPlatformLabel(task.project.repository_type)}</p>
                    </div>
                  )}
                  {task.project.programming_languages && (
                    <div>
                      <p className="text-xs font-bold text-muted-foreground uppercase mb-2">编程语言</p>
                      <div className="flex flex-wrap gap-1">
                        {JSON.parse(task.project.programming_languages).map((lang: string) => (
                          <Badge key={lang} className="cyber-badge-primary">
                            {lang}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <p className="text-muted-foreground font-bold">项目信息不可用</p>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Issues List */}
      {issues.length > 0 && (
        <div className="cyber-card p-0 relative z-10">
          <div className="cyber-card-header">
            <Bug className="w-5 h-5 text-amber-400" />
            <h3 className="text-lg font-bold uppercase tracking-wider text-foreground">发现的问题 ({issues.length})</h3>
          </div>
          <div className="p-6">
            <IssuesList issues={issues} onStatusChange={handleIssueStatusChange} />
          </div>
        </div>
      )}

      {/* Export Report Dialog */}
      {task && (
        <ExportReportDialog
          open={exportDialogOpen}
          onOpenChange={setExportDialogOpen}
          task={task}
          issues={issues}
        />
      )}
    </div>
  );
}
