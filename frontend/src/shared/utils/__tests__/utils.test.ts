import { describe, it, expect, vi } from "vitest";
import {
	cn,
	formatFileSize,
	formatNumber,
	isValidEmail,
	isValidPhone,
	truncateText,
	getFileExtension,
	getLanguageFromExtension,
	calculateQualityGrade,
	calculateTaskProgress,
	getTaskProgressInfo,
	generateId,
	debounce,
	throttle,
	sleep,
} from "../utils";

describe("cn", () => {
	it("merges class names", () => {
		expect(cn("foo", "bar")).toBe("foo bar");
	});

	it("handles conditional classes", () => {
		expect(cn("foo", false && "bar", "baz")).toBe("foo baz");
	});

	it("deduplicates tailwind classes", () => {
		expect(cn("px-2", "px-4")).toBe("px-4");
	});
});

describe("formatFileSize", () => {
	it("formats bytes", () => {
		expect(formatFileSize(0)).toBe("0 B");
		expect(formatFileSize(500)).toBe("500 B");
	});

	it("formats KB", () => {
		expect(formatFileSize(1024)).toBe("1 KB");
		expect(formatFileSize(1536)).toBe("1.5 KB");
	});

	it("formats MB", () => {
		expect(formatFileSize(1048576)).toBe("1 MB");
	});

	it("formats GB", () => {
		expect(formatFileSize(1073741824)).toBe("1 GB");
	});
});

describe("formatNumber", () => {
	it("formats numbers with locale", () => {
		const result = formatNumber(12345);
		expect(result).toBeTruthy();
		expect(typeof result).toBe("string");
	});
});

describe("isValidEmail", () => {
	it("accepts valid emails", () => {
		expect(isValidEmail("user@example.com")).toBe(true);
		expect(isValidEmail("a.b+c@domain.org")).toBe(true);
	});

	it("rejects invalid emails", () => {
		expect(isValidEmail("invalid")).toBe(false);
		expect(isValidEmail("missing@domain")).toBe(false);
		expect(isValidEmail("@missing-user.com")).toBe(false);
		expect(isValidEmail("")).toBe(false);
	});
});

describe("isValidPhone", () => {
	it("accepts valid Chinese mobile numbers", () => {
		expect(isValidPhone("13812345678")).toBe(true);
		expect(isValidPhone("19999999999")).toBe(true);
	});

	it("rejects invalid phone numbers", () => {
		expect(isValidPhone("12345678901")).toBe(false); // starts with 12
		expect(isValidPhone("1381234567")).toBe(false); // 10 digits
		expect(isValidPhone("138123456789")).toBe(false); // 12 digits
	});
});

describe("truncateText", () => {
	it("returns text unchanged if within limit", () => {
		expect(truncateText("hello", 10)).toBe("hello");
	});

	it("truncates and adds ellipsis", () => {
		expect(truncateText("hello world", 5)).toBe("hello...");
	});

	it("handles exact length", () => {
		expect(truncateText("hello", 5)).toBe("hello");
	});
});

describe("getFileExtension", () => {
	it("extracts extension", () => {
		expect(getFileExtension("test.py")).toBe("py");
		expect(getFileExtension("component.tsx")).toBe("tsx");
	});

	it("handles no extension", () => {
		// No dot means .pop() returns the whole string
		expect(getFileExtension("README")).toBe("readme");
	});

	it("lowercases extension", () => {
		expect(getFileExtension("file.PY")).toBe("py");
	});

	it("handles multiple dots", () => {
		expect(getFileExtension("archive.tar.gz")).toBe("gz");
	});
});

describe("getLanguageFromExtension", () => {
	it("maps known extensions", () => {
		expect(getLanguageFromExtension("py")).toBe("python");
		expect(getLanguageFromExtension("js")).toBe("javascript");
		expect(getLanguageFromExtension("ts")).toBe("typescript");
		expect(getLanguageFromExtension("go")).toBe("go");
	});

	it("returns text for unknown extensions", () => {
		expect(getLanguageFromExtension("xyz")).toBe("text");
	});
});

