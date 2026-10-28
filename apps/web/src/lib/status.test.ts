import { describe, expect, it } from "vitest";
import {
  REVIEW_STATUS_META,
  SCAN_STATUS_META,
  STAGE_STATUS_META,
  toReviewStatus,
  toScanStatus,
  toStageStatus,
} from "./status";
import { REVIEW_STATUSES, SCAN_STATUSES } from "./types";

describe("toScanStatus", () => {
  it("maps the documented pipeline statuses", () => {
    expect(toScanStatus("queued")).toBe("queued");
    expect(toScanStatus("validating")).toBe("running");
    expect(toScanStatus("disassembling")).toBe("running");
    expect(toScanStatus("rules_analysis")).toBe("running");
    expect(toScanStatus("normalising_results")).toBe("running");
    expect(toScanStatus("completed")).toBe("completed");
    expect(toScanStatus("partial")).toBe("partial");
    expect(toScanStatus("failed")).toBe("failed");
    expect(toScanStatus("cancelled")).toBe("cancelled");
  });

  it("falls back to queued for unknown values", () => {
    expect(toScanStatus("mystery")).toBe("queued");
    expect(toScanStatus(null)).toBe("queued");
  });

  it("has a badge for every canonical status", () => {
    for (const status of SCAN_STATUSES) {
      expect(SCAN_STATUS_META[status].label).toBeTruthy();
      expect(SCAN_STATUS_META[status].badge).toBeTruthy();
    }
  });
});

describe("toReviewStatus", () => {
  it("maps review statuses", () => {
    expect(toReviewStatus("new")).toBe("new");
    expect(toReviewStatus("needs_review")).toBe("new");
    expect(toReviewStatus("confirmed")).toBe("confirmed");
    expect(toReviewStatus("false_positive")).toBe("false_positive");
    expect(toReviewStatus("needs_more_evidence")).toBe("needs_evidence");
  });

  it("falls back to new", () => {
    expect(toReviewStatus("???")).toBe("new");
  });

  it("has a badge for every canonical review status", () => {
    for (const status of REVIEW_STATUSES) {
      expect(REVIEW_STATUS_META[status].label).toBeTruthy();
    }
  });
});

describe("toStageStatus", () => {
  it("maps stage states", () => {
    expect(toStageStatus("completed")).toBe("completed");
    expect(toStageStatus("running")).toBe("running");
    expect(toStageStatus("failed")).toBe("failed");
    expect(toStageStatus("skipped")).toBe("skipped");
    expect(toStageStatus("pending")).toBe("pending");
  });

  it("falls back to pending", () => {
    expect(toStageStatus(undefined)).toBe("pending");
  });

  it("has a badge for every canonical stage status", () => {
    for (const status of ["pending", "running", "completed", "failed", "skipped"] as const) {
      expect(STAGE_STATUS_META[status].label).toBeTruthy();
    }
  });
});
