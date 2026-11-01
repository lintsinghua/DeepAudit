/**
 * Export Report Dialog
 * Cyberpunk Terminal Aesthetic
 */

import { useState } from "react";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogFooter
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Label } from "@/components/ui/label";
import { FileJson, FileText, FileCode2, FileDown, Download, Loader2, Terminal } from "lucide-react";
import type { AuditTask, AuditIssue } from "@/shared/types";
import { exportToJSON, exportToPDF, exportToMarkdown, exportToHTML } from "@/features/reports/services/reportExport";
import { toast } from "sonner";

interface ExportReportDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    task: AuditTask;
    issues: AuditIssue[];
}

type ExportFormat = "json" | "pdf" | "markdown" | "html";

const FORMAT_OPTIONS: Array<{
    value: ExportFormat;
    icon: React.ReactNode;
    title: string;
    desc: string;
    bullet: string;
}> = [
    {
        value: "pdf",
        icon: <FileText className="w-5 h-5 text-rose-400" />,
        title: "PDF 格式",
        desc: "专业报告，适合打印和分享，含统计概览",
        bullet: "完整排版 · 打印友好"
    },
    {
        value: "json",
        icon: <FileJson className="w-5 h-5 text-amber-400" />,
        title: "JSON 格式",
        desc: "结构化数据，适合程序处理和集成",
        bullet: "机器可读 · CI/CD 集成"
    },
    {
        value: "markdown",
        icon: <FileDown className="w-5 h-5 text-sky-400" />,
        title: "Markdown 格式",
        desc: "轻量纯文本，便于版本管理与文档系统",
        bullet: "纯文本 · Wiki 友好"
    },
    {
        value: "html",
        icon: <FileCode2 className="w-5 h-5 text-emerald-400" />,
        title: "HTML 格式",
        desc: "自包含网页报告，可直接在浏览器中查看",
        bullet: "离线可读 · 自带样式"
    },
];

export default function ExportReportDialog({
    open,
    onOpenChange,
    task,
    issues
}: ExportReportDialogProps) {
    const [selectedFormat, setSelectedFormat] = useState<ExportFormat>("pdf");
    const [isExporting, setIsExporting] = useState(false);

    const handleExport = async () => {
        setIsExporting(true);
        try {
            switch (selectedFormat) {
                case "pdf":
                    await exportToPDF(task, issues);
                    toast.success("PDF 报告已导出");
                    break;
                case "json":
                    await exportToJSON(task, issues);
                    toast.success("JSON 报告已导出");
                    break;
                case "markdown":
                    await exportToMarkdown(task, issues);
                    toast.success("Markdown 报告已导出");
                    break;
                case "html":
                    await exportToHTML(task, issues);
                    toast.success("HTML 报告已导出");
                    break;
            }
            onOpenChange(false);
        } catch (error) {
            console.error("导出报告失败:", error);
            toast.error("导出报告失败，请重试");
        } finally {
            setIsExporting(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[640px] cyber-dialog border-border">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-3 text-lg font-bold uppercase tracking-wider text-foreground">
                        <Download className="w-5 h-5 text-primary" />
                        导出审计报告
                    </DialogTitle>
                    <DialogDescription className="text-muted-foreground font-mono text-xs">
                        选择报告格式并导出完整的代码审计结果（支持 PDF / JSON / Markdown / HTML）
                    </DialogDescription>
                </DialogHeader>

                <div className="py-4">
                    <RadioGroup
                        value={selectedFormat}
                        onValueChange={(value) => setSelectedFormat(value as ExportFormat)}
                        className="space-y-3"
                    >
                        {FORMAT_OPTIONS.map((opt) => (
                            <div
                                key={opt.value}
                                className="flex items-center space-x-3 p-4 border border-border rounded bg-muted/50 cursor-pointer hover:bg-muted transition-colors"
                            >
                                <RadioGroupItem value={opt.value} id={opt.value} />
                                <Label htmlFor={opt.value} className="flex items-center gap-3 cursor-pointer flex-1">
                                    {opt.icon}
                                    <div className="flex-1">
                                        <div className="font-bold text-foreground">{opt.title}</div>
                                        <div className="text-xs text-muted-foreground">{opt.desc}</div>
                                    </div>
                                    <span className="hidden sm:inline-flex text-[10px] font-mono text-primary/80 border border-primary/30 rounded px-2 py-0.5 whitespace-nowrap">
                                        {opt.bullet}
                                    </span>
                                </Label>
                            </div>
                        ))}
                    </RadioGroup>

                    {/* 报告预览信息 */}
                    <div className="mt-6 border border-border rounded bg-muted/50">
                        <div className="px-4 py-2 border-b border-border bg-muted flex items-center gap-2">
                            <Terminal className="w-3 h-3 text-primary" />
                            <h4 className="font-bold text-foreground uppercase text-xs">报告内容预览 · 含统计概览</h4>
                        </div>
                        <div className="p-4 grid grid-cols-2 gap-3 text-xs font-mono">
                            <div className="flex items-center justify-between border-b border-border pb-2">
                                <span className="text-muted-foreground">项目名称:</span>
                                <span className="font-bold text-foreground">{task.project?.name || "未知"}</span>
                            </div>
                            <div className="flex items-center justify-between border-b border-border pb-2">
                                <span className="text-muted-foreground">质量评分:</span>
                                <span className="font-bold text-emerald-400">{task.quality_score.toFixed(1)}/100</span>
                            </div>
                            <div className="flex items-center justify-between border-b border-border pb-2">
                                <span className="text-muted-foreground">扫描文件:</span>
                                <span className="font-bold text-foreground">{task.scanned_files}/{task.total_files}</span>
                            </div>
                            <div className="flex items-center justify-between border-b border-border pb-2">
                                <span className="text-muted-foreground">发现问题:</span>
                                <span className="font-bold text-amber-400">{issues.length}</span>
                            </div>
                            <div className="flex items-center justify-between border-b border-border pb-2">
                                <span className="text-muted-foreground">代码行数:</span>
                                <span className="font-bold text-foreground">{task.total_lines.toLocaleString()}</span>
                            </div>
                            <div className="flex items-center justify-between border-b border-border pb-2">
                                <span className="text-muted-foreground">严重问题:</span>
                                <span className="font-bold text-rose-400">
                                    {issues.filter(i => i.severity === "critical").length}
                                </span>
                            </div>
                        </div>
                    </div>
                </div>

                <DialogFooter className="border-t border-border pt-4">
                    <Button
                        variant="outline"
                        onClick={() => onOpenChange(false)}
                        disabled={isExporting}
                    >
                        取消
                    </Button>
                    <Button
                        onClick={handleExport}
                        disabled={isExporting}
                    >
                        {isExporting ? (
                            <>
                                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                                导出中...
                            </>
                        ) : (
                            <>
                                <Download className="w-4 h-4 mr-2" />
                                导出报告
                            </>
                        )}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
