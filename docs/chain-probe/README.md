# The chain survey

The Blockscout instance registry (`https://api.blockscout.com/v2/instances`)
answers **HTTP 402 Payment Required** without a paid plan, so it can no
longer tell us which chains have a free per-chain instance. The chain
list is therefore found by **probing**.

## Method

1. Candidate hosts are derived from public registries:
   `https://chainid.network/chains.json` and the Etherscan V2 chainlist
   `https://api.etherscan.io/v2/chainlist`. Neither needs a key.
2. Each candidate is probed **one at a time** (one request per second)
   with a descriptive User-Agent. No credential is ever sent.
3. A host counts as live when `/api/v2/smart-contracts` answers with the
   v2 shape.

## What the numbers mean

| Outcome | Meaning |
|---|---|
| `live` | The v2 smart-contracts API answered. |
| `blocked` | HTTP 403. The instance is very likely alive and is blocking our agent. **This is "unknown", not "dead".** |
| `not_found` | HTTP 404. The host name does not resolve to a Blockscout. |
| `not_blockscout` | The host answered, but not with a Blockscout v2 API. |
| `unreachable` | The host could not be connected to. |

A 403 is kept in the *blocked* list on purpose. Two of the routes
belonging to this product's own chains answer 403 to every agent tried,
and one of the large chains answers 403 to every request we made. Calling
those "dead" would be wrong, and the difference matters when a chain
suddenly stops being discovered.

## The record

`survey.json` holds the hosts that carry a decision -- live, blocked, or
otherwise interesting -- with the chain id where the probe could tell it.
The four thousand-odd hostnames that answered 404 are counted, not
listed; the full reports are run output and live in `var/chain-probe/`.

Regenerate and cross-check against the registry with:

```
python scripts/summarise_chain_probe.py --write   # rewrite survey.json
python scripts/summarise_chain_probe.py --check   # fail on drift
```

`tests/unit/test_chain_probe_survey.py` runs the same comparison as a
gate, so a registry entry that the survey never saw live -- or a chain
the survey found that the registry does not carry -- fails the suite.
