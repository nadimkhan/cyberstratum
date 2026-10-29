"""Tests for the source-to-bytecode correspondence prover.

The prover is the gate that lets a disclosure report name a source line. The
tests therefore concentrate on the ways it can be wrong:

* a compiler that fails must not become a mismatch,
* a metadata difference must not become a mismatch,
* and an unavailable verification record must not become a proof.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app.db.enums import CorrespondenceStatus
from app.services.correspondence import (
    CorrespondenceOutcome,
    CorrespondenceProver,
    RecompileError,
    compare_runtime,
    expand_source_map,
    find_solc,
    prepare_standard_json,
    recompile,
    sha256_hex,
)

#: A runtime with a trailing Solidity-style metadata trailer.
EXECUTABLE = bytes.fromhex("60006000f4")

#: A runtime whose interesting opcode is an SSTORE.
EXECUTABLE_WITH_STORE = bytes.fromhex("6000600055")


def _metadata(content_hash: str) -> bytes:
    """Build a real Solidity metadata trailer.

    The trailer is a CBOR map carrying a ``bzzr0`` key, followed by its
    two-byte big-endian length. Building a *real* one matters: the detector
    is conservative, and a hand-rolled fake would not be recognised as
    metadata at all.

    Args:
        content_hash: The hex content hash to embed.

    Returns:
        The trailer bytes.
    """
    payload = bytes.fromhex("a165627a7a72305820") + bytes.fromhex(content_hash)
    return payload + len(payload).to_bytes(2, "big")


METADATA = _metadata("11" * 32)
OTHER_METADATA = _metadata("22" * 32)
RUNTIME = EXECUTABLE + METADATA


# --------------------------------------------------------------------------
# expand_source_map
# --------------------------------------------------------------------------


def test_an_empty_entry_inherits_the_previous_range() -> None:
    """solc's compressed map inherits an omitted field from the previous entry."""
    ranges = expand_source_map(["10:5", "", "20:7"])
    assert ranges[0] == (10, 5)
    assert ranges[1] == (10, 5)
    assert ranges[2] == (20, 7)


def test_a_wholly_empty_entry_inherits_everything() -> None:
    """An entry with no fields at all inherits the previous start and length."""
    ranges = expand_source_map(["10:5", ":"])
    assert ranges[1] == (10, 5)


def test_a_leading_empty_entry_has_no_range() -> None:
    """Nothing precedes the first entry, so nothing is known yet."""
    ranges = expand_source_map(["", "10:5"])
    assert ranges[0] is None
    assert ranges[1] == (10, 5)


# --------------------------------------------------------------------------
# compare_runtime
# --------------------------------------------------------------------------


def test_an_identical_runtime_matches() -> None:
    """The same bytes twice are a match."""
    matches, why = compare_runtime(RUNTIME, RUNTIME)
    assert matches is True
    assert "byte-identical" in why


def test_a_metadata_difference_does_not_break_correspondence() -> None:
    """The metadata trailer is non-executable, so it cannot break the proof."""
    other = EXECUTABLE + OTHER_METADATA
    matches, why = compare_runtime(RUNTIME, other)
    assert matches is True
    assert "executable code identical" in why
    assert "metadata trailer differs" in why


def test_a_differing_executable_byte_is_a_real_mismatch() -> None:
    """A difference in executable code is a genuine mismatch."""
    other = bytearray(EXECUTABLE)
    other[2] = 0x01
    matches, why = compare_runtime(EXECUTABLE, bytes(other))
    assert matches is False
    assert "first differing byte at offset 0x2" in why


def test_a_length_difference_is_a_mismatch() -> None:
    """A runtime of a different length cannot correspond."""
    matches, why = compare_runtime(EXECUTABLE, EXECUTABLE + b"\x00")
    assert matches is False
    assert "length differs" in why


# --------------------------------------------------------------------------
# prepare_standard_json
# --------------------------------------------------------------------------


def test_a_missing_output_selection_is_injected() -> None:
    """Sourcify stores no output selection, so one is injected."""
    text, injected, _fetched = prepare_standard_json({"settings": {"optimizer": {}}})
    assert injected is True
    document = json.loads(text)
    assert "outputSelection" in document["settings"]
    assert document["settings"]["optimizer"] == {}


