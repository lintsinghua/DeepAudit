/**
 * Agent 审计模式选择器
 * Cyberpunk Terminal Aesthetic
 */

import { Bot, Zap, CheckCircle2, Clock, Shield, Code, Microscope } from "lucide-react";
import { cn } from "@/shared/utils/utils";

export type AuditMode = "fast" | "agent" | "yasa";

interface AgentModeSelectorProps {
  value: AuditMode;
  onChange: (mode: AuditMode) => void;
  disabled?: boolean;
}

export default function AgentModeSelector({
  value,
  onChange,
  disabled = false,
}: AgentModeSelectorProps) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 mb-2">
        <Shield className="w-4 h-4 text-violet-600 dark:text-violet-400" />
        <span className="font-mono text-xs font-bold text-muted-foreground uppercase tracking-wider">
          审计模式
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {/* 快速审计模式 */}
        <label
          className={cn(
            "relative flex flex-col p-4 border cursor-pointer transition-all rounded",
            value === "fast"
              ? "border-amber-500/50 bg-amber-50 dark:bg-amber-950/30"
              : "border-border hover:border-border bg-muted/50",
            disabled && "opacity-50 cursor-not-allowed"
          )}
        >
          <input
            type="radio"
            name="auditMode"
            value="fast"
            checked={value === "fast"}
            onChange={() => onChange("fast")}
            disabled={disabled}
            className="sr-only"
          />

          <div className="flex items-center gap-2 mb-2">
            <div className={cn(
              "p-1.5 rounded border",
              value === "fast"
                ? "bg-amber-500/20 border-amber-500/50"
                : "bg-muted border-border"
            )}>
              <Zap className={cn(
                "w-4 h-4",
                value === "fast" ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground"
              )} />
            </div>
            <span className={cn(
              "font-bold text-sm font-mono uppercase",
              value === "fast" ? "text-amber-700 dark:text-amber-300" : "text-muted-foreground"
            )}>
              快速审计
            </span>
            {value === "fast" && (
              <CheckCircle2 className="w-4 h-4 text-amber-600 dark:text-amber-400 ml-auto" />
            )}
          </div>

          <ul className="text-xs text-muted-foreground space-y-1 mb-3 font-mono">
            <li className="flex items-center gap-1">
              <Clock className="w-3 h-3" />
              速度快（分钟级）
            </li>
            <li className="flex items-center gap-1">
              <Code className="w-3 h-3" />
              逐文件 LLM 分析
            </li>
            <li className="flex items-center gap-1 text-muted-foreground">
              <Shield className="w-3 h-3" />
              无漏洞验证
            </li>
          </ul>

          <div className="mt-auto pt-2 border-t border-border">
            <span className="text-xs uppercase tracking-wider text-muted-foreground font-bold font-mono">
              适合: CI/CD 集成、日常检查
            </span>
          </div>
        </label>

        {/* Agent 审计模式 */}
        <label
          className={cn(
            "relative flex flex-col p-4 border cursor-pointer transition-all rounded",
            value === "agent"
              ? "border-violet-500/50 bg-violet-50 dark:bg-violet-950/30"
              : "border-border hover:border-border bg-muted/50",
            disabled && "opacity-50 cursor-not-allowed"
          )}
        >
          <input
            type="radio"
            name="auditMode"
            value="agent"
            checked={value === "agent"}
            onChange={() => onChange("agent")}
            disabled={disabled}
            className="sr-only"
          />

          {/* 推荐标签 */}
          <div className="absolute -top-2 -right-2 px-2 py-0.5 bg-violet-600 text-white text-xs font-bold uppercase font-mono rounded shadow-[0_0_10px_rgba(139,92,246,0.5)]">
            推荐
          </div>

          <div className="flex items-center gap-2 mb-2">
            <div className={cn(
              "p-1.5 rounded border",
              value === "agent"
                ? "bg-violet-500/20 border-violet-500/50"
                : "bg-muted border-border"
            )}>
              <Bot className={cn(
                "w-4 h-4",
                value === "agent" ? "text-violet-600 dark:text-violet-400" : "text-muted-foreground"
              )} />
            </div>
            <span className={cn(
              "font-bold text-sm font-mono uppercase",
              value === "agent" ? "text-violet-700 dark:text-violet-300" : "text-muted-foreground"
            )}>
              Agent 审计
            </span>
            {value === "agent" && (
              <CheckCircle2 className="w-4 h-4 text-violet-600 dark:text-violet-400 ml-auto" />
            )}
          </div>

          <ul className="text-xs text-muted-foreground space-y-1 mb-3 font-mono">
            <li className="flex items-center gap-1">
              <Bot className="w-3 h-3" />
              AI Agent 自主分析
            </li>
            <li className="flex items-center gap-1">
              <Code className="w-3 h-3" />
              跨文件关联 + RAG
            </li>
            <li className={cn(
              "flex items-center gap-1",
              value === "agent" ? "text-violet-600 dark:text-violet-400 font-medium" : "text-muted-foreground"
            )}>
              <Shield className="w-3 h-3" />
              沙箱漏洞验证
            </li>
          </ul>

          <div className="mt-auto pt-2 border-t border-border">
            <span className="text-xs uppercase tracking-wider text-muted-foreground font-bold font-mono">
              适合: 发版前审计、深度安全评估
            </span>
          </div>
        </label>
        {/* YASA 混合审计模式 */}
        <label
          className={cn(
            "relative flex flex-col p-4 border cursor-pointer transition-all rounded",
            value === "yasa"
              ? "border-emerald-500/50 bg-emerald-50 dark:bg-emerald-950/30"
              : "border-border hover:border-border bg-muted/50",
            disabled && "opacity-50 cursor-not-allowed"
          )}
        >
          <input
            type="radio"
            name="auditMode"
            value="yasa"
            checked={value === "yasa"}
            onChange={() => onChange("yasa")}
            disabled={disabled}
            className="sr-only"
          />

          <div className="flex items-center gap-2 mb-2">
            <div className={cn(
              "p-1.5 rounded border",
              value === "yasa"
                ? "bg-emerald-500/20 border-emerald-500/50"
                : "bg-muted border-border"
            )}>
              <Microscope className={cn(
                "w-4 h-4",
                value === "yasa" ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground"
              )} />
            </div>
            <span className={cn(
              "font-bold text-sm font-mono uppercase",
              value === "yasa" ? "text-emerald-700 dark:text-emerald-300" : "text-muted-foreground"
            )}>
              YASA 混合审计
            </span>
            {value === "yasa" && (
              <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400 ml-auto" />
            )}
          </div>

          <ul className="text-xs text-muted-foreground space-y-1 mb-3 font-mono">
            <li className="flex items-center gap-1">
              <Code className="w-3 h-3" />
              Agent 建规则 + YASA 污点引擎
            </li>
            <li className="flex items-center gap-1">
              <Shield className="w-3 h-3" />
              数据流 + 权限（路由表）审计
            </li>
            <li className="flex items-center gap-1">
              <Clock className="w-3 h-3" />
              限时 30 分钟，未审项列出
            </li>
          </ul>

          <div className="mt-auto pt-2 border-t border-border">
            <span className="text-xs uppercase tracking-wider text-muted-foreground font-bold font-mono">
              适合: Java / JS·TS / Python / PHP Web 项目
            </span>
          </div>
        </label>
      </div>

      {/* 模式说明 */}
      {value === "agent" && (
        <div className="p-3 bg-violet-50 dark:bg-violet-950/30 border border-violet-500/30 text-xs text-violet-700 dark:text-violet-300 rounded font-mono">
          <p className="font-bold mb-1 uppercase text-violet-700 dark:text-violet-400">Agent 审计模式说明：</p>
          <ul className="list-disc list-inside space-y-0.5 text-violet-600 dark:text-violet-300/80">
            <li>AI Agent 会自主规划审计策略</li>
            <li>使用 RAG 技术进行代码语义检索</li>
            <li>在 Docker 沙箱中验证发现的漏洞</li>
            <li>可生成可复现的 PoC（概念验证）代码</li>
            <li>审计时间较长，但结果更全面准确</li>
          </ul>
        </div>
      )}
    </div>
  );
}
