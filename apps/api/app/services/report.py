"""Deterministic PDF reporting for CyberStratum scans.

The PDF is the product surface for disclosure: it is what gets emailed to a
project team. Two properties make it defensible:

**Reproducibility.** The same evidence must always produce the same document,
byte for byte. ReportLab's ``invariant`` mode is used together with pinned
document metadata, a pinned creation date, and a total order on every
collection, so re-rendering a scan yields an identical SHA-256. A report can
therefore be regenerated and diffed against the original to show it was not
edited afterwards, and its hash can be recorded next to the finding.

**Honesty about evidence.** The evidence model (ADR-0017) has two kinds that
are not interchangeable: *bytecode* evidence (byte offset / PC, opcode,
instruction sequence, CFG path, reachability) and *source* evidence (a file
and a line). A source file and line may only be claimed when the
source-to-bytecode correspondence chain was actually proven; otherwise the
finding is bytecode-only and the report says so instead of inventing a
location. Likewise an engine that produced no verdict is reported as
``no verdict`` -- never as ``clean`` or ``passed`` -- because an engine that
did not run has not cleared the contract of anything.

The renderer is deliberately split from the data model:

* :func:`build_report_data` turns already-materialised values (plain dicts and
  dataclasses, never ORM rows) into a :class:`ReportData` value object.
* :func:`render_report` is a pure function of that value object and returns
  the PDF bytes.
* :func:`report_sha256` hashes the bytes.

Because :class:`ReportData` carries no database and no framework types, the
content rules are unit-testable without a database, without FastAPI, and
without ReportLab being importable at all.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import os
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Final

from app.core.logging import get_logger
from app.services.knowledge import guidance_for

log = get_logger(__name__)

#: Rendered wherever a value is absent. A missing value is never silently
#: omitted: a reader has to be able to tell "not applicable" from "we did
#: not look".
NOT_AVAILABLE: Final[str] = "not available"

#: Rendered for an engine that did not produce a verdict. The wording is
#: fixed by the product's evidence rules: an engine that did not run has not
#: cleared the contract, so it is never described as clean or passed.
NO_VERDICT: Final[str] = "no verdict"

#: The correspondence statuses that license a source file and line in the
#: report. ``established`` is the stored enum value
#: (``CorrespondenceStatus.ESTABLISHED``); ``proven`` is the plain word the
#: design notes use. ``mismatch``, ``skipped`` and ``unavailable`` are
#: deliberately absent: they mean the check ran and failed, or never ran.
PROVEN_CORRESPONDENCE_STATUSES: Final[frozenset[str]] = frozenset({"established", "proven"})

#: The severities, most urgent first, in the order the summary table lists
#: them. Every severity is listed, including the ones with a count of zero.
SEVERITY_ORDER: Final[tuple[str, ...]] = ("critical", "high", "medium", "low", "info")

#: The epoch the PDF's own creation date is pinned to. It is the same value
#: ReportLab's invariant mode uses, and it is deliberately in the past: a
#: report's PDF metadata carries no information about when it was produced.
#: The generation time, when it is wanted at all, is supplied by the caller
#: and printed in the document body.
PINNED_EPOCH: Final[str] = "946684800"

#: Serialises the brief window in which the epoch environment variable is
#: pinned. ReportLab reads that variable when it constructs the document, so
#: the read has to happen under the pin.
_EPOCH_LOCK: Final[threading.Lock] = threading.Lock()

#: Document metadata. These are constants: they must never carry a machine
#: name, a user name, a file system path or a version that varies between
#: machines, because the PDF bytes are meant to be reproducible.
DOC_TITLE: Final[str] = "CyberStratum Security Analysis Report"
DOC_AUTHOR: Final[str] = "CyberStratum"
DOC_SUBJECT: Final[str] = "Automated smart-contract analysis report"
DOC_CREATOR: Final[str] = "CyberStratum Report Service"
DOC_PRODUCER: Final[str] = "CyberStratum Report Service"

#: The one-line statement of what the report is and is not.
DOC_PURPOSE: Final[str] = (
    "This report presents the evidence collected by automated static analysis of a "
    "deployed contract's runtime bytecode. It does not assert that any finding is "
    "exploitable, and it is not a statement that the contract is free of "
    "vulnerabilities."
)

#: The closing limitations block. The wording is fixed for the same reason as
#: the evidence rules: the report must not imply more than the analysis can
#: establish.
DOC_DISCLAIMER: Final[tuple[str, ...]] = (
    "This report presents evidence collected by automated analysis of the deployed "
    "runtime bytecode. It does not assert that any finding is exploitable, that any "
    "code path is reachable in production, or that any finding is a false positive.",
    "The absence of findings is not proof of the absence of vulnerabilities. Coverage "
    "is limited by what static analysis can decide: unresolved control flow, "
    "unverified source and engines that produced no verdict all reduce it.",
    "Source file and line numbers appear only where the source-to-bytecode "
    "correspondence chain was proven. Elsewhere the evidence is byte offset, "
    "instruction sequence and control-flow reachability, and no source location is "
    "claimed.",
)


class ReportRenderError(RuntimeError):
    """Raised when a report cannot be rendered."""


class ReportLabUnavailableError(ReportRenderError):
    """Raised when ReportLab is not importable.

    ReportLab is imported lazily, inside the render call, so that this module
    stays importable in environments where the dependency is absent (for
    example a documentation build or a lint-only container). The failure is
    reported at call time and is catchable on its own.
    """


@dataclass(frozen=True, slots=True)
class ReportFinding:
    """One finding, in the shape the report renders it.

    Attributes:
        detector_id: The detector that produced the finding.
        category: The shared risk category.
        title: A one-line summary of the finding.
        description: The longer explanation.
        severity: The severity name, e.g. ``"high"``.
        confidence: The detector's confidence, between 0 and 1. Severity and
            confidence are separate: neither implies the other.
        source: Which engine produced the finding (``rule``, ``slither``,
            ``ml``, ...).
        evidence: The evidence dict, as stored on the finding row.
        limitations: What this evidence does and does not establish.
        status: The triage status of the finding.
        finding_id: The finding's identifier, used to link back to the
            platform.
    """

    detector_id: str
    category: str
    title: str
    description: str
    severity: str
    confidence: float
    source: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    limitations: str = ""
    status: str = ""
    finding_id: str = ""
    guidance: Mapping[str, Any] | None = None
    """What the detector's finding means and what to do about it.

    The guidance is what turns a pattern into an action. It is absent
    when the product has no guidance for that detector, and the report
    then says nothing about a fix rather than inventing one.
    """


@dataclass(frozen=True, slots=True)
class ReportArtifact:
    """One stored artifact of a scan."""

    kind: str
    object_key: str
    content_type: str = ""
    byte_size: int | None = None
    sha256: str = ""


@dataclass(frozen=True, slots=True)
class EngineReport:
    """The coverage of one analysis engine on one scan.

    Attributes:
        name: The engine name (``rule``, ``slither``, ...).
        ran: Whether the engine ran at all.
        finding_count: How many findings the engine produced.
        detail: A verbatim note, e.g. the reason the engine was skipped.
    """

    name: str
    ran: bool
    finding_count: int = 0
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ManifestRef:
    """A reference to a dataset or model manifest."""

    manifest_id: str = ""
    sha256: str = ""


@dataclass(frozen=True, slots=True)
class CorrespondenceProof:
    """The outcome of the source-to-bytecode correspondence chain.

    Attributes:
        status: ``proven``, ``failed``, ``skipped``, ``error`` or
            ``not_attempted``.
        compiler: The compiler used for the recompilation, when there was one.
        settings: The compiler settings used.
        statement: A one-line statement of the outcome.
    """

    status: str = "not_attempted"
    compiler: str = ""
    settings: str = ""
    statement: str = ""


@dataclass(frozen=True, slots=True)
class ReportData:
    """Everything the report renders, and nothing else.

    This is a plain value object: it holds no ORM row, no session, no
    framework type and no reference to ReportLab. Two instances that carry
    the same content render to the same bytes regardless of the order in
    which their collections were assembled.
    """

    scan_id: str
    contract_address: str
    chain_id: int | None = None
    fork: str = ""
    fork_source: str = ""
    fork_conflict: bool = False
    scan_status: str = ""
    findings: tuple[ReportFinding, ...] = ()
    artifacts: tuple[ReportArtifact, ...] = ()
    engines: tuple[EngineReport, ...] = ()
    tool_versions: Mapping[str, str] = field(default_factory=dict)
    dataset_manifest: ManifestRef | None = None
    model_manifest: ManifestRef | None = None
    correspondence: CorrespondenceProof | None = None
    timestamp: str | None = None
    """An explicitly supplied timestamp.

    The report never reads the clock. When a timestamp is wanted it is
    passed in by the caller, so the document still reproduces.
    """

    block_number: int | None = None
    """The block the bytecode was fetched at, when it is known."""

    runtime_sha256: str = ""
    """The SHA-256 of the analysed runtime bytecode, when it is known."""

    compiler_version: str = ""
    """The compiler version recorded for the contract, when it is known."""

    verification_state: str = ""
    """The contract's verification state, when it is known."""

    reproduction: tuple[str, ...] = ()
    """The commands and inputs a reviewer needs to reproduce the analysis."""

    disclosure_status: str = ""
    """The disclosure status: draft, ready, submitted or closed."""

    disclosure_reference: str = ""
    """The disclosure programme or reference, when there is one."""

    finding_base_url: str = ""
    """The base URL a finding is linked back to on the platform.

    When set, every finding carries a link to its machine-readable form.
    """

    limitations: tuple[str, ...] = ()
    """What the analysis could not cover, in plain sentences.

    A partial scan is not a clean scan with fewer findings. These
    lines say what was left out, so a reader can judge the result
    instead of having to trust it.
    """


