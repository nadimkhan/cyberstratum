"""CyberStratum EVM analysis engine.

A deterministic, fork-aware bytecode analysis library:

* :mod:`evm_analysis.opcodes` -- the vendored fork-aware opcode table.
* :mod:`evm_analysis.disassembler` -- instruction tokenization.
* :mod:`evm_analysis.cfg` -- basic blocks and the control-flow graph.
* :mod:`evm_analysis.features` -- feature extraction for downstream detectors.
* :mod:`evm_analysis.metadata` -- Solidity CBOR metadata trailer detection.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .cfg import Block, ControlFlowGraph, Edge, EdgeType, Resolution, build_cfg
from .disassembler import Disassembly, Instruction, InstructionStatus, disassemble
from .features import ContractFeatures, extract_features
from .metadata import (
    CborError,
    MetadataRegion,
    decode_cbor,
    detect_solidity_metadata,
    split_metadata,
)
from .opcodes import (
    Fork,
    ForkTable,
    Opcode,
    canonical_opcode_name,
    load_fork,
    normalize_fork,
    supported_forks,
)

__all__ = [
    "Block",
    "CborError",
    "ContractFeatures",
    "ControlFlowGraph",
    "Disassembly",
    "Edge",
    "EdgeType",
    "Fork",
    "ForkTable",
    "Instruction",
    "InstructionStatus",
    "MetadataRegion",
    "Opcode",
    "Resolution",
    "build_cfg",
    "canonical_opcode_name",
    "decode_cbor",
    "detect_solidity_metadata",
    "disassemble",
    "extract_features",
    "load_fork",
    "normalize_fork",
    "split_metadata",
    "supported_forks",
]
