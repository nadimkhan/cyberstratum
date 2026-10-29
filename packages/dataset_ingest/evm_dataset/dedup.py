"""Deduplication in three tiers, each producing a stable hash id.

ADR-0015 step 4 requires deduplication in three stages: exact hash, then
normalised-code hash, then near-duplicate clustering within a family. The
tiers are ordered from cheapest and strictest to most expensive and
loosest, and each one answers a different question:

* ``exact`` - is this byte-for-byte the same file we already have?
* ``normalised`` - is this the same code after comments and formatting are
  stripped? (a re-indent or a licence header must not create a new
  "sample")
* ``near_duplicate`` - is this a *variant* of code we already have, i.e. a
  fork, a renamed-variable copy or a lightly edited PoC?

Every hash here is deterministic across runs, machines and Python
versions. In particular nothing uses the builtin :func:`hash` (which is
salted per process) and nothing uses an unseeded RNG. The similarity
signature is a 64-bit simhash over identifier-normalised token shingles,
hashed with BLAKE2b.

Near-duplicate clustering uses a banded LSH candidate generation (16 bands
of 4 bits) followed by an exact token-set Jaccard verification against
:data:`NEAR_DUPLICATE_JACCARD_THRESHOLD`. The banding guarantees that any
pair whose simhash is within 3 bits becomes a candidate, and the Jaccard
check keeps the actual decision conservative.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from .records import DatasetRecord

__all__ = [
    "DeduplicationResult",
    "DedupTier",
    "NEAR_DUPLICATE_JACCARD_THRESHOLD",
    "cluster_near_duplicates",
    "deduplicate",
    "exact_hash",
    "near_duplicate_hash",
    "normalised_hash",
    "normalise_source",
    "tokenise",
]


#: Minimum token-set Jaccard similarity for two records to be considered
#: near-duplicates of each other. 0.85 is deliberately strict: a false
#: merge of two different variants into one family is harmless, a false
#: split of the same exploit into two families is what leaks a test set.
NEAR_DUPLICATE_JACCARD_THRESHOLD: Final[float] = 0.85

#: Number of bits in the simhash signature.
_SIMHASH_BITS: Final[int] = 64

#: Number of bands the simhash is split into for LSH candidate generation.
_BAND_COUNT: Final[int] = 16

#: Number of bits per band.
_BAND_BITS: Final[int] = _SIMHASH_BITS // _BAND_COUNT

#: Number of tokens in a shingle.
_SHINGLE_SIZE: Final[int] = 3

_COMMENT_BLOCK_RE: Final[re.Pattern[str]] = re.compile(r"/\*.*?\*/", re.DOTALL)
_COMMENT_LINE_RE: Final[re.Pattern[str]] = re.compile(r"//[^\n]*")
_STRING_LITERAL_RE: Final[re.Pattern[str]] = re.compile(
    r'"(?:[^"\\]|\\.)*"' + r"|'(?:[^'\\]|\\.)*'"
)
_WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"\s+")
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_$][A-Za-z_$0-9]*|\d+|[^\sA-Za-z_$0-9]")

#: Solidity keywords and literals are kept verbatim when normalising
#: identifiers; everything else becomes a placeholder so that a renamed
#: variable does not look like different code.
_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "pragma",
        "solidity",
        "contract",
        "library",
        "interface",
        "function",
        "constructor",
        "modifier",
        "event",
        "struct",
        "enum",
        "mapping",
        "public",
        "private",
        "internal",
        "external",
        "pure",
        "view",
        "payable",
        "returns",
        "return",
        "if",
        "else",
        "for",
        "while",
        "do",
        "break",
        "continue",
        "new",
        "delete",
        "emit",
        "require",
        "assert",
        "revert",
        "address",
        "bool",
        "string",
        "bytes",
        "byte",
        "uint",
        "uint8",
        "uint16",
        "uint32",
        "uint64",
        "uint128",
        "uint256",
        "int",
        "int8",
        "int256",
        "true",
        "false",
        "memory",
        "storage",
        "calldata",
        "msg",
        "block",
        "tx",
        "now",
        "this",
        "super",
        "wei",
        "ether",
        "seconds",
        "minutes",
        "hours",
        "days",
        "weeks",
    }
)


class DedupTier(StrEnum):
    """Which deduplication tier matched a record against an earlier one."""

    UNIQUE = "unique"
    EXACT = "exact"
    NORMALISED = "normalised"
    NEAR_DUPLICATE = "near_duplicate"


def exact_hash(code: str) -> str:
    """SHA-256 over the raw bytes of ``code``.

    This is the strictest tier: any byte change, including a changed
    comment or a changed indent, changes the hash.
    """
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def normalise_source(code: str) -> str:
    """Strip comments, collapse whitespace and blank out string literals.

    The normalisation is intentionally conservative: it removes the noise
    that makes two copies of one file differ (comments, indentation,
    trailing whitespace, the contents of string literals) but changes
    nothing else. Identifiers are *not* renamed here - that happens one
    tier down, in the similarity signature.
    """
    without_block_comments = _COMMENT_BLOCK_RE.sub(" ", code)
    without_line_comments = _COMMENT_LINE_RE.sub(" ", without_block_comments)
    without_strings = _STRING_LITERAL_RE.sub('""', without_line_comments)
    return _WHITESPACE_RE.sub(" ", without_strings).strip()


def normalised_hash(code: str) -> str:
    """SHA-256 over the normalised source.

    Two files that differ only in comments, whitespace or string literal
    contents share this hash; two files that differ in a single statement
    do not.
    """
    return hashlib.sha256(normalise_source(code).encode("utf-8")).hexdigest()


def tokenise(code: str) -> list[str]:
    """Split normalised source into lexical tokens."""
    return _TOKEN_RE.findall(normalise_source(code))


def _identifier_shape(token: str) -> str:
    """Map an identifier to a placeholder unless it is a Solidity keyword."""
    if token in _KEYWORDS:
        return token
    if token[0].isdigit():
        return "<num>"
    return "<id>"


def _structure_tokens(code: str) -> list[str]:
    """The token stream with identifiers removed.

    The near-duplicate signature must be insensitive to a *renamed*
    variable, but it must still distinguish two genuinely different
    contracts. Keeping keywords, numeric literals and operators while
    dropping identifiers does both: a renamed copy produces an identical
    stream, while two contracts with different logic produce different
    ones.
    """
    return [
        token
        for token in tokenise(code)
        if token in _KEYWORDS or token[0].isdigit() or not (token[0].isalpha() or token[0] in "_$")
    ]


def shape_tokens(code: str) -> list[str]:
    """The token stream with identifiers collapsed to a placeholder.

    Used as a coarse, renaming-invariant fingerprint of a contract's
    shape. Two copies of one contract with renamed variables share it.
    """
    return [_identifier_shape(token) for token in tokenise(code)]


def _stable_token_hash(token: str) -> int:
    """A process-stable 64-bit hash of a token.

    Uses BLAKE2b rather than the builtin :func:`hash`, whose string
    hashing is salted per interpreter run and would make every signature
    irreproducible across processes.
    """
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def _structure_shingles(code: str) -> list[str]:
    """The overlapping structure shingles used by the similarity signature."""
    tokens = _structure_tokens(code)
    if not tokens:
        return []
    if len(tokens) < _SHINGLE_SIZE:
        return [" ".join(tokens)]
    return [
        " ".join(tokens[index : index + _SHINGLE_SIZE])
        for index in range(len(tokens) - _SHINGLE_SIZE + 1)
    ]


def near_duplicate_hash(code: str) -> str:
    """The 64-bit simhash similarity signature, as a hex string.

    The signature is computed over identifier-free structure shingles, so
    two copies of one contract with renamed variables produce the same
    signature while genuinely different contracts produce different ones.
    """
    shingles = _structure_shingles(code)
    if not shingles:
        return "0" * 16

    accumulator = [0] * _SIMHASH_BITS
    for shingle in shingles:
        value = _stable_token_hash(shingle)
        for bit in range(_SIMHASH_BITS):
            if value & (1 << bit):
                accumulator[bit] += 1
            else:
                accumulator[bit] -= 1

    signature = 0
    for bit in range(_SIMHASH_BITS):
        if accumulator[bit] > 0:
            signature |= 1 << bit
    return f"{signature:016x}"


def _band_keys(signature: str) -> list[tuple[int, str]]:
    """Split a simhash into LSH bands."""
    value = int(signature, 16)
    keys: list[tuple[int, str]] = []
    for band in range(_BAND_COUNT):
        chunk = (value >> (band * _BAND_BITS)) & ((1 << _BAND_BITS) - 1)
        keys.append((band, f"{chunk:04x}"))
    return keys


def _token_set(code: str) -> frozenset[str]:
    """The set of structure shingles, used for the exact Jaccard check.

    Jaccard is computed over shingles rather than raw tokens: a token
    set is too coarse (two contracts made of the same keywords would
    collide) while a shingle set is a real structural fingerprint.
    """
    return frozenset(_structure_shingles(code))


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


@dataclass(frozen=True)
class DeduplicationResult:
    """The three hashes, the cluster and the tier, for one record."""

    record_id: str
    exact: str
    normalised: str
    near_duplicate: str
    cluster_id: str
    matched_tier: DedupTier
    duplicate_of: str | None = None

    def to_dict(self) -> dict[str, object]:
        """A JSON-serialisable view, used inside the dataset manifest."""
        return {
            "record_id": self.record_id,
            "exact": self.exact,
            "normalised": self.normalised,
            "near_duplicate": self.near_duplicate,
            "cluster_id": self.cluster_id,
            "matched_tier": self.matched_tier.value,
            "duplicate_of": self.duplicate_of,
        }


def cluster_near_duplicates(
    records: Sequence[DatasetRecord],
    *,
    threshold: float = NEAR_DUPLICATE_JACCARD_THRESHOLD,
) -> dict[str, str]:
    """Group records into near-duplicate clusters.

    Candidate pairs come from the banded simhash sketch; each candidate
    is then verified with an exact token-set Jaccard comparison against
    ``threshold``. Clusters are formed with a union-find over the
    verified pairs, and the cluster id is the SHA-256 of the sorted
    member record ids, so it is stable for a given set of members.

    The function is deterministic: the same records in the same order
    always produce the same clusters and the same ids.
    """
    token_sets = {record.record_id: _token_set(record.code) for record in records}
    signatures = {record.record_id: near_duplicate_hash(record.code) for record in records}

    buckets: dict[tuple[int, str], list[str]] = {}
    for record in records:
        for key in _band_keys(signatures[record.record_id]):
            buckets.setdefault(key, []).append(record.record_id)

    parent: dict[str, str] = {record.record_id: record.record_id for record in records}

    def find(node: str) -> str:
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            # Keep the lexicographically smaller root so the result does
            # not depend on the order the pairs were discovered in.
            if left_root < right_root:
                parent[right_root] = left_root
            else:
                parent[left_root] = right_root

    seen_pairs: set[tuple[str, str]] = set()
    for members in buckets.values():
        if len(members) < 2:
            continue
        for index, left in enumerate(members):
            for right in members[index + 1 :]:
                pair = (left, right) if left < right else (right, left)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                if _jaccard(token_sets[pair[0]], token_sets[pair[1]]) >= threshold:
                    union(pair[0], pair[1])

    groups: dict[str, list[str]] = {}
    for record in records:
        groups.setdefault(find(record.record_id), []).append(record.record_id)

    cluster_ids: dict[str, str] = {}
    for members in groups.values():
        digest = hashlib.sha256("|".join(sorted(members)).encode("utf-8")).hexdigest()
        for member in members:
            cluster_ids[member] = digest
    return cluster_ids


def deduplicate(
    records: Iterable[DatasetRecord],
    *,
    threshold: float = NEAR_DUPLICATE_JACCARD_THRESHOLD,
) -> list[DeduplicationResult]:
    """Run all three deduplication tiers over ``records``.

    The returned list is in the same order as the input. ``matched_tier``
    reports the *first* tier at which the record matched an earlier
    record; a record that matched nothing is :data:`DedupTier.UNIQUE`.
    """
    ordered = list(records)
    cluster_ids = cluster_near_duplicates(ordered, threshold=threshold)

    seen_exact: dict[str, str] = {}
    seen_normalised: dict[str, str] = {}
    cluster_representative: dict[str, str] = {}

    results: list[DeduplicationResult] = []
    for record in ordered:
        exact = exact_hash(record.code)
        normalised = normalised_hash(record.code)
        near = near_duplicate_hash(record.code)
        cluster = cluster_ids[record.record_id]

        if exact in seen_exact:
            tier, duplicate_of = DedupTier.EXACT, seen_exact[exact]
        elif normalised in seen_normalised:
            tier, duplicate_of = DedupTier.NORMALISED, seen_normalised[normalised]
        elif cluster in cluster_representative:
            tier, duplicate_of = DedupTier.NEAR_DUPLICATE, cluster_representative[cluster]
        else:
            tier, duplicate_of = DedupTier.UNIQUE, None

        seen_exact.setdefault(exact, record.record_id)
        seen_normalised.setdefault(normalised, record.record_id)
        cluster_representative.setdefault(cluster, record.record_id)

        results.append(
            DeduplicationResult(
                record_id=record.record_id,
                exact=exact,
                normalised=normalised,
                near_duplicate=near,
                cluster_id=cluster,
                matched_tier=tier,
                duplicate_of=duplicate_of,
            )
        )
    return results
