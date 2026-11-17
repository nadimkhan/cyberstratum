import { describe, expect, it } from "vitest";
import { __testing } from "./api";

const { normaliseNotices } = __testing;

describe("normaliseNotices", () => {
  it("reads a component with its mechanical facts", () => {
    const notices = normaliseNotices({
      version: "1",
      description: "who this is built on",
      components: [
        {
          name: "Slither",
          version: "0.11.6",
          spdx_id: "AGPL-3.0",
          license_url: "https://example.invalid/agpl",
          upstream_url: "https://example.invalid/slither",
          role: "Source-level static analysis",
          imported: false,
          modified: false,
          conveyed_to_customers: false,
          usage: "Run as an external executable.",
          note: "",
        },
      ],
      datasets: [],
    });

    expect(notices.components).toHaveLength(1);
    expect(notices.components[0].name).toBe("Slither");
    expect(notices.components[0].spdxId).toBe("AGPL-3.0");
    expect(notices.components[0].imported).toBe(false);
    expect(notices.components[0].modified).toBe(false);
    expect(notices.components[0].conveyedToCustomers).toBe(false);
  });

  it("reads a dataset and its terms", () => {
    const notices = normaliseNotices({
      version: "1",
      components: [],
      datasets: [
        {
          dataset: "SWC Registry",
          spdx_id: "MIT",
          license_url: "https://example.invalid/mit",
          upstream_url: "https://example.invalid/swc",
          upstream_revision: null,
          redistribution: "permitted with the notice retained",
          derived_artifacts_may_be_redistributed: false,
          per_repository_audit_required: false,
          note: "The weakness taxonomy.",
        },
      ],
    });

    expect(notices.datasets).toHaveLength(1);
    expect(notices.datasets[0].dataset).toBe("SWC Registry");
    expect(notices.datasets[0].derivedArtifactsMayBeRedistributed).toBe(false);
    expect(notices.datasets[0].perRepositoryAuditRequired).toBe(false);
  });

  it("leaves out a component it cannot describe well enough", () => {
    const notices = normaliseNotices({
      components: [{ name: "Something", version: "1" }],
      datasets: [{ dataset: "No licence" }],
    });

    expect(notices.components).toHaveLength(0);
    expect(notices.datasets).toHaveLength(0);
  });
});
