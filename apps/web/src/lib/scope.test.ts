import { describe, expect, it } from "vitest";
import { scopeExpiryProblem, scopeGrantProblem } from "./scope";

describe("scopeGrantProblem", () => {
  it("accepts a contract grant with a real address", () => {
    expect(
      scopeGrantProblem(
        "contract",
        "0x1111111111111111111111111111111111111111",
        "1",
      ),
    ).toBeNull();
  });

  it("refuses a grant of a kind the registry does not know", () => {
    const problem = scopeGrantProblem("everything", "0xabc", "1");
    expect(problem).toBeTruthy();
    expect(problem).toContain("contract");
  });

  it("refuses a grant with nothing in it", () => {
    expect(scopeGrantProblem("contract", "   ", "1")).toBeTruthy();
  });

  it("refuses a contract grant whose address is not an address", () => {
    expect(scopeGrantProblem("contract", "0x123", "1")).toBeTruthy();
    expect(
      scopeGrantProblem("contract", "1111111111111111111111111111111111111111", "1"),
    ).toBeTruthy();
  });

  it("refuses a chain grant with no chain id", () => {
    expect(scopeGrantProblem("chain", "1", "")).toBeTruthy();
    expect(scopeGrantProblem("chain", "1", "not-a-number")).toBeTruthy();
    expect(scopeGrantProblem("chain", "1", "1")).toBeNull();
  });

  it("accepts a programme grant with a name", () => {
    expect(scopeGrantProblem("programme", "Example Bug Bounty", "1")).toBeNull();
  });
});

describe("scopeExpiryProblem", () => {
  it("accepts a date it can read", () => {
    expect(scopeExpiryProblem("")).toBeNull();
    expect(scopeExpiryProblem("2027-01-01")).toBeNull();
    expect(scopeExpiryProblem("2027-01-01T00:00:00Z")).toBeNull();
  });

  it("refuses a date it cannot read", () => {
    expect(scopeExpiryProblem("whenever")).toBeTruthy();
    expect(scopeExpiryProblem("not a date")).toBeTruthy();
  });
});
