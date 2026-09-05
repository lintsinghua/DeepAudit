import { describe, it, expect, vi, beforeEach } from "vitest";
import type { Mock } from "vitest";

// Mock serverClient before importing agentTasks
vi.mock("../serverClient", () => ({
	apiClient: {
		get: vi.fn(),
		post: vi.fn(),
		put: vi.fn(),
		delete: vi.fn(),
		patch: vi.fn(),
	},
}));

import { apiClient } from "../serverClient";
import {
	createAgentTask,
	getAgentTasks,
	getAgentTask,
	startAgentTask,
	cancelAgentTask,
	getAgentEvents,
	getAgentFindings,
	getAgentFinding,
	updateAgentFinding,
	getAgentTaskSummary,
	getAgentTree,
	getAgentCheckpoints,
	getCheckpointDetail,
	downloadAgentReport,
} from "../agentTasks";

describe("agentTasks API", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	// ---- createAgentTask ----
	describe("createAgentTask", () => {
		it("should POST to /agent-tasks/ with task data and return the created task", async () => {
			const requestData = {
				project_id: "proj-1",
				name: "Test Audit",
				verification_level: "analysis_only" as const,
			};
			const mockResponse = {
				data: { id: "task-1", ...requestData, status: "created" },
			};
			(apiClient.post as Mock).mockResolvedValue(mockResponse);

			const result = await createAgentTask(requestData);

			expect(apiClient.post).toHaveBeenCalledWith("/agent-tasks/", requestData);
			expect(result).toEqual(mockResponse.data);
		});

		it("should propagate errors on failure", async () => {
			const error = new Error("Network error");
			(apiClient.post as Mock).mockRejectedValue(error);

			await expect(
				createAgentTask({ project_id: "proj-1" }),
			).rejects.toThrow("Network error");
		});
	});

	// ---- getAgentTasks ----
	describe("getAgentTasks", () => {
		it("should GET /agent-tasks/ with query params and return task list", async () => {
			const mockTasks = [
				{ id: "task-1", status: "completed" },
				{ id: "task-2", status: "running" },
			];
			(apiClient.get as Mock).mockResolvedValue({ data: mockTasks });

			const result = await getAgentTasks({
				project_id: "proj-1",
				status: "running",
				skip: 0,
				limit: 10,
			});

			expect(apiClient.get).toHaveBeenCalledWith("/agent-tasks/", {
				params: { project_id: "proj-1", status: "running", skip: 0, limit: 10 },
			});
			expect(result).toEqual(mockTasks);
		});

		it("should GET /agent-tasks/ without params when none provided", async () => {
			(apiClient.get as Mock).mockResolvedValue({ data: [] });

			const result = await getAgentTasks();

			expect(apiClient.get).toHaveBeenCalledWith("/agent-tasks/", { params: undefined });
			expect(result).toEqual([]);
		});
	});

	// ---- getAgentTask ----
	describe("getAgentTask", () => {
		it("should GET /agent-tasks/:taskId and return task detail", async () => {
			const mockTask = { id: "task-1", status: "completed", name: "Audit" };
			(apiClient.get as Mock).mockResolvedValue({ data: mockTask });

			const result = await getAgentTask("task-1");

			expect(apiClient.get).toHaveBeenCalledWith("/agent-tasks/task-1");
			expect(result).toEqual(mockTask);
		});

		it("should propagate errors for non-existent task", async () => {
			(apiClient.get as Mock).mockRejectedValue(new Error("Not found"));

			await expect(getAgentTask("nonexistent")).rejects.toThrow("Not found");
		});
	});

	// ---- startAgentTask ----
	describe("startAgentTask", () => {
		it("should POST to /agent-tasks/:taskId/start", async () => {
			const mockResponse = { message: "Task started", task_id: "task-1" };
			(apiClient.post as Mock).mockResolvedValue({ data: mockResponse });

			const result = await startAgentTask("task-1");

			expect(apiClient.post).toHaveBeenCalledWith("/agent-tasks/task-1/start");
			expect(result).toEqual(mockResponse);
		});
	});

	// ---- cancelAgentTask ----
	describe("cancelAgentTask", () => {
		it("should POST to /agent-tasks/:taskId/cancel", async () => {
			const mockResponse = { message: "Task cancelled", task_id: "task-1" };
			(apiClient.post as Mock).mockResolvedValue({ data: mockResponse });

			const result = await cancelAgentTask("task-1");

			expect(apiClient.post).toHaveBeenCalledWith("/agent-tasks/task-1/cancel");
			expect(result).toEqual(mockResponse);
		});
	});

	// ---- getAgentEvents ----
	describe("getAgentEvents", () => {
		it("should GET /agent-tasks/:taskId/events/list with params", async () => {
			const mockEvents = [
				{ id: "evt-1", event_type: "tool_call", sequence: 1 },
			];
			(apiClient.get as Mock).mockResolvedValue({ data: mockEvents });

			const result = await getAgentEvents("task-1", {
				after_sequence: 5,
				limit: 20,
			});

			expect(apiClient.get).toHaveBeenCalledWith(
				"/agent-tasks/task-1/events/list",
				{ params: { after_sequence: 5, limit: 20 } },
			);
			expect(result).toEqual(mockEvents);
		});

		it("should work without optional params", async () => {
			(apiClient.get as Mock).mockResolvedValue({ data: [] });

			const result = await getAgentEvents("task-1");

			expect(apiClient.get).toHaveBeenCalledWith(
				"/agent-tasks/task-1/events/list",
				{ params: undefined },
			);
			expect(result).toEqual([]);
		});
	});

	// ---- getAgentFindings ----
	describe("getAgentFindings", () => {
		it("should GET /agent-tasks/:taskId/findings with filter params", async () => {
			const mockFindings = [{ id: "f-1", severity: "critical" }];
			(apiClient.get as Mock).mockResolvedValue({ data: mockFindings });

			const result = await getAgentFindings("task-1", {
				severity: "critical",
				is_verified: true,
			});

			expect(apiClient.get).toHaveBeenCalledWith(
				"/agent-tasks/task-1/findings",
				{ params: { severity: "critical", is_verified: true, skip: 0, limit: 100 } },
			);
			expect(result).toEqual(mockFindings);
		});
	});

	// ---- getAgentFinding ----
	describe("getAgentFinding", () => {
		it("should GET /agent-tasks/:taskId/findings/:findingId", async () => {
			const mockFinding = {
				id: "f-1",
				task_id: "task-1",
				vulnerability_type: "SQLi",
			};
			(apiClient.get as Mock).mockResolvedValue({ data: mockFinding });

			const result = await getAgentFinding("task-1", "f-1");

			expect(apiClient.get).toHaveBeenCalledWith(
				"/agent-tasks/task-1/findings/f-1",
			);
			expect(result).toEqual(mockFinding);
		});
	});

	// ---- updateAgentFinding ----
	describe("updateAgentFinding", () => {
		it("should PATCH /agent-tasks/:taskId/findings/:findingId with data", async () => {
			const updatedFinding = {
				id: "f-1",
				status: "confirmed",
			};
			(apiClient.patch as Mock).mockResolvedValue({ data: updatedFinding });

			const result = await updateAgentFinding("task-1", "f-1", {
				status: "confirmed",
			});

			expect(apiClient.patch).toHaveBeenCalledWith(
				"/agent-tasks/task-1/findings/f-1",
				{ status: "confirmed" },
			);
			expect(result).toEqual(updatedFinding);
		});
	});

	// ---- getAgentTaskSummary ----
	describe("getAgentTaskSummary", () => {
		it("should GET /agent-tasks/:taskId/summary", async () => {
			const mockSummary = {
				task_id: "task-1",
				status: "completed",
				progress_percentage: 100,
				security_score: 85,
				quality_score: 90,
				statistics: {
					total_files: 100,
					indexed_files: 100,
					analyzed_files: 100,
					files_with_findings: 5,
					total_chunks: 200,
					findings_count: 10,
					verified_count: 8,
					false_positive_count: 2,
				},
				severity_distribution: { critical: 1, high: 3, medium: 4, low: 2 },
				vulnerability_types: {},
				duration_seconds: 120,
			};
			(apiClient.get as Mock).mockResolvedValue({ data: mockSummary });

			const result = await getAgentTaskSummary("task-1");

			expect(apiClient.get).toHaveBeenCalledWith("/agent-tasks/task-1/summary");
			expect(result).toEqual(mockSummary);
		});
	});

	// ---- getAgentTree ----
	describe("getAgentTree", () => {
		it("should GET /agent-tasks/:taskId/agent-tree", async () => {
			const mockTree = {
				task_id: "task-1",
				root_agent_id: "agent-root",
				total_agents: 3,
				running_agents: 0,
				completed_agents: 3,
				failed_agents: 0,
				total_findings: 5,
				nodes: [],
			};
			(apiClient.get as Mock).mockResolvedValue({ data: mockTree });

			const result = await getAgentTree("task-1");

			expect(apiClient.get).toHaveBeenCalledWith("/agent-tasks/task-1/agent-tree");
			expect(result).toEqual(mockTree);
		});
	});

	// ---- getAgentCheckpoints ----
	describe("getAgentCheckpoints", () => {
		it("should GET /agent-tasks/:taskId/checkpoints with params", async () => {
			const mockCheckpoints = [{ id: "cp-1", agent_name: "ReconAgent" }];
			(apiClient.get as Mock).mockResolvedValue({ data: mockCheckpoints });

			const result = await getAgentCheckpoints("task-1", {
				agent_id: "agent-1",
				limit: 10,
			});

			expect(apiClient.get).toHaveBeenCalledWith(
				"/agent-tasks/task-1/checkpoints",
				{ params: { agent_id: "agent-1", limit: 10 } },
			);
			expect(result).toEqual(mockCheckpoints);
		});
	});

	// ---- getCheckpointDetail ----
	describe("getCheckpointDetail", () => {
		it("should GET /agent-tasks/:taskId/checkpoints/:checkpointId", async () => {
			const mockDetail = {
				id: "cp-1",
				task_id: "task-1",
				agent_id: "agent-1",
				state_data: {},
				metadata: null,
			};
			(apiClient.get as Mock).mockResolvedValue({ data: mockDetail });

			const result = await getCheckpointDetail("task-1", "cp-1");

			expect(apiClient.get).toHaveBeenCalledWith(
				"/agent-tasks/task-1/checkpoints/cp-1",
			);
			expect(result).toEqual(mockDetail);
		});
	});

	// ---- downloadAgentReport ----
	describe("downloadAgentReport", () => {
		it("should GET /agent-tasks/:taskId/report and trigger download", async () => {
			const blob = new Blob(["report content"], { type: "text/markdown" });
			(apiClient.get as Mock).mockResolvedValue({
				data: blob,
				headers: {},
			});

			// Mock DOM APIs
			const mockLink = {
				href: "",
				setAttribute: vi.fn(),
				click: vi.fn(),
				parentNode: { removeChild: vi.fn() },
			};
			vi.spyOn(document, "createElement").mockReturnValue(mockLink as unknown as HTMLAnchorElement);
			vi.spyOn(document.body, "appendChild").mockImplementation(() => mockLink as unknown as HTMLAnchorElement);
			if (!window.URL.createObjectURL) {
				window.URL.createObjectURL = vi.fn(() => "blob:mock-url");
			} else {
				vi.spyOn(window.URL, "createObjectURL").mockReturnValue("blob:mock-url");
			}
			if (!window.URL.revokeObjectURL) {
				window.URL.revokeObjectURL = vi.fn();
			} else {
				vi.spyOn(window.URL, "revokeObjectURL").mockImplementation(vi.fn());
			}

			await downloadAgentReport("task-12345678", "markdown");

			expect(apiClient.get).toHaveBeenCalledWith("/agent-tasks/task-12345678/report", {
				params: { format: "markdown" },
				responseType: "blob",
			});
			expect(window.URL.createObjectURL).toHaveBeenCalled();
			expect(mockLink.click).toHaveBeenCalled();
			expect(window.URL.revokeObjectURL).toHaveBeenCalledWith("blob:mock-url");

			vi.restoreAllMocks();
		});

		it("should use .json extension when format is json", async () => {
			const blob = new Blob(["{}"], { type: "application/json" });
			(apiClient.get as Mock).mockResolvedValue({
				data: blob,
				headers: {},
			});

			const mockLink = {
				href: "",
				setAttribute: vi.fn(),
				click: vi.fn(),
				parentNode: { removeChild: vi.fn() },
			};
			vi.spyOn(document, "createElement").mockReturnValue(mockLink as unknown as HTMLAnchorElement);
			vi.spyOn(document.body, "appendChild").mockImplementation(() => mockLink as unknown as HTMLAnchorElement);
			vi.spyOn(window.URL, "createObjectURL").mockReturnValue("blob:mock-url");
			vi.spyOn(window.URL, "revokeObjectURL").mockImplementation(vi.fn());

			await downloadAgentReport("task-12345678", "json");

			expect(mockLink.setAttribute).toHaveBeenCalledWith(
				"download",
				"audit-report-task-123.json",
			);

			vi.restoreAllMocks();
		});
	});
});
