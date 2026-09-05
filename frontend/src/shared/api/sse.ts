import type { StreamEventData } from "./agentStream";

/** Preserve the entire unfinished event across arbitrary network chunk boundaries. */
export function parseSSE(buffer: string): {
	parsed: StreamEventData[];
	remaining: string;
} {
	const parsed: StreamEventData[] = [];
	const delimiter = /\r?\n\r?\n/g;
	let start = 0;
	for (
		let match = delimiter.exec(buffer);
		match;
		match = delimiter.exec(buffer)
	) {
		const block = buffer.slice(start, match.index);
		start = match.index + match[0].length;
		let type = "";
		const data: string[] = [];
		for (const line of block.split(/\r?\n/)) {
			if (line.startsWith("event:")) type = line.slice(6).trim();
			if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
		}
		if (!data.length) continue;
		try {
			const payload = JSON.parse(data.join("\n"));
			if (typeof payload !== "object" || payload === null) continue;
			const event = { type, ...payload } as StreamEventData;
			if (event.type) parsed.push(event);
		} catch {
			/* Ignore malformed complete events; preserve subsequent events. */
		}
	}
	return { parsed, remaining: buffer.slice(start) };
}