def test_an_existing_output_selection_is_left_alone() -> None:
    """The verification's own selection is never replaced."""
    original = {"*": {"*": ["evm.bytecode"]}}
    text, injected, _fetched = prepare_standard_json({"settings": {"outputSelection": original}})
    assert injected is False
    assert json.loads(text)["settings"]["outputSelection"] == original


def test_sources_given_by_url_are_reported() -> None:
    """A source fetched over the network makes the recompilation less hermetic."""
    _text, _injected, fetched = prepare_standard_json(
        {
            "sources": {
                "A.sol": {"urls": ["https://example.invalid/A.sol"]},
                "B.sol": {"content": "x"},
            }
        }
    )
    assert fetched == ["A.sol"]


# --------------------------------------------------------------------------
# recompile
# --------------------------------------------------------------------------


def _fake_solc(tmp_path: Path, body: str, exit_code: int = 0) -> Path:
    """Write a fake solc that prints ``body`` and exits with ``exit_code``.

    A bare Python file cannot be executed directly by ``subprocess`` on
    Windows, so a batch wrapper is written alongside it. The wrapper invokes
    the interpreter running the tests, so it never depends on what happens
    to be on ``PATH``.

    Args:
        tmp_path: The directory to write into.
        body: What the fake compiler should print.
        exit_code: What the fake compiler should exit with.

    Returns:
        The path to the executable wrapper.
    """
    script = tmp_path / "fake_solc.py"
    script.write_text(
        f"import sys\nsys.stdin.read()\nsys.stdout.write({body!r})\nsys.exit({exit_code})\n",
        encoding="utf-8",
    )
    if os.name == "nt":
        wrapper = tmp_path / "fake_solc.cmd"
        wrapper.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
        return wrapper
    wrapper = tmp_path / "fake_solc.sh"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    return wrapper


def test_a_successful_compile_returns_the_compiler_output(tmp_path: Path) -> None:
    """A normal compiler run returns its JSON."""
    solc = _fake_solc(tmp_path, json.dumps({"contracts": {}}))
    output = recompile("{}", solc, timeout=30)
    assert output == {"contracts": {}}


def test_non_json_output_is_a_recompile_error(tmp_path: Path) -> None:
    """A compiler that emits nonsense could not be run, so it is not a mismatch."""
    solc = _fake_solc(tmp_path, "not json at all")
    with pytest.raises(RecompileError):
        recompile("{}", solc, timeout=30)


def test_a_crashing_compiler_is_a_recompile_error(tmp_path: Path) -> None:
    """A non-zero exit means the compiler failed, not that the source mismatched."""
    solc = _fake_solc(tmp_path, "", exit_code=1)
    with pytest.raises(RecompileError):
        recompile("{}", solc, timeout=30)


def test_a_hanging_compiler_is_a_recompile_error(tmp_path: Path) -> None:
    """A compiler that never finishes is an error, not a verdict."""
    solc = tmp_path / "slow_solc.py"
    solc.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    with pytest.raises(RecompileError):
        recompile("{}", solc, timeout=1)


def test_a_missing_compiler_is_a_recompile_error(tmp_path: Path) -> None:
    """A compiler that cannot even be started is an error."""
    with pytest.raises(RecompileError):
        recompile("{}", tmp_path / "does-not-exist", timeout=5)


# --------------------------------------------------------------------------
# find_solc
# --------------------------------------------------------------------------


def test_a_compiler_is_found_in_the_solc_select_layout(tmp_path: Path) -> None:
    """The layout solc-select uses is searched."""
    directory = tmp_path / "solc-0.4.24"
    directory.mkdir()
    binary = directory / "solc-0.4.24"
    binary.write_text("x", encoding="utf-8")
    assert find_solc("0.4.24", str(tmp_path)) == binary


def test_a_compiler_is_found_in_the_flat_layout(tmp_path: Path) -> None:
    """The flatter layout some setups use is searched too."""
    directory = tmp_path / "0.4.24"
    directory.mkdir()
    binary = directory / "solc-0.4.24.exe"
    binary.write_text("x", encoding="utf-8")
    assert find_solc("0.4.24", str(tmp_path)) == binary


