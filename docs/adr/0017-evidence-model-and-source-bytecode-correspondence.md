# ADR-0017 — Evidence model: source lines require a proven correspondence chain

- Status: Accepted
- Date: 2026-10-29
- Related: ADR-0009 (Sourcify bytecode acquisition), ADR-0013 (licensing), ADR-0014 (engines)

## Context

The commercial proposition is: scan contracts we find on mainnet, and when we
find an issue, produce something specific enough to email the project — not a
generic "this contract may have reentrancy" message, but the exact file, the
exact line, the exact bytecode offset, and enough detail to reproduce.

The question "code or bytecode?" has a precise answer, and it is **both, in a
specific order of authority**. A single analysis pass cannot produce both,
because they are different kinds of evidence.

## Decision

### The two evidence types are not interchangeable

**Source-level evidence** — from verified source:
- exact file path
- exact line number
- the offending source text
- the function it sits in

**Bytecode-level evidence** — from deployed runtime:
- exact byte offset / PC in the deployed runtime
- the instruction sequence at that offset
- the CFG path that reaches it
- whether it is reachable at all

A bytecode-only finding **cannot** be given a source line. A source-only
finding **cannot** claim anything about what is actually deployed, because the
deployed contract may be a different build of the same source, or a proxy
pointing somewhere else entirely.

Assigning a source line to a bytecode finding would be a fabrication. We do
not do it.

### Evidence type is explicit on every finding

Every finding carries a typed evidence structure, and the type is one of:

| `evidence.type` | Meaning | What it can assert |
| --- | --- | --- |
| `source_line` | Verified source, analysed in place | "this file, this line, this function" |
| `bytecode_offset` | Deployed runtime, offset in the runtime | "these bytes, here" |
| `bytecode_pc` | Deployed runtime, program counter | "at this PC" |
| `cfg_edge` | Control-flow reachability | "this path reaches this block" |
| `source_bytecode_correlation` | Proven source ↔ deployed-runtime mapping | "the deployed code at offset X is the compiled form of file F line L" |

`source_bytecode_correlation` is the only type that bridges the two worlds, and
it must be *earned*.

### The correspondence chain (all five links required)

We have proven this end-to-end on live mainnet contracts. The chain:

1. **Verified source + exact compiler input** — fetched from Sourcify, which
   stores the *exact* standard-JSON input used at verification time, including
   the compiler version, the optimiser settings, the `evmVersion`, and the
   literal source text.

2. **Recompile with that exact compiler.** Not a convenient version. The
   compiler version is taken from the verification record and the matching
   `solc` binary is located locally.

3. **Byte-for-byte comparison with the deployed runtime.** This is the gate.
   If the recompiled runtime is not identical to what is on chain, the source
   does **not** describe the deployed contract and **no source line may be
   claimed**.

4. **Source map → instruction index.** The compiler emits
   `evm.deployedBytecode.sourceMap`. Its entries are indexed by *instruction
   order*, not byte offset. Empty entries inherit the previous non-empty source
   range — the compressed format requires this to be handled explicitly.
   CyberStratum's own disassembler produces the instruction index.

5. **PC/offset → file and line.** The source-map byte offset is converted to a
   line number against the exact source text that was compiled.

### Measured results

**USDC (`0xa0b8...eB48`, Ethereum), live:**

- On-chain runtime: 2186 bytes, fetched from a public RPC.
- Sourcify match id 1532018, compiler `0.4.24+commit.e67f0147`, source
  `FiatTokenProxy.sol`.
- Recompiled with local `solc-0.4.24`: **code identical** to the on-chain
  runtime once the metadata trailer is stripped — 2143 bytes, byte-for-byte.
- The **only** difference is the metadata trailer's content hash. This is
  exactly why CyberStratum separates metadata from executable code: the
  metadata hash embeds the compiler build and the source hash, so it can differ
  between two otherwise identical builds. For this compiler vintage the hash
  key is `bzzr0` (32 bytes), not `ipfs`.
- 807 instructions disassembled from the on-chain runtime, and the source map
  resolves them to source positions.