# -- building the data model ---------------------------------------------


def _severity_name(value: object) -> str:
    """Normalise a severity to its lower-case name."""
    return str(value).strip().lower()


def _confidence(value: object) -> float:
    """Coerce a confidence to a float, defaulting to zero."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _finding_from_mapping(raw: Mapping[str, Any]) -> ReportFinding:
    """Build a :class:`ReportFinding` from a plain mapping."""
    raw_evidence = raw.get("evidence") or raw.get("evidence_json") or {}
    evidence: dict[str, Any] = dict(raw_evidence) if isinstance(raw_evidence, Mapping) else {}
    limitations = str(raw.get("limitations") or evidence.get("limitations") or "")
    detector_id = str(raw.get("detector_id") or "")
    guidance = guidance_for(detector_id)
    return ReportFinding(
        detector_id=str(raw.get("detector_id") or ""),
        category=str(raw.get("category") or ""),
        title=str(raw.get("title") or ""),
        description=str(raw.get("description") or ""),
        severity=_severity_name(raw.get("severity") or ""),
        confidence=_confidence(raw.get("confidence")),
        source=str(raw.get("source") or "rule"),
        evidence=evidence,
        limitations=limitations,
        status=str(raw.get("status") or ""),
        finding_id=str(raw.get("finding_id") or raw.get("id") or ""),
        guidance=guidance.as_dict() if guidance is not None else None,
    )


def _artifact_from_mapping(raw: Mapping[str, Any]) -> ReportArtifact:
    """Build a :class:`ReportArtifact` from a plain mapping."""
    size = raw.get("byte_size")
    return ReportArtifact(
        kind=str(raw.get("kind") or ""),
        object_key=str(raw.get("object_key") or ""),
        content_type=str(raw.get("content_type") or ""),
        byte_size=int(size) if isinstance(size, int) else None,
        sha256=str(raw.get("sha256") or ""),
    )


def _manifest_from_mapping(raw: Mapping[str, Any]) -> ManifestRef:
    """Build a :class:`ManifestRef` from a plain mapping."""
    manifest_id = raw.get("manifest_id") or raw.get("id") or ""
    sha256 = raw.get("sha256") or raw.get("hash") or ""
    return ManifestRef(manifest_id=str(manifest_id), sha256=str(sha256))


def _correspondence_from_mapping(raw: Mapping[str, Any]) -> CorrespondenceProof:
    """Build a :class:`CorrespondenceProof` from a plain mapping."""
    return CorrespondenceProof(
        status=str(raw.get("status") or "not_attempted"),
        compiler=str(raw.get("compiler") or ""),
        settings=str(raw.get("settings") or ""),
        statement=str(raw.get("statement") or ""),
    )


def _engine_from_mapping(raw: Mapping[str, Any]) -> EngineReport:
    """Build an :class:`EngineReport` from a plain mapping."""
    ran = raw.get("ran")
    if ran is None:
        ran = bool(raw.get("verdict")) or str(raw.get("status") or "") == "ran"
    count = raw.get("finding_count")
    return EngineReport(
        name=str(raw.get("name") or raw.get("engine") or ""),
        ran=bool(ran),
        finding_count=int(count) if isinstance(count, int) else 0,
        detail=str(raw.get("detail") or raw.get("reason") or ""),
    )


def _finding_sort_key(finding: ReportFinding) -> tuple[int, str, str, str]:
    """A total order over findings.

    The order is by severity first (most urgent first), then by detector,
    engine and title. The last three components make the order total, so two
    findings that agree on all of them are interchangeable and the rendered
    document cannot depend on the order they arrived in.
    """
    severity = finding.severity
    rank = SEVERITY_ORDER.index(severity) if severity in SEVERITY_ORDER else len(SEVERITY_ORDER)
    return (rank, finding.detector_id, finding.source, finding.title)


def _derive_engines(
    findings: Sequence[ReportFinding],
    scan_status: str,
    source_audited: bool | None,
    source_audit_skipped: str | None,
    mythril_ran: bool | None = None,
    mythril_skipped: str | None = None,
    model_version: str | None = None,
) -> tuple[EngineReport, ...]:
    """Work out which engines ran on a scan.

    Every engine the product knows about is listed, whether it ran or not.
    A report that silently omits an engine is indistinguishable from a
    report where that engine found nothing, so an engine that did not run is
    reported as ``no verdict``.

    The bytecode rule engine runs as part of the pipeline, so it is reported
    as having run unless the scan never got that far. The source engine runs
    only over verified source, so it is reported as not having run when the
    scan recorded a skip reason -- and that reason is carried verbatim.
    """
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.source] = counts.get(finding.source, 0) + 1

    never_ran = {
        "queued",
        "fetching_bytecode",
        "disassembling",
        "building_cfg",
        "extracting_features",
        "failed",
        "cancelled",
    }
    engines: list[EngineReport] = []

    rule_ran = bool(counts.get("rule")) or scan_status.strip().lower() not in never_ran
    engines.append(
        EngineReport(
            name="rule",
            ran=rule_ran,
            finding_count=counts.get("rule", 0),
            detail="" if rule_ran else "the scan did not reach the detector stage",
        )
    )

    if source_audited is True:
        engines.append(
            EngineReport(
                name="slither",
                ran=True,
                finding_count=counts.get("slither", 0),
            )
        )
    elif source_audit_skipped:
        engines.append(
            EngineReport(
                name="slither",
                ran=False,
                finding_count=0,
                detail=source_audit_skipped,
            )
        )
    elif counts.get("slither"):
        engines.append(
            EngineReport(
                name="slither",
                ran=True,
                finding_count=counts["slither"],
            )
        )
    else:
        engines.append(
            EngineReport(
                name="slither",
                ran=False,
                finding_count=0,
                detail="the source engine did not run",
            )
        )

    if mythril_ran is True:
        engines.append(
            EngineReport(
                name="mythril",
                ran=True,
                finding_count=counts.get("mythril", 0),
            )
        )
    elif mythril_skipped:
        engines.append(
            EngineReport(
                name="mythril",
                ran=False,
                finding_count=0,
                detail=mythril_skipped,
            )
        )
    else:
        engines.append(
            EngineReport(
                name="mythril",
                ran=False,
                finding_count=counts.get("mythril", 0),
                detail="the symbolic-execution engine did not run",
            )
        )

    model_ran = bool(model_version) or bool(counts.get("ml"))
    engines.append(
        EngineReport(
            name="ml",
            ran=model_ran,
            finding_count=counts.get("ml", 0),
            detail="" if model_ran else "no model was applied to this scan",
        )
    )

    for name in sorted(set(counts) - {"rule", "slither", "mythril", "ml"}):
        engines.append(
            EngineReport(
                name=name,
                ran=True,
                finding_count=counts[name],
            )
        )
    return tuple(engines)


def build_report_data(
    *,
    scan_id: str,
    contract_address: str,
    chain_id: int | None = None,
    fork: str = "",
    fork_source: str = "",
    fork_conflict: bool = False,
    scan_status: str = "",
    findings: Sequence[Mapping[str, Any]] = (),
    artifacts: Sequence[Mapping[str, Any]] = (),
    tool_versions: Mapping[str, str] | None = None,
    dataset_manifest: Mapping[str, Any] | None = None,
    model_manifest: Mapping[str, Any] | None = None,
    correspondence: Mapping[str, Any] | None = None,
    source_audited: bool | None = None,
    source_audit_skipped: str | None = None,
    mythril_ran: bool | None = None,
    mythril_skipped: str | None = None,
    engines: Sequence[Mapping[str, Any]] | None = None,
    timestamp: str | None = None,
    block_number: int | None = None,
    runtime_sha256: str = "",
    compiler_version: str = "",
    verification_state: str = "",
    reproduction: Sequence[str] = (),
    disclosure_status: str = "",
    disclosure_reference: str = "",
    finding_base_url: str = "",
    limitations: Mapping[str, Any] | None = None,
) -> ReportData:
    """Build a :class:`ReportData` from already-materialised values.

    Args:
        scan_id: The scan's identifier.
        contract_address: The analysed contract's address.
        chain_id: The EIP-155 chain id.
        fork: The EVM fork the analysis targeted.
        fork_source: How the fork was chosen ('requested', 'inferred' or
            'fallback').
        fork_conflict: True when the analysed fork is older than the
            bytecode requires.
        scan_status: The scan's terminal status.
        findings: The findings, as plain mappings.
        artifacts: The scan's artifacts, as plain mappings.
        tool_versions: Tool versions, keyed by tool name (``parser``,
            ``ruleset``, ``model``, and any external engine).
        dataset_manifest: The dataset manifest reference, if there is one.
        model_manifest: The model manifest reference, if there is one.
        correspondence: The outcome of the correspondence chain, if it was
            attempted.
        source_audited: Whether the source engine ran for this scan.
        source_audit_skipped: Why the source engine did not run, verbatim.
        mythril_ran: Whether the symbolic-execution engine ran for this scan.
        mythril_skipped: Why it did not run, verbatim.
        engines: An explicit engine breakdown. When omitted it is derived
            from the findings and the source-audit flags.
        timestamp: An explicitly supplied timestamp for the document.
        block_number: The block the bytecode was fetched at.
        runtime_sha256: The SHA-256 of the analysed runtime bytecode.
        compiler_version: The compiler version recorded for the contract.
        verification_state: The contract's verification state.
        reproduction: The commands a reviewer needs to reproduce the analysis.
        disclosure_status: The disclosure status.
        disclosure_reference: The disclosure programme or reference.
        finding_base_url: The base URL findings are linked back to.

    Returns:
        The report data, ready to render.
    """
    built_findings = tuple(_finding_from_mapping(item) for item in findings)
    built_artifacts = tuple(_artifact_from_mapping(item) for item in artifacts)

    if engines is None:
        built_engines = _derive_engines(
            built_findings,
            scan_status,
            source_audited,
            source_audit_skipped,
            mythril_ran,
            mythril_skipped,
            (tool_versions or {}).get("model") or None,
        )
    else:
        built_engines = tuple(_engine_from_mapping(item) for item in engines)

    return ReportData(
        scan_id=str(scan_id),
        contract_address=str(contract_address),
        chain_id=chain_id,
        fork=str(fork),
        fork_source=str(fork_source),
        fork_conflict=bool(fork_conflict),
        scan_status=str(scan_status),
        findings=built_findings,
        artifacts=built_artifacts,
        engines=built_engines,
        limitations=_limitation_lines(limitations),
        tool_versions=dict(tool_versions or {}),
        dataset_manifest=(
            _manifest_from_mapping(dataset_manifest) if dataset_manifest is not None else None
        ),
        model_manifest=(
            _manifest_from_mapping(model_manifest) if model_manifest is not None else None
        ),
        correspondence=(
            _correspondence_from_mapping(correspondence) if correspondence is not None else None
        ),
        timestamp=timestamp,
        block_number=block_number,
        runtime_sha256=str(runtime_sha256 or ""),
        compiler_version=str(compiler_version or ""),
        verification_state=str(verification_state or ""),
        reproduction=tuple(str(item) for item in reproduction),
        disclosure_status=str(disclosure_status or ""),
        disclosure_reference=str(disclosure_reference or ""),
        finding_base_url=str(finding_base_url or ""),
    )


# -- evidence interpretation ---------------------------------------------


#: The evidence keys that carry bytecode-level facts. Matching is done on
#: the exact key names below plus any key that ends in ``Offset``, which is
#: how the rule engine names its offsets (``callOffset``,
#: ``storageWriteOffset``, ``instructionOffset``).
BYTECODE_OFFSET_KEYS: Final[tuple[str, ...]] = ("offset", "byteOffset", "byte_offset")

#: The evidence keys that carry source-level facts, in priority order: the
#: first key present wins.
SOURCE_FILE_KEYS: Final[tuple[str, ...]] = (
    "sourceFile",
    "source_file",
    "file",
    "contractPath",
)
SOURCE_LINE_KEYS: Final[tuple[str, ...]] = ("sourceLine", "source_line", "line")


def _is_bytecode_key(key: str) -> bool:
    """Whether an evidence key carries bytecode-level information."""
    return key in BYTECODE_OFFSET_KEYS or key.endswith("Offset")


def _evidence_kind(evidence: Mapping[str, Any]) -> str:
    """Classify the evidence of a finding.

    Returns one of ``source_line``, ``bytecode``, ``correlated`` or
    ``other``. The distinction matters because the two kinds support
    different claims.
    """
    declared = str(evidence.get("type") or evidence.get("evidence_type") or "").strip().lower()
    if declared in {"source_line", "bytecode_offset", "bytecode_pc", "cfg_edge"}:
        if declared == "source_line":
            return "source_line"
        return "bytecode"
    if declared == "source_bytecode_correlation":
        return "correlated"

    has_bytecode = any(
        _is_bytecode_key(key)
        or key
        in {
            "pc",
            "programCounter",
            "opcode",
            "opcodeName",
            "opcode_name",
            "instructionSequence",
            "instructions",
            "instruction_sequence",
            "cfgPath",
            "cfg_path",
            "path",
            "offsets",
            "reachable",
            "isReachable",
        }
        for key in evidence
    )
    has_source = any(key in SOURCE_FILE_KEYS or key in SOURCE_LINE_KEYS for key in evidence)
    if has_bytecode and has_source:
        return "correlated"
    if has_bytecode:
        return "bytecode"
    if has_source:
        return "source_line"
    return "other"


def _first_value(evidence: Mapping[str, Any], *keys: str) -> Any:
    """Return the first present, non-empty value among ``keys``."""
    for key in keys:
        if key in evidence:
            value = evidence[key]
            if value not in (None, "", [], {}):
                return value
    return None


def _format_offset(value: object) -> str:
    """Format a byte offset as hex with its decimal value."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"0x{value:x} ({value})"
    return str(value)


