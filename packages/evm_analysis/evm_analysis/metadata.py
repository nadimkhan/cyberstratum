"""Solidity metadata (CBOR) trailer detection.

Solc appends a CBOR-encoded metadata blob to the end of the *runtime* bytecode
(it is also present at the end of the *creation* bytecode). The blob is
delimited by a two-byte big-endian length that sits at the very end of the
code:

    ... executable code ... | CBOR metadata | length (2 bytes, big endian)

The metadata is **not executable**. Decoding it as instructions produces a
tail of nonsense ``INVALID`` opcodes, corrupts the CFG (the trailer's first
byte is usually a ``PUSH``-shaped byte, so a bogus block gets created) and
inflates the instruction count that every downstream artifact is keyed on.

The design doc (§6.4) requires this to be handled carefully: the metadata is
only removed when detection is reliable, and the original artifact must remain
available. This module therefore:

* never mutates the caller's bytes;
* reports *where* the metadata starts and what it contains;
* only claims a metadata region when the CBOR actually decodes to a map that
  carries a key solc writes, so a false positive requires a very specific
  coincidence.

The CBOR subset implemented here is the one solc emits: definite-length
maps, byte strings, text strings, unsigned/negative integers, arrays, booleans
and null.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: The canonical key solc writes into the metadata map.
SOLC_KEY = "solc"

#: Keys that identify a Solidity metadata map. Modern solc (>= 0.4.7) always
#: writes ``solc``; older compilers wrote only ``bzzr0``. A map carrying any of
#: these keys is a Solidity metadata blob.
_METADATA_KEYS = frozenset({"solc", "bzzr0", "bzzr1", "ipfs", "experimental"})

#: Keys solc may write, mapped to a stable name.
_KEY_NAMES = {
    "solc": "compiler_version",
    "ipfs": "ipfs_hash",
    "bzzr0": "bzzr0_hash",
    "experimental": "experimental",
    "bzzr1": "bzzr1_hash",
}

#: The number of trailing bytes that hold the CBOR length.
_LENGTH_FIELD_SIZE = 2


class CborError(ValueError):
    """Raised when a byte string is not valid CBOR in the supported subset."""


@dataclass(frozen=True, slots=True)
class MetadataRegion:
    """A detected Solidity metadata trailer."""

    start_offset: int
    """Byte offset of the first metadata byte within the code."""

    length: int
    """Total length of the region in bytes, including the 2-byte length field."""

    cbor_length: int
    """Length of the CBOR payload as declared by the trailing length field."""

    entries: dict[str, Any] = field(default_factory=dict)
    """Decoded top-level metadata entries, keyed by their CBOR text key."""

    raw: bytes = b""
    """The exact bytes of the region, so the original artifact is preserved."""

    @property
    def confidence(self) -> str:
        """``"high"`` when the compiler version is known, else ``"medium"``."""
        return "high" if self.has_compiler_version else "medium"

    @property
    def end_offset(self) -> int:
        """Offset one past the last byte of the region."""
        return self.start_offset + self.length

    @property
    def compiler_version(self) -> str | None:
        """The ``solc`` version string, when present."""
        value = self.entries.get("compiler_version")
        return value if isinstance(value, str) else None

    @property
    def has_compiler_version(self) -> bool:
        return self.compiler_version is not None


class _CborReader:
    """A minimal, allocation-light CBOR reader for the solc metadata subset."""

    __slots__ = ("data", "pos")

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def _read(self, count: int) -> bytes:
        if count < 0 or self.pos + count > len(self.data):
            raise CborError("truncated CBOR value")
        chunk = self.data[self.pos : self.pos + count]
        self.pos += count
        return chunk

    def _read_argument(self, info: int) -> int:
        """Read the additional-information argument of a head byte."""
        if info < 24:
            return info
        if info == 24:
            return self._read(1)[0]
        if info == 25:
            return int.from_bytes(self._read(2), "big")
        if info == 26:
            return int.from_bytes(self._read(4), "big")
        if info == 27:
            return int.from_bytes(self._read(8), "big")
        raise CborError(f"reserved additional information {info}")

    def read_value(self) -> Any:
        head = self._read(1)[0]
        major = head >> 5
        info = head & 0x1F

        if major == 0:
            return self._read_argument(info)
        if major == 1:
            return -1 - self._read_argument(info)
        if major == 2:
            return self._read(self._read_argument(info))
        if major == 3:
            return self._read(self._read_argument(info)).decode("utf-8", errors="replace")
        if major == 4:
            return [self.read_value() for _ in range(self._read_argument(info))]
        if major == 5:
            return self._read_map(self._read_argument(info))
        if major == 7:
            return self._read_simple(info)
        raise CborError(f"unsupported CBOR major type {major}")

    def _read_map(self, count: int) -> dict[Any, Any]:
        result: dict[Any, Any] = {}
        for _ in range(count):
            key = self.read_value()
            result[key] = self.read_value()
        return result

    def _read_simple(self, info: int) -> Any:
        if info == 20:
            return False
        if info == 21:
            return True
        if info in (22, 23):
            return None
        if info == 25:
            return float.fromhex(self._read(2).hex())
        if info == 26:
            return float.fromhex(self._read(4).hex())
        if info == 27:
            return float.fromhex(self._read(8).hex())
        if info == 24:
            return self._read(1)[0]
        raise CborError(f"unsupported CBOR simple value {info}")


def decode_cbor(data: bytes) -> Any:
    """Decode a complete CBOR item from ``data``.

    Raises :class:`CborError` if the data is not exactly one well-formed
    CBOR item.
    """
    reader = _CborReader(data)
    value = reader.read_value()
    if reader.pos != len(data):
        raise CborError(f"trailing bytes after CBOR item ({len(data) - reader.pos} bytes)")
    return value


def detect_solidity_metadata(code: bytes) -> MetadataRegion | None:
    """Detect the Solidity CBOR metadata trailer in ``code``.

    Returns ``None`` when the code carries no recognisable metadata. The
    detection is conservative: the trailing length field must be consistent
    with the remaining bytes, the CBOR must decode exactly, and the decoded
    map must contain at least one of the keys solc writes
    (``solc``/``bzzr0``/``bzzr1``/``ipfs``/``experimental``).
    """
    if len(code) < _LENGTH_FIELD_SIZE + 1:
        return None

    cbor_length = int.from_bytes(code[-_LENGTH_FIELD_SIZE:], "big")
    if cbor_length == 0 or cbor_length + _LENGTH_FIELD_SIZE > len(code):
        return None

    payload = code[-(cbor_length + _LENGTH_FIELD_SIZE) : -_LENGTH_FIELD_SIZE]
    try:
        decoded = decode_cbor(payload)
    except CborError:
        return None

    if not isinstance(decoded, dict):
        return None
    if not _METADATA_KEYS.intersection(decoded):
        return None

    entries: dict[str, Any] = {}
    for key, value in decoded.items():
        if not isinstance(key, str):
            continue
        name = _KEY_NAMES.get(key, key)
        if isinstance(value, bytes):
            entries[name] = value.hex()
        else:
            entries[name] = value

    return MetadataRegion(
        start_offset=len(code) - cbor_length - _LENGTH_FIELD_SIZE,
        length=cbor_length + _LENGTH_FIELD_SIZE,
        cbor_length=cbor_length,
        entries=entries,
        raw=code[-(cbor_length + _LENGTH_FIELD_SIZE) :],
    )


def split_metadata(code: bytes) -> tuple[bytes, MetadataRegion | None]:
    """Split ``code`` into (executable code, metadata region).

    The executable part is returned unchanged; the metadata region, if any,
    describes the trailer. The original bytes are never modified.
    """
    region = detect_solidity_metadata(code)
    if region is None:
        return code, None
    return code[: region.start_offset], region
