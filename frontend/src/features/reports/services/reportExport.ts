import type { AuditTask, AuditIssue, CodeAnalysisResult } from "@/shared/types";
import { api } from "@/shared/config/database";

// 导出 JSON 格式报告
export async function exportToJSON(task: AuditTask, issues: AuditIssue[]) {
    const report = {
        metadata: {
            exportDate: new Date().toISOString(),
            version: "1.0.0",
            format: "JSON"
        },
        task: {
            id: task.id,
            projectName: task.project?.name || "未知项目",
            taskType: task.task_type,
            status: task.status,
            branchName: task.branch_name,
            createdAt: task.created_at,
            completedAt: task.completed_at,
            qualityScore: task.quality_score,
            totalFiles: task.total_files,
            scannedFiles: task.scanned_files,
            totalLines: task.total_lines,
            issuesCount: task.issues_count
        },
        issues: issues.map(issue => ({
            id: issue.id,
            title: issue.title,
            description: issue.description,
            severity: issue.severity,
            issueType: issue.issue_type,
            filePath: issue.file_path,
            lineNumber: issue.line_number,
            columnNumber: issue.column_number,
            codeSnippet: issue.code_snippet,
            suggestion: issue.suggestion,
            aiExplanation: issue.ai_explanation
        })),
        summary: {
            totalIssues: issues.length,
            critical: issues.filter(i => i.severity === "critical").length,
            high: issues.filter(i => i.severity === "high").length,
            medium: issues.filter(i => i.severity === "medium").length,
            low: issues.filter(i => i.severity === "low").length,
            byType: {
                security: issues.filter(i => i.issue_type === "security").length,
                bug: issues.filter(i => i.issue_type === "bug").length,
                performance: issues.filter(i => i.issue_type === "performance").length,
                style: issues.filter(i => i.issue_type === "style").length,
                maintainability: issues.filter(i => i.issue_type === "maintainability").length
            }
        }
    };

    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    downloadBlob(blob, `audit-report-${task.id.slice(0, 8)}-${Date.now()}.json`);
}

// 导出任务审计报告 PDF（后端生成）
export async function exportToPDF(task: AuditTask, _issues: AuditIssue[]) {
    try {
        const blob = await api.exportTaskReport(task.id, "pdf");
        downloadBlob(blob, `audit-report-${task.id.slice(0, 8)}-${Date.now()}.pdf`);
    } catch (error) {
        console.error('Failed to export PDF:', error);
        throw new Error('PDF 导出失败，请稍后重试');
    }
}

// 导出任务审计报告 Markdown（后端生成）
export async function exportToMarkdown(task: AuditTask, _issues: AuditIssue[]) {
    try {
        const blob = await api.exportTaskReport(task.id, "markdown");
        downloadBlob(blob, `audit-report-${task.id.slice(0, 8)}-${Date.now()}.md`);
    } catch (error) {
        console.error('Failed to export Markdown:', error);
        throw new Error('Markdown 导出失败，请稍后重试');
    }
}

// 导出任务审计报告 HTML（后端生成）
export async function exportToHTML(task: AuditTask, _issues: AuditIssue[]) {
    try {
        const blob = await api.exportTaskReport(task.id, "html");
        downloadBlob(blob, `audit-report-${task.id.slice(0, 8)}-${Date.now()}.html`);
    } catch (error) {
        console.error('Failed to export HTML:', error);
        throw new Error('HTML 导出失败，请稍后重试');
    }
}

// 导出即时分析报告 PDF（后端生成，基于数据库记录）
export async function exportInstantToPDF(analysisId: string, language: string) {
    try {
        const blob = await api.exportInstantReportPDF(analysisId);
        downloadBlob(blob, `instant-analysis-${language}-${Date.now()}.pdf`);
    } catch (error) {
        console.error('Failed to export instant PDF:', error);
        throw new Error('PDF 导出失败，请稍后重试');
    }
}

// 导出即时分析 JSON
export function exportInstantToJSON(
    analysisResult: CodeAnalysisResult,
    language: string,
    analysisTime: number
) {
    const report = {
        metadata: {
            exportDate: new Date().toISOString(),
            version: "1.0.0",
            format: "JSON",
            type: "instant-analysis"
        },
        analysis: {
            language,
            analysisTime,
            qualityScore: analysisResult.quality_score,
            issuesCount: analysisResult.issues.length
        },
        issues: analysisResult.issues.map(issue => ({
            title: issue.title,
            description: issue.description,
            severity: issue.severity,
            type: issue.type,
            line: issue.line,
            column: issue.column,
            codeSnippet: issue.code_snippet,
            suggestion: issue.suggestion,
            aiExplanation: issue.ai_explanation,
            xai: issue.xai
        })),
        summary: analysisResult.summary,
        metrics: analysisResult.metrics
    };

    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    downloadBlob(blob, `instant-analysis-${language}-${Date.now()}.json`);
}

// 通用下载函数
function downloadBlob(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}
