"""Update the tracker and the pending list after a round.

The two documents are written by hand, which is how they drift. This
script applies the changes that are known to be true after a verified
round, so the documents keep saying what the code does.
"""

import pathlib
import sys

TRACKER_SECTION = """### 12.1 The tracked-asset spine, and the three defects it exposed

The product's two modes — the autonomous scan of newly verified contracts
and the developer's own scan — had nothing in common in the database.
Both wrote scans, but nothing recorded *which address* a scan was about,
so "did my fix work?" could not be answered from the data.

`tracked_assets` is that spine: one row per (workspace, chain, address),
classified `owned`, `watched` or `discovered`, carrying the date the
address was first seen. Every scan attaches to it through `scans.asset_id`
(`ON DELETE SET NULL`, so stopping the tracking never deletes evidence).
The progress numbers are *computed* from the scans and findings that
exist, never cached, because a cached counter can disagree with the rows
it claims to count.

With the spine in place, three defects that had been hiding in plain
sight showed up in the first live discovery cycle.

**Defect 1: a verified contract could not be analysed at all.** The
bytecode was fetched from the chain's public RPC, and from Sourcify when
the RPC was unreachable. A chain whose public RPC endpoints are
unreachable from a small server, and whose contracts Sourcify has not
indexed, produced a *failed* scan — even though the contract was
verified on that chain's own explorer, which is where it had just been
discovered. Every Blockscout instance proxies the Ethereum JSON-RPC API
at `/api/eth-rpc`, so the explorer that answered the discovery query can
also serve the contract's bytecode. That is now the third route, and it
is what makes the autonomous path work on the long tail of chains whose
RPC endpoints do not answer.

**Defect 2: "partial" was a shrug.** A scan was marked partial when the
disassembly warned or the control-flow graph could not be fully
resolved, but nothing recorded *what* was missed. The status was
decoration. `scans.limitations` now records the disassembly warnings,
the number of unresolved control-flow edges and their ratio, and the PDF
report renders them under "Coverage limitations". A partial scan now
says what it could not analyse.

**Defect 3: the progress history read backwards, and its order was
random.** The timeline was newest-first, which is a list, not a log. It
is now chronological. The tie-break needed care: `created_at` is a
database `now()`, which is the *transaction* timestamp, so two scans
created in one transaction share it, and the scan id is a random UUID
that says nothing about order. The ordering therefore falls through to
`queued_at`, which the application stamps per call and which is
therefore the real creation order.

### 12.2 The scheduler

`app.cli.discovery_cycle` queues one discovery cycle, and the systemd
units (`cyberstratum-discovery.service` and `.timer`, hourly, with
`Persistent=true` so a missed run happens after a reboot) call it. The
cycle is *queued* rather than run in-process so that there is exactly one
execution path — the same code the API and the worker use — and so that a
cycle waits patiently for the worker instead of dying half-way through a
sweep of sixty chains.

### 12.3 What the live run produced

One cycle, two chains, against the real Blockscout feed:

| Stage | Result |
|---|---|
| Discovery | 100 contracts found, 100 new, 0 chains failed |
| Tracked assets | 100 rows, `kind=discovered` |
| Scans queued | 100, all drained by the workers |
| Findings | baseline (bytecode), slither (source) and mythril findings in one scan set |
| Artifacts | 37 |

A contract that had failed with `sourcify_unavailable` was re-scanned
after the fix and came back `partial` with two findings and an honest
limitations document; the asset's history then showed both scans with
their dates, and the open-finding count moved from 0 to 1.

### 12.4 The gate

| Gate | Result |
|---|---|
| Ruff | All checks passed! |
| mypy | no issues found in 106 source files |
| pytest, full and uncapped | 864 passed, 28 warnings in 151.79s |
| Vitest | 12 files, 100 tests passed |
| `npm run check` | exit 0 — every path resolves |
"""

SCHEDULER_OLD = """6. **A scheduler.** The cycle is still triggered by hand or by the API.
   A systemd timer, in the shape of the update-check timer that already
   exists, is the deployment answer.
"""

SCHEDULER_NEW = """6. **A scheduler — done.** `app.cli.discovery_cycle` queues one cycle and
   the systemd units (`cyberstratum-discovery.service` and `.timer`,
   hourly, with `Persistent=true` so a missed run happens after a
   reboot) call it. The cycle is *queued* rather than run in-process, so
   there is exactly one execution path and a cycle waits for the worker
   instead of dying half-way through a sweep.
"""

NEW_ITEMS = """
7. **The developer's own source.** A developer can paste Solidity, but
   the paste path is not built: the source is not compiled into the
   bytecode the pipeline analyses, and the findings of a pasted
   contract carry no source lines. The compiler call has to be
   out-of-process and bounded, the same way Slither is.
8. **The catalogue of vulnerabilities.** Six baseline detectors have
   guidance — what the bug is, what it does, and the fix — and 122
   Slither detectors have none. The knowledge layer is the thing the
   model reads and the thing a developer acts on, so it is the part
   that has to be complete.
9. **The frontend for the progress spine.** The assets API exists and
   works, and there is no page that shows it: no list of the addresses
   a workspace follows, no dated history, no open-finding count that
   moves when a fix ships.
"""


def main() -> int:
    tracker = pathlib.Path("docs/WORK-TRACKER.md")
    text = tracker.read_text()
    if "### 12.1 The tracked-asset spine" not in text:
        separator = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        tracker.write_text(text + separator + TRACKER_SECTION.strip() + "\n")
        print("tracker updated")

    pending = pathlib.Path("docs/PENDING.md")
    text = pending.read_text()
    if SCHEDULER_OLD in text:
        text = text.replace(SCHEDULER_OLD, SCHEDULER_NEW)
        print("scheduler marked done")
    if "7. **The developer's own source.**" not in text:
        marker = "\n## 7. How this document relates to the others"
        text = text.replace(marker, NEW_ITEMS + marker, 1)
        print("pending items added")
    pending.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
