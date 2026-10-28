# ADR-0013: Licensing posture - FastAPI (MIT) and Slither (AGPL-3.0)

* **Status:** Accepted (framework choice), Open (commercial use of Slither)
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
3. **The commercial-use question is answered by the user, not assumed.** The
   answer decides whether the SaaS path needs a licence review, and it is the one
   open item in this ADR.
