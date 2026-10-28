"""Fork-aware EVM opcode table.

The table is a vendored, generated artifact (``data/opcodes.json``) produced by
``scripts/generate_opcodes.mjs``. It is derived from:

* ``ethereum/execution-specs`` for per-fork opcode *availability* and canonical
  names (``PUSH1``..``PUSH32``, ``DUP1``..``DUP16``, ...);
* ``evm-opcodes`` (Yellow-Paper derived) and ``@ethereumjs/evm`` (EIP-5450
  metadata) for *stack effects*.

Loading is strict: an unknown fork or a malformed table raises rather than
silently degrading, because a wrong opcode table would corrupt every downstream
finding.
"""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "opcodes.json"

Fork = Literal[
    "frontier",
    "homestead",
    "tangerine_whistle",
    "spurious_dragon",
    "byzantium",
    "constantinople",
    "petersburg",
    "istanbul",
    "berlin",
    "london",
    "paris",
    "shanghai",
    "cancun",
    "prague",
]

#: Forks in chronological order. Used for ordering and for validating that a
#: requested fork is supported.
FORK_ORDER: tuple[Fork, ...] = (
    "frontier",
    "homestead",
    "tangerine_whistle",
    "spurious_dragon",
    "byzantium",
    "constantinople",
    "petersburg",
    "istanbul",
    "berlin",
    "london",
    "paris",
    "shanghai",
    "cancun",
    "prague",
)

#: The designated invalid opcode. It is never a real instruction: encountering
#: it means the bytecode is invalid at that offset.
INVALID_OPCODE = 0xFE

#: Alternate spellings used by other EVM toolchains, mapped to the canonical
#: name used in the vendored table. The vendored table keeps the names from
#: ``ethereum/execution-specs`` verbatim so it stays reproducible from its
#: source; this table exists so that names coming from other tools
#: (``evmole``, ``solc``, EthereumJS) can be compared without renames
#: leaking into the comparison logic.
OPCODE_ALIASES: dict[str, str] = {
    "KECCAK256": "KECCAK",
}


@dataclass(frozen=True, slots=True)
class Opcode:
    """A single opcode definition within a specific fork."""

    code: int
    name: str
    push_bytes: int
    stack_in: int
    stack_out: int
    terminating: bool

    @property
    def stack_delta(self) -> int:
        """Net change to stack depth contributed by this instruction."""
        return self.stack_out - self.stack_in

    @property
    def is_push(self) -> bool:
        return self.name.startswith("PUSH")

    @property
    def is_jump(self) -> bool:
        return self.name in {"JUMP", "JUMPI"}

    @property
    def is_jumpdest(self) -> bool:
        return self.name == "JUMPDEST"


@dataclass(frozen=True, slots=True)
class ForkTable:
    """The opcode set for one fork."""

    fork: str
    opcodes: dict[int, Opcode]
    schema_version: str
    source: str

    def get(self, code: int) -> Opcode | None:
        """Return the opcode for ``code``, or ``None`` if the fork lacks it."""
        return self.opcodes.get(code)

    def __contains__(self, code: int) -> bool:
        return code in self.opcodes


def _parse_entry(raw: dict[str, Any]) -> Opcode:
    stack_in = raw.get("stackIn")
    stack_out = raw.get("stackOut")
    if not isinstance(stack_in, int) or not isinstance(stack_out, int):
        raise ValueError(f"opcode {raw.get('name')!r} is missing a stack effect")
    try:
        return Opcode(
            code=int(raw["code"]),
            name=str(raw["name"]),
            push_bytes=int(raw["pushBytes"]),
            stack_in=stack_in,
            stack_out=stack_out,
            terminating=bool(raw.get("terminating", False)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed opcode entry {raw!r}") from exc


@functools.lru_cache(maxsize=1)
def _load_raw() -> dict[str, Any]:
    if not DATA_PATH.exists():
        raise FileNotFoundError(
            f"opcode table not found at {DATA_PATH}. "
            "Run `npm run generate:opcodes` to regenerate it."
        )
    with DATA_PATH.open(encoding="utf-8") as fh:
        raw: dict[str, Any] = json.load(fh)
        return raw


@functools.cache
def load_fork(fork: str) -> ForkTable:
    """Load the opcode table for ``fork``.

    Raises ``ValueError`` for an unsupported fork.
    """
    raw: dict[str, Any] = _load_raw()
    forks = raw.get("forks", [])
    if fork not in forks:
        raise ValueError(f"unsupported EVM fork {fork!r}; supported: {', '.join(forks)}")

    entries = raw["opcodes"][fork]
    opcodes: dict[int, Opcode] = {}
    for item in entries:
        opcode = _parse_entry(item)
        if opcode.code in opcodes:
            raise ValueError(f"duplicate opcode 0x{opcode.code:02x} in fork {fork!r}")
        opcodes[opcode.code] = opcode

    sources = raw.get("sources", {})
    source = sources.get("opcodes", "unknown")
    return ForkTable(
        fork=fork,
        opcodes=opcodes,
        schema_version=raw.get("schemaVersion", "unknown"),
        source=source,
    )


def canonical_opcode_name(name: str) -> str:
    """Normalise an opcode name coming from another toolchain."""
    return OPCODE_ALIASES.get(name.upper(), name)


def supported_forks() -> tuple[str, ...]:
    """Return every fork the vendored table covers, oldest first."""
    raw = _load_raw()
    return tuple(raw.get("forks", FORK_ORDER))


def normalize_fork(fork: str) -> str:
    """Normalise a fork name (case/spacing tolerant)."""
    candidate = fork.strip().lower().replace("-", "_").replace(" ", "_")
    if candidate not in supported_forks():
        raise ValueError(f"unsupported EVM fork {fork!r}")
    return candidate
