"""Source-level audit.

This is the bridge between the source engine (Slither, run out of process)
and the bytecode engine (CyberStratum's own fork-aware analysis). Both
produce findings in the same shape, so the unified findings table can hold
them side by side and a reviewer can see the whole picture of one contract.

The source engine can only see verified source. The bytecode engine can see
everything that is deployed. Neither is a superset of the other, and a
contract whose source says one thing and whose deployed bytecode does
another is itself worth flagging.

Slither itself is AGPL-3.0 and is never imported here. This module calls
:mod:`app.services.slither`, which runs it as an unmodified external
executable and reads its JSON across the process boundary. See ADR-0013.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from app.db.enums import Severity
from app.services.rules import RuleFinding
from app.services.slither import (
    DETECTOR_TO_VECTOR,
    SlitherFinding,
    SlitherResult,
    SlitherRunner,
    vector_for,
)

log = logging.getLogger("cyberstratum.source_audit")

#: The prefix every source-engine detector carries.
#:
#: The unified findings table distinguishes the engine that produced a
#: finding. Until the ``findings.source`` column lands (see
#: docs/SCHEMA-RECONCILIATION.md), the prefix carries it.
SOURCE_PREFIX: Final[str] = "slither"

#: The version stamped on source findings, so a result can be tied to the
#: detector set that produced it.
SOURCE_DETECTOR_VERSION: Final[str] = "slither-1"

#: Slither's confidence words mapped onto the 0..1 scale the findings table
#: stores.
CONFIDENCE_SCORES: Final[dict[str, float]] = {
    "high": 0.9,
    "medium": 0.6,
    "low": 0.3,
}

#: The source engine's risk vectors mapped onto the bytecode engine's
#: category vocabulary.
#:
#: The bytecode rules use the categories from the design document
#: (``reentrancy_candidate``, ``selfdestruct_usage``, ...). The source engine
#: has its own vector names. Where the two describe the same class of risk,
#: the source finding is given the *bytecode* category, so a reviewer looking
#: at one contract sees one category for the same risk regardless of which
#: engine found it.
#:
#: Source-only classes -- ``unchecked_call``, ``dos``, ``accesscontrol`` and
#: the rest -- keep their own vector name as the category. There is no
#: bytecode counterpart to hide behind, and inventing one would be a lie.
SOURCE_VECTOR_TO_CATEGORY: Final[dict[str, str]] = {
    "reentrancy": "reentrancy_candidate",
    "selfdestruct": "selfdestruct_usage",
    "tx_origin_auth": "tx_origin_dependency",
    "delegatecall": "delegatecall_usage",
}


def category_for(vector: str) -> str:
    """The shared category for a source-engine risk vector."""
    return SOURCE_VECTOR_TO_CATEGORY.get(vector, vector)


#: A readable title per detector, for the ones worth naming individually.
DETECTOR_TITLES: Final[dict[str, str]] = {
    "reentrancy_eth": "Reentrancy — state updated after an external call",
    "reentrancy_no_eth": "Reentrancy — state updated after an external call",
    "reentrancy_benign": "Reentrancy pattern (benign-looking, still unverified)",
    "reentrancy_events": "Reentrancy through an event emission",
    "tx_origin": "tx.origin used for authorisation",
    "suicidal": "Contract can destroy itself",
    "unchecked_lowlevel": "Unchecked return value of a low-level call",
    "unused_return": "Return value ignored",
    "arbitrary_send": "Arbitrary value sent to an untrusted recipient",
    "front_running": "Front-running exposure",
    "integer_overflow": "Arithmetic that can overflow",
    "incorrect_equality": "Incorrect equality on a balance or amount",
    "divide_before_multiply": "Division performed before multiplication",
    "locked_ether": "Ether can be locked in the contract",
    "centralization": "Privileged role controls the contract",
    "admin_administrated": "Admin can change the contract's behaviour",
    "pausable": "Contract can be paused",
    "proxy_upgrade": "Contract can be upgraded",
    "upgradeable_proxy": "Contract is an upgradeable proxy",
    "state_shadowing": "State variable shadows another declaration",
    "shadowing_state": "State variable shadows another declaration",
    "ecrecover": "ecrecover without a signature check",
    "signature_replay": "Signature can be replayed",
    "weak_prng": "Weak source of randomness",
    "uninitialized_state": "Uninitialised storage variable",
    "uninitialized_storage": "Uninitialised storage variable",
    "access_control": "Access control depends on a single role",
    "assembly": "Inline assembly bypasses the compiler's checks",
    "constant": "Constant value suggests an unfinished placeholder",
    "reused_base": "Base contract reused with a different implementation",
    "reused_constructor": "Base constructor reused by a derived contract",
    "costly_loop": "Unbounded loop can run out of gas",
    "calls_loop": "External call inside a loop",
    "msg_value_loop": "msg.value used inside a loop",
    "flash_loan": "Flash-loan exposure",
    "price_manipulation": "Price can be manipulated within the transaction",
    "block_bounding": "Behaviour depends on the block number",
    "chainlink_feed_registry": "Chainlink feed used without a registry check",
    "low_level_calls": "Low-level call with an unchecked return value",
    "unchecked_send": "Return value of send is not checked",
    "unchecked_transfer": "Return value of transfer is not checked",
    "arbitrary_send_eth": "Ether can be sent to an arbitrary recipient",
    "arbitrary_send_erc20": "Tokens can be sent to an arbitrary recipient",
    "arbitrary_send_erc20_permit": "Permit-based transfer to an arbitrary recipient",
    "reentrancy_balance": "Reentrancy — balance read before the state update",
    "reentrancy_unlimited_gas": "Reentrancy — the reentrant call is given unlimited gas",
    "unprotected_upgrade": "Upgrade can be performed without authorisation",
    "protected_vars": "State variable is protected by a naming convention only",
    "events_access": "Missing access-control check on an event",
    "incorrect_modifier": "Modifier used in a way that does not do what it looks like",
    "controlled_delegatecall": "Delegatecall target is controlled by a tainted value",
    "delegatecall_loop": "Delegatecall inside a loop",
    "uninitialized_local": "Local variable used before it is initialised",
    "uninitialized_fptr_cst": "Function pointer used before it is initialised",
    "timestamp": "Block timestamp used as a source of randomness",
    "gelato_unprotected_randomness": "Randomness requested without protecting the caller",
    "domain_separator_collision": "Domain separator can collide",
    "out_of_order_retryable": "Retryable call used out of order",
    "pyth_unchecked_confidence": "Pyth price used without checking the confidence interval",
    "pyth_unchecked_publishtime": "Pyth price used without checking the publish time",
    "pyth_deprecated_functions": "Deprecated Pyth function is used",
    "chronicle_unchecked_price": "Chronicle price used without a freshness check",
    "erc20_interface": "ERC-20 interface is implemented incorrectly",
    "erc721_interface": "ERC-721 interface is implemented incorrectly",
    "erc20_indexed": "ERC-20 event field is not indexed as expected",
    "deprecated_standards": "Deprecated standard is used",
    "unindexed_event_address": "Address in an event is not indexed",
    "events_maths": "Event arguments do not match the arithmetic they describe",
    "multiple_constructors": "More than one constructor is declared",
    "name_reused": "Contract reuses the name of another contract",
    "solc_version": "An old compiler version is in use",
    "pragma": "The pragma does not pin the compiler version",
    "naming_convention": "Identifier does not follow the naming convention",
    "external_function": "Function is declared external but does not need to be",
    "variable_scope": "Variable is used outside the scope it was declared in",
    "shadowing_local": "Local variable shadows another declaration",
    "shadowing_builtin": "Declaration shadows a built-in symbol",
    "too_many_digits": "A literal has more digits than its type can hold",
    "function_init_state": "State is written in a function that runs once",
    "msg_value_in_nonpayable": "msg.value is used in a non-payable function",
    "encode_packed_collision": "abi.encodePacked can produce colliding values",
    "abiencoderv2_array": "abi.encode v2 on an array can collide",
    "public_mappings_nested": "Public mapping holds a nested structure",
    "missing_zero_check": "A zero address is not checked",
    "missing_inheritance": "An expected base contract is not inherited",
    "unimplemented_functions": "A declared function has no implementation",
    "void_cst": "A constructor is declared but does nothing",
    "assert_state_change": "An assertion does not change any state",
    "write_after_write": "A state write is overwritten before it is used",
    "dead_code": "Code that can never run",
    "unused_state": "State variable is never used",
    "redundant_statements": "Statement has no effect",
    "boolean_cst": "Boolean constant used where a check was meant",
    "boolean_equal": "Boolean compared for equality",
    "rtlo": "Right-to-left override of a storage variable",
    "enum_conversion": "Enum converted out of range",
    "controlled_array_length": "Array length comes from a tainted value",
    "cache_array_length": "Cached array length can go stale",
    "array_by_reference": "Storage array is modified through a reference",
    "mapping_deletion": "Mapping key is deleted, which does not clear the value",
    "incorrect_using_for": "A for loop is used incorrectly",
    "incorrect_shift": "Shift is applied in the wrong order",
    "incorrect_exp": "Exponentiation is applied in the wrong order",
    "incorrect_unary": "Unary operator is applied incorrectly",
    "incorrect_return": "A return value is incorrect",
    "return_leave": "A return is used where the function should leave",
    "storage_array": "Signed storage integer can hold an out-of-range value",
    "return_bomb": "A low-level callee can return a large amount of data",
    "tautology": "A condition is always true or always false",
    "tautological_compare": "Comparison is always true or always false",
    "constant_function_asm": "Constant function uses inline assembly",
    "constant_function_state": "Constant function reads state",
    "constable_states": "A constant is stored in state",
    "immutable_states": "An immutable is assigned more than once",
    "optimism_deprecation": "Deprecated Optimism precompile is used",
    "var_read_using_this": "State read through `this` bypasses the modifier",
}


@dataclass(frozen=True)
class SourceAudit:
    """The outcome of auditing one contract's source.

    Attributes:
        findings: The findings, in CyberStratum's shared finding shape.
        skipped: Why the audit did not happen, if it did not.
        detector_count: How many findings were produced.
    """

    findings: tuple[RuleFinding, ...]
    skipped: str | None = None

    @property
    def ran(self) -> bool:
        """Whether the source engine actually ran."""
        return self.skipped is None


def detector_title(detector: str) -> str:
    """A readable title for a detector."""
    if detector in DETECTOR_TITLES:
        return DETECTOR_TITLES[detector]
    return detector.replace("_", " ").capitalize()


def confidence_score(confidence: str) -> float:
    """Slither's confidence word as a 0..1 score."""
    return CONFIDENCE_SCORES.get(confidence.strip().lower(), 0.6)


