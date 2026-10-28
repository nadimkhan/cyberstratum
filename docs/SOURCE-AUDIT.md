# Source Audit — running Slither without touching its licence

This is the "Audit" half of the merged platform. The "Analysis" half is
CyberStratum's own fork-aware bytecode engine, which reads deployed bytecode
and needs no source at all.

The two halves are complementary:

| | Bytecode engine | Source engine |
|---|---|---|
| Needs source | no | yes |
| Works on unverified contracts | yes | no |
| Sees the deployed code | yes | no |
| Sees intent, names, and comments | no | yes |
| Licence | ours (MIT/BSD) | Slither, AGPL-3.0 |

Neither is a superset of the other. A contract whose verified source says
one thing and whose deployed bytecode does another is itself worth flagging,
which is why the product keeps both paths rather than choosing.

---

## The licence boundary

Slither and crytic-compile are AGPL-3.0. The commercial product is a
multi-tenant SaaS, so the boundary is load-bearing rather than academic.

The rule, from [ADR-0013](adr/0013-licensing-fastapi-mit-and-slither-agpl.md):

> Slither is run as an unmodified, out-of-process executable. CyberStratum's
> own source never imports, vendors or patches it. The two exchange
> structured JSON across the process boundary.

What that looks like in practice:

```
CyberStratum                          Slither
-----------                          -------
write source to a temp file    ──────▶ read it
                                     compile with solc
                                     run its detectors
read the JSON findings        ◀──────  print JSON to stdout
```

`apps/api/app/services/slither.py` is the whole of the integration: locate
an executable, write the source, run it, read the JSON. Nothing else in the
repository knows what Slither is.

`tests/unit/test_agpl_boundary.py` enforces it mechanically. It fails the
build if any shipped file imports `slither`, `crytic_compile` or `crytic`, if
a vendored copy appears, or if a file mentions Slither without either
running it as a subprocess or citing ADR-0013.

**Slither is not a dependency of CyberStratum's virtual environment.** It is
an external tool, installed separately, like `solc` or `postgres`. That is
the point: a dependency would pull AGPL code into the process.

### What this does not settle

Running AGPL software as a separate process is the strongest position
available without a legal opinion, but it is not a legal opinion. Slither's
AGPL network clause is about *offering* the software to users over a
network. A commercial hosted product that runs Slither server-side needs
review by a lawyer who can advise on whether the offering constitutes
distribution, and what the obligations are. Get that reviewed before
charging anyone money.

---

## How the two engines run together

The source engine is not a separate product. It is a stage inside the same
scan, and both engines write into the same findings table.

```
scan
 ├── 1. fetch the deployed runtime          (RPC, then Sourcify)
 ├── 2. bytecode engine
 │      disassembly, CFG, features, rules   -> findings with source = "rule"
 └── 3. source engine
        fetch the verified source            (Blockscout instance, then Sourcify)
        run Slither out of process           -> findings with source = "slither"
```

A finding carries the engine that produced it in `findings.source`:

| `source` | Produced by | Can see |
|---|---|---|
| `rule` | CyberStratum's own bytecode rules | the deployed runtime |
| `slither` | the external Slither executable | the verified source |
| `ml` | the machine-learning baseline | the bytecode features |

The scan records the source engine's outcome explicitly:

| Field | Meaning |
|---|---|
| `Scan.source_audited` | the source engine ran and produced findings |
| `Scan.source_audit_skipped` | why it did not run |

### Skip reasons

| Reason | Meaning |
|---|---|
| `no_source` | the contract has no verified source anywhere |
| `slither_not_installed` | the executable could not be found |
| `solc_not_installed` | no solc binary for the contract's compiler |
| `compilation_failed` | the source did not compile |
| `slither_failed` | Slither ran and failed |
| `slither_timeout` | Slither ran out of time |
| `malformed_output` | Slither's output could not be read |
| `source_fetch_failed` | the source could not be fetched |

**None of these fail the scan.** The bytecode findings are kept exactly as
they were. A contract without verified source is the normal case on most
chains, and the platform must still analyse it.

### The source is an artifact

When the source is fetched it is stored as a scan artifact
(`kind = "source"`), whether or not the audit could run. The source is what
makes the scan reproducible, so it is worth keeping even when Slither is
not installed.

### Configuring the tool

Two settings, both optional:

| Setting | Meaning |
|---|---|
| `SLITHER_BIN` | the path to the Slither executable. Empty means it is looked up on `PATH`. |
| `SOLC_ARTIFACTS_DIR` | where the solc binaries live. Defaults to `~/.solc-select/artifacts`. |

The scan pipeline reads them from the application's settings, so putting
them in `.env` is enough.

### Verifying it end to end

```
node scripts/py.mjs --cwd . -m scripts.live_check_merged_engine
```

This runs the whole pipeline over a real, verified contract and prints what
each engine found:

```
=== scan ===
  status             : partial
  findings           : 20
  source audited     : True
  source skipped     : None
=== findings by engine ===
  rule: 2
    baseline.delegatecall [high]
    baseline.unresolved_jumps [info]
  slither: 18
    slither.low_level_calls [low]
    slither.shadowing_local [low]
    ...
```

`partial` there is the bytecode engine's usual verdict, not a source
problem: it means some jump destinations could not be resolved
conservatively, which is the honest answer for a dynamic dispatch table.

---

## Installing the tool

Slither and the solc binaries are external prerequisites, like PostgreSQL.

```bash
# In its own environment. NOT CyberStratum's .venv.
python -m venv E:/tools/slither
E:/tools/slither/Scripts/pip install slither-analyzer

# The solc binaries, one per compiler version you care about.
solc-select install 0.8.26
```

