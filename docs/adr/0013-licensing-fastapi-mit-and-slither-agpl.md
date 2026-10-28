# ADR-0013: Licensing posture - FastAPI (MIT) and Slither (AGPL-3.0)

* **Status:** Accepted — framework choice settled; AGPL boundary is a hard constraint
* **Date:** 2026-10-28

## The question

"FastAPI is not free for our use case - what do we suggest?"

## Answer: FastAPI is free, and it stays

Verified from the installed distribution, not from memory:

```
.venv/Lib/site-packages/fastapi-*.dist-info/METADATA
License-Expression: MIT
```

FastAPI is MIT-licensed. That means: free to use commercially, no per-seat or
per-request fees, no runtime licence server, no copyleft obligation, no
attribution requirement in the product. The MIT licence only requires the
copyright notice to be kept in copies of the software.

The rest of the backend stack is permissively licensed as well: Starlette (BSD),
Pydantic (MIT), SQLAlchemy (MIT), Alembic (MIT), RQ (BSD), Redis (BSD),
scikit-learn (BSD), PostgreSQL (PostgreSQL licence), Next.js (MIT), React (MIT),
Tailwind (MIT).

**The honest caveat is not the licence, it is the hosting.** FastAPI costs nothing
to run; the server it runs on is what costs money. Free options that suit this
project: Oracle Cloud Always Free (2 ARM cores, 1 GB each, 10 GB block storage -
comfortable for the API plus a worker), Fly.io and Render free tiers, or a
Hetzner CX22 at ~EUR 4/month, which is the cheapest thing that is actually
production-reasonable. The database and Redis are the real recurring cost, and
both can run on the same box at this scale.

**Decision: keep FastAPI.** There is no licence or cost argument for changing it,
and the codebase is already built on it with a tested launcher, Alembic migrations
and an RQ worker. Moving to Django or Litestar would cost weeks and buy nothing.

## The licensing issue that actually matters: Slither

Watchdog's source-level engine is Slither, and Slither is **not** permissively
licensed:

```
.venv/Lib/site-packages/slither_analyzer-*.dist-info/METADATA
License: AGPL-3.0

.venv/Lib/site-packages/crytic_compile-*.dist-info/METADATA
License-Expression: AGPL-3.0-only
```

AGPL-3.0 is the strongest copyleft licence in common use. If you *convey* a
program that is derived from AGPL code, or *offer it over a network*, the AGPL
obligations attach.

How this applies depends entirely on what CyberStratum becomes:

| Use case | AGPL exposure | Recommendation |
|---|---|---|
| Internal tool for your own consultancy; source code never published; clients receive reports, not the software | Low. Running Slither as a separate process and consuming its JSON output is aggregation, not derivative work. | **Proceed.** This is the expected case. |
| Hosted multi-tenant SaaS where users interact with the software over a network, source not published | Moderate. The AGPL network clause is the one people get wrong; running Slither out-of-process and returning only findings is the defensible pattern, but this is a question for an actual lawyer, not for a README. | **Get legal advice before launch.** |
| Ship a product that embeds or links Slither's code in our own source | High. That would make our combined work AGPL. | **Do not do this.** Run Slither as a subprocess. |
| Publish our source as permissively licensed while depending on Slither | High if Slither code is copied in; manageable if it stays an external process the user installs. | Keep Slither an external, separately-installed dependency. |

The architecture already avoids the worst case: Slither runs as a subprocess and
the product consumes its JSON output. CyberStratum's own EVM engine is entirely
our own code and carries no such restriction, so the bytecode half of the product
is licence-clean regardless of this decision.

## Decision

1. **FastAPI stays.** MIT, free, already built on.
2. **Slither stays an out-of-process subprocess.** Its AGPL licence must not
   infect our own source. This is a hard architectural constraint, not a
   preference: it means `apps/api/app/services/slither.py` shells out and parses
   JSON, and never imports Slither's Python API.
3. **The commercial-use answer is: commercial multi-tenant SaaS.** This ADR was
   written before that was confirmed, and the answer changes the posture, so the
   rest of this section is binding rather than advisory.

## Binding constraints for the commercial SaaS

These are enforced in the repository, not just documented:

1. **Never import Slither.** No `import slither`, no `from slither...`, no
   vendored Slither source, in any file we ship. Slither is an external
   executable that we invoke and read JSON from. A test asserts this
   (`tests/unit/test_agpl_boundary.py`) so a future contributor cannot quietly
   break it.
2. **Never modify Slither.** AGPL Section 13 attaches to *modified* versions.
   The tool is installed unmodified, from its own distribution, and we do not
   patch it. Patches belong upstream.
3. **No code copying across the boundary.** The interface is a JSON file on
   disk. We do not translate or restructure its source into our code.
4. **The bytecode engine is the licence-clean primary path.** Everything we
   wrote — the EVM engine, the CFG, the resolver, the feature extraction, the
   ML baseline — is our own work and carries no copyleft obligation. The hosted
   product can ship and run without the Slither lane enabled.
5. **Legal review before commercial launch.** The constraints above are the
   defensible engineering position, not legal advice. An AGPL-licensed
   tool run as an out-of-process service in a multi-tenant SaaS has been
   litigated in this space, and a qualified lawyer should confirm the position
   before the product charges anyone money. **This is a launch blocker, not a
   post-launch cleanup item.**

## What this means commercially

The good news is that the valuable half of the product is licence-clean. The
deep bytecode analysis — the part that works on unverified contracts, is
cross-validated against an independent implementation, and produces reproducible
artifacts — is entirely ours. Slither adds source-level detectors and `file:line`
locations; it is an enhancement, not a foundation.
