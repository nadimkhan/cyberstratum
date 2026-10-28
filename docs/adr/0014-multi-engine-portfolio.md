# ADR-0014 — Multi-engine portfolio for the source/bytecode analysis layer

- Status: Accepted
- Date: 2026-10-29
- Supersedes: nothing
- Related: ADR-0013 (licensing posture), ADR-0012 (merged platform)

## Context

The platform currently has two analysis paths:

1. CyberStratum's own bytecode engine (licence-clean, fork-aware, deterministic).
2. An out-of-process Slither runner for verified source.

Slither is pattern-oriented. It cannot analyse an unverified deployment, and it
cannot prove an exploit path the way a symbolic engine can. The commercial
position is multi-tenant SaaS, so every engine that is added has to clear a
licence boundary, a runtime boundary, a determinism boundary, and a resource
boundary before it is allowed near production.

A "add every tool we can find" approach is explicitly rejected: an engine that
cannot be benchmarked on the same labelled corpus as the existing engines adds
noise, cost, and false positives to every report we send to a project.

## Decision

Engines are admitted through a single external-engine contract and a staged,
benchmark-driven gate. Engines never import into the application process and
never write to the database.

### The external-engine contract

Every engine must expose:

| Field | Meaning |
| --- | --- |
| `engine_id` | Stable identifier, e.g. `slither`, `mythril` |
| `engine_version` | Version string of the tool that produced the result |
| `mode` | `source` or `bytecode` — the engine's input contract |
| `command` / `toolchain` | Exact argv and compiler used |
| `findings[]` | Normalised findings |
| `status` | `completed`, `skipped`, `failed`, `timeout` |
| `limits` | Solver timeout, execution timeout, memory ceiling, wall-clock ceiling |

Normalised findings carry: `detector_id`, `category`, `title`, `severity`,
`confidence`, `evidence` (structured, engine-native), and `limitations`.

Skips and failures are explicit outcomes, never silent. A missing tool, a
compiler that will not install, a malformed payload, or a timeout are recorded
as `skipped`/`failed` with the reason, and the scan continues with the other
engines. This is already the behaviour of the Slither runner.

### Admission gates

An engine is admitted only when it clears all of these:

1. **Licence** — permits commercial SaaS use without a network-copyleft
   obligation on the hosted service.
2. **Runtime** — installs and runs in a supported, isolated environment that is
   not the application interpreter.
3. **Determinism** — produces machine-readable output with a documented shape.
4. **Resource ceiling** — completes within a bounded time and memory budget.
5. **Incremental coverage** — measurably finds things the existing engines do
   not, on the same labelled corpus.
6. **Normalisation** — maps into the shared finding model without lossy
   hand-waving.

Gate 5 is the one that stops tool-count inflation. Popularity is not evidence.

## Measured findings

### Slither — already integrated

- Licence: AGPL-3.0 (`slither-analyzer`, `crytic-compile`).
- Version in use: 0.11.6. All 122 detectors mapped.
- Role: source-level pattern and dataflow analysis.
- Boundary: unmodified external executable, JSON over a process boundary.
  Enforced mechanically by `tests/unit/test_agpl_boundary.py`.

### Mythril — admitted as the first symbolic engine

- Licence: MIT.
- Version: 0.24.8.
- **It cannot run in the application environment.** Its `z3-solver<=4.12.5.0`
  pin has no clean Python 3.14 path. It is isolated in WSL Ubuntu at
  `~/venvs/mythril` and invoked out of process, exactly like Slither.
- Verified behaviour:
  - Source mode returns `issues[]` with `swc-id`, `title`, `severity`,
    `filename`, `lineno`, `function`, and the offending source text. The
    top-level keys are `error`, `issues`, `success` — **not** the older
    `vulnerabilities` shape.
  - Raw-runtime mode (`-c <hex> --bin-runtime`) analyses unverified deployed
    bytecode and returns the same issue shape, with `swc-id` and a
    `tx_sequence` proving the exploit path.
- Measured cost: a 40-line vulnerable fixture in source mode completes in
  about 109 seconds. Real USDC runtime bytecode in raw mode exceeded 850
  seconds without producing output. **Mythril on production-sized bytecode
  needs a hard time budget, an execution sandbox, and cancellation, or it will
  simply be too slow to be usable.** It is a deep-analysis engine triggered on
  demand, not a default scan step.
- Mythril's `swc-id` values map 1:1 onto the SWC registry, which gives us a
  clean join key against the dataset side.

#### Mythril's silent-zero-failure mode — a trap for the engine contract

Mythril does **not** fail loudly when it cannot find a compiler. It logs

```
mythril.interfaces.cli [ERROR]: Compiler not found. Make sure that solc is
installed and in PATH, or set the SOLC environment variable.
```

and still emits well-formed JSON:

```json
{"success": false, "error": "Compiler not found. ...", "issues": []}
```

The trap: the `issues` array is empty, so a consumer that reads only
`issues[]` sees **zero findings and concludes the contract is clean**. An
early fixture run in this project produced `issues: 0` and looked like
non-determinism; it was actually this failure, and the same fixture produced
a real SWC-107 finding once `SOLC` was set explicitly.

The engine contract therefore has two hard requirements, both of which apply
to every engine and not just Mythril:

1. **`success` and `error` are checked before `issues` are trusted.** A
   non-empty `error` means the run produced no verdict at all, and the result
   must be classified `skipped` with the reason, never `completed` with zero
   findings.
