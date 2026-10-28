"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { parseLabels } from "@/lib/format";

const EVM_FORKS = [
  "frontier",
  "homestead",
  "tangerine_whistle",
  "spurious_dragon",
  "byzantium",
  "constantinople",
  "petersburg",
  "istanbul",
  "berlin",
  "london",
  "paris",
  "shanghai",
  "cancun",
  "prague",
  "osaka",
];

const ADDRESS_PATTERN = /^0x[0-9a-fA-F]{40}$/;

export function NewScanForm() {
  const router = useRouter();
  const [contractAddress, setContractAddress] = useState("");
  const [chainId, setChainId] = useState("1");
  const [fork, setFork] = useState("prague");
  const [labels, setLabels] = useState("");
  const [bytecodeHex, setBytecodeHex] = useState("");
  const [experimentalMl, setExperimentalMl] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const trimmedAddress = contractAddress.trim();
    if (!ADDRESS_PATTERN.test(trimmedAddress)) {
      setError("Enter a valid 20-byte contract address beginning with 0x.");
      return;
    }
    const parsedChainId = Number.parseInt(chainId, 10);
    if (!Number.isFinite(parsedChainId) || parsedChainId < 1) {
      setError("Chain id must be a positive integer.");
      return;
    }

    setSubmitting(true);
    try {
      // Posted to the same-origin proxy so the API base URL is read on the
      // server at request time rather than inlined into the client bundle.
      const response = await fetch("/api/scans", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contractAddress: trimmedAddress,
          chainId: parsedChainId,
          fork,
          labels: parseLabels(labels),
          bytecodeHex: bytecodeHex.trim() || undefined,
          enableExperimentalMl: experimentalMl,
        }),
      });

      const payload = (await response.json().catch(() => null)) as
        | { id?: string; detail?: string }
        | null;

      if (!response.ok) {
        setError(payload?.detail ?? `The scan could not be queued (HTTP ${response.status}).`);
        setSubmitting(false);
        return;
      }

      if (!payload?.id) {
        setError("The backend did not return a scan id.");
        setSubmitting(false);
        return;
      }

      router.push(`/scans/${encodeURIComponent(payload.id)}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unexpected error while queueing the scan.");
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="max-w-2xl space-y-5" noValidate>
      <div className="space-y-1.5">
        <label htmlFor="contract-address" className="block text-sm font-medium text-[var(--cs-fg)]">
          Contract address
        </label>
        <input
          id="contract-address"
          name="contractAddress"
          value={contractAddress}
          onChange={(event) => setContractAddress(event.target.value)}
          required
          spellCheck={false}
          placeholder="0x0000000000000000000000000000000000000000"
          aria-describedby="contract-address-help"
          className="w-full rounded-md border border-[var(--cs-border)] bg-[var(--cs-raised)] px-3 py-2 font-mono text-sm text-[var(--cs-fg)] placeholder:text-[var(--cs-muted)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
        />
        <p id="contract-address-help" className="text-xs text-[var(--cs-muted)]">
          The deployed contract whose runtime bytecode will be analysed.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <label htmlFor="chain-id" className="block text-sm font-medium text-[var(--cs-fg)]">
            Chain id
          </label>
          <input
            id="chain-id"
            name="chainId"
            type="number"
            min={0}
            value={chainId}
            onChange={(event) => setChainId(event.target.value)}
            required
            className="w-full rounded-md border border-[var(--cs-border)] bg-[var(--cs-raised)] px-3 py-2 font-mono text-sm text-[var(--cs-fg)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
          />
        </div>

        <div className="space-y-1.5">
          <label htmlFor="fork" className="block text-sm font-medium text-[var(--cs-fg)]">
            EVM fork
          </label>
          <select
            id="fork"
            name="fork"
            value={fork}
            onChange={(event) => setFork(event.target.value)}
            className="w-full rounded-md border border-[var(--cs-border)] bg-[var(--cs-raised)] px-3 py-2 text-sm text-[var(--cs-fg)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
          >
            {EVM_FORKS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="space-y-1.5">
        <label htmlFor="labels" className="block text-sm font-medium text-[var(--cs-fg)]">
          Labels <span className="font-normal text-[var(--cs-muted)]">(optional)</span>
        </label>
        <input
          id="labels"
          name="labels"
          value={labels}
          onChange={(event) => setLabels(event.target.value)}
          placeholder="defi, vault, pending-review"
          className="w-full rounded-md border border-[var(--cs-border)] bg-[var(--cs-raised)] px-3 py-2 text-sm text-[var(--cs-fg)] placeholder:text-[var(--cs-muted)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
        />
        <p className="text-xs text-[var(--cs-muted)]">Comma separated.</p>
      </div>

      <div className="space-y-1.5">
        <label htmlFor="bytecode" className="block text-sm font-medium text-[var(--cs-fg)]">
          Bytecode hex <span className="font-normal text-[var(--cs-muted)]">(optional)</span>
        </label>
        <textarea
          id="bytecode"
          name="bytecode"
          rows={3}
          value={bytecodeHex}
          onChange={(event) => setBytecodeHex(event.target.value)}
          spellCheck={false}
          placeholder="0x60806040..."
          className="w-full rounded-md border border-[var(--cs-border)] bg-[var(--cs-raised)] px-3 py-2 font-mono text-xs text-[var(--cs-fg)] placeholder:text-[var(--cs-muted)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
        />
        <p className="text-xs text-[var(--cs-muted)]">
          Supply runtime bytecode to analyse when the contract is not available from an RPC node.
        </p>
      </div>

      <div className="flex items-start gap-2">
        <input
          id="experimental-ml"
          name="enableExperimentalMl"
          type="checkbox"
          checked={experimentalMl}
          onChange={(event) => setExperimentalMl(event.target.checked)}
          className="mt-1 h-4 w-4 accent-[var(--cs-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
        />
        <label
          htmlFor="experimental-ml"
          className="text-sm text-[var(--cs-muted)]"
        >
          Enable experimental ML inference. Model-based results are labelled experimental and may
          produce false positives or false negatives.
        </label>
      </div>

      {error ? (
        <p role="alert" className="rounded-md bg-[var(--cs-danger-soft)] px-3 py-2 text-sm text-[var(--cs-danger)]">
          {error}
        </p>
      ) : null}

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-[var(--cs-accent)] px-4 py-2 text-sm font-semibold text-[var(--cs-accent-fg)] hover:opacity-90 disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
        >
          {submitting ? "Queueing…" : "Queue scan"}
        </button>
        <p className="text-xs text-[var(--cs-muted)]">
          A queued scan returns a scan id; the pipeline runs asynchronously.
        </p>
      </div>
    </form>
  );
}