describe("calculateQualityGrade", () => {
	it("returns A for 90+", () => {
		expect(calculateQualityGrade(95)).toEqual(
			expect.objectContaining({ grade: "A" }),
		);
	});

	it("returns B for 80-89", () => {
		expect(calculateQualityGrade(85)).toEqual(
			expect.objectContaining({ grade: "B" }),
		);
	});

	it("returns C for 70-79", () => {
		expect(calculateQualityGrade(75)).toEqual(
			expect.objectContaining({ grade: "C" }),
		);
	});

	it("returns D for 60-69", () => {
		expect(calculateQualityGrade(65)).toEqual(
			expect.objectContaining({ grade: "D" }),
		);
	});

	it("returns F for below 60", () => {
		expect(calculateQualityGrade(30)).toEqual(
			expect.objectContaining({ grade: "F" }),
		);
	});

	it("handles boundary values", () => {
		expect(calculateQualityGrade(90).grade).toBe("A");
		expect(calculateQualityGrade(89).grade).toBe("B");
		expect(calculateQualityGrade(60).grade).toBe("D");
		expect(calculateQualityGrade(59).grade).toBe("F");
	});
});

describe("calculateTaskProgress", () => {
    it("separates completed work from successfully analyzed files", () => {
        expect(calculateTaskProgress(349, 368, "completed")).toBe(100);
        expect(calculateTaskProgress(349, 368, "failed")).toBe(95);
    });

	it("returns 0 for zero total files", () => {
		expect(calculateTaskProgress(0, 0)).toBe(0);
		expect(calculateTaskProgress(5, 0)).toBe(0);
	});

	it("calculates correct percentage", () => {
		expect(calculateTaskProgress(50, 100)).toBe(50);
		expect(calculateTaskProgress(33, 100)).toBe(33);
	});

	it("clamps to 0-100", () => {
		expect(calculateTaskProgress(150, 100)).toBe(100);
		expect(calculateTaskProgress(-5, 100)).toBe(0);
	});

	it("handles undefined values", () => {
		expect(calculateTaskProgress(undefined, undefined)).toBe(0);
		expect(calculateTaskProgress(50, undefined)).toBe(0);
	});
});

describe("getTaskProgressInfo", () => {
	it("returns complete info", () => {
		const info = getTaskProgressInfo(50, 100);
		expect(info.percentage).toBe(50);
		expect(info.scanned).toBe(50);
		expect(info.total).toBe(100);
		expect(info.isComplete).toBe(false);
		expect(info.isStarted).toBe(true);
	});

	it("detects completion", () => {
		const info = getTaskProgressInfo(100, 100);
		expect(info.isComplete).toBe(true);
	});

	it("detects not started", () => {
		const info = getTaskProgressInfo(0, 100);
		expect(info.isStarted).toBe(false);
	});
});

describe("generateId", () => {
	it("returns a non-empty string", () => {
		const id = generateId();
		expect(id).toBeTruthy();
		expect(typeof id).toBe("string");
	});

	it("generates unique ids", () => {
		const ids = new Set(Array.from({ length: 100 }, () => generateId()));
		expect(ids.size).toBe(100);
	});
});

describe("debounce", () => {
	it("debounces function calls", () => {
		vi.useFakeTimers();
		const fn = vi.fn();
		const debounced = debounce(fn, 100);

		debounced();
		debounced();
		debounced();

		expect(fn).not.toHaveBeenCalled();

		vi.advanceTimersByTime(100);
		expect(fn).toHaveBeenCalledTimes(1);

		vi.useRealTimers();
	});
});

describe("throttle", () => {
	it("throttles function calls", () => {
		vi.useFakeTimers();
		const fn = vi.fn();
		const throttled = throttle(fn, 100);

		throttled();
		throttled();
		throttled();

		expect(fn).toHaveBeenCalledTimes(1);

		vi.advanceTimersByTime(100);
		throttled();
		expect(fn).toHaveBeenCalledTimes(2);

		vi.useRealTimers();
	});
});

describe("sleep", () => {
	it("resolves after timeout", async () => {
		vi.useFakeTimers();
		const promise = sleep(100);
		vi.advanceTimersByTime(100);
		await expect(promise).resolves.toBeUndefined();
		vi.useRealTimers();
	});
});
