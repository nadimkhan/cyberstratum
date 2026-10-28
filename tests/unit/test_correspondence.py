"""Tests for the source-to-bytecode correspondence comparison.

The gate is what decides whether a source file and line may be claimed for a
deployed contract. It has to reject a genuine mismatch and accept a genuine
match, so both directions are tested here.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "live_check_correspondence.py"


def _load_module():
    """Load the live-check script as a module."""
    spec = importlib.util.spec_from_file_location("live_check_correspondence", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


module = _load_module()


def _metadata_trailer(content_hash: bytes) -> bytes:
    """Build a minimal solc-style CBOR metadata trailer.

    Args:
        content_hash: The 32-byte content hash to embed.

    Returns:
        The trailer bytes.
    """
    assert len(content_hash) == 32
    # a1 = map(1), 62 7a 72 30 = text(2) "z0", 58 20 = bytes(32)
    return bytes.fromhex("a165627a7a72305820") + content_hash + bytes.fromhex("0029")


def test_identical_runtime_is_accepted():
    code = bytes.fromhex("6001600055")
    ok, why = module.compare_runtime(code, code)
    assert ok
    assert "byte-identical" in why


def test_metadata_only_difference_is_accepted():
    """The metadata trailer is non-executable, so it cannot break a match."""
    code = bytes.fromhex("6001600055")
    onchain = code + _metadata_trailer(b"\x01" * 32)
    recompiled = code + _metadata_trailer(b"\x02" * 32)
    ok, why = module.compare_runtime(onchain, recompiled)
    assert ok, why
    assert "executable code identical" in why
    assert "metadata" in why


def test_executable_difference_is_rejected():
    """A real difference in the code must fail the gate."""
    onchain = bytes.fromhex("6001600055")
    recompiled = bytes.fromhex("6002600055")
    ok, why = module.compare_runtime(onchain, recompiled)
    assert not ok
    assert "executable code differs" in why
    assert "offset 0x1" in why
    assert "on-chain 0x01 vs recompiled 0x02" in why


def test_length_difference_is_rejected():
    onchain = bytes.fromhex("6001600055")
    recompiled = bytes.fromhex("600160005560")
    ok, why = module.compare_runtime(onchain, recompiled)
    assert not ok
    assert "length differs" in why


def test_metadata_does_not_hide_a_code_difference():
    """A difference hidden behind a metadata trailer is still rejected."""
    onchain = bytes.fromhex("6001600055") + _metadata_trailer(b"\x01" * 32)
    recompiled = bytes.fromhex("6002600055") + _metadata_trailer(b"\x01" * 32)
    ok, _why = module.compare_runtime(onchain, recompiled)
    assert not ok


def test_expand_source_map_inherits_previous_values():
    """An empty field inherits the previous value; an empty entry inherits all."""
    entries = ["10:20", ":30", "", "40:50"]
    ranges = module.expand_source_map(entries)
    assert ranges == [(10, 20), (10, 30), (10, 30), (40, 50)]


def test_expand_source_map_handles_dash():
    """A dash also means "inherit"."""
    ranges = module.expand_source_map(["10:20", "-:-"])
    assert ranges == [(10, 20), (10, 20)]


def test_expand_source_map_leaves_unknown_unresolved():
    """An entry before any known value stays unresolved."""
    assert module.expand_source_map(["", "-:-"]) == [None, None]


def test_find_solc_returns_none_when_absent():
    assert module._find_solc("0.0.0-not-a-real-version") is None


def test_find_solc_honours_solc_artifacts_dir(tmp_path, monkeypatch):
    """The compiler location must be overridable, or a machine whose
    compilers live elsewhere can never prove a correspondence."""
    artifacts = tmp_path / "artifacts"
    binary = artifacts / "solc-0.9.9" / "solc-0.9.9"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"")
    monkeypatch.setenv("SOLC_ARTIFACTS_DIR", str(artifacts))
    assert module._find_solc("0.9.9") == binary


def test_find_solc_accepts_the_flat_version_layout(tmp_path, monkeypatch):
    """Some setups keep the binary directly under the version directory."""
    artifacts = tmp_path / "artifacts"
    binary = artifacts / "0.9.9" / "solc-0.9.9"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"")
    monkeypatch.setenv("SOLC_ARTIFACTS_DIR", str(artifacts))
    assert module._find_solc("0.9.9") == binary


def _fake_solc(tmp_path, kind: str):
    """Write something that stands in for solc.

    Windows cannot execute a bare script file, so the stand-in is a ``.cmd``
    wrapper there and a shell script elsewhere.

    Args:
        tmp_path: Where to write it.
        kind: One of ``"hang"``, ``"crash"`` or ``"garbage"``.

    Returns:
        The path to the fake compiler.
    """
    if os.name == "nt":
        script = tmp_path / "fake_solc.cmd"
        # A builtin loop, not a child process: a killed parent leaves a
        # child holding the output pipe open, and the test would then wait
        # for the child instead of failing fast.
        bodies = {
            "hang": "@for /l %%i in (1,1,200000000) do @rem",
            "crash": "@echo boom 1>&2\r\n@exit /b 1",
            "garbage": "@echo not json at all",
        }
        script.write_text(bodies[kind] + "\r\n", encoding="utf-8")
        return script

    script = tmp_path / "fake_solc"
    bodies = {
        "hang": "while true; do :; done",
        "crash": "echo boom >&2\nexit 1",
        "garbage": "echo 'not json at all'",
    }
    script.write_text(f"#!/bin/sh\n{bodies[kind]}\n", encoding="utf-8")
    script.chmod(0o755)
    return script


def test_a_hung_compiler_is_an_error_not_a_mismatch(tmp_path):
    """A compiler that never finishes teaches us nothing.

    Reporting it as a mismatch would be a false negative, so it must be
    raised as a distinct failure.
    """
    compiler = _fake_solc(tmp_path, "hang")
    with pytest.raises(module.RecompileError) as caught:
        module._recompile("{}", compiler, timeout=1.0)
    assert "did not finish" in str(caught.value)


def test_a_crashing_compiler_is_an_error_not_a_mismatch(tmp_path):
    """A compiler that exits non-zero must not be read as a mismatch."""
    compiler = _fake_solc(tmp_path, "crash")
    with pytest.raises(module.RecompileError) as caught:
        module._recompile("{}", compiler)
    assert "exited with 1" in str(caught.value)
    assert "boom" in str(caught.value)


def test_a_compiler_that_emits_non_json_is_an_error(tmp_path):
    """solc printing something that is not JSON must not be parsed anyway."""
    compiler = _fake_solc(tmp_path, "garbage")
    with pytest.raises(module.RecompileError) as caught:
        module._recompile("{}", compiler)
    assert "did not emit JSON" in str(caught.value)


def test_a_compiler_that_cannot_be_run_is_an_error(tmp_path):
    """A missing binary is an error, not a mismatch."""
    with pytest.raises(module.RecompileError) as caught:
        module._recompile("{}", tmp_path / "does_not_exist")
    assert "could not be run" in str(caught.value)


def test_the_exit_codes_separate_a_mismatch_from_an_error():
    """The three outcomes must not be confused with one another."""
    assert module.EXIT_CORRESPONDENCE == 0
    assert module.EXIT_NO_CORRESPONDENCE == 1
    assert module.EXIT_COMPILER_ERROR == 2
    assert len({module.EXIT_CORRESPONDENCE, module.EXIT_NO_CORRESPONDENCE,
                module.EXIT_COMPILER_ERROR}) == 3