def _format_sequence(value: object) -> str:
    """Format an instruction sequence or a CFG path as a readable string."""
    if isinstance(value, (list, tuple)):
        return " -> ".join(_format_offset(item) for item in value)
    return str(value)


def _source_location(evidence: Mapping[str, Any]) -> tuple[str, str]:
    """Return the source file and source line carried by an evidence dict."""
    file_value = _first_value(evidence, *SOURCE_FILE_KEYS)
    line_value = _first_value(evidence, *SOURCE_LINE_KEYS)
    file_name = str(file_value) if file_value is not None else ""
    line = str(line_value) if line_value is not None else ""
    return file_name, line


def _correspondence_is_proven(
    evidence: Mapping[str, Any],
    proof: CorrespondenceProof | None,
) -> bool:
    """Whether a source location may be claimed for a finding.

    A location is claimable only when the correspondence chain was proven.
    The chain can be proven for the scan as a whole, or recorded on the
    finding itself.

    The accepted status spellings cover both the stored enum
    (``CorrespondenceStatus.ESTABLISHED``) and the plain word ``proven``.
    Nothing else counts: ``mismatch`` means the published source does not
    describe the deployed contract, and ``skipped`` / ``unavailable`` mean
    the check never ran. Neither licenses a source location.
    """
    if evidence.get("correspondenceProven") or evidence.get("correspondence_proven"):
        return True
    if proof is None:
        return False
    return proof.status.strip().lower() in PROVEN_CORRESPONDENCE_STATUSES


