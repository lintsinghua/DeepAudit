import { describe, it, expect, beforeEach, vi } from "vitest";
import {
	buildAgentTree,
	findAgentInTree,
	findAgentName,
	generateLogId,
	resetLogIdCounter,
	getTimeString,
	createLogItem,
	cleanThinkingContent,
	truncateOutput,
	calculateSeverityCounts,
	isTaskRunning,
	isTaskComplete,
	formatTokens,
	filterLogsByAgent,
	debounce,
} from "../utils";
import type { AgentTreeNode, LogItem } from "../types";

beforeEach(() => {
	resetLogIdCounter();
});

// ============ buildAgentTree ============

describe("buildAgentTree", () => {
	it("returns empty array for null/undefined input", () => {
		expect(buildAgentTree(null as any)).toEqual([]);
		expect(buildAgentTree(undefined as any)).toEqual([]);
	});

	it("returns empty array for empty array input", () => {
		expect(buildAgentTree([])).toEqual([]);
	});

	it("builds flat tree for nodes without parents", () => {
		const nodes: AgentTreeNode[] = [
			{ agent_id: "1", agent_name: "agent-1" },
			{ agent_id: "2", agent_name: "agent-2" },
		];
		const tree = buildAgentTree(nodes);
		expect(tree).toHaveLength(2);
		expect(tree[0].agent_id).toBe("1");
		expect(tree[1].agent_id).toBe("2");
	});

	it("builds parent-child tree from flat list", () => {
		const nodes: AgentTreeNode[] = [
			{ agent_id: "parent", agent_name: "orchestrator" },
			{
				agent_id: "child1",
				agent_name: "recon",
				parent_agent_id: "parent",
			},
			{
				agent_id: "child2",
				agent_name: "analysis",
				parent_agent_id: "parent",
			},
		];
		const tree = buildAgentTree(nodes);
		expect(tree).toHaveLength(1);
		expect(tree[0].agent_id).toBe("parent");
		expect(tree[0].children).toHaveLength(2);
		expect(tree[0].children![0].agent_id).toBe("child1");
		expect(tree[0].children![1].agent_id).toBe("child2");
	});

	it("builds deeply nested tree", () => {
		const nodes: AgentTreeNode[] = [
			{ agent_id: "root", agent_name: "root" },
			{ agent_id: "mid", agent_name: "mid", parent_agent_id: "root" },
			{ agent_id: "leaf", agent_name: "leaf", parent_agent_id: "mid" },
		];
		const tree = buildAgentTree(nodes);
		expect(tree).toHaveLength(1);
		expect(tree[0].children).toHaveLength(1);
		expect(tree[0].children![0].children).toHaveLength(1);
		expect(tree[0].children![0].children![0].agent_id).toBe("leaf");
	});

	it("treats nodes with non-existent parent_agent_id as root nodes", () => {
		const nodes: AgentTreeNode[] = [
			{
				agent_id: "orphan",
				agent_name: "orphan",
				parent_agent_id: "nonexistent",
			},
		];
		const tree = buildAgentTree(nodes);
		expect(tree).toHaveLength(1);
		expect(tree[0].agent_id).toBe("orphan");
	});
});

// ============ findAgentInTree ============

describe("findAgentInTree", () => {
	const tree: AgentTreeNode[] = [
		{
			agent_id: "root",
			agent_name: "root",
			children: [
				{
					agent_id: "child",
					agent_name: "child",
					children: [
						{ agent_id: "grandchild", agent_name: "grandchild", children: [] },
					],
				},
			],
		},
	];

	it("finds a root node", () => {
		expect(findAgentInTree(tree, "root")?.agent_name).toBe("root");
	});

	it("finds a child node", () => {
		expect(findAgentInTree(tree, "child")?.agent_name).toBe("child");
	});

	it("finds a deeply nested node", () => {
		expect(findAgentInTree(tree, "grandchild")?.agent_name).toBe("grandchild");
	});

	it("returns null for non-existent id", () => {
		expect(findAgentInTree(tree, "missing")).toBeNull();
	});

	it("returns null for empty tree", () => {
		expect(findAgentInTree([], "any")).toBeNull();
	});
});

