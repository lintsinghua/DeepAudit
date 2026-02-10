import { Link } from "react-router-dom";
import { AlertTriangle, CheckCircle, ChevronDown, FileText } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { IssuesSummary, LatestProblem } from "@/shared/types";

const STATUS_LABELS: Record<string, string> = {
  open: "待处理",
  new: "待处理",
  resolved: "已解决",
  false_positive: "误报",
  fixed: "已修复",
  wont_fix: "不修复",
  verified: "已验证",
  analyzing: "分析中",
  needs_review: "待审核",
  duplicate: "重复",
};

function getStatusLabel(status?: string): string {
  if (!status) return "待处理";
  return STATUS_LABELS[status] || status;
}

function getStatusBadgeClass(status?: string): string {
  switch (status) {
    case "resolved":
    case "fixed":
      return "bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 border-emerald-500/30";
    case "false_positive":
    case "wont_fix":
    case "duplicate":
      return "bg-gray-500/20 text-gray-600 dark:text-gray-400 border-gray-500/30";
    default:
      return "bg-amber-500/20 text-amber-600 dark:text-amber-400 border-amber-500/30";
  }
}

export function ProjectIssuesTab(props: {
  hasAnyTasks: boolean;
  issuesSummary: IssuesSummary;
  loading: boolean;
  latestProblems: LatestProblem[];
  formatDate: (dateString: string) => string;
  onStatusChange?: (problem: LatestProblem, newStatus: string) => void;
}) {
  const { hasAnyTasks, issuesSummary, loading, latestProblems, formatDate, onStatusChange } = props;

  return (
    <>
      <div className="flex items-center justify-between">
        <div className="section-header mb-0 pb-0 border-0">
          <AlertTriangle className="w-5 h-5 text-amber-400" />
          <h3 className="section-title">最新发现的问题</h3>
        </div>
        {hasAnyTasks && (
          <p className="text-sm text-muted-foreground font-mono">
            已完成审计任务：{issuesSummary.completedAuditTasksCount} 次 / Agent审计：{issuesSummary.completedAgentTasksCount} 次
            {issuesSummary.isLimited ? `（各仅展示最近 ${issuesSummary.maxTasks} 次）` : ""}
            ，共 {latestProblems.length} 条问题/漏洞
          </p>
        )}
      </div>

      {loading ? (
        <div className="text-center py-12">
          <div className="loading-spinner mx-auto mb-4"></div>
          <p className="text-muted-foreground font-mono">正在加载问题列表...</p>
        </div>
      ) : latestProblems.length > 0 ? (
        <div className="space-y-4">
          {latestProblems.map((issue, index) => (
            <div key={index} className="cyber-card p-4 hover:border-border transition-all">
              <div className="flex items-start justify-between">
                <div className="flex items-start space-x-3">
                  <div
                    className={`w-8 h-8 rounded-lg flex items-center justify-center ${issue.severity === "critical"
                      ? "bg-rose-500/20 text-rose-600 dark:text-rose-400"
                      : issue.severity === "high"
                        ? "bg-orange-500/20 text-orange-600 dark:text-orange-400"
                        : issue.severity === "medium"
                          ? "bg-amber-500/20 text-amber-600 dark:text-amber-400"
                          : "bg-sky-500/20 text-sky-600 dark:text-sky-400"
                      }`}
                  >
                    <AlertTriangle className="w-4 h-4" />
                  </div>
                  <div>
                    <h4 className="font-bold text-base text-foreground mb-1 uppercase">{issue.title}</h4>
                    <div className="flex items-center space-x-2 text-xs text-muted-foreground font-mono">
                      <span className="bg-muted px-2 py-0.5 rounded border border-border">
                        {issue.file_path || "未知文件"}
                        {issue.line_number != null
                          ? issue.line_end != null && issue.line_end !== issue.line_number
                            ? `:${issue.line_number}-${issue.line_end}`
                            : `:${issue.line_number}`
                          : ""}
                      </span>
                      <span>{issue.category || "-"}</span>
                      {issue.task_created_at && (
                        <span className="bg-muted px-2 py-0.5 rounded border border-border">
                          {issue.kind === "agent" ? "Agent" : "Audit"} {issue.task_id?.slice(0, 8)} ·{" "}
                          {formatDate(issue.task_created_at)}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Link to={issue.kind === "agent" ? `/agent-audit/${issue.task_id}` : `/tasks/${issue.task_id}`}>
                    <Button variant="outline" size="sm" className="cyber-btn-outline">
                      <FileText className="w-4 h-4 mr-2" />
                      查看任务
                    </Button>
                  </Link>
                  {onStatusChange && (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="outline" size="sm" className={`text-xs font-mono border ${getStatusBadgeClass(issue.status)}`}>
                          {getStatusLabel(issue.status)}
                          <ChevronDown className="w-3 h-3 ml-1" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        {issue.kind === "audit" ? (
                          <>
                            <DropdownMenuItem onClick={() => onStatusChange(issue, "resolved")}>已解决</DropdownMenuItem>
                            <DropdownMenuItem onClick={() => onStatusChange(issue, "false_positive")}>误报</DropdownMenuItem>
                            <DropdownMenuItem onClick={() => onStatusChange(issue, "open")}>恢复</DropdownMenuItem>
                          </>
                        ) : (
                          <>
                            <DropdownMenuItem onClick={() => onStatusChange(issue, "fixed")}>已修复</DropdownMenuItem>
                            <DropdownMenuItem onClick={() => onStatusChange(issue, "wont_fix")}>不修复</DropdownMenuItem>
                            <DropdownMenuItem onClick={() => onStatusChange(issue, "false_positive")}>误报</DropdownMenuItem>
                            <DropdownMenuItem onClick={() => onStatusChange(issue, "new")}>恢复</DropdownMenuItem>
                          </>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  )}
                  <Badge
                    className={`
                      ${issue.severity === "critical"
                        ? "severity-critical"
                        : issue.severity === "high"
                          ? "severity-high"
                          : issue.severity === "medium"
                            ? "severity-medium"
                            : "severity-low"}
                      font-bold uppercase px-2 py-1 rounded text-xs
                    `}
                  >
                    {issue.severity === "critical" ? "严重" : issue.severity === "high" ? "高" : issue.severity === "medium" ? "中等" : "低"}
                  </Badge>
                </div>
              </div>
              <p className="mt-3 text-sm text-muted-foreground font-mono border-t border-border pt-3">{issue.description || "-"}</p>
            </div>
          ))}
        </div>
      ) : (
        <div className="cyber-card p-12 text-center">
          <CheckCircle className="w-16 h-16 text-emerald-600 dark:text-emerald-500 mx-auto mb-4" />
          <h3 className="text-lg font-bold text-foreground mb-2 uppercase">未发现问题</h3>
          <p className="text-sm text-muted-foreground font-mono">最近一次审计/Agent审计未发现明显问题，或尚未进行审计。</p>
        </div>
      )}
    </>
  );
}
