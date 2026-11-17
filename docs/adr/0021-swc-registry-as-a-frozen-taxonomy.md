# ADR 0021: The SWC registry is a frozen taxonomy and a join key

**Status:** Accepted
**Date:** 2026-11-17

## Context

Other tools, auditors, and readers describe contract weaknesses in the
Smart Contract Weakness Classification vocabulary. CyberStratum detects
patterns; it says what pattern it found, but not, on its own, what class of
weakness that pattern belongs to in a vocabulary other people share.

The registry is MIT licensed and was last pushed upstream in 2024. It
states that it is no longer actively maintained. It records no per-entry
severity.

## Decision

1. The registry is **frozen** into the product as a snapshot, with the
   upstream revision, the upstream path of every entry, and the SHA-256 of
   every file it was read from. The snapshot is a join key between a
   detector and a class, never a source of severity and never current
   guidance.
2. The severity this product reports for a finding still comes from
   CyberStratum's own detectors. The registry's silence on severity is
   carried through as `null`, not filled in from elsewhere.
3. Every detector-to-class correspondence names **who is making the claim**
   and on what basis: the tool's own documentation, the identifier itself,
   or CyberStratum's own correspondence with the reason written down.
   Correspondence is never attributed to a tool that did not state it.
4. A detector with no recorded correspondence has **no class**. The product
   says that rather than inventing one, and the findings summary counts
   those findings as unclassified rather than dropping them.
5. The registry's own maintenance notice is carried in the product, so a
   reader can see that the taxonomy is frozen.

## Consequences

- Findings can be grouped by a shared vocabulary, and the list can be
  narrowed by class the way it is narrowed by detector or chain.
- The taxonomy can go stale, and the product says so. It is a naming
  convention, not a statement about current best practice.
- A class is not a verdict. It changes no severity, no confidence, and no
  review state, and it plays no part in model promotion.
- The correspondence table is a product artefact that must be maintained
  alongside the detector catalogue; the tests fail if it names a detector
  without guidance or a class the registry does not hold.
