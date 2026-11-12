"""A scan says what it covered, and is only partial for a real gap.

Real Solidity bytecode carries two things that look like defects and are
not: a metadata trailer of non-executable data at the end, and the
guard byte the compiler puts in front of it. It also jumps to addresses
that are computed at run time, which no static analysis can follow.

Calling those gaps made almost every contract "partial", which turned
the word into decoration. These tests pin the distinction: measurements
go into the coverage document, and only a genuine defect makes a scan
partial.
"""

from __future__ import annotations

import pytest

from app.services.report import _coverage_lines
from app.services.source_compile import compile_source
from evm_analysis import build_cfg, disassemble, load_fork

SOURCE = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

contract Coverage {
    address public owner;

    constructor() {
        owner = msg.sender;
    }

    function withdraw() public {
        (bool ok, ) = msg.sender.call{value: address(this).balance}("");
        require(ok);
    }
}
"""


@pytest.fixture(scope="module")
def runtime_bytecode() -> bytes:
    """The runtime a real compiler produced, metadata trailer and all."""
    return compile_source(SOURCE).compiled.runtime_bytecode


@pytest.fixture(scope="module")
def table():
    """The opcode table of a recent fork."""
    return load_fork("cancun")


def test_the_metadata_trailer_is_a_note_not_a_warning(runtime_bytecode: bytes, table) -> None:
    """The trailer is data. Excluding it from the code is correct."""
    disassembly = disassemble(runtime_bytecode, table)

    assert disassembly.metadata is not None
    assert disassembly.warnings == [], disassembly.warnings
    assert any("metadata" in note for note in disassembly.notes)


def test_the_guard_byte_before_the_trailer_is_a_note(runtime_bytecode: bytes, table) -> None:
    """Solidity puts an invalid opcode in front of the trailer on purpose."""
    disassembly = disassemble(runtime_bytecode, table)

    assert not any("invalid opcode" in warning for warning in disassembly.warnings)
    assert any("guard" in note for note in disassembly.notes)


def test_an_invalid_opcode_in_the_code_is_still_a_warning(table) -> None:
    """Only the deliberate guard is forgiven."""
    code = bytes.fromhex("60006000fe")

    disassembly = disassemble(code, table)

    assert any("invalid opcode" in warning for warning in disassembly.warnings)


def test_a_dynamic_jump_is_a_note_not_a_warning(runtime_bytecode: bytes, table) -> None:
    """The function dispatcher is built out of jumps nobody can follow."""
    disassembly = disassemble(runtime_bytecode, table)

    cfg = build_cfg(disassembly)

    assert cfg.unresolved_edges, "the fixture is expected to have dynamic jumps"
    assert cfg.warnings == [], cfg.warnings
    assert any("unresolved" in note for note in cfg.notes)


def test_coverage_renders_as_sentences() -> None:
    """The report turns the measurement into something a reader can use."""
    lines = _coverage_lines(
        {
            "instructions": 118,
            "executable_bytes": 449,
            "metadata_bytes": 53,
            "edges": 46,
            "dynamic_jumps": 6,
            "unreachable_blocks": 1,
            "notes": ["solidity metadata detected at offset 449"],
        }
    )

    assert any("118 instruction" in line for line in lines)
    assert any("449 byte" in line for line in lines)
    assert any("53 byte" in line for line in lines)
    assert any("6 dynamic" in line for line in lines)
    assert any("not reachable" in line for line in lines)
    assert any("metadata detected" in line for line in lines)


def test_no_coverage_renders_as_nothing() -> None:
    """A scan with no measurement says nothing about coverage."""
    assert _coverage_lines(None) == ()
    assert _coverage_lines({}) == ()
