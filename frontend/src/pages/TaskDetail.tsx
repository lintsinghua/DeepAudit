import { Pagination } from "@/components/common/Pagination";
import { IssuesList } from "./task-detail/IssuesList";
/**
 * Task Detail Page
 * Cyberpunk Terminal Aesthetic
 */

import ExportReportDialog from "@/components/reports/ExportReportDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { api } from "@/shared/config/database";
import type { AuditIssue, AuditTask } from "@/shared/types";
import {
	getRepositoryPlatformLabel,
	getSourceTypeLabel,
	isRepositoryProject,
} from "@/shared/utils/projectUtils";
import { calculateTaskProgress } from "@/shared/utils/utils";
import {
	Activity,
	AlertTriangle,
	ArrowLeft,
	Bug,
	Calendar,
	CheckCircle,
	ChevronDown,
	ChevronRight,
	Clock,
	Download,
	FileText,
	GitBranch,
	Shield,
	TrendingUp,
	XCircle,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";

export default function TaskDetail() {
	const { id } = useParams<{ id: string }>();
	const [task, setTask] = useState<AuditTask | null>(null);
	const [issues, setIssues] = useState<AuditIssue[]>([]);
	const [issuePage, setIssuePage] = useState(0);
	const [issueTotal, setIssueTotal] = useState(0);
	const [reportIssues, setReportIssues] = useState<AuditIssue[]>([]);
	const pageSize = 50;
	const requestVersion = useRef(0);
	useEffect(() => {
		setIssuePage(0);
	}, [id]);

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
		return () => {
			requestVersion.current += 1;
		};
	}, [id, issuePage]);

	// Silent progress update for running tasks
	useEffect(() => {
		if (!task || !id) {
			return;
		}

		if (task.status === "running" || task.status === "pending") {
			let disposed = false;
			const intervalId = setInterval(async () => {
				try {
					const [taskData, issuesData] = await Promise.all([
						api.getAuditTaskById(id),
						api.getAuditIssuePage(id, {
							skip: issuePage * pageSize,
							limit: pageSize,
						}),
					]);

					if (disposed) return;
					if (!taskData) {
						console.error("任务数据获取失败");
						return;
					}

					const currentProgress = taskData.scanned_files || 0;
					if (currentProgress !== lastProgress) {
						setLastProgress(currentProgress);
						setLastProgressTime(Date.now());
					} else if (
						taskData.status === "running" &&
						Date.now() - lastProgressTime > ZOMBIE_TIMEOUT
					) {
						toast.warning("任务可能已停止响应，建议取消后重试", {
							id: "zombie-warning",
							duration: 10000,
						});
					}

					if (
						taskData.status !== task.status ||
						taskData.scanned_files !== task.scanned_files ||
						taskData.issues_count !== task.issues_count
					) {
						setTask(taskData);
						setIssues(issuesData.items);
						setIssueTotal(issuesData.total);

						if (
							["completed", "failed", "cancelled"].includes(taskData.status)
						) {
							clearInterval(intervalId);
						}
					}
				} catch (error) {
					console.error("静默更新任务失败:", error);
					toast.error("获取任务状态失败，请检查网络连接", {
						id: "network-error",
						duration: 5000,
					});
				}
			}, 3000);

			return () => {
				disposed = true;
				clearInterval(intervalId);
			};
		}
	}, [
		task?.status,
		task?.scanned_files,
		id,
		issuePage,
		lastProgress,
		lastProgressTime,
	]);

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
			console.error("取消任务失败:", error);
			toast.error(error?.response?.data?.detail || "取消任务失败");
		} finally {
			setCancelling(false);
		}
	};

	const loadTaskDetail = async () => {
		if (!id) return;
		const version = ++requestVersion.current;

		try {
			setLoading(true);
			const [taskData, issuesData] = await Promise.all([
				api.getAuditTaskById(id),
				api.getAuditIssuePage(id, {
					skip: issuePage * pageSize,
					limit: pageSize,
				}),
			]);

			if (version !== requestVersion.current) return;
			setTask(taskData);
			setIssues(issuesData.items);
			setIssueTotal(issuesData.total);
		} catch (error) {
			console.error("Failed to load task detail:", error);
			toast.error("加载任务详情失败");
		} finally {
			if (version === requestVersion.current) setLoading(false);
		}
	};

	const handleIssueStatusChange = async (
		issue: AuditIssue,
		newStatus: string,
	) => {
		if (!id) return;
		try {
			await api.updateAuditIssue(id, issue.id, { status: newStatus } as any);
			toast.success("状态已更新");
			const issuesData = await api.getAuditIssuePage(id, {
				skip: issuePage * pageSize,
				limit: pageSize,
			});
			setIssues(issuesData.items);
			setIssueTotal(issuesData.total);
		} catch (error) {
			console.error("Failed to update issue status:", error);
			toast.error("状态更新失败");
		}
	};

	const getStatusBadge = (status: string) => {
		switch (status) {
			case "completed":
				return <Badge className="cyber-badge-success">完成</Badge>;
			case "running":
				return <Badge className="cyber-badge-info">运行中</Badge>;
			case "failed":
				return <Badge className="cyber-badge-danger">失败</Badge>;
			case "cancelled":
				return <Badge className="cyber-badge-muted">已取消</Badge>;
			default:
				return <Badge className="cyber-badge-muted">等待中</Badge>;
		}
	};

	const getStatusIcon = (status: string) => {
		switch (status) {
			case "completed":
				return <CheckCircle className="w-4 h-4 text-emerald-400" />;
			case "running":
				return <Activity className="w-4 h-4 text-sky-400" />;
			case "failed":
				return <AlertTriangle className="w-4 h-4 text-rose-400" />;
			case "cancelled":
				return <XCircle className="w-4 h-4 text-muted-foreground" />;
			default:
				return <Clock className="w-4 h-4 text-muted-foreground" />;
		}
	};

	const formatDate = (dateString: string) => {
		return new Date(dateString).toLocaleDateString("zh-CN", {
			year: "numeric",
			month: "short",
			day: "numeric",
			hour: "2-digit",
			minute: "2-digit",
		});
	};

	if (loading) {
		return (
			<div className="flex items-center justify-center min-h-[60vh]">
				<div className="text-center space-y-4">
					<div className="loading-spinner mx-auto" />
					<p className="text-muted-foreground font-mono text-sm uppercase tracking-wider">
						加载任务详情...
					</p>
				</div>
			</div>
		);
	}

	if (!task) {
		return (
			<div className="space-y-6 p-6 cyber-bg-elevated min-h-screen font-mono">
				<div className="flex items-center space-x-4">
					<Link to="/audit-tasks">
						<Button
							variant="outline"
							size="sm"
							className="cyber-btn-ghost h-10 w-10 p-0"
						>
							<ArrowLeft className="w-5 h-5" />
						</Button>
					</Link>
				</div>
				<div className="cyber-card p-16 text-center">
					<AlertTriangle className="w-16 h-16 text-rose-400 mx-auto mb-4" />
					<h3 className="text-xl font-bold text-foreground uppercase mb-2">
						任务不存在
					</h3>
					<p className="text-muted-foreground font-mono">
						请检查任务ID是否正确
					</p>
				</div>
			</div>
		);
	}

	const progressPercentage = calculateTaskProgress(
		task.scanned_files,
		task.total_files,
	);

	return (
		<div className="space-y-6 p-6 cyber-bg-elevated min-h-screen font-mono relative">
			{/* Grid background */}
			<div className="absolute inset-0 cyber-grid-subtle pointer-events-none" />

			{/* Top Action Bar */}
			<div className="flex items-center justify-between relative z-10">
				<Link to="/audit-tasks">
					<Button
						variant="outline"
						size="sm"
						className="cyber-btn-ghost h-10 w-10 p-0"
					>
						<ArrowLeft className="w-5 h-5" />
					</Button>
				</Link>

				<div className="flex items-center space-x-3">
					{getStatusBadge(task.status)}

					{(task.status === "running" || task.status === "pending") && (
						<Button
							size="sm"
							className="cyber-btn bg-rose-500/90 border-rose-500/50 text-foreground hover:bg-rose-500 h-10"
							onClick={handleCancelTask}
							disabled={cancelling}
						>
							<XCircle className="w-4 h-4 mr-2" />
							{cancelling ? "取消中..." : "取消任务"}
						</Button>
					)}

					{task.status === "completed" && (
						<Button
							size="sm"
							className="cyber-btn-primary h-10"
							onClick={async () => {
								try {
									setReportIssues(await api.getAuditIssues(id!));
									setExportDialogOpen(true);
								} catch {
									toast.error("报告数据加载失败");
								}
							}}
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
							<Progress
								value={progressPercentage}
								className="h-2 bg-muted [&>div]:bg-primary"
							/>
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
							<p className="stat-value text-emerald-400">
								{task.quality_score.toFixed(1)}
							</p>
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
							<p className="stat-value text-violet-400">
								{task.total_lines.toLocaleString()}
							</p>
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
							<h3 className="text-lg font-bold uppercase tracking-wider text-foreground">
								任务信息
							</h3>
						</div>
						<div className="p-6 space-y-4 font-mono">
							<div className="grid grid-cols-2 gap-4">
								<div>
									<p className="text-xs font-bold text-muted-foreground uppercase mb-1">
										任务类型
									</p>
									<p className="text-base font-bold text-foreground">
										{task.task_type === "repository"
											? "仓库审计任务"
											: "即时分析任务"}
									</p>
								</div>
								<div>
									<p className="text-xs font-bold text-muted-foreground uppercase mb-1">
										目标分支
									</p>
									<p className="text-base font-bold text-foreground flex items-center">
										<GitBranch className="w-4 h-4 mr-1" />
										{task.branch_name || "默认分支"}
									</p>
								</div>
								<div>
									<p className="text-xs font-bold text-muted-foreground uppercase mb-1">
										创建时间
									</p>
									<p className="text-base font-bold text-foreground flex items-center">
										<Calendar className="w-4 h-4 mr-1" />
										{formatDate(task.created_at)}
									</p>
								</div>
								{task.completed_at && (
									<div>
										<p className="text-xs font-bold text-muted-foreground uppercase mb-1">
											完成时间
										</p>
										<p className="text-base font-bold text-foreground flex items-center">
											<CheckCircle className="w-4 h-4 mr-1" />
											{formatDate(task.completed_at)}
										</p>
									</div>
								)}
							</div>

							{task.exclude_patterns && (
								<div>
									<p className="text-xs font-bold text-muted-foreground uppercase mb-2">
										排除模式
									</p>
									<div className="flex flex-wrap gap-2">
										{JSON.parse(task.exclude_patterns).map(
											(pattern: string) => (
												<Badge key={pattern} className="cyber-badge-muted">
													{pattern}
												</Badge>
											),
										)}
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
							<h3 className="text-lg font-bold uppercase tracking-wider text-foreground">
								项目信息
							</h3>
						</div>
						<div className="p-6 space-y-4 font-mono">
							{task.project ? (
								<>
									<div>
										<p className="text-xs font-bold text-muted-foreground uppercase mb-1">
											项目名称
										</p>
										<Link
											to={`/projects/${task.project.id}`}
											className="text-base font-bold text-primary hover:underline"
										>
											{task.project.name}
										</Link>
									</div>
									{task.project.description && (
										<div>
											<p className="text-xs font-bold text-muted-foreground uppercase mb-1">
												项目描述
											</p>
											<p className="text-sm text-foreground">
												{task.project.description}
											</p>
										</div>
									)}
									<div>
										<p className="text-xs font-bold text-muted-foreground uppercase mb-1">
											项目类型
										</p>
										<p className="text-base font-bold text-foreground">
											{getSourceTypeLabel(task.project.source_type)}
										</p>
									</div>
									{isRepositoryProject(task.project) && (
										<div>
											<p className="text-xs font-bold text-muted-foreground uppercase mb-1">
												仓库平台
											</p>
											<p className="text-base font-bold text-foreground">
												{getRepositoryPlatformLabel(
													task.project.repository_type,
												)}
											</p>
										</div>
									)}
									{task.project.programming_languages && (
										<div>
											<p className="text-xs font-bold text-muted-foreground uppercase mb-2">
												编程语言
											</p>
											<div className="flex flex-wrap gap-1">
												{JSON.parse(task.project.programming_languages).map(
													(lang: string) => (
														<Badge key={lang} className="cyber-badge-primary">
															{lang}
														</Badge>
													),
												)}
											</div>
										</div>
									)}
								</>
							) : (
								<p className="text-muted-foreground font-bold">
									项目信息不可用
								</p>
							)}
						</div>
					</div>
				</div>
			</div>

			{/* Issues List */}
			{issueTotal > 0 && (
				<div className="cyber-card p-0 relative z-10">
					<div className="cyber-card-header">
						<Bug className="w-5 h-5 text-amber-400" />
						<h3 className="text-lg font-bold uppercase tracking-wider text-foreground">
							发现的问题 ({issueTotal})
						</h3>
					</div>
					<div className="p-6">
						<IssuesList
							issues={issues}
							onStatusChange={handleIssueStatusChange}
						/>
						<Pagination
							page={issuePage}
							pageSize={pageSize}
							total={issueTotal}
							onChange={setIssuePage}
							disabled={loading}
						/>
					</div>
				</div>
			)}

			{/* Export Report Dialog */}
			{task && (
				<ExportReportDialog
					open={exportDialogOpen}
					onOpenChange={setExportDialogOpen}
					task={task}
					issues={reportIssues}
				/>
			)}
		</div>
	);
}
