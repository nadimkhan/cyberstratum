"""Tests for the source-to-bytecode correspondence comparison.

The gate is what decides whether a source file and line may be claimed for a
deployed contract. It has to reject a genuine mismatch and accept a genuine
match, so both directions are tested here.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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