def _evidence_lines(
    finding: ReportFinding,
    proof: CorrespondenceProof | None,
) -> list[str]:
    """Render the evidence of a finding as report lines.

    Bytecode evidence is rendered as offset, opcode, instruction sequence,
    CFG path and reachability. A source file and line are rendered only when
    the correspondence chain was proven; otherwise the report states that the
    finding is bytecode-only and claims no source location.
    """
    evidence = finding.evidence
    kind = _evidence_kind(evidence)
    lines: list[str] = []

    if kind == "other":
        lines.append("Evidence type: not classified")
    elif kind == "source_line":
        lines.append("Evidence type: source line")
    elif kind == "correlated":
        lines.append("Evidence type: source-to-bytecode correlation")
    else:
        lines.append("Evidence type: bytecode")

    offset = _first_value(evidence, "offset", "byteOffset", "byte_offset")
    if offset is not None:
        lines.append(f"Byte offset: {_format_offset(offset)}")

    pc = _first_value(evidence, "pc", "programCounter")
    if pc is not None:
        lines.append(f"Program counter: {_format_offset(pc)}")

    offsets = _first_value(evidence, "offsets")
    if offsets is not None:
        if isinstance(offsets, (list, tuple)):
            lines.append(f"Byte offsets: {_format_sequence(offsets)}")
        else:
            lines.append(f"Byte offsets: {_format_offset(offsets)}")

    # The rule engine names its offsets after the role they play
    # (``callOffset``, ``storageWriteOffset``, ``instructionOffset``). Each
    # is reported under its own name so the reader knows what the offset
    # refers to, and none of them is a source location.
    for key in sorted(evidence):
        if not _is_bytecode_key(key) or key in BYTECODE_OFFSET_KEYS:
            continue
        value = evidence[key]
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (list, tuple)):
            lines.append(f"{key}: {_format_sequence(value)}")
        else:
            lines.append(f"{key}: {_format_offset(value)}")

    opcode = _first_value(evidence, "opcode", "opcodeName", "opcode_name")
    if opcode is not None:
        lines.append(f"Opcode: {opcode}")

    sequence = _first_value(evidence, "instructionSequence", "instructions", "instruction_sequence")
    if sequence is not None:
        lines.append(f"Instruction sequence: {_format_sequence(sequence)}")

    cfg_path = _first_value(evidence, "cfgPath", "cfg_path", "path")
    if cfg_path is not None:
        lines.append(f"CFG path: {_format_sequence(cfg_path)}")

    reachable = _first_value(evidence, "reachable", "isReachable")
    if reachable is not None:
        if isinstance(reachable, bool):
            lines.append(f"Reachability: {'reachable' if reachable else 'not reachable'}")
        else:
            lines.append(f"Reachability: {reachable}")

    file_name, line = _source_location(evidence)
    proven = _correspondence_is_proven(evidence, proof)
    if file_name or line:
        if proven:
            if file_name:
                lines.append(f"Source file: {file_name}")
            if line:
                lines.append(f"Source line: {line}")
        elif kind == "source_line":
            lines.append(
                "Source location withheld: the source-to-bytecode correspondence chain "
                "was not proven, so no source file or line is claimed."
            )
        else:
            lines.append(
                "Bytecode-only finding: no source file or line is claimed, because the "
                "source-to-bytecode correspondence chain was not proven."
            )
    elif kind in {"bytecode", "correlated"} and not proven:
        lines.append(
            "Bytecode-only finding: no source file or line is claimed, because the "
            "source-to-bytecode correspondence chain was not proven."
        )

    extras = _extra_evidence(evidence)
    if extras:
        lines.append("Additional evidence:")
        lines.extend(f"  {key}: {value}" for key, value in extras)
    return lines


