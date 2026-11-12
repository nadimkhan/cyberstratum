"""Tests for putting a finding on a line of the developer's source.

The mapping is only worth anything if it is right. These tests cover
the two ways it can go wrong -- the source map describes different code,
or the code has instructions the map never covered -- and what the
product does about it. It refuses. A finding on the wrong line is worse
than a finding on no line.
"""

from __future__ import annotations

from app.services.source_lines import (
    MAX_UNCOVERED_INSTRUCTIONS,
    annotate_evidence,
    build_offset_lines,
    line_of_offset,
)

SOURCE = """line one
line two
line three
line four
"""


def test_a_line_number_is_counted_from_the_start() -> None:
    """Line numbers are one-based, the way an editor counts them."""
    assert line_of_offset(SOURCE, 0) == 1
    assert line_of_offset(SOURCE, SOURCE.index("line two")) == 2
    assert line_of_offset(SOURCE, SOURCE.index("line four")) == 4


def test_the_map_puts_each_instruction_on_its_line() -> None:
    """A compressed map is expanded, and offsets become lines."""
    source_map = "0:8:0;9:9:0;18:9:0"

    lines = build_offset_lines(SOURCE, source_map, [0, 10, 20])

    assert lines == {0: 1, 10: 2, 20: 3}


def test_an_empty_entry_inherits_the_previous_range() -> None:
    """solc's compression leaves out what has not changed."""
    source_map = "0:8:0;;9:9:0"

    lines = build_offset_lines(SOURCE, source_map, [0, 10, 20])

    assert lines == {0: 1, 10: 1, 20: 2}


def test_a_metadata_tail_is_tolerated() -> None:
    """The contract's metadata is not code, and the map stops before it."""
    source_map = "0:8:0;9:9:0"

    lines = build_offset_lines(SOURCE, source_map, [0, 10, 20, 30])

    assert lines == {0: 1, 10: 2}


def test_a_map_that_describes_different_code_is_refused() -> None:
    """More instructions in the map than in the code is not a metadata tail."""
    source_map = "0:8:0;9:9:0;18:9:0;27:9:0"

    assert build_offset_lines(SOURCE, source_map, [0, 10]) == {}


def test_a_long_uncovered_tail_is_refused() -> None:
    """A tail longer than a metadata blob means the map does not fit."""
    source_map = "0:8:0;"
    offsets = list(range(0, 20 * 10, 10))

    assert build_offset_lines(SOURCE, source_map, offsets) == {}


def test_a_tail_within_the_tolerance_is_accepted() -> None:
    """The tolerance is a tolerance, and it is bounded."""
    source_map = "0:8:0;"
    offsets = list(range(0, (MAX_UNCOVERED_INSTRUCTIONS + 1) * 10, 10))

    lines = build_offset_lines(SOURCE, source_map, offsets)

    assert lines == {0: 1, 10: 1}


def test_an_empty_map_maps_nothing() -> None:
    """No map, no lines."""
    assert build_offset_lines(SOURCE, "", [0, 10]) == {}
    assert build_offset_lines("", "0:8:0;;", [0, 10]) == {}


def test_evidence_gets_the_line_of_its_first_mapped_offset() -> None:
    """A finding points at a line when the map can place one of its offsets."""
    evidence = {"offsets": [20, 999], "signals": ["tx_origin"]}

    annotated = annotate_evidence(evidence, {20: 3}, source_file="Contract.sol")

    assert annotated["source_line"] == 3
    assert annotated["source_file"] == "Contract.sol"
    assert annotated["signals"] == ["tx_origin"]


def test_evidence_without_a_mappable_offset_is_left_alone() -> None:
    """An unplaceable finding keeps its evidence rather than getting a wrong line."""
    evidence = {"offsets": [999], "signals": ["tx_origin"]}

    annotated = annotate_evidence(evidence, {20: 3}, source_file="Contract.sol")

    assert annotated == evidence
    assert "source_line" not in annotated


def test_evidence_with_no_offsets_is_left_alone() -> None:
    """A finding that points at nothing has no line to give."""
    evidence = {"signals": ["tx_origin"]}

    annotated = annotate_evidence(evidence, {20: 3})

    assert annotated == evidence
