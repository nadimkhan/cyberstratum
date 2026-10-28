"""Tests for the opcode tokenizer and n-gram construction."""

from __future__ import annotations

import pytest
from evm_ml.tokenize import (
    Normalization,
    address_like,
    build_ngrams,
    normalize_instruction,
    tokenize,
)

from evm_analysis import disassemble, load_fork

TABLE = load_fork("cancun")


def _instructions(code: str) -> list:
    return disassemble(bytes.fromhex(code), TABLE).instructions


def test_raw_tokens_keep_the_opcode_name():
    instructions = _instructions("6001600201")
    stream = tokenize(instructions, Normalization())
    assert stream.raw_tokens == ("PUSH1", "PUSH1", "ADD")


def test_normalised_stream_collapses_push_width():
    instructions = _instructions("6001600201")
    stream = tokenize(instructions, Normalization())
    assert stream.normalized_tokens == ("PUSH:<CONST>", "PUSH:<CONST>", "ADD")


def test_normalisation_can_be_switched_off():
    instructions = _instructions("6001600201")
    options = Normalization(
        collapse_push_width=False,
        mask_constants=False,
        mask_addresses=False,
    )
    stream = tokenize(instructions, options)
    assert stream.normalized_tokens == ("PUSH1", "PUSH1", "ADD")


def test_address_sized_immediates_are_masked_as_addresses():
    address = "11" * 20
    instructions = _instructions(f"7f{address}")
    stream = tokenize(instructions, Normalization())
    assert stream.normalized_tokens == ("PUSH:<ADDR>",)


def test_shorter_immediates_are_masked_as_constants():
    instructions = _instructions("6312345678")
    stream = tokenize(instructions, Normalization())
    assert stream.normalized_tokens == ("PUSH:<CONST>",)


def test_address_like_only_matches_twenty_byte_values():
    assert address_like(bytes(20))
    assert not address_like(bytes(19))
    assert not address_like(bytes(21))


def test_non_push_opcodes_are_untouched_by_normalisation():
    instructions = _instructions("600156")
    stream = tokenize(instructions, Normalization())
    assert stream.normalized_tokens[-1] == "JUMP"


def test_normalize_instruction_uses_the_instruction_name():
    instructions = _instructions("60ff")
    assert normalize_instruction(instructions[0], Normalization()) == "PUSH:<CONST>"


def test_push0_is_available_on_cancun_and_kept_distinct():
    instructions = _instructions("5f")
    assert instructions[0].name == "PUSH0"
    stream = tokenize(instructions, Normalization())
    assert stream.normalized_tokens == ("PUSH0:<CONST>",)


def test_push0_can_be_collapsed_into_push():
    instructions = _instructions("5f")
    options = Normalization(preserve_push0=False)
    stream = tokenize(instructions, options)
    assert stream.normalized_tokens == ("PUSH:<CONST>",)


def test_raw_and_normalised_documents_are_kept_separate():
    instructions = _instructions("6001600201")
    stream = tokenize(instructions, Normalization())
    assert stream.raw != stream.normalized
    assert stream.documents == (stream.raw, stream.normalized)


def test_ngrams_have_the_expected_count():
    assert build_ngrams(["A", "B", "C", "D"], 3) == ["A B C", "B C D"]


def test_ngrams_shorter_than_n_are_kept_as_one_gram():
    assert build_ngrams(["A", "B"], 3) == ["A B"]


def test_ngrams_of_an_empty_sequence_are_empty():
    assert build_ngrams([], 3) == []


def test_ngram_size_must_be_positive():
    with pytest.raises(ValueError, match="n must be >= 1"):
        build_ngrams(["A"], 0)


def test_metadata_is_not_tokenised_as_executable_code():
    # A PUSH1 0x00 followed by a CBOR trailer that encodes a Solidity
    # metadata map, with the two-byte length suffix that Solidity appends.
    def _text(value: bytes) -> bytes:
        if len(value) < 24:
            return bytes([0x60 | len(value)]) + value
        return bytes([0x78, len(value)]) + value

    version = b"0.8.24+commit.e11b9ed9"
    ipfs_hash = bytes(34)

    cbor = bytearray()
    cbor.append(0xA2)  # a map with two entries
    cbor += _text(b"solc")
    cbor += _text(version)
    cbor += _text(b"ipfs")
    cbor += bytes([0x58, len(ipfs_hash)]) + ipfs_hash
    # Solidity appends the length of the CBOR map as the final two bytes.
    payload = bytes(cbor) + len(cbor).to_bytes(2, "big")

    code = bytes.fromhex("6000") + payload

    disassembly = disassemble(code, TABLE)
    assert disassembly.metadata is not None

    # Only the executable prefix is tokenised: the trailer contributes
    # no instructions.
    assert len(disassembly.instructions) == 1
    stream = tokenize(disassembly.instructions, Normalization())
    assert stream.raw_tokens == ("PUSH1",)
    assert disassembly.metadata.raw == payload
