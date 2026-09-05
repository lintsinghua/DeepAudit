import { apiClient } from "./serverClient";

export interface Page<T> {
	items: T[];
	total: number;
}
export interface PageOptions {
	skip?: number;
	limit?: number;
	status?: string;
	search?: string;
	severity?: string;
}

export async function fetchPage<T>(
	url: string,
	params: Record<string, unknown> = {},
): Promise<Page<T>> {
	const response = await apiClient.get<T[]>(url, { params });
	return {
		items: response.data,
		total: Number(response.headers?.["x-total-count"] ?? response.data.length),
	};
}

/** Explicitly used by exports and legacy aggregate views that require every row. */
export async function fetchAllPages<T>(
	url: string,
	params: Record<string, unknown> = {},
): Promise<T[]> {
	const items: T[] = [];
	const limit = 100;
	for (let skip = 0; ; skip += limit) {
		const page = await fetchPage<T>(url, { ...params, skip, limit });
		items.push(...page.items);
		if (page.items.length < limit) return items;
	}
}
