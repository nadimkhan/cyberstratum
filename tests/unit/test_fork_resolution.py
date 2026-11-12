"""Tests for the fork resolution rules."""

from __future__ import annotations

from app.services.fork_resolution import (
    SOURCE_FALLBACK,
    SOURCE_INFERRED,
    SOURCE_REQUESTED,
    resolve_fork,
)
from evm_analysis.fork_inference import ForkRequirement


def _requirement(
    required: str = "shanghai",
    *,
    unknown: tuple[int, ...] = (),
) -> ForkRequirement:
    return ForkRequirement(
        required_fork=required,
        opcodes_used=frozenset({0x60}),
        newest_opcode="PUSH0",
        newest_opcode_byte=0x5F,
        unknown_opcodes=unknown,
        conflict=False,
    )


def test_a_request_newer_than_the_floor_is_honoured():
    resolution = resolve_fork("cancun", _requirement("shanghai"))
    assert resolution.fork == "cancun"
    assert resolution.source == SOURCE_REQUESTED
    assert not resolution.conflict


def test_a_request_equal_to_the_floor_is_honoured():
    resolution = resolve_fork("shanghai", _requirement("shanghai"))
    assert resolution.fork == "shanghai"
    assert resolution.source == SOURCE_REQUESTED
    assert not resolution.conflict


def test_a_request_older_than_the_floor_is_honoured_and_recorded():
    """An explicit request is an instruction, not a suggestion.

    A caller who analyses a contract under an older fork is usually
    asking a deliberate question -- what does this code mean on a chain
    from before that opcode existed? The older table answering "that
    opcode is invalid" is the answer they wanted. The disagreement must
    still be recorded.
    """
    resolution = resolve_fork("london", _requirement("shanghai"))
    assert resolution.fork == "london"
    assert resolution.source == SOURCE_REQUESTED
    assert resolution.conflict
    assert "predates" in resolution.reason
    assert "cannot execute" in resolution.reason


def test_no_request_means_the_floor_is_used():
    resolution = resolve_fork(None, _requirement("cancun"))
    assert resolution.fork == "cancun"
    assert resolution.source == SOURCE_INFERRED
    assert not resolution.conflict


def test_an_empty_request_means_the_floor_is_used():
    resolution = resolve_fork("", _requirement("cancun"))
    assert resolution.fork == "cancun"
    assert resolution.source == SOURCE_INFERRED


def test_code_that_cannot_be_placed_falls_back_and_is_marked():
    resolution = resolve_fork(None, _requirement("shanghai", unknown=(0x0C,)))
    assert resolution.source == SOURCE_FALLBACK
    assert resolution.conflict
    assert "cannot be placed" in resolution.reason


def test_a_request_is_kept_even_when_the_code_cannot_be_placed():
    resolution = resolve_fork("london", _requirement("shanghai", unknown=(0x0C,)))
    assert resolution.fork == "london"
    assert resolution.source == SOURCE_FALLBACK
    assert resolution.conflict


def test_the_resolution_serialises_for_the_artifact():
    payload = resolve_fork(None, _requirement("shanghai")).as_dict()
    assert payload["fork"] == "shanghai"
    assert payload["source"] == SOURCE_INFERRED
    assert payload["conflict"] is False
    assert payload["required_fork"] == "shanghai"
    assert "reason" in payload