def test_a_missing_compiler_is_not_an_error(tmp_path: Path) -> None:
    """A missing compiler yields ``None``, so the caller can skip."""
    assert find_solc("0.9.9", str(tmp_path)) is None


# --------------------------------------------------------------------------
# CorrespondenceProver
# --------------------------------------------------------------------------


class _StubProver(CorrespondenceProver):
    """A prover whose network is replaced."""

    def __init__(self, document: Any, **kwargs: Any) -> None:
        """Create the stub.

        Args:
            document: The verification record, or the exception to raise.
            **kwargs: Passed to the base class.
        """
        super().__init__(**kwargs)
        self._document = document

    def _fetch_document(self, address: str, chain_id: str) -> dict[str, Any]:
        """Return the stubbed verification record.

        Args:
            address: The contract address.
            chain_id: The chain id.

        Returns:
            The stubbed document.

        Raises:
            OSError: When the stub is configured to fail.
        """
        if isinstance(self._document, Exception):
            raise self._document
        return self._document


def _document(
    *,
    compiler_version: str = "0.8.26+commit.8a97fa7a",
    std_json: Any = None,
    source: str = "contract A { function f() public { assembly { sstore(0, 1) } } }",
) -> dict[str, Any]:
    """Build a stub Sourcify document.

    Args:
        compiler_version: The compiler version to claim.
        std_json: The stored compiler input, or ``None`` to omit it.
        source: The source content.

    Returns:
        The document.
    """
    document: dict[str, Any] = {
        "matchId": "1",
        "compilation": {"compilerVersion": compiler_version},
        "sources": {"A.sol": {"content": source}},
    }
    if std_json is not None:
        document["stdJsonInput"] = std_json
    return document


def test_an_unreachable_verification_record_is_unavailable() -> None:
    """Nothing was learned, so nothing may be claimed."""
    prover = _StubProver(OSError("network down"))
    outcome = prover.prove("0xabc", "1", RUNTIME)
    assert outcome.status is CorrespondenceStatus.UNAVAILABLE
    assert outcome.established is False
    assert outcome.skipped == "verification_record_unreachable"


def test_a_record_without_a_compiler_input_is_skipped() -> None:
    """There is nothing to recompile, so the check is skipped."""
    prover = _StubProver(_document())
    outcome = prover.prove("0xabc", "1", RUNTIME)
    assert outcome.status is CorrespondenceStatus.SKIPPED
    assert outcome.skipped == "no_standard_json_input"


def test_a_record_without_a_compiler_version_is_skipped() -> None:
    """The compiler cannot be located without a version."""
    prover = _StubProver(_document(compiler_version="", std_json={"sources": {}, "settings": {}}))
    outcome = prover.prove("0xabc", "1", RUNTIME)
    assert outcome.status is CorrespondenceStatus.SKIPPED
    assert outcome.skipped == "no_compiler_version"


def test_a_missing_compiler_is_skipped_not_mismatched(tmp_path: Path) -> None:
    """An uninstalled compiler means no verdict at all."""
    prover = _StubProver(
        _document(std_json={"sources": {}, "settings": {}}),
        artifacts_dir=str(tmp_path),
    )
    outcome = prover.prove("0xabc", "1", RUNTIME)
    assert outcome.status is CorrespondenceStatus.SKIPPED
    assert outcome.skipped == "compiler_not_installed"


def test_a_crashing_compiler_is_unavailable_not_mismatched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A compiler that cannot be run must never be reported as a mismatch."""
    import app.services.correspondence as module

    def _boom(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RecompileError("solc died")

    monkeypatch.setattr(module, "recompile", _boom)
    monkeypatch.setattr(module, "find_solc", lambda *a, **k: tmp_path / "solc")

    prover = _StubProver(
        _document(std_json={"sources": {}, "settings": {}}),
        artifacts_dir=str(tmp_path),
    )
    outcome = prover.prove("0xabc", "1", RUNTIME)
    assert outcome.status is CorrespondenceStatus.UNAVAILABLE
    assert outcome.skipped == "compiler_could_not_run"


def test_a_differing_recompilation_is_a_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The check ran and the source does not describe the deployed contract."""
    import app.services.correspondence as module

    monkeypatch.setattr(
        module,
        "recompile",
        lambda *a, **k: {
            "contracts": {"A.sol": {"A": {"evm": {"deployedBytecode": {"object": "60016000f4"}}}}}
        },
    )
    monkeypatch.setattr(module, "find_solc", lambda *a, **k: tmp_path / "solc")

    prover = _StubProver(
        _document(std_json={"sources": {}, "settings": {}}),
        artifacts_dir=str(tmp_path),
    )
    outcome = prover.prove("0xabc", "1", EXECUTABLE)
    assert outcome.status is CorrespondenceStatus.MISMATCH
    assert outcome.established is False


