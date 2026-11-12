import { describe, expect, it } from "vitest";
import { __testing } from "./api";

const { normaliseDiscoveryCursor, normaliseDiscoveryRun } = __testing;

describe("normaliseDiscoveryCursor", () => {
  it("maps the backend cursor payload", () => {
    const cursor = normaliseDiscoveryCursor({
      chain_id: 1,
      chain_name: "Ethereum",
      last_address: "0x496d26eaff5889ed623ffc1ff003e20c26e2d270",
      contracts_seen: 400,
      next_page: 8,
      last_verified_at: "2026-11-13T02:02:06.731654+05:30",
      updated_at: "2026-11-13T02:33:20.989843+05:30",
    });

    expect(cursor.chainId).toBe(1);
    expect(cursor.chainName).toBe("Ethereum");
    expect(cursor.contractsSeen).toBe(400);
    expect(cursor.nextPage).toBe(8);
    expect(cursor.lastAddress).toBe(
      "0x496d26eaff5889ed623ffc1ff003e20c26e2d270",
    );
    expect(cursor.updatedAt).not.toBeNull();
  });

  it("says where the feed will read next", () => {
    const cursor = normaliseDiscoveryCursor({ chainId: 10, nextPage: 4 });
    expect(cursor.nextPage).toBe(4);
    expect(cursor.chainName).toBe("Unknown chain");
  });

  it("survives a payload that says nothing", () => {
    const cursor = normaliseDiscoveryCursor({});
    expect(cursor.chainId).toBe(0);
    expect(cursor.contractsSeen).toBe(0);
    expect(cursor.nextPage).toBe(1);
    expect(cursor.lastAddress).toBeNull();
  });
});

describe("normaliseDiscoveryRun", () => {
  it("maps a completed cycle", () => {
    const run = normaliseDiscoveryRun({
      id: "run-1",
      status: "completed",
      started_at: "2026-11-13T02:00:00Z",
      finished_at: "2026-11-13T02:00:31Z",
      chains_covered: 20,
      chains_failed: 0,
      contracts_found: 1570,
      contracts_new: 1485,
      contracts_updated: 0,
      errors: [],
    });

    expect(run.id).toBe("run-1");
    expect(run.status).toBe("completed");
    expect(run.chainsCovered).toBe(20);
    expect(run.chainsFailed).toBe(0);
    expect(run.contractsFound).toBe(1570);
    expect(run.contractsNew).toBe(1485);
    expect(run.errors).toEqual([]);
  });

  it("keeps the chains a partial cycle could not reach", () => {
    const run = normaliseDiscoveryRun({
      status: "partial",
      chains_covered: 18,
      chains_failed: 2,
      errors: [
        { chain_id: 100, reason: "BLOCKSCOUT_API_KEY is not set" },
        { chain_id: 137, reason: "BLOCKSCOUT_API_KEY is not set" },
      ],
    });

    expect(run.status).toBe("partial");
    expect(run.chainsFailed).toBe(2);
    expect(run.errors).toHaveLength(2);
    expect(run.errors[0].reason).toBe("BLOCKSCOUT_API_KEY is not set");
    expect(run.errors[0].chain_id).toBe(100);
  });
});
