"""Tests for compiling a developer's pasted Solidity.

The compiler is the one place where a developer's own text is handed to
another program. These tests care about what happens at that boundary:

* a source that compiles produces runtime bytecode and a source map,
* a source that does not compile says what the compiler said, because
  that message is the developer's next action,
* a source that compiles to nothing deployable is refused rather than
  analysed as an empty contract,
* no compiler on the server is an honest error, not a crash,
* the identity a pasted source is filed under is stable, so that the
  same contract keeps one history.
"""

from __future__ import annotations

import json

import pytest

from app.services.source_compile import (
    CompilationError,
    build_standard_json,
    compile_source,
    pasted_address,
    resolve_solc,
)

VULNERABLE_SOURCE = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

contract Pasted {
    address public owner;

    constructor() {
        owner = msg.sender;
    }

    function withdraw() public {
        (bool ok, ) = msg.sender.call{value: address(this).balance}("");
        require(ok);
    }

    function originalSender() public view returns (address) {
        return tx.origin;
    }
}
"""

INTERFACE_ONLY = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

interface IThing {
    function doThing() external;
}
"""

BROKEN_SOURCE = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

contract Broken {
    function oops() public {
        this is not solidity
    }
}
"""


def _solc_installed() -> bool:
    """Whether a compiler is available to compile with."""
    try:
        resolve_solc()
    except CompilationError:
        return False
    return True


needs_solc = pytest.mark.skipif(
    not _solc_installed(),
    reason="no solc compiler is installed on this machine",
)


def test_the_standard_json_asks_for_the_source_map() -> None:
    """The source map is what turns an offset into a line."""
    document = json.loads(build_standard_json(VULNERABLE_SOURCE))

    assert document["language"] == "Solidity"
    assert document["sources"]["Contract.sol"]["content"] == VULNERABLE_SOURCE
    selection = document["settings"]["outputSelection"]["*"]["*"]
    assert "evm.deployedBytecode.sourceMap" in selection
    assert "evm.deployedBytecode.object" in selection


def test_a_pasted_source_is_filed_under_a_stable_address() -> None:
    """The same source is always the same target, so history accumulates."""
    first = pasted_address(VULNERABLE_SOURCE)
    second = pasted_address(VULNERABLE_SOURCE)
    other = pasted_address(BROKEN_SOURCE)

    assert first == second
    assert first != other
    assert first.startswith("0x")
    assert len(first) == 42


def test_an_empty_source_is_refused() -> None:
    """Empty source is a mistake, not a contract."""
    with pytest.raises(CompilationError, match="empty"):
        compile_source("   \n  ")


def test_a_source_over_the_limit_is_refused() -> None:
    """A source too large to compile is refused before the compiler runs."""
    huge = "// " + ("x" * (600 * 1024))

    with pytest.raises(CompilationError, match="limit"):
        compile_source(huge)


def test_a_missing_compiler_is_an_honest_error(tmp_path) -> None:
    """No compiler is a message, not a crash and not an empty analysis."""
    with pytest.raises(CompilationError, match="No solc compiler"):
        compile_source(VULNERABLE_SOURCE, artifacts_dir=str(tmp_path))


def test_an_uninstalled_version_is_named(tmp_path) -> None:
    """Asking for a compiler that is not there says which one."""
    with pytest.raises(CompilationError, match="0.4.0"):
        compile_source(VULNERABLE_SOURCE, solc_version="0.4.0", artifacts_dir=str(tmp_path))


@needs_solc
def test_a_source_that_does_not_compile_says_what_the_compiler_said() -> None:
    """The developer's next action is to read the compiler's message."""
    with pytest.raises(CompilationError) as raised:
        compile_source(BROKEN_SOURCE)

    message = str(raised.value)
    assert "Broken.sol" in message or "Error" in message


@needs_solc
def test_an_interface_is_refused_rather_than_analysed_as_empty() -> None:
    """An interface has no runtime to analyse."""
    with pytest.raises(
        CompilationError, match="no runtime bytecode|no contract with deployable"
    ):
        compile_source(INTERFACE_ONLY)


@needs_solc
def test_a_compiling_source_yields_bytecode_and_a_source_map() -> None:
    """The runtime bytecode and the map that points back at the source."""
    compiled = compile_source(VULNERABLE_SOURCE).compiled

    assert compiled.contract_name == "Pasted"
    assert len(compiled.runtime_bytecode) > 0
    assert compiled.source_map != ""
    assert compiled.source_name == "Contract.sol"
    assert compiled.solc_version
    assert "withdraw" in compiled.abi


@needs_solc
def test_the_newest_installed_compiler_is_used_by_default() -> None:
    """Without a version, the newest compiler that is installed is used."""
    path, version = resolve_solc()

    assert path.is_file()
    assert version
