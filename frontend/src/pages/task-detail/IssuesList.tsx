import { Button } from "@/components/ui/button";

import { Badge } from "@/components/ui/badge";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import {
	AlertTriangle,
	CheckCircle,
	ChevronDown,
	Code,
	FileText,
	Info,
	Lightbulb,
	Shield,
	Zap,
} from "lucide-react";

import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

import type { AuditIssue } from "@/shared/types";

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
export function IssuesList({
	issues,
	onStatusChange,
}: {
	issues: AuditIssue[];
	onStatusChange?: (issue: AuditIssue, newStatus: string) => void;
}) {
	const getSeverityClasses = (severity: string) => {
		switch (severity) {
			case "critical":
				return "severity-critical";
			case "high":
				return "severity-high";
			case "medium":
				return "severity-medium";
			case "low":
				return "severity-low";
			default:
				return "severity-info";
		}
	};

	const getTypeIcon = (type: string) => {
		switch (type) {
			case "security":
				return <Shield className="w-4 h-4" />;
			case "bug":
				return <AlertTriangle className="w-4 h-4" />;
			case "performance":
				return <Zap className="w-4 h-4" />;
			case "style":
				return <Code className="w-4 h-4" />;
			case "maintainability":
				return <FileText className="w-4 h-4" />;
			default:
				return <Info className="w-4 h-4" />;
		}
	};

	const criticalIssues = issues.filter(
		(issue) => issue.severity === "critical",
	);
	const highIssues = issues.filter((issue) => issue.severity === "high");
	const mediumIssues = issues.filter((issue) => issue.severity === "medium");
	const lowIssues = issues.filter((issue) => issue.severity === "low");

	const renderIssue = (issue: AuditIssue, index: number) => (
		<div
			key={issue.id || index}
			className="cyber-card p-4 hover:border-border transition-all group"
		>
			<div className="flex items-start justify-between mb-3">
				<div className="flex items-start space-x-3">
					<div
						className={`w-10 h-10 rounded-lg flex items-center justify-center ${
							issue.severity === "critical"
								? "bg-rose-500/20 text-rose-400"
								: issue.severity === "high"
									? "bg-orange-500/20 text-orange-400"
									: issue.severity === "medium"
										? "bg-amber-500/20 text-amber-400"
										: "bg-sky-500/20 text-sky-400"
						}`}
					>
						{getTypeIcon(issue.issue_type)}
					</div>
					<div className="flex-1">
						<h4 className="font-bold text-base text-foreground mb-1 group-hover:text-primary transition-colors uppercase">
							{issue.title}
						</h4>
						<div className="flex items-center space-x-1 text-xs text-muted-foreground font-mono">
							<FileText className="w-3 h-3" />
							<span className="bg-muted px-2 py-0.5 rounded border border-border">
								{issue.file_path}
							</span>
						</div>
						{issue.line_number && (
							<div className="flex items-center space-x-1 text-xs text-muted-foreground mt-1 font-mono">
								<span className="text-primary">&gt;</span>
								<span>LINE: {issue.line_number}</span>
								{issue.column_number && (
									<span>, COL: {issue.column_number}</span>
								)}
							</div>
						)}
					</div>
				</div>
				<div className="flex items-center gap-2">
					{onStatusChange && (
						<DropdownMenu>
							<DropdownMenuTrigger asChild>
								<Button
									variant="outline"
									size="sm"
									className="text-xs font-mono"
								>
									{issue.status === "resolved"
										? "已解决"
										: issue.status === "false_positive"
											? "误报"
											: "待处理"}
									<ChevronDown className="w-3 h-3 ml-1" />
								</Button>
							</DropdownMenuTrigger>
							<DropdownMenuContent align="end">
								<DropdownMenuItem
									onClick={() => onStatusChange(issue, "resolved")}
								>
									已解决
								</DropdownMenuItem>
								<DropdownMenuItem
									onClick={() => onStatusChange(issue, "false_positive")}
								>
									误报
								</DropdownMenuItem>
								<DropdownMenuItem onClick={() => onStatusChange(issue, "open")}>
									恢复
								</DropdownMenuItem>
							</DropdownMenuContent>
						</DropdownMenu>
					)}
					<Badge
						className={`${getSeverityClasses(issue.severity)} font-bold uppercase px-2 py-1 rounded text-xs`}
					>
						{issue.severity === "critical"
							? "严重"
							: issue.severity === "high"
								? "高"
								: issue.severity === "medium"
									? "中等"
									: "低"}
					</Badge>
				</div>
			</div>

			{issue.description && (
				<div className="bg-muted border border-border p-3 mb-3 rounded font-mono">
					<div className="flex items-center mb-1 border-b border-border pb-1">
						<Info className="w-3 h-3 text-muted-foreground mr-1" />
						<span className="font-bold text-muted-foreground text-xs uppercase">
							问题详情
						</span>
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
							<span className="text-emerald-600 dark:text-emerald-400 text-xs font-bold font-mono uppercase">
								CODE_SNIPPET
							</span>
						</div>
						{issue.line_number && (
							<span className="text-muted-foreground text-xs font-mono">
								LINE: {issue.line_number}
							</span>
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
							<span className="font-bold text-sky-700 dark:text-sky-300 text-sm uppercase">
								修复建议
							</span>
						</div>
						<p className="text-sky-800 dark:text-sky-200/80 text-xs leading-relaxed font-mono">
							{issue.suggestion}
						</p>
					</div>
				)}

				{issue.ai_explanation &&
					(() => {
						const parsedExplanation = parseAIExplanation(issue.ai_explanation);

						if (parsedExplanation) {
							return (
								<div className="bg-violet-500/10 border border-violet-500/30 p-3 rounded">
									<div className="flex items-center mb-2 border-b border-violet-500/20 pb-1">
										<div className="w-5 h-5 bg-violet-500/20 border border-violet-500/40 rounded flex items-center justify-center mr-2">
											<Zap className="w-3 h-3 text-violet-600 dark:text-violet-400" />
										</div>
										<span className="font-bold text-violet-700 dark:text-violet-300 text-sm uppercase">
											AI 解释
										</span>
									</div>

									<div className="space-y-2 text-xs font-mono">
										{parsedExplanation.what && (
											<div className="border-l-2 border-rose-500 pl-2">
												<span className="font-bold text-rose-600 dark:text-rose-400 uppercase">
													问题：
												</span>
												<span className="text-foreground ml-1">
													{parsedExplanation.what}
												</span>
											</div>
										)}

										{parsedExplanation.why && (
											<div className="border-l-2 border-amber-500 pl-2">
												<span className="font-bold text-amber-600 dark:text-amber-400 uppercase">
													原因：
												</span>
												<span className="text-foreground ml-1">
													{parsedExplanation.why}
												</span>
											</div>
										)}

										{parsedExplanation.how && (
											<div className="border-l-2 border-emerald-500 pl-2">
												<span className="font-bold text-emerald-600 dark:text-emerald-400 uppercase">
													方案：
												</span>
												<span className="text-foreground ml-1">
													{parsedExplanation.how}
												</span>
											</div>
										)}

										{parsedExplanation.learn_more && (
											<div className="border-l-2 border-sky-500 pl-2">
												<span className="font-bold text-sky-600 dark:text-sky-400 uppercase">
													链接：
												</span>
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
										<span className="font-bold text-violet-700 dark:text-violet-300 text-sm uppercase">
											AI 解释
										</span>
									</div>
									<p className="text-foreground text-xs leading-relaxed font-mono">
										{issue.ai_explanation}
									</p>
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
				<h3 className="text-xl font-bold text-emerald-700 dark:text-emerald-300 mb-2 uppercase">
					代码质量优秀！
				</h3>
				<p className="text-emerald-600 dark:text-emerald-400/80 mb-4 font-mono">
					恭喜！没有发现任何问题
				</p>
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
				<TabsTrigger
					value="all"
					className="data-[state=active]:bg-primary data-[state=active]:text-foreground font-mono font-bold uppercase py-2 text-muted-foreground transition-all rounded-sm text-xs"
				>
					全部 ({issues.length})
				</TabsTrigger>
				<TabsTrigger
					value="critical"
					className="data-[state=active]:bg-rose-500 data-[state=active]:text-foreground font-mono font-bold uppercase py-2 text-muted-foreground transition-all rounded-sm text-xs"
				>
					严重 ({criticalIssues.length})
				</TabsTrigger>
				<TabsTrigger
					value="high"
					className="data-[state=active]:bg-orange-500 data-[state=active]:text-foreground font-mono font-bold uppercase py-2 text-muted-foreground transition-all rounded-sm text-xs"
				>
					高 ({highIssues.length})
				</TabsTrigger>
				<TabsTrigger
					value="medium"
					className="data-[state=active]:bg-amber-500 data-[state=active]:text-background font-mono font-bold uppercase py-2 text-muted-foreground transition-all rounded-sm text-xs"
				>
					中等 ({mediumIssues.length})
				</TabsTrigger>
				<TabsTrigger
					value="low"
					className="data-[state=active]:bg-sky-500 data-[state=active]:text-foreground font-mono font-bold uppercase py-2 text-muted-foreground transition-all rounded-sm text-xs"
				>
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
						<h3 className="text-lg font-bold text-foreground uppercase mb-2">
							没有发现严重问题
						</h3>
						<p className="text-muted-foreground font-mono">
							代码在严重级别的检查中表现良好
						</p>
					</div>
				)}
			</TabsContent>

			<TabsContent value="high" className="space-y-4 mt-6">
				{highIssues.length > 0 ? (
					highIssues.map((issue, index) => renderIssue(issue, index))
				) : (
					<div className="cyber-card p-12 text-center border-dashed">
						<CheckCircle className="w-16 h-16 text-emerald-400 mx-auto mb-4" />
						<h3 className="text-lg font-bold text-foreground uppercase mb-2">
							没有发现高优先级问题
						</h3>
						<p className="text-muted-foreground font-mono">
							代码在高优先级检查中表现良好
						</p>
					</div>
				)}
			</TabsContent>

			<TabsContent value="medium" className="space-y-4 mt-6">
				{mediumIssues.length > 0 ? (
					mediumIssues.map((issue, index) => renderIssue(issue, index))
				) : (
					<div className="cyber-card p-12 text-center border-dashed">
						<CheckCircle className="w-16 h-16 text-emerald-400 mx-auto mb-4" />
						<h3 className="text-lg font-bold text-foreground uppercase mb-2">
							没有发现中等优先级问题
						</h3>
						<p className="text-muted-foreground font-mono">
							代码在中等优先级检查中表现良好
						</p>
					</div>
				)}
			</TabsContent>

			<TabsContent value="low" className="space-y-4 mt-6">
				{lowIssues.length > 0 ? (
					lowIssues.map((issue, index) => renderIssue(issue, index))
				) : (
					<div className="cyber-card p-12 text-center border-dashed">
						<CheckCircle className="w-16 h-16 text-emerald-400 mx-auto mb-4" />
						<h3 className="text-lg font-bold text-foreground uppercase mb-2">
							没有发现低优先级问题
						</h3>
						<p className="text-muted-foreground font-mono">
							代码在低优先级检查中表现良好
						</p>
					</div>
				)}
			</TabsContent>
		</Tabs>
	);
}
