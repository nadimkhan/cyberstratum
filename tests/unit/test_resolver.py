"""Tests for jump-target resolution, reachability and data-region detection."""

from __future__ import annotations

from evm_analysis.cfg import EdgeType, build_cfg
from evm_analysis.disassembler import disassemble
from evm_analysis.opcodes import load_fork
from evm_analysis.resolver import resolve_jump_targets, run_dataflow


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


def test_a_carried_value_survives_across_several_jumps() -> None:
    # The destination of the last jump is a value that was pushed in the
    # first block and carried across two jumps. The dataflow has to keep
    # that value alive the whole way.
    #
    #    0: PUSH1 0x0e   stack: [14]
    #    2: PUSH1 0x06   stack: [14, 6]
    #    4: JUMP         -> 6,  stack: [14]
    #    5: STOP
    #    6: JUMPDEST     stack: [14]
    #    7: PUSH1 0x0b   stack: [14, 11]
    #    9: JUMP         -> 11, stack: [14]
    #   10: STOP
    #   11: JUMPDEST     stack: [14]
    #   12: JUMP         -> 14, stack: []
    #   13: STOP
    #   14: JUMPDEST
    #   15: STOP
    code = bytes.fromhex("600e600656005b600b56005b56005b00")
    disassembly, cfg = _cfg(code)
    resolved = resolve_jump_targets(disassembly, cfg)
    assert resolved.get(4) == 6
    assert resolved.get(9) == 11
    assert resolved.get(12) == 14


def test_the_first_path_to_a_block_is_not_merged_with_the_empty_initial_state() -> None:
    # Regression test for the dataflow bug in which the *initial* state of
    # a block ("no path has reached it yet") was merged with the first path
    # that reached it. The empty initial state looked like a second path
    # with an unknown stack, so every known value the first path carried
    # was wiped out and the jump could not be resolved.
    #
    # The fixture above is exactly that case: block 11 is reached only
    # through a jump, and the value it needs was pushed in block 0.
    code = bytes.fromhex("600e600656005b600b56005b56005b00")
    disassembly, cfg = _cfg(code)
    states, _ = run_dataflow(disassembly, cfg)
    window = states[11]
    assert window is not None
    assert window[-1] == 14


def test_two_paths_that_disagree_leave_the_value_unknown() -> None:
    # Two paths reach the same block with different values on top of the
    # stack. The merged state must not keep either one of them.
    #
    #    0: PUSH1 0x01   the condition
    #    2: PUSH1 0x0b   the destination
    #    4: JUMPI        -> 11 with an empty stack
    #    5: PUSH1 0x05   stack: [5]
    #    7: PUSH1 0x0b   stack: [5, 11]
    #    9: JUMP         -> 11 with [5]
    #   10: STOP
    #   11: JUMPDEST
    #   12: POP
    #   13: JUMP         -> the destination differs per path
    code = bytes.fromhex("6001600b576005600b56005b5056")
    disassembly, cfg = _cfg(code)
    states, _ = run_dataflow(disassembly, cfg)
    window = states[11]
    assert window is not None
    assert not window or window[-1] is None
    # The ambiguous jump must not be resolved.
    resolved = resolve_jump_targets(disassembly, cfg)
    assert 13 not in resolved


def test_a_jumpi_reads_the_destination_and_not_the_condition() -> None:
    # A conditional branch jumps to the top of the stack (mu_s[0]) when the
    # second item (mu_s[1]) is non-zero, so the condition is pushed first
    # and the destination last. Both the resolver and the fallback rule
    # have to agree on that order, otherwise the edge points at the
    # condition instead of the destination.
    #
    #    0: PUSH1 0x01   the condition
    #    2: PUSH1 0x07   the destination
    #    4: JUMPI        -> 7
    #    5: STOP
    #    6: STOP
    #    7: JUMPDEST     the real destination
    #    8: STOP
    code = bytes.fromhex("600160075700005b00")
    disassembly, cfg = _cfg(code)
    resolved = resolve_jump_targets(disassembly, cfg)
    assert resolved.get(4) == 7

    targets = {
        e.target for e in cfg.edges if e.edge_type is EdgeType.CONDITIONAL_JUMP
    }
    # 1 is the condition, not a destination: it must not be a target.
    assert 1 not in targets
    assert targets == {7}