// ============ findAgentName ============

describe("findAgentName", () => {
	const tree: AgentTreeNode[] = [
		{
			agent_id: "a1",
			agent_name: "orchestrator",
			children: [
				{ agent_id: "a2", agent_name: "recon_agent", children: [] },
			],
		},
	];

	it("returns agent name when found", () => {
		expect(findAgentName(tree, "a1")).toBe("orchestrator");
		expect(findAgentName(tree, "a2")).toBe("recon_agent");
	});

	it("returns null when agent not found", () => {
		expect(findAgentName(tree, "nonexistent")).toBeNull();
	});

	it("returns null when agent has no name", () => {
		const nodes: AgentTreeNode[] = [
			{ agent_id: "no-name", children: [] },
		];
		expect(findAgentName(nodes, "no-name")).toBeNull();
	});
});

// ============ generateLogId / resetLogIdCounter ============

describe("generateLogId and resetLogIdCounter", () => {
	it("generates sequential IDs starting from log-1", () => {
		expect(generateLogId()).toBe("log-1");
		expect(generateLogId()).toBe("log-2");
		expect(generateLogId()).toBe("log-3");
	});

	it("resets counter back to 0", () => {
		generateLogId();
		generateLogId();
		resetLogIdCounter();
		expect(generateLogId()).toBe("log-1");
	});
});

// ============ getTimeString ============

describe("getTimeString", () => {
	it("returns a string in HH:MM:SS format", () => {
		const result = getTimeString();
		expect(result).toMatch(/^\d{2}:\d{2}:\d{2}$/);
	});
});

// ============ createLogItem ============

describe("createLogItem", () => {
	it("preserves the recorded time when replaying a task", () => {
		const log = createLogItem({ type: "info", title: "Completed", time: "09:12:03" });
		expect(log.time).toBe("09:12:03");
	});

	it("creates a log item with id and time", () => {
		const item = createLogItem({
			type: "info",
			title: "test log",
		});
		expect(item.id).toBe("log-1");
		expect(item.time).toMatch(/^\d{2}:\d{2}:\d{2}$/);
		expect(item.type).toBe("info");
		expect(item.title).toBe("test log");
	});

	it("preserves extra properties", () => {
		const item = createLogItem({
			type: "tool",
			title: "tool call",
			agentName: "recon",
			content: "some content",
		});
		expect(item.agentName).toBe("recon");
		expect(item.content).toBe("some content");
	});

	it("generates sequential IDs across calls", () => {
		const item1 = createLogItem({ type: "info", title: "first" });
		const item2 = createLogItem({ type: "info", title: "second" });
		expect(item1.id).toBe("log-1");
		expect(item2.id).toBe("log-2");
	});
});

// ============ cleanThinkingContent ============

describe("cleanThinkingContent", () => {
	it("returns empty string for empty input", () => {
		expect(cleanThinkingContent("")).toBe("");
	});

	it("extracts content after Thought: and before Action:", () => {
		const input = "Thought: I should analyze this file.\nAction: read_file\nAction Input: {\"path\": \"/src/app.ts\"}";
		const result = cleanThinkingContent(input);
		expect(result).toBe("I should analyze this file.");
	});

	it("removes Action: section when no Thought: prefix", () => {
		const input = "Let me check the code.\nAction: read_file\nAction Input: {\"path\": \"/src/app.ts\"}";
		const result = cleanThinkingContent(input);
		expect(result).toBe("Let me check the code.");
	});

	it("removes Action Input: residual", () => {
		const input = "Some analysis here.\nAction Input: {\"key\": \"value\"}";
		const result = cleanThinkingContent(input);
		expect(result).toBe("Some analysis here.");
	});

	it("returns empty for content shorter than 5 characters", () => {
		expect(cleanThinkingContent("abc")).toBe("");
		expect(cleanThinkingContent("four")).toBe("");
	});

	it("returns empty for content that is just 'Action'", () => {
		expect(cleanThinkingContent("Action")).toBe("");
		expect(cleanThinkingContent("Action  ")).toBe("");
	});

	it("returns content that starts with Action: (strips it entirely)", () => {
		const input = "Action: do_something\nAction Input: stuff";
		const result = cleanThinkingContent(input);
		expect(result).toBe("");
	});
});

