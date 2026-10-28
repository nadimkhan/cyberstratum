"""Tests for jump-target resolution, reachability and data-region detection."""

from __future__ import annotations

from evm_analysis.cfg import EdgeType, build_cfg
from evm_analysis.disassembler import disassemble
from evm_analysis.opcodes import load_fork
from evm_analysis.resolver import resolve_jump_targets


def _cfg(code: bytes):
    table = load_fork("cancun")
    disassembly = disassemble(code, table)
    return disassembly, build_cfg(disassembly)


def test_resolves_a_plain_jump() -> None:
    # PUSH1 0x04; JUMP; STOP; JUMPDEST; STOP
    _, cfg = _cfg(bytes.fromhex("600456005b00"))
    jump_edges = [e for e in cfg.edges if e.edge_type is EdgeType.UNCONDITIONAL_JUMP]
    assert len(jump_edges) == 1
    assert jump_edges[0].target == 4


def test_resolves_a_jump_when_the_destination_is_duplicated() -> None:
    # The destination is pushed, duplicated, and branched on. The immediate
    # "push right before the branch" rule cannot see this; the abstract stack
    # simulation can.
    #
    #   0: PUSH1 0x06   stack: [6]
    #   2: DUP1         stack: [6, 6]
    #   3: JUMPI        destination is the top of the stack -> 6
    #   4: STOP
    #   5: STOP
    #   6: JUMPDEST
    #   7: STOP
    code = bytes.fromhex("6006805760005b00")
    disassembly, cfg = _cfg(code)
    resolved = resolve_jump_targets(disassembly, cfg)
    assert resolved.get(3) == 6

    jump_edges = [e for e in cfg.edges if e.edge_type is EdgeType.CONDITIONAL_JUMP]
    assert len(jump_edges) == 1
    assert jump_edges[0].target == 6


def test_dynamic_jump_stays_unresolved() -> None:
    # The destination comes from a runtime value (CALLDATALOAD), so it must
    # not be guessed.
    #
    #   0: PUSH1 0x00
    #   2: CALLDATALOAD   stack: [runtime value]
    #   3: JUMP           destination is unknown
    #   4: STOP
    #   5: JUMPDEST
    #   6: STOP
    code = bytes.fromhex("60003556005b00")
    _, cfg = _cfg(code)
    unresolved = cfg.unresolved_edges
    assert len(unresolved) == 1
    assert unresolved[0].target is None
    assert unresolved[0].resolution.value == "unresolved"


def test_resolved_target_must_be_a_jumpdest() -> None:
    # The push names an offset that is not a JUMPDEST: the EVM would revert,
    # so the edge must not claim that destination.
    code = bytes.fromhex("6004560000")
    _, cfg = _cfg(code)
    jump_edges = [e for e in cfg.edges if e.edge_type is EdgeType.UNCONDITIONAL_JUMP]
    assert jump_edges == []
    assert len(cfg.unresolved_edges) == 1


def test_data_region_behind_an_invalid_guard_is_unreachable() -> None:
    # Solidity appends data (revert strings) behind an INVALID guard. The
    # bytes decode into instructions but are never executed.
    #
    #   0: PUSH1 0x08   -> jump over the data
    #   2: JUMP
    #   3: STOP
    #   4: INVALID      <- the guard
    #   5: JUMPDEST     <- data that decodes as code
    #   6: STOP
    #   7: STOP
    #   8: JUMPDEST     <- the real target
    #   9: STOP
    code = bytes.fromhex("600856005b00fe5b0060005b00")
    _, cfg = _cfg(code)

    assert cfg.reachable_block_count < len(cfg.blocks)
    assert cfg.unreachable_byte_size > 0
    assert cfg.unreachable_regions


def test_everything_is_reachable_in_a_linear_program() -> None:
    _, cfg = _cfg(bytes.fromhex("6001600201600055"))
    assert cfg.reachable_block_count == len(cfg.blocks)
    assert cfg.unreachable_byte_size == 0


def test_cycles_are_found_in_a_loop() -> None:
    # 0: JUMPDEST; 1: PUSH1 0x00; 3: JUMP  -> jumps back to 0
    code = bytes.fromhex("5b600056")
    _, cfg = _cfg(code)
    cycles = cfg.find_cycles()
    assert cycles, "a self-loop must be reported as a cycle"
    assert any(0 in cycle for cycle in cycles)