Then point CyberStratum at it:

```bash
# .env
SLITHER_BIN=E:/tools/slither/Scripts/slither.exe
SOLC_ARTIFACTS_DIR=C:/Users/<you>/.solc-select/artifacts
```

`SLITHER_BIN` is optional — without it, the runner looks for `slither` on
`PATH`. `SOLC_ARTIFACTS_DIR` defaults to `~/.solc-select/artifacts`, which
is where `solc-select` puts them.

Both are optional. Without them the product still works: the bytecode
engine is the licence-clean primary path, and source audits are reported as
skipped rather than failed.

---

## The detector map

Slither's detectors are mapped onto CyberStratum's shared risk-vector
vocabulary, so a source finding and a bytecode finding of the same class
compare equal:

| Slither detector | Risk vector |
|---|---|
| `reentrancy-eth`, `reentrancy-benign`, `reentrancy-events`, `reentrancy-balance` | `reentrancy` |
| `tx-origin` | `tx_origin_auth` |
| `suicidal` | `selfdestruct` |
| `unchecked-lowlevel`, `low-level-calls`, `unused-return` | `unchecked_call` |
| `shadowing-state`, `controlled-delegatecall`, `reused-constructor` | `proxy_governance_risk` |
| `weak-prng`, `timestamp`, `ecrecover` | `signature_replay` |
| `costly-loop`, `calls-loop`, `locked-ether` | `dos` |
| `incorrect-equality`, `divide-before-multiply` | `integer_overflow` |
| `uninitialized-state`, `uninitialized-storage` | `uninitialized_storage` |
| `assembly`, `dead-code`, `constant` | `formal_verification_gaps` |

The map covers **all 122 detectors** in Slither 0.11.6. The legacy names
(`unchecked-lowlevel` before it became `low-level-calls`) are kept, so an
older Slither still maps correctly. A detector with no entry falls back to
its own name, which keeps the finding but means it will not match the
bytecode vocabulary.

`tests/unit/test_slither.py` asserts the coverage against the real detector
list, so a Slither upgrade that adds detectors fails the build rather than
silently producing unmatched findings.

### The category, not the vector

The `category` column in the unified findings table uses the bytecode
engine's vocabulary from the design document, because that is what the
frontend groups by. The source engine's vector is kept in the evidence, so
nothing is lost:

| Source vector | Stored category |
|---|---|
| `reentrancy` | `reentrancy_candidate` |
| `selfdestruct` | `selfdestruct_usage` |
| `tx_origin_auth` | `tx_origin_dependency` |
| `delegatecall` | `delegatecall_usage` |
| anything else | the vector's own name |

Source-only classes — `unchecked_call`, `dos`, `accesscontrol` — keep their
own name, because there is no bytecode counterpart to hide behind and
inventing one would be a lie.

---

## Failure modes, and what each one means

A missing tool is not a failure of the contract. Every one of these is
reported as a *skip* with a reason, and the caller carries on:

| Skip | Meaning |
|---|---|
| `no_source` | The contract is not verified, so there is no source to audit. Expected for most discovered contracts. |
| `source_too_short` | The source is under 50 characters. Not worth a run. |
| `slither_not_installed` | The executable was not found. The source path is simply unavailable. |
| `solc_not_found` | No solc binary for the contract's compiler version. |
| `compilation_failed` | The source does not compile. Worth telling apart from silence — it is a defect in the contract. |
| `timeout` | The run exceeded its budget. |
| `no_output` | Slither ran and said nothing. |
| `engine_error` | Slither produced a valid JSON envelope whose `error` field was set, so the run did not complete. |

`compilation_failed` is separated from `no_output` on purpose. "The contract
does not compile" and "the contract is clean" are very different statements,
and collapsing them into one would hide a real defect.

### The envelope is checked before the findings

Slither's JSON output is always an envelope:

```json
{"success": <error is None>, "error": <message or null>, "results": {...}}
```

`success` is literally `error is None` in Slither's own output writer. A run
that fails part-way through still emits a well-formed envelope, with a
`results` object and **no detectors in it**.

So the finding list alone cannot tell you whether the audit happened. The
integration reads the envelope first:

- `error` set → the run produced **no verdict**. It is recorded as
  `skipped="engine_error"`, not as a clean contract.
- `error` null → the verdict is real. An empty detector list then genuinely
  means "clean".

This matters because a failed audit reported as a clean contract is worse than
no audit at all: it is a false negative that looks like a positive result. It
is the same failure mode Mythril has, and the rule is now enforced for every
engine the platform runs.

---

## Checking it against the real tool

```bash
node scripts/py.mjs scripts/live_check_source_audit.py
```

This runs the actual Slither binary against a deliberately vulnerable vault
and a deliberately clean counter, and reports what came back. It also
compares the detector map against `slither --list-detectors` and reports
anything unmapped.

Current result, against Slither 0.11.6:

```
detectors mapped  : 122
uncovered         : 0

--- VulnerableVault ---
  findings: 2
    slither.tx_origin       medium  tx_origin_dependency  conf=0.6
    slither.low_level_calls low     unchecked_call        conf=0.9

--- CleanCounter ---
  findings: 0
```

---

## What is not built yet

- The source audit is not yet wired into the scan pipeline. It is a
  service with tests, not a stage of a running scan.
- The proxy-template allowlist is still the helper function Watchdog used.
  The schema reconciliation replaces it with an auditable table.
- A source/bytecode divergence check is not built. It needs both analyses
  of the same contract to be runnable and comparable, which the unified
  findings table makes possible but does not yet do.
