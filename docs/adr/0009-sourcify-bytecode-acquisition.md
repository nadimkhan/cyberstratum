# ADR-0009: Sourcify as the bytecode source, with RPC and user-supplied bytes

- **Status:** Accepted
- **Date:** 2026-10-28
- **Governs:** design-document §5.1, §6.1, §10, §18.1, §25.5

## Context

The scan pipeline needs the deployed runtime bytecode of a contract before it
can disassemble anything. The design document assumes this comes from an
EVM RPC endpoint or an explorer API (§5.1, §25.5), with the user able to
paste or upload bytecode instead (§6.1, §18.1).

Two facts on the ground contradicted the first assumption:

1. **Public RPC hosts are not reachable from this environment.** Probing the
   common public endpoints returned HTTP `525` (SSL handshake failed at the
   CDN edge) while an unrelated HTTPS host returned `200`. The network path
   out is fine; those specific hosts are filtered.
2. **Explorers require a key, and keys cost money.** Etherscan and its
   family need a registered API key, which conflicts with the free-tier
   constraint (§24).

Sourcify does not need a key. It serves the deployed runtime bytecode of
*verified* contracts over plain HTTPS, which is a stronger provenance
guarantee than an arbitrary RPC node: the source is matched to the on-chain
code.

The document also has to distinguish two things that a naive implementation
conflates: a contract that has no deployed code, and a transport failure.
An RPC that answers `"0x"` for an address means the address has no code. That
is a fact about the contract, not an error, and it must not trigger a
fallback or a failure status.

## Decision

Bytecode acquisition in `apps/api/app/services/bytecode.py` has exactly three
inputs, tried in this order:

| Input | Path | Network |
|---|---|---|
| User-supplied bytes | `bytecode_hex` on the scan request, stored on `contract_targets.inline_bytecode` | **none** |
| Configured RPC | `EVM_RPC_URL` via `eth_getCode` | yes, one call |
| Sourcify | `https://sourcify.dev/server/v2/contract/{chain_id}/{address}?fields=all` | yes, one call |

Rules that follow from this:

- **User-supplied bytes never touch the network.** A scan of pasted bytecode
  performs zero acquisition requests. The artifact records
  `bytecode_source = "upload"`.
- **RPC is the primary source when one is configured**, because it is the
  most general: it reaches contracts that no explorer has verified. Sourcify
  is the fallback, and the reason the product is usable at all while public
  RPC hosts are filtered.
- **An RPC result of `"0x"` is an empty contract**, not a failure. It is
  returned as empty bytes with a clear reason, and it does not fall through
  to Sourcify. Only a transport error, a malformed response, or a decoding
  failure returns `None` and triggers the fallback.
- **Sourcify's deployed code is `runtimeBytecode.onchainBytecode`**, and the
  request must carry `?fields=all`; the default response omits the bytecode.
- **Sourcify only serves verified contracts.** A contract that is deployed
  but unverified is therefore not reachable through this path. This is a real
  limitation, stated in the UI rather than hidden.

The acquisition service records which path was used, and that path is part
of the scan's reproducibility record.

## Consequences

**Positive**

- The product works end to end today with no API key and no paid provider. A
  mainnet USDC scan completed through the Sourcify path.
- User-supplied bytecode is a first-class input with a guaranteed offline
  path, which is what §6.1 and §18.1 describe.
- Verified-source provenance is stronger than an unverified RPC read.
- A transport failure and an empty contract are now distinguishable, which
  was previously a real bug: `"0x"` was treated as "endpoint unreachable"
  and triggered a pointless fallback.

**Negative / accepted cost**

- Coverage is limited to contracts Sourcify has verified. Unverified
  deployments are only reachable through a configured RPC.
- Sourcify is a single point of failure for the fallback path, and it is a
  third-party service whose availability is not under our control.
- No key is needed, but that also means no usage dashboard and no quota
  visibility from our side.

**Follow-up obligation**

- §27 item 6 ("Initial EVM chains and RPC/explorer provider") stays open.
  When the chain set is decided, the Sourcify chain id mapping must be
  extended to match, and the choice of a primary RPC provider revisited.