def _extra_evidence(evidence: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Return the evidence entries that are not rendered above, sorted.

    The source-location keys are excluded here as well: they must never
    reach the document through the back door when the correspondence chain
    was not proven.
    """
    rendered = {
        "type",
        "evidence_type",
        "pc",
        "programCounter",
        "offsets",
        "opcode",
        "opcodeName",
        "opcode_name",
        "instructionSequence",
        "instructions",
        "instruction_sequence",
        "cfgPath",
        "cfg_path",
        "path",
        "reachable",
        "isReachable",
        "correspondenceProven",
        "correspondence_proven",
        "limitations",
    }
    rendered.update(BYTECODE_OFFSET_KEYS)
    rendered.update(SOURCE_FILE_KEYS)
    rendered.update(SOURCE_LINE_KEYS)
    extras: list[tuple[str, str]] = []
    for key in sorted(evidence):
        if key in rendered or _is_bytecode_key(key):
            continue
        value = evidence[key]
        if isinstance(value, (list, tuple)):
            text = ", ".join(str(item) for item in value)
        elif isinstance(value, Mapping):
            text = ", ".join(f"{name}={item}" for name, item in sorted(value.items()))
        else:
            text = str(value)
        extras.append((key, text))
    return extras


# -- the content model ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Line:
    """A single line of text with a named style."""

    text: str
    style: str = "body"


@dataclass(frozen=True, slots=True)
class _Table:
    """A table of rows, with a header row."""

    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    widths: tuple[float, ...] | None = None
    right_aligned: tuple[int, ...] = ()


_Block = _Line | _Table


def _severity_summary(findings: Sequence[ReportFinding]) -> _Table:
    """The count of findings per severity.

    Every known severity is listed, including the ones with a count of zero,
    so that a reader can see what was looked for and not found. A severity
    outside the known set is listed after them rather than dropped, so the
    counts always add up to the number of findings.
    """
    counts: dict[str, int] = {}
    for name in SEVERITY_ORDER:
        counts[name] = 0
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    ordered = [*SEVERITY_ORDER, *sorted(set(counts) - set(SEVERITY_ORDER))]
    rows = tuple((name, str(counts[name])) for name in ordered)
    return _Table(header=("Severity", "Findings"), rows=rows, widths=(0.7, 0.3), right_aligned=(1,))


def _limitation_lines(limitations: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Turn a scan's stored limitations into readable sentences.

    The stored form is a JSON document so that it can be queried. The
    report is for a reader, so the same information is rendered as
    sentences, in a fixed order, and nothing is dropped.
    """
    if not limitations:
        return ()

    lines: list[str] = []
    warnings = limitations.get("disassembly_warnings")
    if isinstance(warnings, list) and warnings:
        shown = "; ".join(str(item) for item in warnings[:5])
        more = "" if len(warnings) <= 5 else f" (and {len(warnings) - 5} more)"
        lines.append(f"{len(warnings)} disassembly warning(s): {shown}{more}")

    edges = limitations.get("unresolved_control_flow_edges")
    if isinstance(edges, int):
        ratio = limitations.get("unresolved_edge_ratio")
        detail = f"{edges} control-flow edge(s) could not be resolved statically"
        if isinstance(ratio, (int, float)):
            detail += f" ({float(ratio):.1%} of the graph)"
        lines.append(detail)

    known = {"disassembly_warnings", "unresolved_control_flow_edges", "unresolved_edge_ratio"}
    for key in sorted(limitations):
        if key in known:
            continue
        lines.append(f"{key}: {limitations[key]}")
    return tuple(lines)


def _engine_summary(engines: Sequence[EngineReport]) -> _Table:
    """The per-engine breakdown: who ran, who did not, and why."""
    rows: list[tuple[str, ...]] = []
    for engine in sorted(engines, key=lambda item: item.name):
        status = "ran" if engine.ran else NO_VERDICT
        rows.append((engine.name, status, str(engine.finding_count), engine.detail))
    if not rows:
        rows.append((NOT_AVAILABLE, NO_VERDICT, "0", ""))
    return _Table(
        header=("Engine", "Status", "Findings", "Notes"),
        rows=tuple(rows),
        widths=(0.18, 0.22, 0.15, 0.45),
        right_aligned=(2,),
    )


def _provenance_lines(data: ReportData) -> list[_Block]:
    """The provenance blocks: versions, manifests and the correspondence proof."""
    versions = data.tool_versions
    known = ("parser", "ruleset", "model")
    rows: list[tuple[str, ...]] = []
    for name in known:
        rows.append((f"{name} version", versions.get(name) or NOT_AVAILABLE))
    for name in sorted(set(versions) - set(known)):
        rows.append((f"{name} version", versions.get(name) or NOT_AVAILABLE))

    dataset = data.dataset_manifest
    model = data.model_manifest
    rows.append(("dataset manifest id", (dataset.manifest_id if dataset else "") or NOT_AVAILABLE))
    rows.append(("dataset manifest sha256", (dataset.sha256 if dataset else "") or NOT_AVAILABLE))
    rows.append(("model manifest id", (model.manifest_id if model else "") or NOT_AVAILABLE))
    rows.append(("model manifest sha256", (model.sha256 if model else "") or NOT_AVAILABLE))

    proof = data.correspondence
    rows.append(("correspondence proof", (proof.status if proof else "") or NOT_AVAILABLE))
    if proof is not None:
        rows.append(("correspondence compiler", proof.compiler or NOT_AVAILABLE))
        rows.append(("correspondence settings", proof.settings or NOT_AVAILABLE))

    blocks: list[_Block] = [
        _Line("Provenance", "heading"),
        _Table(header=("Item", "Value"), rows=tuple(rows), widths=(0.35, 0.65)),
    ]

    if proof is not None and proof.statement:
        blocks.append(_Line(f"Correspondence proof: {proof.statement}", "body"))
    elif proof is None:
        blocks.append(
            _Line(
                "Correspondence proof: not available. No source location is claimed "
                "anywhere in this report.",
                "body",
            )
        )

    artifacts = sorted(data.artifacts, key=lambda item: (item.kind, item.object_key))
    if artifacts:
        artifact_rows = tuple(
            (
                artifact.kind,
                artifact.object_key,
                NOT_AVAILABLE if artifact.byte_size is None else str(artifact.byte_size),
                artifact.sha256 or NOT_AVAILABLE,
            )
            for artifact in artifacts
        )
        blocks.append(_Line("Artifacts", "heading"))
        blocks.append(
            _Table(
                header=("Kind", "Object key", "Bytes", "SHA-256"),
                rows=artifact_rows,
                widths=(0.16, 0.44, 0.14, 0.26),
                right_aligned=(2,),
            )
        )
    return blocks


def _guidance_blocks(finding: ReportFinding) -> list[_Block]:
    """Render the guidance for a finding, if there is any.

    Four things, in the order a reader needs them: what the pattern is,
    why it matters, what to change, and -- the part that saves a
    reviewer an afternoon -- when it is not a problem at all.
    """
    guidance = finding.guidance
    if not guidance:
        return []
    blocks: list[_Block] = [_Line("What this means", "heading")]
    for label, key in (
        ("What it is", "what_it_means"),
        ("Why it matters", "why_it_matters"),
        ("What to change", "how_to_fix"),
        ("When it is not a problem", "false_positive_patterns"),
        ("References", "references"),
    ):
        value = str(guidance.get(key) or "").strip()
        if value:
            blocks.append(_Line(f"{label}: {value}", "body"))
    return blocks


def _finding_blocks(
    finding: ReportFinding,
    proof: CorrespondenceProof | None,
    finding_base_url: str = "",
) -> list[_Block]:
    """Render one finding."""
    blocks: list[_Block] = [
        _Line(f"[{finding.severity.upper()}] {finding.title}", "finding"),
        _Line(f"Detector: {finding.detector_id or NOT_AVAILABLE}", "body"),
        _Line(f"Category: {finding.category or NOT_AVAILABLE}", "body"),
        _Line(f"Engine: {finding.source or NOT_AVAILABLE}", "body"),
        _Line(f"Confidence: {finding.confidence:.2f}", "body"),
    ]
    if finding.status:
        blocks.append(_Line(f"Status: {finding.status}", "body"))
    if finding.description:
        blocks.append(_Line(finding.description, "body"))
    blocks.extend(_guidance_blocks(finding))
    blocks.extend(_Line(line, "evidence") for line in _evidence_lines(finding, proof))
    limitations = finding.limitations or str(finding.evidence.get("limitations") or "")
    if limitations:
        blocks.append(_Line(f"Limitations: {limitations}", "body"))
    if finding_base_url and finding.finding_id:
        blocks.append(
            _Line(
                f"Platform record: {finding_base_url.rstrip('/')}/{finding.finding_id}",
                "body",
            )
        )
    return blocks


def _build_blocks(data: ReportData) -> list[_Block]:
    """Build the whole document as an ordered list of blocks.

    The blocks are the single source of truth for the document's content:
    the PDF renderer and :func:`text_fragments` both read them, so the text
    that is asserted on in the tests is exactly the text that is drawn.
    """
    blocks: list[_Block] = [
        _Line(DOC_TITLE, "title"),
        _Line(DOC_PURPOSE, "body"),
        _Line("Scan identity", "heading"),
    ]

    identity_rows: list[tuple[str, ...]] = [
        ("Contract address", data.contract_address or NOT_AVAILABLE),
        ("Chain id", NOT_AVAILABLE if data.chain_id is None else str(data.chain_id)),
        ("Fork", data.fork or NOT_AVAILABLE),
        ("Fork source", data.fork_source or NOT_AVAILABLE),
        (
            "Fork conflict",
            "yes - the bytecode cannot execute under the analysed fork"
            if data.fork_conflict
            else "no",
        ),
        ("Scan id", data.scan_id or NOT_AVAILABLE),
        ("Scan status", data.scan_status or NOT_AVAILABLE),
        ("Report timestamp", data.timestamp or NOT_AVAILABLE),
        ("Block number", NOT_AVAILABLE if data.block_number is None else str(data.block_number)),
        ("Runtime bytecode sha256", data.runtime_sha256 or NOT_AVAILABLE),
        ("Compiler version", data.compiler_version or NOT_AVAILABLE),
        ("Verification state", data.verification_state or NOT_AVAILABLE),
    ]
    blocks.append(_Table(header=("Field", "Value"), rows=tuple(identity_rows), widths=(0.3, 0.7)))

    findings = sorted(data.findings, key=_finding_sort_key)

    blocks.append(_Line("Summary", "heading"))
    blocks.append(_severity_summary(findings))
    blocks.append(_Line("Engine coverage", "heading"))
    blocks.append(_engine_summary(data.engines))
    blocks.append(
        _Line(
            "An engine that produced no verdict has not cleared the contract. "
            "'No verdict' means the engine did not run, or ran without producing "
            "a verdict.",
            "body",
        )
    )

    if data.limitations:
        blocks.append(_Line("Coverage limitations", "heading"))
        blocks.extend(_Line(f"  {line}", "evidence") for line in data.limitations)
        blocks.append(
            _Line(
                "These are the parts of the contract this scan could not "
                "analyse. The findings below are what the engines that did "
                "run were able to see.",
                "body",
            )
        )
        blocks.append(_Line("Findings", "heading"))
    if not findings:
        blocks.append(_Line("No findings were produced by the engines that ran.", "body"))
    for finding in findings:
        blocks.extend(_finding_blocks(finding, data.correspondence, data.finding_base_url))

    if data.reproduction:
        blocks.append(_Line("Reproduction", "heading"))
        blocks.extend(_Line(f"  {step}", "evidence") for step in data.reproduction)

    blocks.extend(_provenance_lines(data))

    blocks.append(_Line("Disclosure status", "heading"))
    blocks.append(
        _Table(
            header=("Field", "Value"),
            rows=(
                ("disclosure status", data.disclosure_status or NOT_AVAILABLE),
                ("disclosure reference", data.disclosure_reference or NOT_AVAILABLE),
            ),
            widths=(0.35, 0.65),
        )
    )

    blocks.append(_Line("Limitations and disclaimer", "heading"))
    blocks.extend(_Line(paragraph, "body") for paragraph in DOC_DISCLAIMER)
    return blocks


def text_fragments(data: ReportData) -> list[str]:
    """Return the text the report draws, in order.

    This is the content of the document without the rendering. It exists so
    the content rules can be asserted on without producing a PDF and
    without ReportLab being installed.
    """
    fragments: list[str] = []
    for block in _build_blocks(data):
        if isinstance(block, _Line):
            fragments.append(block.text)
        else:
            fragments.append(" | ".join(block.header))
            for row in block.rows:
                fragments.append(" | ".join(row))
    return fragments


#: Kept as a private alias so the helper can be reached under the name the
#: design notes use.
_text_fragments = text_fragments


# -- rendering -------------------------------------------------------------


def _import_reportlab(name: str) -> Any:
    """Import a ReportLab module, or raise a clear, catchable error."""
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise ReportLabUnavailableError(
            f"ReportLab is required to render a report but {name!r} could not be "
            "imported. Install the 'reportlab' package in the API environment."
        ) from exc


@contextmanager
def _pinned_epoch() -> Iterator[None]:
    """Pin the PDF creation epoch for the duration of a render.

    ReportLab's invariant mode uses a fixed epoch, but it defers to
    ``SOURCE_DATE_EPOCH`` when that variable is set. Left alone, the bytes
    of a report would then depend on an ambient environment variable that
    nobody passed to the renderer. Pinning the variable to a constant
    keeps the document identical on every machine and in every deployment.

    The variable is process-wide, so the window is serialised: a concurrent
    render in another thread would otherwise observe the pinned value, or
    the original one, at the wrong moment.
    """
    with _EPOCH_LOCK:
        previous = os.environ.get("SOURCE_DATE_EPOCH")
        os.environ["SOURCE_DATE_EPOCH"] = PINNED_EPOCH
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("SOURCE_DATE_EPOCH", None)
            else:
                os.environ["SOURCE_DATE_EPOCH"] = previous


def _story_for(blocks: Sequence[_Block], width: float) -> list[Any]:
    """Turn the blocks into ReportLab flowables."""
    platypus = _import_reportlab("reportlab.platypus")
    styles_module = _import_reportlab("reportlab.lib.styles")

    style_specs = {
        "title": ("Helvetica-Bold", 16, 20, 0, 8),
        "heading": ("Helvetica-Bold", 11, 14, 10, 4),
        "finding": ("Helvetica-Bold", 10, 13, 8, 2),
        "body": ("Helvetica", 9, 12, 0, 3),
        "evidence": ("Courier", 8, 10, 0, 1),
    }
    styles = {
        name: styles_module.ParagraphStyle(
            name,
            fontName=font,
            fontSize=size,
            leading=leading,
            spaceBefore=before,
            spaceAfter=after,
        )
        for name, (font, size, leading, before, after) in style_specs.items()
    }

    from xml.sax.saxutils import escape

    story: list[Any] = []
    for block in blocks:
        if isinstance(block, _Line):
            story.append(
                platypus.Paragraph(escape(block.text), styles.get(block.style, styles["body"]))
            )
            continue
        header = [platypus.Paragraph(escape(cell), styles["body"]) for cell in block.header]
        rows = [
            [platypus.Paragraph(escape(cell), styles["body"]) for cell in row] for row in block.rows
        ]
        table_data = [header, *rows]
        col_widths = (
            [width * fraction for fraction in block.widths] if block.widths is not None else None
        )
        table = platypus.Table(table_data, colWidths=col_widths, repeatRows=1)
        commands = [
            ("GRID", (0, 0), (-1, -1), 0.25, (0.6, 0.6, 0.6)),
            ("BACKGROUND", (0, 0), (-1, 0), (0.9, 0.9, 0.9)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        for column in block.right_aligned:
            commands.append(("ALIGN", (column, 1), (column, -1), "RIGHT"))
        table.setStyle(platypus.TableStyle(commands))
        story.append(table)
        story.append(platypus.Spacer(1, 6))
    return story


def render_report(data: ReportData) -> bytes:
    """Render the report and return the PDF bytes.

    The result is byte-identical for identical evidence: the document
    metadata is pinned to constants, the creation date is fixed by ReportLab's
    invariant mode, page compression is off so the byte layout does not
    depend on the compression library, and every collection in the document
    has a total order.

    Args:
        data: The report data.

    Returns:
        The PDF bytes.

    Raises:
        ReportLabUnavailableError: when ReportLab is not importable.
    """
    platypus = _import_reportlab("reportlab.platypus")
    pagesizes = _import_reportlab("reportlab.lib.pagesizes")
    canvas_module = _import_reportlab("reportlab.pdfgen.canvas")

    buffer = io.BytesIO()
    document = platypus.SimpleDocTemplate(
        buffer,
        pagesize=pagesizes.A4,
        leftMargin=45,
        rightMargin=45,
        topMargin=45,
        bottomMargin=45,
        title=DOC_TITLE,
        author=DOC_AUTHOR,
        subject=DOC_SUBJECT,
        creator=DOC_CREATOR,
        producer=DOC_PRODUCER,
        invariant=1,
        pageCompression=0,
    )
    story = _story_for(_build_blocks(data), document.width)
    with _pinned_epoch():
        document.build(story, canvasmaker=canvas_module.Canvas)
    payload = buffer.getvalue()
    log.info("report_rendered", bytes=len(payload), scan_id=data.scan_id)
    return payload


def report_sha256(pdf_bytes: bytes) -> str:
    """Return the SHA-256 of the rendered report, as a hex digest."""
    return hashlib.sha256(pdf_bytes).hexdigest()


__all__ = [
    "DOC_AUTHOR",
    "DOC_CREATOR",
    "DOC_DISCLAIMER",
    "DOC_PRODUCER",
    "DOC_PURPOSE",
    "DOC_SUBJECT",
    "DOC_TITLE",
    "NO_VERDICT",
    "NOT_AVAILABLE",
    "PINNED_EPOCH",
    "PROVEN_CORRESPONDENCE_STATUSES",
    "SEVERITY_ORDER",
    "CorrespondenceProof",
    "EngineReport",
    "ManifestRef",
    "ReportArtifact",
    "ReportData",
    "ReportFinding",
    "ReportLabUnavailableError",
    "ReportRenderError",
    "build_report_data",
    "render_report",
    "report_sha256",
    "text_fragments",
]