**Why metadata stripping matters.** A naive "compare the whole hex string"
check produces a false negative on real deployments and would cause us to
discard a valid correspondence. A naive "compare the code prefix" check would
be too weak. The correct comparison is: strip the metadata, compare the
executable code, and record the metadata compiler version separately as
provenance.

**A second Sourcify trap: the stored input has no `outputSelection`.**
Sourcify's `stdJsonInput` carries the verification's compiler settings but no
`outputSelection`, so solc emits **no bytecode at all**. That is
indistinguishable from a failed correspondence check — every contract comes
back empty, and a strict comparison reports "no match" for a contract that
genuinely corresponds. The correspondence service must inject the
`outputSelection` it needs (without altering any other setting, so the
recompilation still uses the verification's own compiler options) and must
distinguish "solc emitted nothing" from "solc emitted different code". The
live check is `scripts/live_check_correspondence.py`; the comparison logic is
covered by `tests/unit/test_correspondence.py`.

**Where correspondence legitimately fails.** Some deployments cannot be
reproduced exactly and must be reported as bytecode-only. We measured this on
the Uniswap V3 contracts: contracts using Solidity `immutable` variables embed
constructor-set values in the runtime, so a recompile from source alone
differs from the deployed bytes in the immutable slots (617 differing bytes on
the UniversalRouter runtime). The correct handling is to compare the
executable code with immutable slots masked, and to say so in the evidence.

### Proxies

A proxy deployment's runtime is the proxy, not the logic. The chain therefore
resolves in two hops:

1. The proxy runtime is analysed as bytecode — delegatecall targets, storage
   slot layout, admin functions, upgrade paths. These are bytecode findings
   about the proxy itself.
2. The implementation is resolved (from the verified source's storage slot, or
   from the standard proxy slot) and analysed separately.

A finding in the implementation is reported against the implementation, with
its own chain. A finding in the proxy is reported against the proxy. They are
never conflated, and a proxy finding must never carry the implementation's
source lines.

### What a report may assert

- `source_line`: "In `Vault.sol:9`, `msg.sender.call{value: amt}("")` transfers
  value to a caller-supplied address." Supported by: source provenance,
  the compiler and settings, the recompile result.
- `bytecode_offset`: "At runtime offset 0x2e6 the deployed contract executes
  `CALL`, reachable via the path …". Supported by: the disassembled runtime
  and the CFG.
- `source_bytecode_correlation`: "The deployed runtime is byte-identical to the
  recompilation of `Vault.sol` with solc 0.8.26; runtime offset 0x2e6 maps to
  `Vault.sol:9`."

And explicitly **not**: "In `Vault.sol:9` the deployed contract is
vulnerable", when the only evidence is a bytecode finding with no proven
correspondence. That sentence is not supported and will not be generated.

### Severity, confidence and honesty

Severity and confidence remain separate fields. Every finding carries a
`limitations` string stating what the evidence does and does not establish.
A report must not imply that a finding is exploitable, that it is reachable in
production, or that it is definitely a false positive — because in general the
analysis cannot establish any of those three.

## Consequences

- We can produce the "exact line number" reports the business wants, **but
  only for contracts where the correspondence chain completes**, and the report
  says which chain completed.
- Unverified contracts still get analysed — via bytecode — and produce
  offset-level findings with CFG evidence. That is still far more actionable
  than a generic message, and it is truthful.
- The correspondence check is a real cost: a compiler download and a recompile
  per contract. It is cached by `(contract address, compiler version, input
  hash)` and reused.
- Every correspondence decision is stored, so a report can be re-verified
  later, and a customer can be shown the proof.

## Alternatives considered

- **Map bytecode findings to source lines heuristically.** Rejected: it is a
  guess presented as a fact. In a disclosure email that is exactly the failure
  that destroys credibility.
- **Report source lines only, drop bytecode.** Rejected: it loses the majority
  of mainnet contracts, which are unverified.
- **Report bytecode only.** Rejected: it loses the precision the business
  actually wants, and it ignores what source analysis is for.
