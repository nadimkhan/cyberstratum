"""Deterministic static rules operating on an analysed contract.

The rules are intentionally conservative: they report *patterns* that need
manual validation, never confirmed vulnerabilities (design doc section 6.5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.db.enums import Severity
from evm_analysis.cfg import ControlFlowGraph
from evm_analysis.disassembler import Disassembly
from evm_analysis.features import ContractFeatures

#: Version of the rule set recorded on every scan.
RULESET_VERSION = "0.1.0"

#: Version of the parser recorded on every scan.
PARSER_VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class RuleFinding:
    """One pattern reported by the rule engine."""

    detector_id: str
    category: str
    title: str
    description: str
    severity: Severity
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)
    limitations: str = ""


def _call_then_storage_write(
    disassembly: Disassembly, cfg: ControlFlowGraph, features: ContractFeatures
) -> RuleFinding | None:
    """Flag a storage write that follows an external call inside one block."""
    if not features.call_then_storage_write:
        return None
    call_offset, write_offset = features.call_then_storage_write[0]
    return RuleFinding(
        detector_id="baseline.call_before_state_write",
        category="reentrancy_candidate",
        title="Potential reentrancy pattern — manual validation required",
        description=(
            "A storage write occurs after an external call within the same basic block. "
            "This is a heuristic signal only; exploitability is not established."
        ),
        severity=Severity.MEDIUM,
        confidence=0.55,
        evidence={
            "callOffset": call_offset,
            "storageWriteOffset": write_offset,
            "signals": ["external_call_before_state_write"],
        },
        limitations="Static pattern only; exploitability has not been confirmed.",
    )


def _delegatecall(
    disassembly: Disassembly, cfg: ControlFlowGraph, features: ContractFeatures
) -> RuleFinding | None:
    """Flag DELEGATECALL usage, which forwards control and storage context."""
    delegatecalls = [
        instr.offset for instr in disassembly.instructions if instr.name == "DELEGATECALL"
    ]
    if not delegatecalls:
        return None
    return RuleFinding(
        detector_id="baseline.delegatecall",
        category="delegatecall_usage",
        title="DELEGATECALL executes foreign code in the caller's storage context",
        description=(
            "The contract uses DELEGATECALL. The callee runs in the caller's storage "
            "context, so a malicious implementation can overwrite state."
        ),
        severity=Severity.HIGH,
        confidence=0.7,
        evidence={"offsets": delegatecalls, "signals": ["delegatecall"]},
        limitations="Presence of DELEGATECALL does not by itself imply a vulnerable proxy.",
    )


def _selfdestruct(
    disassembly: Disassembly, cfg: ControlFlowGraph, features: ContractFeatures
) -> RuleFinding | None:
    """Flag SELFDESTRUCT, which can destroy a contract and forward its balance."""
    offsets = [instr.offset for instr in disassembly.instructions if instr.name == "SELFDESTRUCT"]
    if not offsets:
        return None
    return RuleFinding(
        detector_id="baseline.selfdestruct",
        category="selfdestruct_usage",
        title="Contract contains SELFDESTRUCT",
        description=(
            "The contract can destroy itself and forward the remaining balance to an "
            "address. Any party able to reach that path can end the contract."
        ),
        severity=Severity.MEDIUM,
        confidence=0.6,
        evidence={"offsets": offsets, "signals": ["selfdestruct"]},
        limitations="Access control around the SELFDESTRUCT path was not verified.",
    )


def _tx_origin(
    disassembly: Disassembly, cfg: ControlFlowGraph, features: ContractFeatures
) -> RuleFinding | None:
    """Flag TX.ORIGIN, which is a known phishing/authorization footgun."""
    offsets = [instr.offset for instr in disassembly.instructions if instr.name == "ORIGIN"]
    if not offsets:
        return None
    return RuleFinding(
        detector_id="baseline.tx_origin",
        category="tx_origin_dependency",
        title="Contract reads TX.ORIGIN",
        description=(
            "The contract depends on tx.origin for an authorization decision. "
            "tx.origin can be an intermediate contract, enabling phishing attacks."
        ),
        severity=Severity.LOW,
        confidence=0.6,
        evidence={"offsets": offsets, "signals": ["tx_origin"]},
        limitations="The surrounding authorization logic was not traced.",
    )


def _dynamic_jumps(
    disassembly: Disassembly, cfg: ControlFlowGraph, features: ContractFeatures
) -> RuleFinding | None:
    """Flag a contract whose control flow cannot be fully resolved statically."""
    unresolved = cfg.unresolved_edges
    if not unresolved:
        return None
    ratio = len(unresolved) / max(len(cfg.edges), 1)
    return RuleFinding(
        detector_id="baseline.unresolved_jumps",
        category="analysis_limitation",
        title="Control flow contains unresolved dynamic jumps",
        description=(
            f"{len(unresolved)} control-flow edge(s) could not be resolved statically, "
            "so some code paths were not analysed."
        ),
        severity=Severity.INFO,
        confidence=round(min(ratio, 1.0), 3),
        evidence={
            "unresolvedEdgeCount": len(unresolved),
            "edgeCount": len(cfg.edges),
            "signals": ["unresolved_dynamic_jump"],
        },
        limitations="Coverage of the analysis is reduced by the unresolved edges.",
    )


def _stack_underflow(
    disassembly: Disassembly, cfg: ControlFlowGraph, features: ContractFeatures
) -> RuleFinding | None:
    """Flag bytecode whose linear stack tracking goes negative."""
    if not features.stack_underflow_offsets:
        return None
    return RuleFinding(
        detector_id="baseline.stack_underflow",
        category="bytecode_anomaly",
        title="Stack depth tracking goes negative",
        description=(
            "A linear stack simulation reaches a negative depth, which would revert at "
            "runtime. The code may be malformed or non-reachable code."
        ),
        severity=Severity.LOW,
        confidence=0.5,
        evidence={
            "offsets": features.stack_underflow_offsets[:50],
            "signals": ["stack_underflow"],
        },
        limitations="Linear stack tracking ignores branches, so offsets may be false positives.",
    )


_RULES = (
    _call_then_storage_write,
    _delegatecall,
    _selfdestruct,
    _tx_origin,
    _dynamic_jumps,
    _stack_underflow,
)


def run_rules(
    disassembly: Disassembly, cfg: ControlFlowGraph, features: ContractFeatures
) -> list[RuleFinding]:
    """Run every baseline rule and return the findings in a stable order."""
    findings: list[RuleFinding] = []
    for rule in _RULES:
        finding = rule(disassembly, cfg, features)
        if finding is not None:
            findings.append(finding)
    return findings


__all__ = ["PARSER_VERSION", "RULESET_VERSION", "RuleFinding", "run_rules"]
