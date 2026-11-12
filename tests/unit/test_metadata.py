"""Tests for the Solidity metadata (CBOR) trailer detection."""

from __future__ import annotations

import pytest

from evm_analysis.disassembler import disassemble
from evm_analysis.metadata import (
    CborError,
    decode_cbor,
    detect_solidity_metadata,
    split_metadata,
)
from evm_analysis.opcodes import load_fork


def _cbor_head(major: int, length: int) -> bytes:
    """Encode a CBOR head with the given major type and argument.

    Lengths below 24 use the immediate form; longer ones use the 8/16/32-bit
    forms, exactly as a real CBOR encoder does.
    """
    if length < 24:
        return bytes([(major << 5) | length])
    if length < 0x100:
        return bytes([(major << 5) | 24, length])
    if length < 0x10000:
        return bytes([(major << 5) | 25]) + length.to_bytes(2, "big")
    return bytes([(major << 5) | 26]) + length.to_bytes(4, "big")


def _cbor_map(entries: dict[str, bytes | str]) -> bytes:
    """Encode a flat CBOR map of text keys to byte/text values."""
    out = bytearray()
    out.extend(_cbor_head(5, len(entries)))
    for key, value in entries.items():
        key_bytes = key.encode("utf-8")
        out.extend(_cbor_head(3, len(key_bytes)))
        out.extend(key_bytes)
        if isinstance(value, str):
            value_bytes = value.encode("utf-8")
            out.extend(_cbor_head(3, len(value_bytes)))
        else:
            value_bytes = value
            out.extend(_cbor_head(2, len(value_bytes)))
        out.extend(value_bytes)
    return bytes(out)


def _with_metadata(code: bytes, entries: dict[str, bytes | str]) -> bytes:
    payload = _cbor_map(entries)
    return code + payload + len(payload).to_bytes(2, "big")


MODERN = {"solc": "0.8.24+commit.e11b9ed9", "ipfs": bytes(range(34))}
LEGACY = {"bzzr0": bytes(range(32))}


def test_detects_modern_metadata() -> None:
    code = _with_metadata(b"\x60\x80", MODERN)
    region = detect_solidity_metadata(code)
    assert region is not None
    assert region.cbor_length == len(_cbor_map(MODERN))
    assert region.length == region.cbor_length + 2
    assert region.start_offset == 2
    assert region.compiler_version == "0.8.24+commit.e11b9ed9"
    assert region.confidence == "high"
    assert region.end_offset == len(code)


def test_detects_legacy_metadata_without_solc_key() -> None:
    # Pre-0.4.7 solc wrote only a bzzr0 hash and no compiler version.
    code = _with_metadata(b"\x60\x80", LEGACY)
    region = detect_solidity_metadata(code)
    assert region is not None
    assert region.compiler_version is None
    assert region.confidence == "medium"
    assert "bzzr0_hash" in region.entries


def test_no_metadata_on_plain_code() -> None:
    assert detect_solidity_metadata(b"\x60\x80\x60\x40\x52") is None
    assert detect_solidity_metadata(b"") is None
    assert detect_solidity_metadata(b"\x00") is None


def test_length_field_must_be_consistent() -> None:
    payload = _cbor_map(MODERN)
    # A length field that points past the start of the code.
    code = payload + (len(payload) + 100).to_bytes(2, "big")
    assert detect_solidity_metadata(code) is None

    # A length field of zero.
    code = payload + (0).to_bytes(2, "big")
    assert detect_solidity_metadata(code) is None


def test_cbor_without_a_solc_key_is_not_metadata() -> None:
    # A well-formed CBOR map that is not a Solidity metadata blob.
    payload = _cbor_map({"hello": "world"})
    code = b"\x60\x80" + payload + len(payload).to_bytes(2, "big")
    assert detect_solidity_metadata(code) is None


def test_split_metadata_preserves_the_original_bytes() -> None:
    code = _with_metadata(b"\x60\x80", MODERN)
    executable, region = split_metadata(code)
    assert region is not None
    assert executable == b"\x60\x80"
    assert code.startswith(executable)
    assert region.raw == code[len(executable) :]


def test_decode_cbor_rejects_trailing_bytes() -> None:
    payload = _cbor_map(MODERN)
    with pytest.raises(CborError):
        decode_cbor(payload + b"\x00")


def test_decode_cbor_round_trip() -> None:
    payload = _cbor_map({"solc": "0.8.24"})
    assert decode_cbor(payload) == {"solc": "0.8.24"}


def test_disassembler_stops_before_the_metadata() -> None:
    table = load_fork("cancun")
    code = _with_metadata(b"\x60\x80\x00", MODERN)
    disassembly = disassemble(code, table)

    assert disassembly.metadata is not None
    assert disassembly.code_size == len(code)
    assert disassembly.executable_size == 3
    # PUSH1 0x80, STOP -- and nothing from the metadata region.
    assert [i.name for i in disassembly.instructions] == ["PUSH1", "STOP"]
    assert any("metadata" in note for note in disassembly.notes)


def test_disassembler_can_skip_metadata_detection() -> None:
    table = load_fork("cancun")
    code = _with_metadata(b"\x60\x80\x00", MODERN)
    disassembly = disassemble(code, table, detect_metadata=False)
    assert disassembly.metadata is None
    assert disassembly.executable_size == len(code)