2. **The compiler is always passed explicitly.** Mythril resolves `solc` from
   `PATH` or the `SOLC` environment variable, which is unreliable across the
   Windows/WSL boundary. The runner resolves the exact `solc` binary from the
   verified contract's compiler version and sets it in the child's
   environment.

A "clean" result and a "did not run" result are different facts and the
platform must never confuse them.

#### Two more traps, measured on Mythril v0.24.8

Both of these were found by re-running the raw-runtime fixture with a
correctly prepared input, and both produce a **confident wrong answer**
rather than a visible error.

**Trap A: Mythril's exit code is inverted.** Mythril exits `1` when it finds
issues and `0` when it finds none:

| Run | Exit | `success` | Issues |
|---|---|---|---|
| Runtime bytecode of the reentrancy fixture | `1` | `true` | 2 (SWC-105 High, SWC-114 Medium) |
| Creation bytecode of the same contract | `0` | `true` | 0 |

A runner that treats a non-zero exit as "the engine failed" would discard
every genuine Mythril result and report the contract as never analysed. A
runner that treats exit `0` as "clean" would report the creation-bytecode
case as a clean contract. Neither exit status carries the verdict; the
**JSON envelope does**. The engine contract must therefore read `success`,
`error` and `issues` from the payload, and use the exit code only to detect
that the process died.

**Trap B: creation bytecode analysed as runtime yields a silent false
clean.** `--bin-runtime` tells Mythril the input is deployed runtime code. Hand
it creation code instead and it analyses the constructor, finds no reachable
exploit path, and returns `{"error": null, "issues": [], "success": true}`
with exit `0`. Measured on the same contract: creation code is 910 hex
characters, runtime code is 854, and the two produce opposite verdicts.

So a raw-runtime Mythril run must be given the *runtime* bytecode, and the
runner must be able to tell which it was handed. The platform already has
that machinery: the bytecode engine separates creation and runtime segments
and `evm_analysis.metadata` reports the metadata trailer, which appears only
in runtime code. A runtime whose length matches the creation segment, or a
runtime with no metadata trailer where one is expected, is a setup error, not
a clean contract.

**Mythril's console script is `myth`, not `mythril`.** The executable is
`~/venvs/mythril/bin/myth`. Pointing the runner at `bin/mythril` gives a
missing-file error, which the runner must classify as an engine error and
never as a clean result.

#### The same trap existed in our own Slither integration — and is now fixed

Slither's JSON output uses the same envelope shape:

```json
{"success": <error is None>, "error": <message or null>, "results": {...}}
```

Verified against the installed Slither 0.11.6: the envelope is written by
`slither/utils/output.py`, and `success` is literally `error is None`. A run
that fails part-way through still emits a well-formed envelope with a
`results` object and **no detectors in it**.

The integration read only `results.detectors`, so an internal Slither failure
was recorded as "the source engine ran and found nothing" — a failed audit
reported as a clean contract. This was a real defect, not a hypothetical.

The fix is in `apps/api/app/services/slither.py`:

- `parse_slither_envelope()` returns `(findings, error)` and reads `error`
  alongside `success`.
- The runner turns any non-empty `error` into `skipped="engine_error"`, so the
  scan records *no verdict* rather than a clean result.
- `parse_slither_json()` is kept as the findings-only convenience wrapper.

Regression coverage lives in `tests/unit/test_slither.py`, including an
end-to-end test that a failed engine run is a skip and a successful run with
no detectors remains a genuine clean verdict.

The same rule now applies to every engine the platform will ever run: the
envelope is checked first, and only a successful verdict with an empty finding
list means "clean".

### Echidna, Halmos, Medusa, Manticore — deferred, not rejected

These are property/fuzzing engines. They need a generated harness, a seed
corpus, a coverage-guided loop, and a per-run time budget — a different class
of integration from Slither or Mythril, and materially more expensive to
operate. Some are AGPL-licensed, which has to be resolved on the same terms as
Slither. They are a later phase, not a later version of this ADR.

### Aderyn, Wake, Solhint, Semgrep — rejected for the analysis path

Rust-based linters and Semgrep rules. Semgrep's own rule licence is
`LGPL-2.1` and it is a separate product line; Aderyn/Wake/Solhint duplicate
coverage that Slither and the bytecode rules already provide, at a cost in
runtime and in report noise. Not worth an engine slot.

## Consequences

- The platform is no longer dependent on Slither for vulnerability discovery.
  Six bytecode rules already run independently; Slither is one opinion among
  several.
- Every additional engine must ship with a benchmark result on the labelled
  corpus before it is enabled by default.
- Mythril arrives with a runtime caveat that the team must accept: WSL
  isolation, and a per-contract time budget with recorded timeouts.
- Findings carry their producing engine in `findings.source`, so a report can
  say which tool said what.

## Alternatives considered

- **Vendor everything into the app process.** Rejected: breaks the AGPL
  boundary for Slither and pins us to Mythril's Z3 pin inside our own
  interpreter.
- **Adopt every available tool.** Rejected: no shared corpus to prove
  incremental value, unbounded operational cost, higher false-positive rate in
  customer-facing reports.
- **Mythril only, drop Slither.** Rejected: Slither's 122 pattern detectors
  are complementary to symbolic execution, and Slither is already integrated,
  tested and licensed-out.
