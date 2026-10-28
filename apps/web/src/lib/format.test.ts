import { describe, expect, it } from "vitest";
import {
  formatBytes,
  formatChainId,
  formatConfidence,
  formatDateTime,
  formatDuration,
  formatLabels,
  formatRelativeTime,
  parseLabels,
  shortAddress,
  shortHash,
  truncate,
} from "./format";

describe("formatBytes", () => {
  it("formats zero and small sizes in bytes", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(512)).toBe("512 B");
  });

  it("scales to larger units", () => {
    expect(formatBytes(1024)).toBe("1.0 KB");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(1024 * 1024)).toBe("1.0 MB");
  });

  it("returns an em dash for missing values", () => {
    expect(formatBytes(null)).toBe("—");
    expect(formatBytes(undefined)).toBe("—");
    expect(formatBytes(-1)).toBe("—");
  });
});

describe("shortHash", () => {
  it("shortens long hashes", () => {
    const hash = `0x${"a".repeat(64)}`;
    expect(shortHash(hash)).toBe("0xaaaa…aaaa");
    expect(shortHash(hash, 14, 8)).toBe("0xaaaaaaaaaaaa…aaaaaaaa");
  });

  it("leaves short values untouched", () => {
    expect(shortHash("0x1234")).toBe("0x1234");
    expect(shortHash(null)).toBe("—");
  });
});

describe("shortAddress", () => {
  it("keeps the 0x prefix and the tail", () => {
    const address = "0x1234567890abcdef1234567890abcdef12345678";
    expect(shortAddress(address)).toBe("0x1234…5678");
  });

  it("handles missing addresses", () => {
    expect(shortAddress(undefined)).toBe("—");
  });
});

describe("formatChainId", () => {
  it("names well-known chains", () => {
    expect(formatChainId(1)).toBe("1 (mainnet)");
    expect(formatChainId(11155111)).toBe("11155111 (sepolia)");
  });

  it("falls back to the bare id", () => {
    expect(formatChainId(4242)).toBe("4242");
    expect(formatChainId(null)).toBe("—");
  });
});

describe("formatDuration", () => {
  it("formats milliseconds and seconds", () => {
    expect(formatDuration(340)).toBe("340 ms");
    expect(formatDuration(1200)).toBe("1.2 s");
    expect(formatDuration(65000)).toBe("1m 5s");
  });

  it("handles missing values", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(-5)).toBe("—");
  });
});

describe("formatConfidence", () => {
  it("renders a 0-1 value as a percentage", () => {
    expect(formatConfidence(0.72)).toBe("72%");
    expect(formatConfidence(1)).toBe("100%");
    expect(formatConfidence(0)).toBe("0%");
  });

  it("handles missing values", () => {
    expect(formatConfidence(null)).toBe("—");
  });
});

describe("formatDateTime", () => {
  it("formats an ISO timestamp", () => {
    expect(formatDateTime("2026-03-12T10:30:00Z")).toBe("12 Mar 2026, 10:30");
  });

  it("returns an em dash for invalid input", () => {
    expect(formatDateTime(null)).toBe("—");
    expect(formatDateTime("not-a-date")).toBe("—");
  });
});

describe("formatRelativeTime", () => {
  const now = new Date("2026-03-12T12:00:00Z");

  it("describes past times", () => {
    expect(formatRelativeTime("2026-03-12T11:55:00Z", now)).toBe("5 minutes ago");
  });

  it("describes future times", () => {
    expect(formatRelativeTime("2026-03-13T12:00:00Z", now)).toBe("tomorrow");
  });
});

describe("labels", () => {
  it("parses comma or newline separated labels", () => {
    expect(parseLabels("defi, vault\npending")).toEqual(["defi", "vault", "pending"]);
    expect(parseLabels("")).toEqual([]);
  });

  it("formats a label list", () => {
    expect(formatLabels(["a", "b"])).toBe("a, b");
    expect(formatLabels([])).toBe("—");
  });
});

describe("truncate", () => {
  it("truncates long strings", () => {
    expect(truncate("abcdefghij", 5)).toBe("abcd…");
    expect(truncate("abc", 5)).toBe("abc");
  });
});