def test_an_identical_recompilation_establishes_the_proof(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The check ran and the executable code is identical."""
    import app.services.correspondence as module

    monkeypatch.setattr(
        module,
        "recompile",
        lambda *a, **k: {
            "contracts": {
                "A.sol": {
                    "A": {
                        "evm": {
                            "deployedBytecode": {
                                "object": EXECUTABLE.hex(),
                                "sourceMap": "0:10:0:-:0:0",
                            }
                        }
                    }
                }
            }
        },
    )
    monkeypatch.setattr(module, "find_solc", lambda *a, **k: tmp_path / "solc")

    prover = _StubProver(
        _document(std_json={"sources": {}, "settings": {}}),
        artifacts_dir=str(tmp_path),
    )
    outcome = prover.prove("0xabc", "1", EXECUTABLE)
    assert outcome.status is CorrespondenceStatus.ESTABLISHED
    assert outcome.established is True
    assert outcome.source_path == "A.sol"
    assert outcome.runtime_sha256 == sha256_hex(EXECUTABLE)
    assert outcome.executable_sha256 == sha256_hex(EXECUTABLE)
    assert outcome.instruction_count is not None and outcome.instruction_count > 0


def test_the_established_proof_records_the_source_lines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The compiler's own source map turns an offset into a file and line."""
    import app.services.correspondence as module

    source = "line one\nline two\nline three\n"
    monkeypatch.setattr(
        module,
        "recompile",
        lambda *a, **k: {
            "contracts": {
                "A.sol": {
                    "A": {
                        "evm": {
                            "deployedBytecode": {
                                "object": EXECUTABLE_WITH_STORE.hex(),
                                "sourceMap": "0:8:0:-:0:0;0:8:0:-:0:0;0:8:0:-:0:0",
                            }
                        }
                    }
                }
            }
        },
    )
    monkeypatch.setattr(module, "find_solc", lambda *a, **k: tmp_path / "solc")

    prover = _StubProver(
        _document(std_json={"sources": {}, "settings": {}}, source=source),
        artifacts_dir=str(tmp_path),
    )
    outcome = prover.prove("0xabc", "1", EXECUTABLE_WITH_STORE)
    assert outcome.status is CorrespondenceStatus.ESTABLISHED
    assert outcome.locations
    location = outcome.locations[0]
    assert location.file == "A.sol"
    assert location.line == 1
    assert location.snippet == "line one"


def test_the_evidence_payload_carries_the_proof() -> None:
    """The stored payload is JSON-serialisable and complete."""
    outcome = CorrespondenceOutcome(
        status=CorrespondenceStatus.ESTABLISHED,
        detail="executable code identical",
        compiler_version="0.8.26",
        source_path="A.sol",
        runtime_sha256="a" * 64,
        executable_sha256="b" * 64,
        metadata_sha256="c" * 64,
        runtime_byte_size=10,
        executable_byte_size=5,
        instruction_count=3,
        mapped_instruction_count=1,
    )
    evidence = outcome.to_evidence()
    assert json.loads(json.dumps(evidence)) == evidence
    assert evidence["status"] == "established"
    assert evidence["compilerVersion"] == "0.8.26"


def test_the_fake_compiler_helper_produces_a_runnable_script(tmp_path: Path) -> None:
    """The helper itself is exercised, so the tests cannot rot silently."""
    solc = _fake_solc(tmp_path, json.dumps({"ok": True}))
    completed = subprocess.run(  # noqa: S603 - test helper, fixed argv
        [str(solc)], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0
