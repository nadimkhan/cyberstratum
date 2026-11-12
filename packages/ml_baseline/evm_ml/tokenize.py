"""Opcode tokenization and N-gram construction.

The product design requires that the model consumes *decoded instructions*
rather than raw hex bytes (design doc section 6.2). This module turns a
disassembled instruction stream into token documents.

Two token streams are produced from every contract and kept separate:

``raw``
    The opcode name exactly as decoded, with ``PUSH1``..``PUSH32`` kept
    distinct and no immediate data included.

``normalized``
    A normalisation of the raw stream in which the ``PUSH`` width is
    collapsed, immediate constants are masked, and address-like constants
    are masked separately.

Keeping the two streams separate (rather than concatenating them into one
document) lets the training pipeline fit two independent vocabularies and
lets an analyst attribute a signal to either the raw or the normalised
view.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from evm_analysis import Instruction

__all__ = [
    "Normalization",
    "TokenStream",
    "address_like",
    "build_ngrams",
    "normalize_instruction",
    "tokenize",
]

#: Opcode names that carry an immediate operand.
_PUSH_OPCODES: Final[frozenset[str]] = frozenset([f"PUSH{n}" for n in range(1, 33)] + ["PUSH0"])

#: A PUSH whose immediate is exactly this wide is treated as an address.
_ADDRESS_WIDTH: Final[int] = 20


@dataclass(frozen=True)
class Normalization:
    """Normalisation options applied when producing the normalised stream.

    The defaults match the MVP settings in design doc section 6.2. Every
    option is recorded in the model artifact manifest so that a trained
    model can always be reproduced.
    """

    collapse_push_width: bool = True
    mask_constants: bool = True
    mask_addresses: bool = True
    preserve_push0: bool = True

    def as_dict(self) -> dict[str, bool]:
        return {
            "collapse_push_width": self.collapse_push_width,
            "mask_constants": self.mask_constants,
            "mask_addresses": self.mask_addresses,
            "preserve_push0": self.preserve_push0,
        }


@dataclass(frozen=True)
class TokenStream:
    """The token documents for a single contract."""

    raw: str
    normalized: str
    raw_tokens: tuple[str, ...]
    normalized_tokens: tuple[str, ...]

    @property
    def documents(self) -> tuple[str, str]:
        """The two documents, in a fixed order."""
        return (self.raw, self.normalized)


def address_like(value: bytes) -> bool:
    """Return whether a PUSH immediate looks like a 20-byte address.

    A 20-byte immediate is treated as address-like. This is a heuristic on
    the encoding only; it makes no claim about what the value means.
    """
    return len(value) == _ADDRESS_WIDTH


def normalize_instruction(instruction: Instruction, options: Normalization) -> str:
    """Return the normalised token for a single instruction."""
    name = instruction.name

    if name not in _PUSH_OPCODES:
        return name

    # PUSH0 is kept distinct by default: it is a distinct compiler output
    # from Shanghai onwards, and collapsing it into PUSH1 0x00 would hide
    # that signal.
    is_push0 = name == "PUSH0"
    if options.collapse_push_width and not (is_push0 and options.preserve_push0):
        name = "PUSH"

    if not options.mask_constants:
        return str(name)

    immediate = instruction.immediate or b""
    if options.mask_addresses and address_like(immediate):
        return f"{name}:<ADDR>"
    return f"{name}:<CONST>"


def tokenize(instructions: list[Instruction], options: Normalization) -> TokenStream:
    """Build the raw and normalised token streams for an instruction list.

    Only the executable prefix of the contract is tokenised: the Solidity
    metadata trailer is not executable code and must not contribute
    features (design doc section 6.2).
    """
    raw_tokens = tuple(instruction.name for instruction in instructions)
    normalized_tokens = tuple(
        normalize_instruction(instruction, options) for instruction in instructions
    )
    return TokenStream(
        raw=" ".join(raw_tokens),
        normalized=" ".join(normalized_tokens),
        raw_tokens=raw_tokens,
        normalized_tokens=normalized_tokens,
    )


def build_ngrams(tokens: list[str] | tuple[str, ...], n: int) -> list[str]:
    """Return the n-grams of a token sequence.

    A sequence shorter than ``n`` yields a single gram containing all of
    its tokens, so that very short contracts are still represented rather
    than silently dropped.
    """
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    token_list = list(tokens)
    if not token_list:
        return []
    if len(token_list) < n:
        return [" ".join(token_list)]
    return [" ".join(token_list[i : i + n]) for i in range(len(token_list) - n + 1)]