def to_rule_finding(finding: SlitherFinding) -> RuleFinding:
    """Convert one Slither finding into the shared finding shape.

    Args:
        finding: The normalised Slither finding.

    Returns:
        The same finding, in the shape the bytecode rule engine produces.
    """
    vector = finding.vector or vector_for(finding.detector)
    return RuleFinding(
        detector_id=f"{SOURCE_PREFIX}.{finding.detector}",
        category=category_for(vector),
        title=detector_title(finding.detector),
        description=finding.description,
        severity=_severity_for(finding.severity),
        confidence=confidence_score(finding.confidence),
        evidence={
            "detector": finding.detector,
            "vector": vector,
            "category": category_for(vector),
            "sourceEngine": "slither",
            "slitherConfidence": finding.confidence,
            "contractPath": finding.contract_path,
        },
        limitations=(
            "Source-level analysis only. The deployed bytecode was not compared "
            "against this source, so a mismatch is not ruled out."
        ),
    )


def _severity_for(severity: str) -> Severity:
    """Map a severity name onto the enum."""
    try:
        return Severity(severity.strip().lower())
    except ValueError:
        return Severity.MEDIUM


def audit_source(
    source_code: str | None,
    contract_name: str = "",
    compiler_version: str = "",
    runner: SlitherRunner | None = None,
    extra_files: Mapping[str, str] | None = None,
) -> SourceAudit:
    """Audit one contract's source.

    Args:
        source_code: The Solidity source. ``None`` or empty means there is
            nothing to audit -- an unverified contract has no source.
        contract_name: The contract's name, used for logging and file naming.
        compiler_version: The compiler version, used to pick a solc binary.
        runner: The runner to use. One is created when not supplied.
        extra_files: The rest of the project, keyed by path. A contract
            that imports another file will not compile without them.

    Returns:
        The findings, or the reason the audit was skipped.
    """
    if not source_code or not source_code.strip():
        return SourceAudit(findings=(), skipped="no_source")

    active = runner or SlitherRunner()
    result: SlitherResult = active.run(
        source_code, contract_name, compiler_version, extra_files=extra_files
    )
    if not result.ran:
        log.info("source audit skipped for %s: %s", contract_name or "<unnamed>", result.skipped)
        return SourceAudit(findings=(), skipped=result.skipped)

    findings = tuple(to_rule_finding(f) for f in result.findings)
    return SourceAudit(findings=findings)


def risk_vectors(findings: Mapping[str, int] | list[str]) -> list[str]:
    """The distinct risk vectors in a set of detectors.

    Args:
        findings: Either a mapping of detector name to count, or a list of
            detector names.

    Returns:
        The distinct vectors, sorted, so a report can summarise coverage.
    """
    names = findings.keys() if isinstance(findings, Mapping) else findings
    vectors = {DETECTOR_TO_VECTOR.get(name, name) for name in names}
    return sorted(vectors)
