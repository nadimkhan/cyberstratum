"""Deterministic static rules operating on an analysed contract.

The rules are intentionally conservative: they report *patterns* that need
manual validation, never confirmed vulnerabilities (design doc section 6.5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.db.enums import Severity
from app.services.context import (
    USE_CALL_TARGET,
    USE_COMPARED,
    analyse_graph,
)
from evm_analysis.cfg import ControlFlowGraph
from evm_analysis.disassembler import Disassembly
from evm_analysis.features import ContractFeatures
from evm_analysis.opcodes import FORK_ORDER

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
    """Flag DELEGATECALL whose target an attacker could choose.

    DELEGATECALL to a *compile-time constant* target is the expected
    shape of an upgradeable proxy whose implementation is immutable: the
    target cannot be swapped, so there is nothing to act on. Reporting
    it anyway is the single largest source of noise in a proxy-heavy
    codebase, and a reviewer who learns to ignore the rule stops seeing
    the one that matters.

    The narrowing is deliberately one-sided. A target the analysis
    cannot resolve -- because it came from calldata, from storage, or
    from a value the analysis does not track -- is reported. Only a
    target proven to be a constant is passed over.
    """
    delegatecalls = [
        instr.offset for instr in disassembly.instructions if instr.name == "DELEGATECALL"
    ]
    if not delegatecalls:
        return None

    facts = analyse_graph(cfg)
    fixed = {target.offset for target in facts.delegatecall_targets if target.is_fixed}
    risky = [offset for offset in delegatecalls if offset not in fixed]
    if not risky:
        # Every delegatecall goes to a constant target: the expected
        # proxy pattern. Nothing to report.
        return None

    kinds = {
        target.offset: target.kind for target in facts.delegatecall_targets
    }
    return RuleFinding(
        detector_id="baseline.delegatecall",
        category="delegatecall_usage",
        title="DELEGATECALL executes foreign code in the caller's storage context",
        description=(
            "The contract uses DELEGATECALL to an address this analysis could not "
            "prove to be fixed at compile time. The callee runs in the caller's "
            "storage context, so an implementation an attacker can choose can "
            "overwrite state."
        ),
        severity=Severity.HIGH,
        confidence=0.7,
        evidence={
            "offsets": risky,
            "signals": ["delegatecall"],
            "targetKinds": {str(offset): kinds.get(offset, "unknown") for offset in risky},
            "fixedTargetOffsets": sorted(fixed),
        },
        limitations=(
            "A target that could not be resolved is reported, not dismissed. "
            "DELEGATECALL to a compile-time constant is the expected proxy "
            "pattern and is not reported."
        ),
    )


#: The fork in which EIP-6780 changed what SELFDESTRUCT does.
SELFDESTRUCT_NARROWING_FORK = "cancun"


def _fork_is_at_least(fork: str, target: str) -> bool:
    """Whether *fork* is *target* or a later fork.

    An unknown fork is not "at least" anything: the caller has to decide
    what to do about it, and a rule that guesses would be guessing about
    the chain rather than about the code.
    """
    if fork not in FORK_ORDER or target not in FORK_ORDER:
        return False
    return FORK_ORDER.index(fork) >= FORK_ORDER.index(target)


def _selfdestruct(
    disassembly: Disassembly, cfg: ControlFlowGraph, features: ContractFeatures
) -> RuleFinding | None:
    """Flag SELFDESTRUCT, and say what it actually does on this fork.

    Before Cancun, SELFDESTRUCT destroys the contract's code and
    forwards the remaining balance to the target address. From Cancun
    onwards (EIP-6780) the code survives and only the balance moves,
    unless the contract was created in the same transaction -- which the
    runtime bytecode cannot show. A finding that says "the contract can
    destroy itself" on a modern chain states something the chain no
    longer does, so the finding narrows with the fork instead of
    repeating an outdated claim.
    """
    offsets = [instr.offset for instr in disassembly.instructions if instr.name == "SELFDESTRUCT"]
    if not offsets:
        return None

    if _fork_is_at_least(disassembly.fork, SELFDESTRUCT_NARROWING_FORK):
        return RuleFinding(
            detector_id="baseline.selfdestruct",
            category="selfdestruct_usage",
            title="Contract can forward its balance on SELFDESTRUCT",
            description=(
                "The contract contains SELFDESTRUCT. From Cancun onwards the "
                "contract's code is not destroyed: the opcode only forwards the "
                "remaining balance to the target address. Whoever reaches the path "
                "can still sweep the balance away."
            ),
            severity=Severity.LOW,
            confidence=0.45,
            evidence={
                "offsets": offsets,
                "signals": ["selfdestruct", "balance_forwarding_only"],
                "fork": disassembly.fork,
            },
            limitations=(
                "From Cancun onwards the code survives SELFDESTRUCT unless the "
                "contract was created in the same transaction, which the runtime "
                "bytecode cannot show. Access control around the path was not "
                "verified."
            ),
        )

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
    """Flag TX.ORIGIN, and say how it is used when that can be shown.

    Reading tx.origin is not a finding. Using it to *authorise* is:
    tx.origin is the outermost signer, so an intermediary contract can
    make the original signer look like the caller.

    The analysis can show an authorisation-shaped use -- a comparison, or
    a use as the target of a call. It cannot show the absence of one,
    because a value can be written to memory and compared in another
    block. So the finding is still reported when the use is not
    established, but with a lower confidence and a limitation that says
    exactly what is and is not known.
    """
    offsets = [instr.offset for instr in disassembly.instructions if instr.name == "ORIGIN"]
    if not offsets:
        return None

    facts = analyse_graph(cfg)
    shaped = [use.offset for use in facts.origin_uses if use.is_authorisation_shaped]
    if shaped:
        return RuleFinding(
            detector_id="baseline.tx_origin",
            category="tx_origin_dependency",
            title="TX.ORIGIN is used in an authorisation decision",
            description=(
                "The contract compares tx.origin, or calls it, in a way that "
                "authorises the transaction. tx.origin is the outermost signer, "
                "so an intermediary contract can act with the signer's authority."
            ),
            severity=Severity.MEDIUM,
            confidence=0.75,
            evidence={
                "offsets": offsets,
                "signals": ["tx_origin", "authorisation_shaped_use"],
                "authorisationOffsets": sorted(shaped),
                "useKinds": {
                    str(use.offset): use.kind
                    for use in facts.origin_uses
                    if use.kind in (USE_COMPARED, USE_CALL_TARGET)
                },
            },
            limitations=(
                "The authorisation-shaped use was located; whether the "
                "comparison is reachable by an attacker was not established."
            ),
        )

    return RuleFinding(
        detector_id="baseline.tx_origin",
        category="tx_origin_dependency",
        title="Contract reads TX.ORIGIN",
        description=(
            "The contract reads tx.origin. This analysis did not find an "
            "authorisation-shaped use of it, but it cannot rule one out: the "
            "value could be written to memory and compared elsewhere."
        ),
        severity=Severity.LOW,
        confidence=0.3,
        evidence={"offsets": offsets, "signals": ["tx_origin"]},
        limitations=(
            "No authorisation-shaped use was located, and the analysis is not "
            "strong enough to rule one out. Treat this as a prompt to look, "
            "not as a finding of an authorisation bug."
        ),
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
