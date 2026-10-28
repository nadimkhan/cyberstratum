# ADR-0005: `evmole` as cross-validation oracle only

- **Status:** Accepted
- **Date:** 2026-10-28
- **Governs:** design-document §6.1, §14.1, §14.4, §21, §23.1

## Context

A fork-aware tokenizer written from scratch needs an independent check. §14.1
lists "Opcode table mapping by EVM version", "PUSH1–PUSH32 immediate parsing",
"Truncated PUSH behavior", and "Unknown/invalid opcode handling" as unit-test
requirements; §14.4 requires a versioned evaluation corpus of known benign
contracts, known vulnerable contracts, synthetic edge cases, malformed/truncated
bytecode, and proxy/implementation pairs.

Unit tests built from the same assumptions as the implementation do not
establish correctness — they only establish self-consistency. An
independently-written engine applied to real deployed bytecode does.

`evmole` 0.9.4 is a Rust implementation of the same problem (bytecode →
instruction stream) with a Python binding. It is already installed in the
project virtual environment. It is a genuinely independent implementation: a
different language, a different codebase, and a different set of assumptions
about how to handle PUSH immediates.

## Decision

`evmole` is retained **exclusively as an independent cross-validation oracle**.
It is **not** the production parser.

The production analysis path is entirely `packages/evm_analysis`
(see [ADR-0004](0004-custom-vendored-opcode-table.md)). `evmole` is invoked
only from the manual validation scripts, never from the scan pipeline:

- `scripts/crosscheck_evmole.py` — fetches deployed runtime bytecode for a set
  of well-known, publicly-verified mainnet contracts from Sourcify, then
  compares, instruction by instruction, against `evm_analysis`:

  | Check | Requirement |
  |---|---|
  | Instruction count | Must match exactly |
  | Byte offsets | Must match for every instruction |
  | Opcode names | Must match for every instruction |

  Any divergence means at least one of the two engines is wrong, and the
  disagreement is surfaced rather than reconciled.

- `scripts/validate_real_bytecode.py` — fetches the same class of real
  bytecode, disassembles it, builds the CFG, extracts features, and cross-checks
  the instruction count against `evmole` when it is available.

The scripts are **manual validation tools**, not part of the automated test
suite: they require network access to Sourcify, and a network outage must not
be able to fail the build.

The contracts used as validation fixtures are named in both scripts: USDC,
WETH, DAI, Uniswap V2 Router, Uniswap V3 SwapRouter02, SushiSwap Router,
Aave V3 Pool, and Lido stETH — all publicly verified, so the bytecode is
stable and independently checkable.

## Consequences

**Positive**

- Real-world validation against deployed contracts, not just synthetic fixtures.
- The oracle is independent of the implementation, so agreement is meaningful
  evidence and disagreement is a genuine bug report.
- Keeping `evmole` out of the production path means the scan pipeline has a
  single tokenizer whose behaviour is fully determined by the vendored opcode
  table — which is what makes §15's reproducibility requirement achievable.
- `evmole` covers modern opcodes independently, so it is a useful check on the
  table's modern-fork entries specifically.

**Negative / accepted cost**

- `evmole` is a **development and CI-audit dependency only**. It is installed
  in the virtual environment but is not a runtime dependency of the API or the
  worker.
- The cross-check is not automatic, so it can silently stop being run. It must
  be re-run on a schedule and whenever the opcode table is regenerated.
- The validation scripts depend on an external service (Sourcify) and on the
  continued availability and unchanged behaviour of those specific contracts.

**Explicitly not decided here**

- Whether `evmole` becomes a CI job on a schedule. The dependency is present
  and the scripts are written; the scheduling decision belongs to the CI
  configuration, which is not yet in place.

## Design-document sections resolved

- **§6.1** — the input model is exercised against real deployed runtime
  bytecode, not only pasted input.
- **§14.1** — the four parser unit-test requirements are met by
  `tests/unit/test_opcodes.py` and `tests/unit/test_disassembler.py`, with
  `evmole` providing the out-of-band real-world check.
- **§14.4** — the evaluation corpus requirement is served in part by the
  Sourcify-fetched real-contract fixtures used by the validation scripts.
- **§21** — question 3 is answered jointly with ADR-0004: the production
  parser is custom; `evmole` is the oracle; `pyevmasm` is rejected.
- **§23.1** — the "EVM disassembly" row names `evm_analysis` as production and
  records `evmole`'s oracle-only role.
