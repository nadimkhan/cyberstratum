# ADR-0011 — Static jump resolution: an abstract stack, and what it cannot do

- Status: Accepted
- Date: 2026-10-28
- Deciders: CyberStratum implementation
- Related: `packages/evm_analysis/evm_analysis/{stack,resolver,cfg}.py`,
  `scripts/crosscheck_evmole.py`, ADR-0004 (fork-accurate opcode table)

## Context

The CFG builder needs to know where each `JUMP`/`JUMPI` goes. A naive rule
("the destination is the `PUSH` right before the branch") matches a large
share of `solc` output but not all of it: the compiler frequently shuffles
the destination around the stack (`DUP`, `SWAP`) before branching, and
frequently pushes the destination in one block and consumes it several
blocks later.

A security tool must never *guess* a destination. A wrong edge produces a
wrong CFG, wrong reachability, wrong findings, and a false sense of
coverage. An unresolved jump, on the other hand, is an honest answer: the
tool reports that it could not determine the destination statically.

## Decision

Resolve jump destinations with a small abstract interpreter over the block
graph, and treat every destination it cannot prove as unresolved.

### The stack model

The interpreter tracks a **top-anchored window** of stack slots, where each
slot is either a known constant or unknown. Only the top of the stack
matters (a jump's destination is `μs[0]`), so a window is enough.

The **absolute stack depth is deliberately not tracked**. `solc` joins paths
that reach one block with different stack heights — the "calldata too short"
path and the "no selector matched" path meet at the same `JUMPDEST` — so an
absolute depth is unknowable for most blocks, and gating the analysis on it
would discard jumps that are in fact statically determinable.

A `JUMPI` consumes the destination *and* the condition. The destination is
the top of the stack (`mu_s[0]`) and the condition is the item below it
(`mu_s[1]`), so the condition is pushed *before* the destination. This
ordering is easy to get backwards, and getting it backwards would draw the
conditional edge to the condition instead of the destination. It is pinned
by a unit test and verified against real `solc` output in the cross-check.

`DUPn` and `SWAPn` use their **legacy** EVM semantics (`DUPn` peeks, `SWAPn`
peeks, neither consumes). EIP-5450 redefines them to consume their operands,
which is correct for EOF but not for the deployed legacy bytecode this
project analyses. Both upstream stack-effect sources we consulted
(`@ethereumjs/evm` and `evm-opcodes`) report the EOF behaviour, so the
generated opcode table applies an explicit legacy override for these
opcodes; see `scripts/generate_opcodes.mjs`.

### The dataflow

* The window known on entry to a block is merged, top-aligned, from every
  path that reaches it. A slot that only one path knows, or that the paths
  disagree on, becomes unknown — keeping one path's value would be a guess.
* A block that no path has reached yet is **not** the same as a block that is
  reached with an empty stack. The former means "no information"; the latter
  is a real path. Merging them is a bug that silently destroys every value
  the first arriving path carried.
* No stack state is propagated through an unresolved dynamic transfer. Doing
  so floods every `JUMPDEST` with a stack shape belonging to a single path,
  and the resulting contradictions poison the whole dataflow.
* The fixpoint is deterministic: blocks are processed in ascending offset
  order, and the target map only grows.

## Validation

`scripts/crosscheck_evmole.py` compares the analysis against `evmole`, an
independent Rust implementation, on seven well-known mainnet contracts
(USDC, WETH, DAI, Uniswap V2 Router, Uniswap V3 SwapRouter02, Aave V3 Pool,
Lido stETH).

| Contract | Instructions | Reachable blocks (ours / evmole) | Static jumps agreed | Wrong destinations |
|---|---|---|---|---|
| USDC | 807 | 89 / 89 | 57 / 64 | 0 |
| WETH | 1 555 | 102 / 102 | 63 / 74 | 0 |
| DAI | 3 488 | 198 / 198 | 124 / 142 | 0 |
| Uniswap V2 Router | 11 012 | 814 / 814 | 464 / 522 | 0 |
| Uniswap V3 SwapRouter02 | 13 164 | 1 274 / 1 274 | 858 / 954 | 0 |
| Aave V3 Pool | 982 | 126 / 126 | 83 / 96 | 0 |
| Lido stETH | 496 | 60 / 60 | 37 / 39 | 0 |

Totals: 31 504 instructions cross-checked with **0 instruction mismatches**,
**0 wrong jump destinations**, and **1 686 of 1 891** statically resolvable
jumps agreed (89.2 %).

The reachable block count matches `evmole` exactly on all seven contracts,
which is an independent check that the block splitting and the reachability
analysis agree with another implementation.

The cross-check fails the build on an instruction mismatch, a target only we
produce, or a jump we resolve to a *different* destination than `evmole`. A
jump we leave unresolved is reported as a metric, not a failure: the
analysis is conservative by design, and the disagreement is a coverage
limit rather than a defect.

### What the correction bought

Measured over the same seven contracts, comparing the implementation before
this change with the one after it:

| | before | after |
|---|---|---|
| unique resolved jump targets | 1 284 | 1 316 |
| unresolved CFG edges | 199 | 148 |

The unresolved-edge count is the number that matters for the product: every
unresolved edge is a candidate for the "control flow contains unresolved
dynamic jumps" finding, so removing 51 of them removes that many false
positives from a check that would otherwise fire on every real contract.

The correction did not reach parity with `evmole`, and it was not expected
to. The residual gap is values carried across shared utility blocks, where
several paths merge and no single merged window can prove the value. A
path-sensitive variant was tried and measured: keeping up to eight incoming
windows per block moved the agreement from 1 686 to 1 687 static jumps, so
it was not worth the complexity and was removed.

## Known limitation

Roughly one static jump in ten is left unresolved. The cause is a value that
is pushed in one block and consumed several blocks later, crossing a
*shared* utility block that is reached by many call sites with different
stack layouts. The merge at that block sees conflicting paths and correctly
gives up on the value.

Closing this needs path-sensitive analysis: one stack state per path
instead of one merged state per block. A prototype that keeps a set of
windows per block was measured against the same seven contracts and changed
the result by one jump (1 687 of 1 891), because the value is already lost
before the shared block is reached. We therefore did not adopt it.

The consequence for the product is bounded and honest: the "unresolved
dynamic jump" detector reports these jumps as unresolved, which is a
conservative over-report for roughly 10 % of the statically resolvable
jumps in a real contract. It never produces a wrong edge.

## Consequences

* The CFG is trusted: every edge we draw is one we could prove.
* Reachability, dead-code and cycle analysis inherit that trust.
* The `unresolved` resolution state is a first-class result, not an error
  case, and the API reports it separately from the findings that depend on
  it.
* A future improvement should target path-sensitive state, and should be
  measured with `scripts/crosscheck_evmole.py` before it is adopted.
