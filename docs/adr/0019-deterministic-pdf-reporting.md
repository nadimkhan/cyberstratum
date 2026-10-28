# ADR-0019 — Deterministic PDF report generation

- Status: Accepted
- Date: 2026-10-29
- Related: ADR-0017 (evidence model), ADR-0018 (disclosure workflow)

## Context

The business requirement is a PDF that can be emailed directly to a project.
That makes the PDF the product surface for disclosure, so it has to be
defensible on its own terms: every claim in it must trace back to persisted
evidence, and the same evidence must always produce the same document.

## Decision

### Library: ReportLab

Measured and installed: **ReportLab 5.1.0**, BSD-licensed, and it imports
cleanly on this project's Python 3.14.

The alternatives were checked and rejected:

| Option | Verdict |
| --- | --- |
| ReportLab | **Chosen.** BSD licence, pure Python, no system browser dependency, direct control over byte layout, works on Python 3.14. |
| WeasyPrint | Heavy system dependency stack (Pango, cairo, GTK). Fragile on a Windows host without admin, and adds a whole rendering platform to the deploy surface. |
| xhtml2pdf | Wraps ReportLab but adds an HTML/CSS engine we do not need, and pulls in `svglib`. |
| fpdf2 | BSD and pleasant, but weaker for the structured, paginated layout a report needs. |
| Playwright / headless Chromium | Heaviest option by far — a full browser per report. Unjustified when the report is generated from structured data. |

### Determinism

ReportLab's canvas supports an `invariant` mode:

```python
canvas.Canvas(path, invariant=True)
```

Combined with fixed document metadata — no creation timestamp embedded in the
PDF, no random IDs, no wall-clock in the document — the same evidence produces
a **byte-identical** PDF.

This was verified: the same evidence rendered twice produced two files with an
identical SHA-256 hash.

Determinism matters beyond tidiness. It means:

- A report can be regenerated and diffed against the original to prove it was
  not edited after the fact.
- The PDF's hash can be recorded in the database next to the finding, so a
  customer or a programme can verify the artifact they received.
- Reproducibility claims in the product stay honest — the same scan against
  the same contract produces the same document.

The generation timestamp is therefore **not** written into the PDF body. If a
timestamp is wanted, it is passed in explicitly from the persisted scan record,
so the document still reproduces.

### Report content

The report is generated from persisted evidence only. It never recomputes and
never guesses.

Required sections:

1. **Summary** — target contract, chain, address, scan id, analysis date.
2. **Scope** — what was analysed and what was not: which engines ran, which
   were skipped and why, whether the correspondence chain completed.
3. **Contract identity** — address, chain id, block number, runtime bytecode
   hash, compiler version, metadata compiler version, verification state.
4. **Findings** — each finding with:
   - severity and confidence, kept separate
   - the evidence type, stated explicitly
   - the exact location: file and line for `source_line`; offset and PC for
     bytecode evidence; the CFG path for reachability
   - the offending source text or instruction sequence
   - the tool that produced it and its version
   - the limitations — what this evidence does not establish
5. **Reproduction** — the exact commands and inputs, so a reviewer can
   reproduce the finding independently.
6. **Correspondence proof** (when it completed) — the compiler, the settings,
   the recompile result, and the byte-equality statement.
7. **Disclosure status** — draft, ready, submitted, or closed, with the
   programme and reference if applicable.

Every finding in the report is hyperlinked back to its machine-readable form in
the platform.

### Architecture

```
ReportService
  ├─ loads the persisted scan, findings, evidence, artifacts, tool versions
  ├─ builds a ReportModel (pure data, no rendering)
  ├─ renders through a ReportLab renderer
  └─ returns bytes + sha256

GET /api/v1/scans/{scan_id}/report.pdf
```

The renderer is a pure function of the `ReportModel`. The model is separated
from the rendering so that the same model can later drive HTML or JSON
disclosure formats without duplicating the content rules, and so the content
rules are testable without producing a PDF.

Report generation happens in the API process on demand for a single scan. It
is deterministic and cheap, so it does not need a queue. If it ever becomes
expensive enough to need one, the job boundary is the same as any other scan
job.

## Consequences

- Reports are reproducible, verifiable and diffable.
- The PDF is a first-class artifact: it can be hashed, stored, and compared.
- No browser and no heavy native stack in the deploy path. The free-tier
  hosting target stays simple.
- The content rules live in one place, so a claim cannot be added to one
  output format and forgotten in another.

## Alternatives considered

- **HTML template printed to PDF.** Rejected: it requires a browser engine,
  and it makes byte-level determinism much harder to guarantee.
- **WeasyPrint for typographic quality.** Rejected on the system-dependency
  cost, not on quality — the report is a technical document with tables and
  code, not a brochure.
- **Non-deterministic PDFs with a timestamp.** Rejected: it forfeits the
  reproducibility guarantee that the rest of the platform is built on.
