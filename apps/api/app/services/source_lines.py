"""Putting a finding on a line of the developer's code.

A finding that says "there is a DELEGATECALL at offset 0x1f4" is
technically correct and practically useless to the developer who has to
fix it. What they need is the line.

For a deployed contract, the line is only known when the source that
produced the bytecode has been *proven* to be the source of those bytes.
For a source the developer pasted and this server compiled, the line is
known by construction: the compiler told us which range of the source
each instruction came from, and we analysed the very bytes it produced.

This module turns solc's compressed source map into a map from bytecode
offset to source line, and attaches that line to a finding's evidence.

The map is built once per scan and only when it can be built honestly:
if the number of source-map entries does not match the number of
instructions, the mapping is refused rather than guessed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.core.logging import get_logger
from app.services.correspondence import expand_source_map

log = get_logger(__name__)

#: The evidence key the rules use for the bytecode offsets they point at.
OFFSETS_KEY = "offsets"

#: How many instructions the source map may leave uncovered at the end of
#: the code. A contract's metadata blob is not code: the disassembler
#: decodes it as one or two instructions the compiler never accounted
#: for. Anything beyond this is not a metadata tail, and the mapping is
#: refused rather than guessed.
MAX_UNCOVERED_INSTRUCTIONS = 16


def line_of_offset(source: str, offset: int) -> int:
    """Return the one-based line in ``source`` that holds ``offset``."""
    if offset < 0 or offset > len(source):
        return 1
    return source.count("\n", 0, offset) + 1


def build_offset_lines(
    source: str,
    source_map: str,
    instruction_offsets: Sequence[int],
) -> dict[int, int]:
    """Map bytecode offsets to source lines.

    Args:
        source: The developer's source, as it was compiled.
        source_map: solc's compressed source map for the runtime code.
        instruction_offsets: The bytecode offset of each instruction, in
            the order the disassembler produced them.

    Returns:
        A map from bytecode offset to source line. It is empty when the
        mapping cannot be built honestly.
    """
    if not source or not source_map:
        return {}

    entries = source_map.split(";")
    covered = len(instruction_offsets)
    if len(entries) < covered:
        # The source map covers a prefix of the code. The instructions it
        # does not cover are the contract's metadata blob, which is not
        # code at all; a tail that is longer than that is not a metadata
        # tail, and the mapping would be a guess.
        uncovered = covered - len(entries)
        if uncovered > MAX_UNCOVERED_INSTRUCTIONS:
            log.warning(
                "source_map_shorter_than_code",
                entries=len(entries),
                instructions=covered,
            )
            return {}
        covered = len(entries)
    elif len(entries) > covered:
        # The map describes more instructions than the code has, so it
        # describes different code.
        log.warning(
            "source_map_longer_than_code",
            entries=len(entries),
            instructions=covered,
        )
        return {}

    ranges = expand_source_map(entries)
    lines: dict[int, int] = {}
    for index in range(covered):
        offset = instruction_offsets[index]
        source_range = ranges[index]
        if source_range is None:
            continue
        start, _length = source_range
        lines[offset] = line_of_offset(source, start)
    return lines


def annotate_evidence(
    evidence: Mapping[str, Any],
    lines: Mapping[int, int],
    *,
    source_file: str | None = None,
) -> dict[str, Any]:
    """Return the evidence with the source line attached.

    The line is attached to the first bytecode offset the finding points
    at that the source map can explain. A finding whose offsets the map
    cannot place keeps its evidence unchanged: a line that is not there
    is worse than no line at all.
    """
    updated = dict(evidence)
    if not lines:
        return updated

    offsets = updated.get(OFFSETS_KEY)
    candidates: list[int] = []
    if isinstance(offsets, list):
        candidates = [item for item in offsets if isinstance(item, int)]
    elif isinstance(offsets, int):
        candidates = [offsets]

    for offset in candidates:
        line = lines.get(offset)
        if line is None:
            continue
        updated["source_line"] = line
        if source_file:
            updated["source_file"] = source_file
        break
    return updated


__all__ = [
    "OFFSETS_KEY",
    "annotate_evidence",
    "build_offset_lines",
    "line_of_offset",
]
