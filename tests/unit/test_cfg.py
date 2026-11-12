"""Tests for basic block and control-flow graph construction."""

from __future__ import annotations

import pytest

from evm_analysis.cfg import EdgeType, Resolution, build_cfg
from evm_analysis.disassembler import disassemble
from evm_analysis.opcodes import load_fork


@pytest.fixture(scope="module")
def cancun():
    return load_fork("cancun")


def _cfg(code_hex: str, fork="cancun"):
    table = load_fork(fork)
    disassembly = disassemble(bytes.fromhex(code_hex), table)
    return disassembly, build_cfg(disassembly)


def test_linear_code_is_one_block(cancun) -> None:
    # PUSH1 0x01, PUSH1 0x02, ADD, STOP
    _, cfg = _cfg("600160020100")
    assert len(cfg.blocks) == 1
    block = cfg.blocks[0]
    assert block.size == 4
    assert block.terminator == "STOP"
    # The block ends in STOP, so it has a single terminal edge with no target.
    assert len(cfg.edges) == 1
    assert cfg.edges[0].edge_type is EdgeType.STOP
    assert cfg.edges[0].target is None


def test_jumpdest_creates_a_block_boundary(cancun) -> None:
    # JUMPDEST, STOP
    _, cfg = _cfg("5b00")
    assert set(cfg.blocks) == {0}


def test_conditional_jump_produces_two_edges(cancun) -> None:
    # offset 0: JUMPDEST
    # offset 1: PUSH1 0x05
    # offset 3: JUMPI  (0x57)
    # offset 4: STOP
    # offset 5: JUMPDEST
    # offset 6: STOP
    _, cfg = _cfg("5b600557005b00")
    kinds = {(e.edge_type, e.resolution) for e in cfg.edges}
    assert (EdgeType.CONDITIONAL_JUMP, Resolution.INFERRED) in kinds
    assert (EdgeType.CONDITIONAL_FALLTHROUGH, Resolution.RESOLVED) in kinds


def test_unconditional_jump_to_known_target(cancun) -> None:
    # 0: PUSH1 0x04, 2: JUMP, 3: STOP, 4: JUMPDEST, 5: STOP
    _, cfg = _cfg("600456005b00")
    jump_edges = [e for e in cfg.edges if e.edge_type is EdgeType.UNCONDITIONAL_JUMP]
    assert len(jump_edges) == 1
    assert jump_edges[0].target == 4
    assert jump_edges[0].resolution is Resolution.INFERRED


def test_dynamic_jump_is_unresolved(cancun) -> None:
    """A jump whose target comes from a runtime stack value stays unresolved."""
    # 0: PUSH1 0x01, 2: PUSH1 0x01, 4: ADD, 5: JUMP -- the target is computed
    # at runtime, so it cannot be resolved statically.
    _, cfg = _cfg("600160010156")
    unresolved = [e for e in cfg.edges if e.resolution is Resolution.UNRESOLVED]
    assert unresolved
    assert unresolved[0].target is None
    assert cfg.unresolved_edges
    assert any("unresolved" in note for note in cfg.notes)


def test_jump_to_non_jumpdest_is_unresolved(cancun) -> None:
    """A constant push that does not point at a JUMPDEST is not a valid target."""
    # 0: PUSH1 0x03, 2: JUMP -- offset 3 is not a JUMPDEST.
    _, cfg = _cfg("600356")
    unresolved = [e for e in cfg.edges if e.resolution is Resolution.UNRESOLVED]
    assert unresolved
    assert unresolved[0].target is None


def test_cfg_is_not_assumed_to_be_a_dag(cancun) -> None:
    """A backward jump creates a cycle, which must be preserved."""
    # 0: JUMPDEST, 1: PUSH1 0x00, 3: JUMP  -> loops back to offset 0
    _, cfg = _cfg("5b600056")
    cycles = cfg.find_cycles()
    assert cycles, "a backward jump must be reported as a cycle"
    # The graph must not have been 'fixed' by removing the back edge.
    back = [e for e in cfg.edges if e.target == 0]
    assert back
    assert back[0].resolution is Resolution.INFERRED


def test_terminators_end_blocks(cancun) -> None:
    # STOP, STOP
    _, cfg = _cfg("0000")
    assert len(cfg.blocks) == 2
    assert cfg.blocks[0].terminator == "STOP"
    assert cfg.blocks[1].terminator == "STOP"


def test_fallthrough_edge_between_blocks(cancun) -> None:
    """A block that does not end in a terminator flows into the next block."""
    # 0: JUMPDEST, 1: PUSH1 0x01, 3: JUMPDEST, 4: STOP
    # The JUMPDEST at offset 3 starts a new block, and the first block ends on
    # a PUSH rather than a terminator, so control falls through to it.
    _, cfg = _cfg("5b60015b00")
    assert len(cfg.blocks) == 2
    fallthrough = [e for e in cfg.edges if e.edge_type is EdgeType.FALLTHROUGH]
    assert fallthrough
    assert fallthrough[0].source == 0
    assert fallthrough[0].target == 3
    assert fallthrough[0].resolution is Resolution.RESOLVED


def test_return_and_revert_are_terminators(cancun) -> None:
    _, cfg = _cfg("f3fd")
    kinds = {e.edge_type for e in cfg.edges}
    assert EdgeType.RETURN in kinds
    assert EdgeType.REVERT in kinds


def test_block_lookup_by_offset(cancun) -> None:
    _, cfg = _cfg("600160020100")
    block = cfg.block_at(2)
    assert block is not None
    assert block.start == 0


def test_successors_and_predecessors(cancun) -> None:
    _, cfg = _cfg("5b600557005b00")
    assert cfg.blocks
    for block_start in cfg.blocks:
        for edge in cfg.successors(block_start):
            if edge.target is None:
                continue
            # The target must be a real block, and the edge must show up as an
            # incoming edge of that block.
            assert edge.target in cfg.blocks
            incoming = cfg.predecessors(edge.target)
            assert any(e.source == block_start and e.target == edge.target for e in incoming)
            # And the edge must be listed as an outgoing edge of its source.
            assert any(
                e.source == edge.source and e.target == edge.target
                for e in cfg.successors(block_start)
            )


def test_empty_disassembly_produces_empty_graph() -> None:
    table = load_fork("cancun")
    cfg = build_cfg(disassemble(b"", table))
    assert cfg.blocks == {}
    assert cfg.edges == []