// ============ truncateOutput ============

describe("truncateOutput", () => {
	it("returns string unchanged if within maxLength", () => {
		expect(truncateOutput("hello", 10)).toBe("hello");
	});

	it("returns string unchanged if exactly maxLength", () => {
		expect(truncateOutput("hello", 5)).toBe("hello");
	});

	it("truncates and appends truncation notice", () => {
		const result = truncateOutput("a".repeat(1001), 1000);
		expect(result).toBe("a".repeat(1000) + "\n... (truncated)");
		expect(result.length).toBe(1016); // 1000 + 16 for "\n... (truncated)"
	});

	it("uses default maxLength of 1000", () => {
		const input = "x".repeat(1001);
		const result = truncateOutput(input);
		expect(result).toContain("\n... (truncated)");
	});

	it("respects custom maxLength", () => {
		expect(truncateOutput("abcdefghij", 5)).toBe("abcde\n... (truncated)");
	});
});

// ============ calculateSeverityCounts ============

describe("calculateSeverityCounts", () => {
	it("returns all zeros for empty findings", () => {
		expect(calculateSeverityCounts([])).toEqual({
			critical: 0,
			high: 0,
			medium: 0,
			low: 0,
		});
	});

	it("counts each severity correctly", () => {
		const findings = [
			{ severity: "critical" },
			{ severity: "critical" },
			{ severity: "high" },
			{ severity: "high" },
			{ severity: "high" },
			{ severity: "medium" },
			{ severity: "low" },
			{ severity: "low" },
		];
		expect(calculateSeverityCounts(findings)).toEqual({
			critical: 2,
			high: 3,
			medium: 1,
			low: 2,
		});
	});

	it("ignores unknown severities", () => {
		const findings = [
			{ severity: "critical" },
			{ severity: "info" },
			{ severity: "warning" },
		];
		const counts = calculateSeverityCounts(findings);
		expect(counts.critical).toBe(1);
		expect(counts.high).toBe(0);
	});
});

// ============ isTaskRunning ============

describe("isTaskRunning", () => {
	it("returns true for running status", () => {
		expect(isTaskRunning("running")).toBe(true);
	});

	it("returns true for pending status", () => {
		expect(isTaskRunning("pending")).toBe(true);
	});

	it("returns false for completed status", () => {
		expect(isTaskRunning("completed")).toBe(false);
	});

	it("returns false for undefined status", () => {
		expect(isTaskRunning(undefined)).toBe(false);
	});

	it("returns false for other statuses", () => {
		expect(isTaskRunning("failed")).toBe(false);
		expect(isTaskRunning("cancelled")).toBe(false);
	});
});

// ============ isTaskComplete ============

describe("isTaskComplete", () => {
	it("returns true for completed", () => {
		expect(isTaskComplete("completed")).toBe(true);
	});

	it("returns true for failed", () => {
		expect(isTaskComplete("failed")).toBe(true);
	});

	it("returns true for cancelled", () => {
		expect(isTaskComplete("cancelled")).toBe(true);
	});

	it("returns false for running", () => {
		expect(isTaskComplete("running")).toBe(false);
	});

	it("returns false for undefined", () => {
		expect(isTaskComplete(undefined)).toBe(false);
	});
});

// ============ formatTokens ============

