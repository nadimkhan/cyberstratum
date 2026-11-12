"""Feature extraction for downstream detectors and the ML baseline.

The doc (§6.4) lists candidate feature families. This module implements the
deterministic, bytecode-derived subset:

* opcode and N-gram frequencies;
* block size and instruction mix;
* ``CALL`` / ``STATICCALL`` / ``DELEGATECALL`` / ``CREATE`` / ``CREATE2``
  locations;
* storage read/write locations (``SLOAD`` / ``SSTORE``);
* branch count, unresolved jumps, graph cycles, call-to-storage ordering;
* stack-depth consistency where statically derivable.

Everything here is pure and reproducible: the same bytecode and fork always
produce the same feature vector.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .cfg import ControlFlowGraph, Resolution
from .disassembler import Disassembly

#: Opcodes that perform an external call or contract creation.
_CALL_OPCODES = frozenset({"CALL", "CALLCODE", "DELEGATECALL", "STATICCALL"})
_CREATE_OPCODES = frozenset({"CREATE", "CREATE2"})

#: Opcodes that read or write contract storage.
_STORAGE_READ_OPCODES = frozenset({"SLOAD", "TLOAD"})
_STORAGE_WRITE_OPCODES = frozenset({"SSTORE", "TSTORE"})


@dataclass(slots=True)
class ContractFeatures:
    """Deterministic, bytecode-derived features for one contract."""

    fork: str = ""
    code_size: int = 0
    instruction_count: int = 0
    opcode_histogram: dict[str, int] = field(default_factory=dict)
    opcode_frequencies: dict[str, float] = field(default_factory=dict)
    ngram_size: int = 3
    ngram_frequencies: dict[str, float] = field(default_factory=dict)

    block_count: int = 0
    reachable_block_count: int = 0
    unreachable_byte_size: int = 0
    edge_count: int = 0
    branch_count: int = 0
    unresolved_jump_count: int = 0
    cycle_count: int = 0

    call_offsets: list[int] = field(default_factory=list)
    create_offsets: list[int] = field(default_factory=list)
    storage_read_offsets: list[int] = field(default_factory=list)
    storage_write_offsets: list[int] = field(default_factory=list)

    #: ``(call_offset, storage_write_offset)`` pairs where a storage write
    #: occurs after an external call inside the same block.
    call_then_storage_write: list[tuple[int, int]] = field(default_factory=list)

    #: Offsets where the statically-tracked stack depth goes negative, which
    #: indicates the code would revert at runtime.
    stack_underflow_offsets: list[int] = field(default_factory=list)

    max_stack_depth: int = 0

    metadata_size: int = 0
    """Size of the detected Solidity metadata trailer, in bytes (0 if none)."""

    compiler_version: str | None = None
    """The ``solc`` version recorded in the metadata, when present."""

    warnings: list[str] = field(default_factory=list)

    def as_vector(self) -> dict[str, float]:
        """Flatten the features into a numeric mapping for the ML baseline."""
        vector: dict[str, float] = {
            "code_size": float(self.code_size),
            "instruction_count": float(self.instruction_count),
            "block_count": float(self.block_count),
            "reachable_block_count": float(self.reachable_block_count),
            "unreachable_byte_size": float(self.unreachable_byte_size),
            "edge_count": float(self.edge_count),
            "branch_count": float(self.branch_count),
            "unresolved_jump_count": float(self.unresolved_jump_count),
            "cycle_count": float(self.cycle_count),
            "call_count": float(len(self.call_offsets)),
            "create_count": float(len(self.create_offsets)),
            "storage_read_count": float(len(self.storage_read_offsets)),
            "storage_write_count": float(len(self.storage_write_offsets)),
            "call_then_storage_write_count": float(len(self.call_then_storage_write)),
            "stack_underflow_count": float(len(self.stack_underflow_offsets)),
            "max_stack_depth": float(self.max_stack_depth),
            "metadata_size": float(self.metadata_size),
            "unresolved_jump_ratio": (
                float(self.unresolved_jump_count) / float(self.branch_count)
                if self.branch_count
                else 0.0
            ),
        }
        for name, freq in self.opcode_frequencies.items():
            vector[f"opcode_freq__{name}"] = freq
        return vector


def _track_stack_depth(disassembly: Disassembly) -> tuple[list[int], int]:
    """Statically track stack depth and report underflow offsets.

    This is a conservative linear approximation: it does not model branches,
    so it is used only as a signal (and for tests), never as a proof of
    reachability.
    """
    depth = 0
    underflows: list[int] = []
    peak = 0
    for instr in disassembly.instructions:
        if instr.stack_in > depth:
            underflows.append(instr.offset)
        depth += instr.stack_delta
        if depth < 0:
            depth = 0
        peak = max(peak, depth)
    return underflows, peak


def extract_features(
    disassembly: Disassembly,
    cfg: ControlFlowGraph,
    ngram_size: int = 3,
) -> ContractFeatures:
    """Extract the deterministic feature set for one contract."""
    features = ContractFeatures(
        fork=disassembly.fork,
        code_size=disassembly.code_size,
        instruction_count=len(disassembly.instructions),
        ngram_size=ngram_size,
    )

    histogram = disassembly.opcode_histogram()
    features.opcode_histogram = histogram
    total = sum(histogram.values())
    if total:
        features.opcode_frequencies = {
            name: count / total for name, count in sorted(histogram.items())
        }

    if disassembly.metadata is not None:
        features.metadata_size = disassembly.metadata.length
        features.compiler_version = disassembly.metadata.compiler_version

    ngrams = disassembly.ngrams(ngram_size)
    if ngrams:
        counts: dict[str, int] = {}
        for gram in ngrams:
            key = " ".join(gram)
            counts[key] = counts.get(key, 0) + 1
        features.ngram_frequencies = {
            key: count / len(ngrams) for key, count in sorted(counts.items())
        }

    features.block_count = len(cfg.blocks)
    features.reachable_block_count = cfg.reachable_block_count
    features.unreachable_byte_size = cfg.unreachable_byte_size
    features.edge_count = cfg.edge_count
    features.branch_count = sum(
        1
        for e in cfg.edges
        if e.edge_type.value.startswith("conditional")
        or e.edge_type.value == "unconditional_jump"
        or e.edge_type.value == "unresolved"
    )
    features.unresolved_jump_count = sum(
        1 for e in cfg.edges if e.resolution is Resolution.UNRESOLVED
    )
    features.cycle_count = len(cfg.find_cycles())

    for instr in disassembly.instructions:
        if instr.name in _CALL_OPCODES:
            features.call_offsets.append(instr.offset)
        elif instr.name in _CREATE_OPCODES:
            features.create_offsets.append(instr.offset)
        if instr.name in _STORAGE_READ_OPCODES:
            features.storage_read_offsets.append(instr.offset)
        elif instr.name in _STORAGE_WRITE_OPCODES:
            features.storage_write_offsets.append(instr.offset)

    # Call-to-storage-write ordering: within a single block, a storage write
    # that follows an external call is the classic reentrancy shape.
    for block in cfg.blocks.values():
        seen_call: int | None = None
        for instr in block.instructions:
            if instr.name in _CALL_OPCODES or instr.name in _CREATE_OPCODES:
                seen_call = instr.offset
            elif instr.name in _STORAGE_WRITE_OPCODES and seen_call is not None:
                features.call_then_storage_write.append((seen_call, instr.offset))

    underflows, peak = _track_stack_depth(disassembly)
    features.stack_underflow_offsets = underflows
    features.max_stack_depth = peak

    features.warnings = list(disassembly.warnings) + list(cfg.warnings)
    return features
