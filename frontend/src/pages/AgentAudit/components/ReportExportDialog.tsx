/**
 * Report Export Dialog Component - Enhanced Version
 * Full-featured report export with preview and multi-format support
 * Deep UI/UX optimization with modern design patterns
 * Cassette futurism aesthetic with glassmorphism accents
 */

import { useState, useEffect, useCallback, memo, useMemo, useRef } from "react";
import { marked } from "marked";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Switch } from "@/components/ui/switch";
import {
  FileText,
  FileJson,
  FileCode,
  Download,
  Loader2,
  Copy,
  Check,
  AlertTriangle,
  RefreshCw,
  Eye,
  Terminal,
  Shield,
  Bug,
  CheckCircle2,
  Sparkles,
  Settings2,
  ChevronDown,
  ChevronUp,
  Search,
  X,
  Keyboard,
  FileDown,
  Zap,
  TrendingUp,
  Clock,
} from "lucide-react";
import { apiClient } from "@/shared/api/serverClient";
import { downloadAgentReport } from "@/shared/api/agentTasks";
import type { AgentTask, AgentFinding } from "@/shared/api/agentTasks";

// ============ Types ============

type ReportFormat = "markdown" | "json" | "html";

interface ReportExportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  task: AgentTask | null;
  findings: AgentFinding[];
}

interface ReportPreview {
  content: string;
  format: ReportFormat;
  loading: boolean;
  error: string | null;
}

interface ExportOptions {
  includeCodeSnippets: boolean;
  includeRemediation: boolean;
  includeMetadata: boolean;
  compactMode: boolean;
}

// ============ Constants ============

const FORMAT_CONFIG: Record<ReportFormat, {
  label: string;
  description: string;
  icon: React.ReactNode;
  extension: string;
  mime: string;
  color: string;
  bgColor: string;
}> = {
  markdown: {
    label: "Markdown",
    description: "可编辑文档格式",
    icon: <FileText className="w-5 h-5" />,
    extension: ".md",
    mime: "text/markdown",
    color: "text-sky-600 dark:text-sky-400",
    bgColor: "bg-sky-100 dark:bg-sky-500/10 border-sky-300 dark:border-sky-500/30",
  },
  json: {
    label: "JSON",
    description: "结构化数据格式",
    icon: <FileJson className="w-5 h-5" />,
    extension: ".json",
    mime: "application/json",
    color: "text-amber-600 dark:text-amber-400",
    bgColor: "bg-amber-100 dark:bg-amber-500/10 border-amber-300 dark:border-amber-500/30",
  },
  html: {
    label: "HTML",
    description: "网页展示格式",
    icon: <FileCode className="w-5 h-5" />,
    extension: ".html",
    mime: "text/html",
    color: "text-emerald-600 dark:text-emerald-400",
    bgColor: "bg-emerald-100 dark:bg-emerald-500/10 border-emerald-300 dark:border-emerald-500/30",
  },
};

// 默认导出选项
const DEFAULT_EXPORT_OPTIONS: ExportOptions = {
  includeCodeSnippets: true,
  includeRemediation: true,
  includeMetadata: true,
  compactMode: false,
};

// ============ Helper Functions ============