describe("formatTokens", () => {
	it("formats 1000 tokens as 1.0k", () => {
		expect(formatTokens(1000)).toBe("1.0k");
	});

	it("formats 1500 tokens as 1.5k", () => {
		expect(formatTokens(1500)).toBe("1.5k");
	});

	it("formats 0 tokens as 0.0k", () => {
		expect(formatTokens(0)).toBe("0.0k");
	});

	it("formats 2550 tokens as 2.5k", () => {
		expect(formatTokens(2550)).toBe("2.5k");
	});

	it("formats 12345 tokens as 12.3k", () => {
		expect(formatTokens(12345)).toBe("12.3k");
	});
});

// ============ filterLogsByAgent ============

describe("filterLogsByAgent", () => {
	const tree: AgentTreeNode[] = [
		{
			agent_id: "agent-1",
			agent_name: "recon_agent",
			children: [],
		},
		{
			agent_id: "agent-2",
			agent_name: "analysis_agent",
			children: [],
		},
	];
	const logs: LogItem[] = [
		{ id: "l1", time: "12:00:00", type: "info", title: "msg1", agentName: "recon_agent" },
		{ id: "l2", time: "12:00:01", type: "info", title: "msg2", agentName: "analysis_agent" },
		{ id: "l3", time: "12:00:02", type: "info", title: "msg3", agentName: "recon_agent" },
	];

	it("returns all logs when showAllLogs is true", () => {
		expect(filterLogsByAgent(logs, "agent-1", tree, true)).toHaveLength(3);
	});

	it("returns all logs when selectedAgentId is null", () => {
		expect(filterLogsByAgent(logs, null, tree, false)).toHaveLength(3);
	});

	it("filters logs by matching agent name", () => {
		const result = filterLogsByAgent(logs, "agent-1", tree, false);
		expect(result).toHaveLength(2);
		expect(result.every((l) => l.agentName === "recon_agent")).toBe(true);
	});

	it("filters by analysis agent", () => {
		const result = filterLogsByAgent(logs, "agent-2", tree, false);
		expect(result).toHaveLength(1);
		expect(result[0].agentName).toBe("analysis_agent");
	});

	it("returns all logs when agent name is not found in tree", () => {
		const result = filterLogsByAgent(logs, "unknown-id", tree, false);
		expect(result).toHaveLength(3);
	});

	it("matches agent name case-insensitively and by prefix", () => {
		const logsCase: LogItem[] = [
			{ id: "l1", time: "12:00:00", type: "info", title: "msg1", agentName: "Recon_Agent" },
		];
		const result = filterLogsByAgent(logsCase, "agent-1", tree, false);
		expect(result).toHaveLength(1);
	});
});

// ============ debounce ============

describe("debounce", () => {
	it("delays function execution", () => {
		vi.useFakeTimers();
		const fn = vi.fn();
		const debounced = debounce(fn, 200);

		debounced();
		expect(fn).not.toHaveBeenCalled();

		vi.advanceTimersByTime(200);
		expect(fn).toHaveBeenCalledTimes(1);

		vi.useRealTimers();
	});

	it("resets timer on subsequent calls", () => {
		vi.useFakeTimers();
		const fn = vi.fn();
		const debounced = debounce(fn, 200);

		debounced();
		vi.advanceTimersByTime(100);
		debounced();
		vi.advanceTimersByTime(100);
		expect(fn).not.toHaveBeenCalled();

		vi.advanceTimersByTime(100);
		expect(fn).toHaveBeenCalledTimes(1);

		vi.useRealTimers();
	});

	it("passes arguments to the debounced function", () => {
		vi.useFakeTimers();
		const fn = vi.fn();
		const debounced = debounce(fn, 100);

		debounced("arg1", "arg2");
		vi.advanceTimersByTime(100);

		expect(fn).toHaveBeenCalledWith("arg1", "arg2");

		vi.useRealTimers();
	});
});
