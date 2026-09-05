import { Button } from "@/components/ui/button";

export function Pagination({
	page,
	pageSize,
	total,
	onChange,
	disabled = false,
}: {
	page: number;
	pageSize: number;
	total: number;
	onChange: (page: number) => void;
	disabled?: boolean;
}) {
	const pages = Math.max(1, Math.ceil(total / pageSize));
	return (
		<nav aria-label="分页" className="flex items-center justify-end gap-3 py-4">
			<span className="text-sm text-muted-foreground">
				共 {total} 条 · 第 {page + 1} / {pages} 页
			</span>
			<Button
				variant="outline"
				disabled={disabled || page === 0}
				onClick={() => onChange(page - 1)}
			>
				上一页
			</Button>
			<Button
				variant="outline"
				disabled={disabled || page + 1 >= pages}
				onClick={() => onChange(page + 1)}
			>
				下一页
			</Button>
		</nav>
	);
}