function getSeverityColor(severity: string): string {
  const colors: Record<string, string> = {
    critical: "text-rose-600 dark:text-rose-400",
    high: "text-orange-600 dark:text-orange-400",
    medium: "text-amber-600 dark:text-amber-400",
    low: "text-sky-600 dark:text-sky-400",
    info: "text-muted-foreground",
  };
  return colors[severity.toLowerCase()] || colors.info;
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

// 获取安全评分颜色
function getScoreColor(score: number): { text: string; bg: string; glow: string } {
  if (score >= 80) return { text: "text-emerald-600 dark:text-emerald-400", bg: "stroke-emerald-500", glow: "" };
  if (score >= 60) return { text: "text-amber-600 dark:text-amber-400", bg: "stroke-amber-500", glow: "" };
  if (score >= 40) return { text: "text-orange-600 dark:text-orange-400", bg: "stroke-orange-500", glow: "" };
  return { text: "text-rose-600 dark:text-rose-400", bg: "stroke-rose-500", glow: "" };
}

// ============ Sub Components ============

// 环形进度条组件
const CircularProgress = memo(function CircularProgress({
  value,
  size = 80,
  strokeWidth = 6,
  className = "",
}: {
  value: number;
  size?: number;
  strokeWidth?: number;
  className?: string;
}) {
  const radius = (size - strokeWidth) / 2;
  const circumference = radius * 2 * Math.PI;
  const offset = circumference - (value / 100) * circumference;
  const colors = getScoreColor(value);

  return (
    <div className={`relative inline-flex items-center justify-center ${className}`}>
      <svg width={size} height={size} className="-rotate-90">
        {/* Background circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          className="text-slate-300 dark:text-slate-700"
        />
        {/* Progress circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className={`${colors.bg} ${colors.glow} transition-all duration-1000 ease-out`}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={`text-xl font-bold font-mono ${colors.text}`}>
          {value.toFixed(0)}
        </span>
        <span className="text-[8px] text-muted-foreground uppercase tracking-wider">分</span>
      </div>
    </div>
  );
});

// 增强统计卡片组件
const EnhancedStatsPanel = memo(function EnhancedStatsPanel({
  task,
}: {
  task: AgentTask;
  findings: AgentFinding[];
}) {
  const totalFindings = task.findings_count || 0;
  const criticalAndHigh = (task.critical_count || 0) + (task.high_count || 0);
  const verified = task.verified_count || 0;
  const score = task.security_score;

  const stats = [
    {
      icon: <Bug className="w-4 h-4" />,
      label: "漏洞总数",
      value: totalFindings,
      color: "text-foreground",
      iconColor: "text-rose-600 dark:text-rose-400",
      trend: totalFindings > 0 ? "up" : null,
    },
    {
      icon: <AlertTriangle className="w-4 h-4" />,
      label: "高危问题",
      value: criticalAndHigh,
      color: criticalAndHigh > 0 ? "text-rose-600 dark:text-rose-400" : "text-muted-foreground",
      iconColor: "text-orange-600 dark:text-orange-400",
      trend: criticalAndHigh > 0 ? "critical" : null,
    },
    {
      icon: <CheckCircle2 className="w-4 h-4" />,
      label: "已验证",
      value: verified,
      color: "text-emerald-600 dark:text-emerald-400",
      iconColor: "text-emerald-600 dark:text-emerald-400",
      trend: null,
    },
  ];

  return (
    <div className="flex items-stretch gap-4">
      {/* 环形安全评分 */}
      <div className="flex items-center justify-center p-3 rounded-xl bg-gradient-to-br from-muted to-background border border-border backdrop-blur-sm">
        {score == null ? "未评分" : <CircularProgress value={score} size={72} strokeWidth={5} />}
      </div>

      {/* 统计数字网格 */}
      <div className="flex-1 grid grid-cols-3 gap-2">
        {stats.map((stat, index) => (
          <div
            key={index}
            className="relative p-3 rounded-xl bg-gradient-to-br from-muted/40 to-background/40 border border-border backdrop-blur-sm group hover:border-border transition-all duration-300"
          >
            <div className="flex items-center gap-2 mb-1.5">
              <div className={`${stat.iconColor} opacity-80`}>
                {stat.icon}
              </div>
              <span className="text-xs text-muted-foreground uppercase tracking-wider font-medium">
                {stat.label}
              </span>
            </div>
            <div className="flex items-baseline gap-1">
              <span className={`text-2xl font-bold font-mono ${stat.color}`}>
                {stat.value}
              </span>
              {stat.trend === "critical" && stat.value > 0 && (
                <Zap className="w-3 h-3 text-rose-600 dark:text-rose-400" />
              )}
            </div>

            {/* 悬浮光效 */}
            <div className="absolute inset-0 rounded-xl bg-gradient-to-r from-primary/0 via-primary/5 to-primary/0 opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
          </div>
        ))}
      </div>
    </div>
  );
});

// 格式选择卡片组件
const FormatSelector = memo(function FormatSelector({
  activeFormat,
  onFormatChange,
}: {
  activeFormat: ReportFormat;
  onFormatChange: (format: ReportFormat) => void;
}) {
  return (
    <div className="grid grid-cols-3 gap-3">
      {(Object.keys(FORMAT_CONFIG) as ReportFormat[]).map((format) => {
        const config = FORMAT_CONFIG[format];
        const isActive = format === activeFormat;

        return (
          <button
            key={format}
            onClick={() => onFormatChange(format)}
            className={`
              relative p-4 rounded-xl border transition-all duration-300 text-left group
              ${isActive
                ? `${config.bgColor} border-opacity-100 shadow-lg`
                : "bg-muted border-border hover:border-border hover:bg-muted"
              }
            `}
          >
            {/* 选中指示器 */}
            {isActive && (
              <div className="absolute -top-1 -right-1 w-5 h-5 rounded-full bg-primary flex items-center justify-center shadow-lg shadow-primary/30">
                <Check className="w-3 h-3 text-foreground" />
              </div>
            )}

            <div className={`mb-2 ${isActive ? config.color : "text-muted-foreground group-hover:text-foreground"}`}>
              {config.icon}
            </div>

            <div className={`text-sm font-semibold mb-0.5 ${isActive ? "text-foreground" : "text-foreground"}`}>
              {config.label}
            </div>
            <div className="text-xs text-muted-foreground">
              {config.description}
            </div>

            {/* 底部装饰线 */}
            <div
              className={`
                absolute bottom-0 left-1/2 -translate-x-1/2 h-0.5 rounded-full transition-all duration-300
                ${isActive ? "w-12 bg-gradient-to-r from-transparent via-primary to-transparent" : "w-0"}
              `}
            />
          </button>
        );
      })}
    </div>
  );
});

// 导出选项面板
const ExportOptionsPanel = memo(function ExportOptionsPanel({
  options,
  onOptionsChange,
  expanded,
  onToggle,
}: {
  options: ExportOptions;
  onOptionsChange: (options: ExportOptions) => void;
  expanded: boolean;
  onToggle: () => void;
}) {
  const optionItems = [
    { key: "includeCodeSnippets", label: "包含代码片段", description: "导出相关的代码示例" },
    { key: "includeRemediation", label: "包含修复建议", description: "导出漏洞修复方案" },
    { key: "includeMetadata", label: "包含元数据", description: "导出任务和文件信息" },
    { key: "compactMode", label: "紧凑模式", description: "减少空白和间距" },
  ];

  return (
    <div className="rounded-xl border border-border bg-muted/50 overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between p-3 hover:bg-muted/20 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Settings2 className="w-4 h-4 text-muted-foreground" />
          <span className="text-sm font-medium text-foreground">导出选项</span>
        </div>
        {expanded ? (
          <ChevronUp className="w-4 h-4 text-muted-foreground" />
        ) : (
          <ChevronDown className="w-4 h-4 text-muted-foreground" />
        )}
      </button>

      <div
        className={`
          grid transition-all duration-300 ease-out
          ${expanded ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"}
        `}
      >
        <div className="overflow-hidden">
          <div className="p-3 pt-0 space-y-2">
            {optionItems.map((item) => (
              <label
                key={item.key}
                className="flex items-center justify-between p-2 rounded-lg hover:bg-muted/20 cursor-pointer transition-colors"
              >
                <div className="flex-1">
                  <div className="text-xs font-medium text-foreground">{item.label}</div>
                  <div className="text-xs text-muted-foreground">{item.description}</div>
                </div>
                <Switch
                  checked={options[item.key as keyof ExportOptions]}
                  onCheckedChange={(checked) =>
                    onOptionsChange({ ...options, [item.key]: checked })
                  }
                  className="data-[state=checked]:bg-primary"
                />
              </label>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
});

// 搜索栏组件
const PreviewSearchBar = memo(function PreviewSearchBar({
  searchQuery,
  onSearchChange,
  matchCount,
  onClear,
}: {
  searchQuery: string;
  onSearchChange: (query: string) => void;
  matchCount: number;
  onClear: () => void;
}) {
  return (
    <div className="flex items-center gap-2 px-3 py-2 bg-muted border-b border-border">
      <Search className="w-3.5 h-3.5 text-muted-foreground" />
      <input
        type="text"
        value={searchQuery}
        onChange={(e) => onSearchChange(e.target.value)}
        placeholder="搜索预览内容..."
        className="flex-1 bg-transparent text-xs text-foreground placeholder:text-muted-foreground outline-none"
      />
      {searchQuery && (
        <>
          <span className="text-xs text-muted-foreground font-mono">
            {matchCount} 匹配
          </span>
          <button
            onClick={onClear}
            className="p-1 rounded hover:bg-muted/50 text-muted-foreground hover:text-foreground transition-colors"
          >
            <X className="w-3 h-3" />
          </button>
        </>
      )}
    </div>
  );
});

// 骨架屏加载组件
const PreviewSkeleton = memo(function PreviewSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-6 bg-muted/30 rounded w-3/4" />
      <div className="space-y-2">
        <div className="h-4 bg-muted/20 rounded w-full" />
        <div className="h-4 bg-muted/20 rounded w-5/6" />
        <div className="h-4 bg-muted/20 rounded w-4/6" />
      </div>
      <div className="h-20 bg-muted/20 rounded" />
      <div className="space-y-2">
        <div className="h-4 bg-muted/20 rounded w-full" />
        <div className="h-4 bg-muted/20 rounded w-3/4" />
      </div>
      <div className="h-16 bg-muted/20 rounded" />
    </div>
  );
});

// Markdown preview renderer - Enhanced with search highlighting
const MarkdownPreview = memo(function MarkdownPreview({
  content,
  searchQuery = "",
}: {
  content: string;
  searchQuery?: string;
}) {
  // 高亮搜索匹配文本
  const highlightText = useCallback((text: string, query: string) => {
    if (!query) return text;
    const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    const parts = text.split(regex);
    return parts.map((part, i) =>
      regex.test(part) ? (
        <mark key={i} className="bg-primary/40 text-foreground px-0.5 rounded">{part}</mark>
      ) : (
        part
      )
    );
  }, []);

  // Simple markdown to styled elements renderer
  const renderMarkdown = (text: string) => {
    const lines = text.split("\n");
    const elements: React.ReactNode[] = [];
    let inCodeBlock = false;
    let codeContent: string[] = [];
    let codeLanguage = "";

    lines.forEach((line, index) => {
      // Code block handling
      if (line.startsWith("```")) {
        if (inCodeBlock) {
          elements.push(
            <div key={`code-${index}`} className="my-4 rounded-xl bg-card border border-border/50 overflow-hidden shadow-lg">
              <div className="flex items-center justify-between px-4 py-2 bg-gradient-to-r from-muted to-muted/40 border-b border-border/50">
                <div className="flex items-center gap-2">
                  <div className="flex gap-1.5">
                    <div className="w-2.5 h-2.5 rounded-full bg-rose-500/80" />
                    <div className="w-2.5 h-2.5 rounded-full bg-amber-500/80" />
                    <div className="w-2.5 h-2.5 rounded-full bg-emerald-500/80" />
                  </div>
                  <span className="text-xs text-muted-foreground uppercase tracking-wider font-mono ml-2">
                    {codeLanguage || "code"}
                  </span>
                </div>
                <Terminal className="w-3.5 h-3.5 text-muted-foreground" />
              </div>
              <div className="relative">
                {/* 行号 */}
                <div className="absolute left-0 top-0 bottom-0 w-10 bg-background border-r border-border select-none">
                  <div className="p-3 text-xs font-mono text-muted-foreground leading-5">
                    {codeContent.map((_, i) => (
                      <div key={i}>{i + 1}</div>
                    ))}
                  </div>
                </div>
                <pre className="p-3 pl-14 text-xs font-mono text-foreground overflow-x-auto leading-5">
                  {codeContent.map((codeLine, i) => (
                    <div key={i}>{highlightText(codeLine, searchQuery) || " "}</div>
                  ))}
                </pre>
              </div>
            </div>
          );
          codeContent = [];
          codeLanguage = "";
          inCodeBlock = false;
        } else {
          inCodeBlock = true;
          codeLanguage = line.slice(3).trim();
        }
        return;
      }

      if (inCodeBlock) {
        codeContent.push(line);
        return;
      }

      // Headers with decorative elements
      if (line.startsWith("# ")) {
        elements.push(
          <h1 key={index} className="text-xl font-bold text-foreground mt-8 mb-4 pb-3 border-b border-border/50 flex items-center gap-3">
            <span className="w-1 h-6 bg-primary rounded-full" />
            {highlightText(line.slice(2), searchQuery)}
          </h1>
        );
        return;
      }
      if (line.startsWith("## ")) {
        elements.push(
          <h2 key={index} className="text-lg font-bold text-foreground mt-6 mb-3 flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-primary/60" />
            {highlightText(line.slice(3), searchQuery)}
          </h2>
        );
        return;
      }
      if (line.startsWith("### ")) {
        elements.push(
          <h3 key={index} className="text-base font-semibold text-foreground mt-5 mb-2 pl-2 border-l-2 border-border">
            {highlightText(line.slice(4), searchQuery)}
          </h3>
        );
        return;
      }

      // Horizontal rule with style
      if (line.match(/^---+$/)) {
        elements.push(
          <div key={index} className="my-6 flex items-center gap-3">
            <div className="flex-1 h-px bg-gradient-to-r from-transparent via-border to-transparent" />
            <div className="w-1.5 h-1.5 rounded-full bg-muted" />
            <div className="flex-1 h-px bg-gradient-to-r from-transparent via-border to-transparent" />
          </div>
        );
        return;
      }

      // List items with better styling
      if (line.match(/^[-*]\s/)) {
        elements.push(
          <div key={index} className="flex gap-3 text-sm text-foreground ml-3 my-1 group">
            <span className="text-primary mt-1.5 text-xs group-hover:scale-125 transition-transform">●</span>
            <span className="flex-1">{highlightText(line.slice(2), searchQuery)}</span>
          </div>
        );
        return;
      }

      // Bold text handling
      if (line.includes("**")) {
        const parts = line.split(/\*\*(.+?)\*\*/g);
        const lineElements = parts.map((part, i) => {
          if (i % 2 === 1) {
            return <strong key={i} className="text-foreground font-semibold">{highlightText(part, searchQuery)}</strong>;
          }
          return highlightText(part, searchQuery);
        });
        elements.push(
          <p key={index} className="text-sm text-foreground my-1.5 leading-relaxed">
            {lineElements}
          </p>
        );
        return;
      }

      // Empty lines
      if (line.trim() === "") {
        elements.push(<div key={index} className="h-3" />);
        return;
      }

      // Regular paragraphs
      elements.push(
        <p key={index} className="text-sm text-foreground my-1.5 leading-relaxed">
          {highlightText(line, searchQuery)}
        </p>
      );
    });

    return elements;
  };

  return (
    <div className="prose prose-invert max-w-none">
      {renderMarkdown(content)}
    </div>
  );
});

// JSON preview with enhanced syntax highlighting
const JsonPreview = memo(function JsonPreview({
  content,
  searchQuery = "",
}: {
  content: string;
  searchQuery?: string;
}) {
  const highlightJson = (json: string) => {
    try {
      const parsed = JSON.parse(json);
      const formatted = JSON.stringify(parsed, null, 2);

      // 处理搜索高亮
      let result = formatted
        .replace(/"([^"]+)":/g, '<span class="text-violet-400">"$1"</span>:')
        .replace(/: "([^"]+)"/g, ': <span class="text-emerald-400">"$1"</span>')
        .replace(/: (\d+\.?\d*)/g, ': <span class="text-amber-400">$1</span>')
        .replace(/: (true|false)/g, ': <span class="text-sky-400">$1</span>')
        .replace(/: (null)/g, ': <span class="text-muted-foreground">$1</span>');

      if (searchQuery) {
        const regex = new RegExp(`(${searchQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
        result = result.replace(regex, '<mark class="bg-primary/40 text-foreground px-0.5 rounded">$1</mark>');
      }

      return result;
    } catch {
      return json;
    }
  };

  const lines = content.split('\n');

  return (
    <div className="relative">
      {/* 行号区域 */}
      <div className="absolute left-0 top-0 bottom-0 w-10 bg-background border-r border-border select-none">
        <div className="py-3 text-xs font-mono text-muted-foreground text-right pr-2 leading-5">
          {lines.map((_, i) => (
            <div key={i}>{i + 1}</div>
          ))}
        </div>
      </div>
      <pre
        className="text-xs font-mono text-foreground whitespace-pre-wrap pl-14 py-3 leading-5"
        dangerouslySetInnerHTML={{ __html: highlightJson(content) }}
      />
    </div>
  );
});

// HTML预览组件（增强版）
const HtmlPreview = memo(function HtmlPreview({
  content,
  searchQuery = "",
}: {
  content: string;
  searchQuery?: string;
}) {
  const truncatedContent = content.slice(0, 5000);
  const isTruncated = content.length > 5000;

  // 简单的语法高亮
  const highlightHtml = (html: string) => {
    let result = html
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/(&lt;\/?[a-zA-Z][a-zA-Z0-9]*)/g, '<span class="text-rose-400">$1</span>')
      .replace(/(\s[a-zA-Z-]+)=/g, '<span class="text-amber-400">$1</span>=')
      .replace(/"([^"]*)"/g, '"<span class="text-emerald-400">$1</span>"')
      .replace(/(&lt;!DOCTYPE[^&]*&gt;)/gi, '<span class="text-muted-foreground">$1</span>');

    if (searchQuery) {
      const regex = new RegExp(`(${searchQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
      result = result.replace(regex, '<mark class="bg-primary/40 text-foreground px-0.5 rounded">$1</mark>');
    }

    return result;
  };

  return (
    <div className="relative">
      <pre
        className="text-xs font-mono text-muted-foreground whitespace-pre-wrap leading-5"
        dangerouslySetInnerHTML={{ __html: highlightHtml(truncatedContent) }}
      />
      {isTruncated && (
        <div className="mt-4 pt-4 border-t border-border text-center">
          <span className="text-xs text-muted-foreground bg-muted px-3 py-1.5 rounded-full">
            已截断显示，完整内容请下载查看
          </span>
        </div>
      )}
    </div>
  );
});

// ============ Main Component ============

export const ReportExportDialog = memo(function ReportExportDialog({
  open,
  onOpenChange,
  task,
  findings,
}: ReportExportDialogProps) {
  // 基础状态
  const [activeFormat, setActiveFormat] = useState<ReportFormat>("markdown");
  const [preview, setPreview] = useState<ReportPreview>({
    content: "",
    format: "markdown",
    loading: false,
    error: null,
  });
  const [copied, setCopied] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloadSuccess, setDownloadSuccess] = useState(false);

  // 增强功能状态
  const [searchQuery, setSearchQuery] = useState("");
  const [exportOptions, setExportOptions] = useState<ExportOptions>(DEFAULT_EXPORT_OPTIONS);
  const [optionsExpanded, setOptionsExpanded] = useState(false);

  // 预览缓存
  const previewCache = useRef<Map<ReportFormat, string>>(new Map());

  // 计算搜索匹配数
  const searchMatchCount = useMemo(() => {
    if (!searchQuery || !preview.content) return 0;
    const regex = new RegExp(searchQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
    return (preview.content.match(regex) || []).length;
  }, [searchQuery, preview.content]);

  // Fetch report content for preview
  const fetchPreview = useCallback(async (format: ReportFormat, forceRefresh = false) => {
    if (!task) return;

    // 检查缓存
    if (!forceRefresh && previewCache.current.has(format)) {
      setPreview({
        content: previewCache.current.get(format)!,
        format,
        loading: false,
        error: null,
      });
      return;
    }

    setPreview(prev => ({ ...prev, loading: true, error: null }));

    try {
      let content = "";

      if (format === "json") {
        const response = await apiClient.get(`/agent-tasks/${task.id}/report`, {
          params: { format: "json" },
        });
        content = JSON.stringify(response.data, null, 2);
      } else if (format === "html") {
        const mdResponse = await apiClient.get(`/agent-tasks/${task.id}/report`, {
          params: { format: "markdown" },
          responseType: "text",
        });
        content = await generateHtmlReport(mdResponse.data, task);
      } else {
        const response = await apiClient.get(`/agent-tasks/${task.id}/report`, {
          params: { format: "markdown" },
          responseType: "text",
        });
        content = response.data;
      }

      // 缓存结果
      previewCache.current.set(format, content);

      setPreview({
        content,
        format,
        loading: false,
        error: null,
      });
    } catch (err) {
      console.error("Failed to fetch report preview:", err);
      setPreview(prev => ({
        ...prev,
        loading: false,
        error: "加载预览失败，请重试",
      }));
    }
  }, [task]);

  // Generate HTML report from markdown
  const generateHtmlReport = async (markdown: string, task: AgentTask): Promise<string> => {
    const contentHtml = await marked.parse(markdown);
    const score = task.security_score;
    const scoreDisplay = score?.toFixed(0) ?? "—";
    const totalFindings = task.findings_count || 0;
    const criticalCount = task.critical_count || 0;
    const highCount = task.high_count || 0;
    const mediumCount = task.medium_count || 0;
    const lowCount = task.low_count || 0;
    const verifiedCount = task.verified_count || 0;
    const taskName = task.name || `Task ${task.id.slice(0, 8)}`;
    const generateDate = new Date().toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    });

    // 计算评分等级和颜色
    const getScoreGrade = (s: number) => {
      if (s >= 90) return { grade: 'A', color: '#10b981', bg: 'rgba(16, 185, 129, 0.1)' };
      if (s >= 80) return { grade: 'B', color: '#22c55e', bg: 'rgba(34, 197, 94, 0.1)' };
      if (s >= 70) return { grade: 'C', color: '#eab308', bg: 'rgba(234, 179, 8, 0.1)' };
      if (s >= 60) return { grade: 'D', color: '#f97316', bg: 'rgba(249, 115, 22, 0.1)' };
      return { grade: 'F', color: '#ef4444', bg: 'rgba(239, 68, 68, 0.1)' };
    };
    const scoreInfo = score == null ? { grade: "未评分", color: "#64748b", bg: "transparent" } : getScoreGrade(score);

    // SVG 圆环进度条
    const circumference = 2 * Math.PI * 40; // r=40 (smaller)
    const strokeDashoffset = circumference - ((score ?? 0) / 100) * circumference;

    return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>安全审计报告 - ${taskName}</title>
  <style>
    :root {
      --bg-body: #06060a;
      --bg-primary: #0a0a0f;
      --bg-secondary: #0f0f15;
      --bg-tertiary: #16161f;
      --bg-card: #12121a;
      --text-primary: #f8fafc;
      --text-secondary: #94a3b8;
      --text-muted: #64748b;
      --accent: #ff6b2c;
      --accent-glow: rgba(255, 107, 44, 0.2);
      --border: #1e293b;
      --border-light: #334155;
      --success: #10b981;
      --critical: #dc2626;
      --critical-bg: rgba(220, 38, 38, 0.12);
      --high: #f97316;
      --high-bg: rgba(249, 115, 22, 0.1);
      --medium: #eab308;
      --medium-bg: rgba(234, 179, 8, 0.08);
      --low: #3b82f6;
      --low-bg: rgba(59, 130, 246, 0.08);
      --info: #6366f1;
      --info-bg: rgba(99, 102, 241, 0.08);
      --code-bg: #0d1117;
    }

    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    html { scroll-behavior: smooth; }

    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: var(--bg-body);
      color: var(--text-secondary);
      line-height: 1.6;
      font-size: 14px;
    }

    .container { max-width: 900px; margin: 0 auto; padding: 0 1.5rem; }

    /* Header */
    .header {
      background: linear-gradient(135deg, var(--bg-primary), var(--bg-secondary));
      border-bottom: 1px solid var(--border);
      padding: 1.25rem 0;
      position: relative;
    }

    .header::before {
      content: "";
      position: absolute;
      top: -50%;
      right: -10%;
      width: 300px;
      height: 300px;
      background: radial-gradient(circle, var(--accent-glow) 0%, transparent 70%);
      pointer-events: none;
    }

    .header-content {
      position: relative;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }

    .brand-logo {
      width: 28px;
      height: 28px;
      background: linear-gradient(135deg, var(--accent), #ff8f5a);
      border-radius: 6px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 800;
      font-size: 0.9rem;
      color: white;
    }

    .brand-text { font-size: 1rem; font-weight: 700; color: var(--text-primary); }

    .header-title {
      font-size: 1.25rem;
      font-weight: 700;
      color: var(--text-primary);
      text-align: center;
      flex: 1;
      margin: 0 1rem;
    }

    .header-meta {
      text-align: right;
      font-size: 0.7rem;
      color: var(--text-muted);
    }

    /* Stats Section */
    .stats-section {
      padding: 1rem 0;
      background: var(--bg-primary);
      border-bottom: 1px solid var(--border);
    }

    .stats-grid {
      display: flex;
      align-items: center;
      gap: 1.25rem;
    }

    .score-ring-container {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      padding: 0.75rem 1rem;
      background: var(--bg-card);
      border-radius: 12px;
      border: 1px solid var(--border);
    }

    .score-ring {
      position: relative;
      width: 56px;
      height: 56px;
    }

    .score-ring svg {
      transform: rotate(-90deg);
      width: 56px;
      height: 56px;
    }

    .score-ring-bg { fill: none; stroke: var(--border); stroke-width: 5; }
    .score-ring-progress {
      fill: none;
      stroke: ${scoreInfo.color};
      stroke-width: 5;
      stroke-linecap: round;
      stroke-dasharray: ${circumference};
      stroke-dashoffset: ${strokeDashoffset};
      filter: drop-shadow(0 0 4px ${scoreInfo.color}40);
    }

    .score-ring-content {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
    }

    .score-value {
      font-size: 1.1rem;
      font-weight: 800;
      color: ${scoreInfo.color};
      line-height: 1;
      font-family: 'SF Mono', monospace;
    }

    .score-grade {
      font-size: 0.55rem;
      font-weight: 600;
      color: ${scoreInfo.color};
      background: ${scoreInfo.bg};
      padding: 0.1rem 0.3rem;
      border-radius: 3px;
      margin-top: 0.15rem;
    }

    .score-label {
      font-size: 0.65rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }

    .stats-cards {
      display: flex;
      gap: 0.5rem;
      flex: 1;
    }

    .stat-card {
      flex: 1;
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.6rem 0.75rem;
    }

    .stat-card-header {
      display: flex;
      align-items: center;
      gap: 0.4rem;
      margin-bottom: 0.25rem;
    }

    .stat-card-icon {
      width: 18px;
      height: 18px;
      border-radius: 4px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 0.65rem;
      font-weight: 700;
    }

    .stat-card-icon.critical { background: var(--critical-bg); color: var(--critical); }
    .stat-card-icon.high { background: var(--high-bg); color: var(--high); }
    .stat-card-icon.total { background: var(--info-bg); color: var(--info); }
    .stat-card-icon.verified { background: rgba(16,185,129,0.1); color: var(--success); }

    .stat-card-label { font-size: 0.6rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; }
    .stat-card-value { font-size: 1.25rem; font-weight: 700; color: var(--text-primary); font-family: 'SF Mono', monospace; line-height: 1; }
    .stat-card-value.critical { color: var(--critical); }
    .stat-card-value.high { color: var(--high); }

    /* Severity Bar */
    .severity-section {
      padding: 0.75rem 0;
      background: var(--bg-primary);
    }

    .severity-bar-wrap {
      display: flex;
      align-items: center;
      gap: 1rem;
    }

    .severity-bar-title {
      font-size: 0.65rem;
      color: var(--text-muted);
      text-transform: uppercase;
      white-space: nowrap;
    }

    .severity-bar {
      flex: 1;
      display: flex;
      height: 6px;
      border-radius: 3px;
      overflow: hidden;
      background: var(--border);
    }

    .severity-segment { height: 100%; }
    .severity-segment.critical { background: var(--critical); }
    .severity-segment.high { background: var(--high); }
    .severity-segment.medium { background: var(--medium); }
    .severity-segment.low { background: var(--low); }

    .severity-legend {
      display: flex;
      gap: 0.75rem;
    }

    .severity-legend-item {
      display: flex;
      align-items: center;
      gap: 0.25rem;
      font-size: 0.6rem;
      color: var(--text-muted);
    }

    .severity-dot { width: 6px; height: 6px; border-radius: 50%; }
    .severity-dot.critical { background: var(--critical); }
    .severity-dot.high { background: var(--high); }
    .severity-dot.medium { background: var(--medium); }
    .severity-dot.low { background: var(--low); }

    /* Main Content */
    .main-content {
      padding: 1.5rem 0;
      background: var(--bg-body);
    }

    .content-wrapper {
      background: var(--bg-primary);
      border-radius: 12px;
      border: 1px solid var(--border);
      padding: 1.5rem;
    }

    /* Typography */
    h1, h2, h3, h4 {
      color: var(--text-primary);
      font-weight: 600;
      letter-spacing: -0.01em;
    }

    h1 {
      font-size: 1.25rem;
      margin: 1.5rem 0 0.75rem;
      padding-bottom: 0.5rem;
      border-bottom: 2px solid var(--accent);
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }

    h1::before { content: "§"; color: var(--accent); font-weight: 400; }

    h2 {
      font-size: 1.1rem;
      margin: 1.25rem 0 0.5rem;
      padding-bottom: 0.35rem;
      border-bottom: 1px solid var(--border);
    }

    h2::before { content: "//"; color: var(--accent); margin-right: 0.35rem; font-weight: 400; opacity: 0.7; }

    h3 {
      font-size: 1rem;
      margin: 1rem 0 0.4rem;
      padding-left: 0.75rem;
      border-left: 2px solid var(--accent);
    }

    h4 { font-size: 0.9rem; margin: 0.75rem 0 0.35rem; color: var(--text-secondary); }

    p { margin-bottom: 0.6rem; font-size: 0.875rem; }

    /* Code Blocks */
    pre {
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      margin: 0.75rem 0;
      overflow: hidden;
      font-size: 0.8rem;
    }

    pre::before {
      content: "CODE";
      display: block;
      background: var(--bg-tertiary);
      padding: 0.35rem 0.75rem;
      font-size: 0.6rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      border-bottom: 1px solid var(--border);
    }

    pre code {
      display: block;
      padding: 0.75rem;
      overflow-x: auto;
      line-height: 1.5;
    }

    code {
      font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
      font-size: 0.85em;
      color: #e2e8f0;
    }

    p code, li code, td code {
      background: var(--bg-tertiary);
      color: var(--accent);
      padding: 0.15em 0.35em;
      border-radius: 4px;
      font-size: 0.8em;
      border: 1px solid var(--border);
    }

    /* Tables */
    table {
      width: 100%;
      border-collapse: collapse;
      margin: 0.75rem 0;
      background: var(--bg-card);
      border-radius: 8px;
      overflow: hidden;
      border: 1px solid var(--border);
      font-size: 0.8rem;
    }

    th {
      padding: 0.6rem 0.75rem;
      text-align: left;
      font-weight: 600;
      font-size: 0.65rem;
      color: var(--text-secondary);
      text-transform: uppercase;
      background: var(--bg-tertiary);
      border-bottom: 1px solid var(--border);
    }

    td {
      padding: 0.5rem 0.75rem;
      border-bottom: 1px solid var(--border);
    }

    tr:last-child td { border-bottom: none; }
    tr:hover td { background: rgba(255, 255, 255, 0.02); }

    /* Lists */
    ul, ol { margin: 0.5rem 0 0.5rem 1.25rem; }
    li { margin-bottom: 0.25rem; font-size: 0.875rem; }
    li::marker { color: var(--accent); }

    /* Blockquotes */
    blockquote {
      margin: 0.75rem 0;
      padding: 0.6rem 1rem;
      background: var(--bg-card);
      border-left: 3px solid var(--accent);
      border-radius: 0 8px 8px 0;
      font-size: 0.85rem;
    }

    blockquote p:last-child { margin-bottom: 0; }

    /* Links */
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }

    /* HR */
    hr {
      border: none;
      height: 1px;
      background: linear-gradient(90deg, transparent, var(--border), transparent);
      margin: 1.5rem 0;
    }

    strong { color: var(--text-primary); font-weight: 600; }
    em { color: var(--text-muted); }

    /* Footer */
    .report-footer {
      padding: 1rem 0;
      background: var(--bg-primary);
      border-top: 1px solid var(--border);
      text-align: center;
    }

    .footer-content {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 0.5rem;
      font-size: 0.7rem;
      color: var(--text-muted);
    }

    .footer-brand {
      display: flex;
      align-items: center;
      gap: 0.35rem;
      color: var(--text-secondary);
      font-weight: 600;
    }

    .footer-brand-icon {
      width: 16px;
      height: 16px;
      background: linear-gradient(135deg, var(--accent), #ff8f5a);
      border-radius: 4px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 0.6rem;
      color: white;
      font-weight: 800;
    }

    /* Responsive */
    @media (max-width: 768px) {
      .container { padding: 0 1rem; }
      .stats-grid { flex-direction: column; gap: 0.75rem; }
      .score-ring-container { width: 100%; justify-content: center; }
      .stats-cards { flex-wrap: wrap; }
      .stat-card { min-width: calc(50% - 0.25rem); }
      .severity-bar-wrap { flex-direction: column; align-items: stretch; gap: 0.5rem; }
      .severity-legend { justify-content: center; }
      .content-wrapper { padding: 1rem; }
    }

    /* Print */
    @media print {
      :root {
        --bg-body: #fff;
        --bg-primary: #fff;
        --bg-secondary: #f8fafc;
        --bg-tertiary: #f1f5f9;
        --bg-card: #fff;
        --text-primary: #0f172a;
        --text-secondary: #475569;
        --text-muted: #64748b;
        --border: #e2e8f0;
        --code-bg: #f8fafc;
      }
      body { background: white; font-size: 11pt; }
      .header::before { display: none; }
      .content-wrapper { border: none; padding: 0; }
      pre { break-inside: avoid; }
      code { color: #1e293b; }
      p code, li code { background: #f1f5f9; color: #c2410c; }
      a { color: #2563eb; }
    }
  </style>
</head>
<body>
  <header class="header">
    <div class="container">
      <div class="header-content">
        <div class="brand">
          <div class="brand-logo">D</div>
          <span class="brand-text">DeepAudit</span>
        </div>
        <h1 class="header-title">${taskName}</h1>
        <div class="header-meta">${generateDate}</div>
      </div>
    </div>
  </header>

  <section class="stats-section">
    <div class="container">
      <div class="stats-grid">
        <div class="score-ring-container">
          <div class="score-ring">
            <svg viewBox="0 0 56 56">
              <circle class="score-ring-bg" cx="28" cy="28" r="23"></circle>
              <circle class="score-ring-progress" cx="28" cy="28" r="23"></circle>
            </svg>
            <div class="score-ring-content">
              <span class="score-value">${scoreDisplay}</span>
              <span class="score-grade">${scoreInfo.grade}</span>
            </div>
          </div>
          <span class="score-label">安全评分</span>
        </div>
        <div class="stats-cards">
          <div class="stat-card">
            <div class="stat-card-header">
              <div class="stat-card-icon total">∑</div>
              <span class="stat-card-label">总数</span>
            </div>
            <div class="stat-card-value">${totalFindings}</div>
          </div>
          <div class="stat-card">
            <div class="stat-card-header">
              <div class="stat-card-icon critical">!</div>
              <span class="stat-card-label">严重</span>
            </div>
            <div class="stat-card-value critical">${criticalCount}</div>
          </div>
          <div class="stat-card">
            <div class="stat-card-header">
              <div class="stat-card-icon high">▲</div>
              <span class="stat-card-label">高危</span>
            </div>
            <div class="stat-card-value high">${highCount}</div>
          </div>
          <div class="stat-card">
            <div class="stat-card-header">
              <div class="stat-card-icon verified">✓</div>
              <span class="stat-card-label">验证</span>
            </div>
            <div class="stat-card-value" style="color:var(--success)">${verifiedCount}</div>
          </div>
        </div>
      </div>
    </div>
  </section>

  <section class="severity-section">
    <div class="container">
      <div class="severity-bar-wrap">
        <span class="severity-bar-title">分布</span>
        <div class="severity-bar">
          ${totalFindings > 0 ? `
            <div class="severity-segment critical" style="width:${(criticalCount/totalFindings)*100}%"></div>
            <div class="severity-segment high" style="width:${(highCount/totalFindings)*100}%"></div>
            <div class="severity-segment medium" style="width:${(mediumCount/totalFindings)*100}%"></div>
            <div class="severity-segment low" style="width:${(lowCount/totalFindings)*100}%"></div>
          ` : ''}
        </div>
        <div class="severity-legend">
          <div class="severity-legend-item"><div class="severity-dot critical"></div>${criticalCount}</div>
          <div class="severity-legend-item"><div class="severity-dot high"></div>${highCount}</div>
          <div class="severity-legend-item"><div class="severity-dot medium"></div>${mediumCount}</div>
          <div class="severity-legend-item"><div class="severity-dot low"></div>${lowCount}</div>
        </div>
      </div>
    </div>
  </section>

  <main class="main-content">
    <div class="container">
      <div class="content-wrapper">
        ${contentHtml}
      </div>
    </div>
  </main>

  <footer class="report-footer">
    <div class="container">
      <div class="footer-content">
        <div class="footer-brand">
          <div class="footer-brand-icon">D</div>
          DeepAudit
        </div>
        <span>·</span>
        <span>${generateDate}</span>
      </div>
    </div>
  </footer>
</body>
</html>`;
  };

  // Load preview when format changes or dialog opens
  useEffect(() => {
    if (open && task) {
      fetchPreview(activeFormat);
    }
  }, [open, activeFormat, task, fetchPreview]);

  // 清除缓存当对话框关闭时
  useEffect(() => {
    if (!open) {
      previewCache.current.clear();
      setSearchQuery("");
      setDownloadSuccess(false);
    }
  }, [open]);

  // 键盘快捷键
  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl/Cmd + C 复制
      if ((e.metaKey || e.ctrlKey) && e.key === 'c' && !window.getSelection()?.toString()) {
        e.preventDefault();
        handleCopy();
      }
      // Ctrl/Cmd + S 下载
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault();
        handleDownload();
      }
      // Ctrl/Cmd + F 搜索
      if ((e.metaKey || e.ctrlKey) && e.key === 'f') {
        e.preventDefault();
        // 聚焦搜索框（如果存在）
      }
      // 数字键 1-3 切换格式
      if (e.key === '1') setActiveFormat('markdown');
      if (e.key === '2') setActiveFormat('json');
      if (e.key === '3') setActiveFormat('html');
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, preview.content]);

  // Handle copy to clipboard
  const handleCopy = async () => {
    if (!preview.content) return;
    try {
      await navigator.clipboard.writeText(preview.content);
      setCopied(true);
      toast.success("已复制到剪贴板");
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy:", err);
      toast.error("复制失败");
    }
  };

  // Handle download
  const handleDownload = async () => {
    if (!task) return;

    setDownloading(true);
    try {
      let content = preview.content;
      let filename = `audit_report_${task.name || task.id.substring(0, 8)}_${new Date().toISOString().slice(0, 10)}`;
      const config = FORMAT_CONFIG[activeFormat];

      // 如果预览内容为空，重新获取
      if (!content) {
        if (activeFormat === "json") {
          const response = await apiClient.get(`/agent-tasks/${task.id}/report`, {
            params: { format: "json" },
          });
          content = JSON.stringify(response.data, null, 2);
        } else if (activeFormat === "html") {
          const mdResponse = await apiClient.get(`/agent-tasks/${task.id}/report`, {
            params: { format: "markdown" },
            responseType: "text",
          });
          content = await generateHtmlReport(mdResponse.data, task);
        } else {
          const response = await apiClient.get(`/agent-tasks/${task.id}/report`, {
            params: { format: "markdown" },
            responseType: "text",
          });
          content = response.data;
        }
      }

      filename += config.extension;

      // Create download trigger
      const blob = new Blob([content], { type: config.mime });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      // 显示成功状态
      setDownloadSuccess(true);
      toast.success(`报告已导出为 ${config.label} 格式`);

      // 延迟关闭
      setTimeout(() => {
        onOpenChange(false);
      }, 1000);
    } catch (err) {
      console.error("Download failed:", err);
      toast.error("导出报告失败，请重试");
    } finally {
      setDownloading(false);
    }
  };

  if (!task) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl h-[90vh] bg-background border-border p-0 gap-0 overflow-hidden shadow-2xl">
        {/* Header */}
        <div className="relative px-6 py-5 border-b border-border bg-card">
          <DialogHeader className="relative">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="relative p-3 rounded-xl bg-primary/10 border border-primary/30">
                  <FileDown className="w-6 h-6 text-primary" />
                </div>
                <div>
                  <DialogTitle className="text-xl font-bold text-foreground flex items-center gap-2">
                    导出审计报告
                    <Sparkles className="w-4 h-4 text-primary/60" />
                  </DialogTitle>
                  <p className="text-xs text-muted-foreground mt-1 font-mono flex items-center gap-2">
                    <Clock className="w-3 h-3" />
                    {task.name || `Task ${task.id.slice(0, 8)}`}
                  </p>
                </div>
              </div>

              {/* 快捷键提示 */}
              <div className="hidden md:flex items-center gap-2 text-xs text-muted-foreground">
                <div className="flex items-center gap-1 px-2 py-1 rounded bg-muted border border-border">
                  <Keyboard className="w-3 h-3" />
                  <span>⌘S 下载</span>
                </div>
                <div className="flex items-center gap-1 px-2 py-1 rounded bg-muted border border-border">
                  <span>1-3 切换</span>
                </div>
              </div>
            </div>
          </DialogHeader>
        </div>

        {/* 主体内容区域 */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Stats Summary - 增强统计卡片 */}
          <div className="px-6 py-4 border-b border-border bg-card/80">
            <EnhancedStatsPanel task={task} findings={findings} />
          </div>

          {/* 两栏布局：左侧配置，右侧预览 */}
          <div className="flex-1 flex min-h-0">
            {/* 左侧：格式选择和配置 */}
            <div className="w-72 flex-shrink-0 border-r border-border bg-card/50 p-4 space-y-4 overflow-y-auto">
              {/* 格式选择 */}
              <div>
                <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3 flex items-center gap-2">
                  <FileText className="w-3.5 h-3.5" />
                  选择格式
                </h3>
                <FormatSelector
                  activeFormat={activeFormat}
                  onFormatChange={setActiveFormat}
                />
              </div>

              {/* 导出选项 */}
              <ExportOptionsPanel
                options={exportOptions}
                onOptionsChange={setExportOptions}
                expanded={optionsExpanded}
                onToggle={() => setOptionsExpanded(!optionsExpanded)}
              />

              {/* 格式信息 */}
              <div className="p-3 rounded-xl bg-muted border border-border">
                <div className="flex items-center gap-2 mb-2">
                  <div className={FORMAT_CONFIG[activeFormat].color}>
                    {FORMAT_CONFIG[activeFormat].icon}
                  </div>
                  <span className="text-sm font-medium text-foreground">
                    {FORMAT_CONFIG[activeFormat].label}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  {activeFormat === "markdown" && "Markdown格式便于编辑和版本控制，可用任何文本编辑器打开。"}
                  {activeFormat === "json" && "JSON格式包含完整的结构化数据，适合程序处理和数据分析。"}
                  {activeFormat === "html" && "HTML格式可直接在浏览器中查看，包含完整样式和布局。"}
                </p>
              </div>
            </div>

            {/* 右侧：预览区域 */}
            <div className="flex-1 flex flex-col min-h-0 cyber-dialog">
              {/* 预览工具栏 */}
              <div className="flex-shrink-0 flex items-center justify-between px-4 py-2.5 border-b border-border bg-muted/50">
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-2">
                    <Eye className="w-4 h-4 text-muted-foreground" />
                    <span className="text-xs text-muted-foreground font-medium">预览</span>
                  </div>
                  <Badge className="text-xs bg-muted/50 text-muted-foreground border-0 font-mono">
                    {formatBytes(preview.content.length)}
                  </Badge>
                </div>

                <div className="flex items-center gap-2">
                  {/* 搜索框 */}
                  <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-muted border border-border">
                    <Search className="w-3.5 h-3.5 text-muted-foreground" />
                    <input
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="搜索..."
                      className="w-24 bg-transparent text-xs text-foreground placeholder:text-muted-foreground outline-none"
                    />
                    {searchQuery && (
                      <span className="text-xs text-muted-foreground font-mono">
                        {searchMatchCount}
                      </span>
                    )}
                  </div>

                  {/* 操作按钮 */}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleCopy}
                    disabled={preview.loading || !preview.content}
                    className="h-8 px-2.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50"
                  >
                    {copied ? (
                      <Check className="w-3.5 h-3.5 mr-1.5 text-emerald-400" />
                    ) : (
                      <Copy className="w-3.5 h-3.5 mr-1.5" />
                    )}
                    {copied ? "已复制" : "复制"}
                  </Button>

                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => fetchPreview(activeFormat, true)}
                    disabled={preview.loading}
                    className="h-8 px-2.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${preview.loading ? 'animate-spin' : ''}`} />
                    刷新
                  </Button>
                </div>
              </div>

              {/* 预览内容 */}
              <div className="flex-1 min-h-0 overflow-hidden">
                <ScrollArea className="h-full">
                  <div className="p-5">
                  {preview.loading ? (
                    <PreviewSkeleton />
                  ) : preview.error ? (
                    <div className="flex items-center justify-center py-16">
                      <div className="flex flex-col items-center gap-4 text-center">
                        <div className="p-4 rounded-full bg-amber-500/10 border border-amber-500/30">
                          <AlertTriangle className="w-8 h-8 text-amber-400" />
                        </div>
                        <div>
                          <p className="text-sm text-foreground font-medium mb-1">加载失败</p>
                          <p className="text-xs text-muted-foreground">{preview.error}</p>
                        </div>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => fetchPreview(activeFormat, true)}
                          className="mt-2"
                        >
                          <RefreshCw className="w-3.5 h-3.5 mr-1.5" />
                          重试
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="rounded-xl border border-border overflow-hidden bg-card">
                      <div className="p-5 min-h-[300px]">
                        {activeFormat === "markdown" && (
                          <MarkdownPreview content={preview.content} searchQuery={searchQuery} />
                        )}
                        {activeFormat === "json" && (
                          <JsonPreview content={preview.content} searchQuery={searchQuery} />
                        )}
                        {activeFormat === "html" && (
                          <HtmlPreview content={preview.content} searchQuery={searchQuery} />
                        )}
                      </div>
                    </div>
                  )}
                </div>
                </ScrollArea>
              </div>
            </div>
          </div>
        </div>

        {/* Footer - 增强设计 */}
        <div className="px-6 py-4 border-t border-border bg-card">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border ${FORMAT_CONFIG[activeFormat].bgColor}`}>
                <span className={FORMAT_CONFIG[activeFormat].color}>
                  {FORMAT_CONFIG[activeFormat].icon}
                </span>
                <span className="font-mono">
                  {FORMAT_CONFIG[activeFormat].label} ({FORMAT_CONFIG[activeFormat].extension})
                </span>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <Button
                variant="ghost"
                onClick={() => onOpenChange(false)}
                className="h-10 px-5 text-sm text-muted-foreground hover:text-foreground"
              >
                取消
              </Button>

              <Button
                onClick={handleDownload}
                disabled={downloading || preview.loading || !preview.content}
                className={`
                  h-10 px-6 text-sm font-medium transition-all duration-300
                  ${downloadSuccess
                    ? "bg-emerald-600 hover:bg-emerald-600"
                    : "bg-primary hover:bg-primary/90"
                  }
                `}
              >
                {downloading ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    导出中...
                  </>
                ) : downloadSuccess ? (
                  <>
                    <Check className="w-4 h-4 mr-2" />
                    导出成功
                  </>
                ) : (
                  <>
                    <Download className="w-4 h-4 mr-2" />
                    下载 {FORMAT_CONFIG[activeFormat].label}
                  </>
                )}
              </Button>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
});

export default ReportExportDialog;
