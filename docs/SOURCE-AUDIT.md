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

`compilation_failed` is separated from `no_output` on purpose. "The contract
does not compile" and "the contract is clean" are very different statements,
and collapsing them into one would hide a real defect.

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
