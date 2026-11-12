"""The scan pipeline.

Implements design doc section 5.1 stages 3-9:

* intake (hash + store the bytecode artifact),
* disassembly with the fork-specific opcode table,
* CFG construction,
* feature extraction,
* rule engine execution,
* result normalisation into findings,
* terminal scan status.

Every stage is deterministic and versioned; the parser/ruleset versions are
recorded on the scan row.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.enums import FindingStatus, ScanJobStatus, ScanStatus
from app.db.models.identity import ContractTarget
from app.db.models.scans import (
    BasicBlock,
    CfgEdge,
    FeatureRecord,
    Finding,
    Instruction,
    Scan,
    ScanArtifact,
    ScanJob,
)
from app.services import storage
from app.services.bytecode import BytecodeArtifact, BytecodeUnavailableError, fetch_runtime_bytecode
from app.services.fork_resolution import resolve_fork
from app.services.ml_ranking import (
    annotate_findings,
    load_installed_model,
    score_bytecode,
)
from app.services.model_manifest import ModelManifestError
from app.services.rules import PARSER_VERSION, RULESET_VERSION, RuleFinding, run_rules
from app.services.slither import SlitherRunner
from app.services.source_audit import audit_source
from app.services.source_fetch import SourceArtifact, fetch_verified_source
from app.services.source_lines import annotate_evidence, build_offset_lines
from evm_analysis import (
    ContractFeatures,
    ControlFlowGraph,
    Disassembly,
    build_cfg,
    disassemble,
    extract_features,
    load_fork,
)
from evm_analysis.fork_inference import infer_required_fork

log = get_logger(__name__)

#: Version of the feature schema recorded on every feature row.
FEATURE_SCHEMA_VERSION = "1"


@dataclass(slots=True)
class ScanOutcome:
    """The terminal result of a scan run."""

    scan_id: uuid.UUID
    status: ScanStatus
    finding_count: int
    error_code: str | None = None
    error_message: str | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _block_id_for(
    cfg: ControlFlowGraph, block_ids: dict[int, uuid.UUID], offset: int
) -> uuid.UUID | None:
    """Resolve the basic block containing ``offset``, if any."""
    block = cfg.block_at(offset)
    if block is None:
        return None
    return block_ids.get(block.start)


def _persist_graph(
    session: Session,
    scan_id: uuid.UUID,
    disassembly: Disassembly,
    cfg: ControlFlowGraph,
    features: ContractFeatures,
) -> None:
    """Store instructions, blocks, edges and the feature record for a scan."""
    session.execute(delete(Instruction).where(Instruction.scan_id == scan_id))
    session.execute(delete(CfgEdge).where(CfgEdge.scan_id == scan_id))
    session.execute(delete(BasicBlock).where(BasicBlock.scan_id == scan_id))

    block_ids: dict[int, uuid.UUID] = {}
    for start, block in cfg.blocks.items():
        block_id = uuid.uuid4()
        block_ids[start] = block_id
        session.add(
            BasicBlock(
                id=block_id,
                scan_id=scan_id,
                start_offset=block.start,
                end_offset=block.end,
                terminator_opcode=block.terminator,
                is_entry=start == cfg.entry_offset,
                is_exit=block.terminator in {"RETURN", "REVERT", "STOP", "INVALID", "SELFDESTRUCT"},
                metadata_json={"instructionCount": block.size, "byteSize": block.byte_size},
            )
        )

    for edge in cfg.edges:
        session.add(
            CfgEdge(
                scan_id=scan_id,
                from_block_id=block_ids[edge.source],
                to_block_id=block_ids.get(edge.target) if edge.target is not None else None,
                edge_type=edge.edge_type.value,
                resolution=edge.resolution.value,
                evidence_json={"instructionOffset": edge.instruction_offset},
            )
        )

    for instr in disassembly.instructions:
        session.add(
            Instruction(
                scan_id=scan_id,
                byte_offset=instr.offset,
                opcode_byte=instr.opcode,
                opcode_name=instr.name,
                immediate_hex=instr.immediate.hex() if instr.immediate else None,
                instruction_size=instr.size,
                block_id=_block_id_for(cfg, block_ids, instr.offset),
                stack_in=instr.stack_in,
                stack_out=instr.stack_out,
            )
        )

    session.add(
        FeatureRecord(
            scan_id=scan_id,
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            feature_type="contract_features",
            feature_json=features.as_vector(),
        )
    )


def persist_findings(
    session: Session,
    scan: Scan,
    findings: Sequence[RuleFinding],
    source: str = "rule",
    source_lines: Mapping[int, int] | None = None,
    source_file: str | None = None,
) -> None:
    """Replace the findings of a scan with the newly produced ones.

    The ``source`` column says which engine produced a finding: ``rule``
    for the bytecode engine, ``slither`` for the source engine, ``ml``
    for the model. One table, several engines, and no way to tell them
    apart by guessing.

    The findings are *replaced* rather than appended, so re-running a scan
    does not leave a stale finding behind.

    ``source_lines`` maps a bytecode offset to a line of the developer's
    source. When it is given, a finding that points at a bytecode offset
    also points at the line that offset came from.
    """
    if source == "rule":
        session.execute(delete(Finding).where(Finding.scan_id == scan.id))
    else:
        session.execute(
            delete(Finding).where(
                Finding.scan_id == scan.id,
                Finding.source == source,
            )
        )
    for finding in findings:
        evidence = finding.evidence
        if source_lines:
            evidence = annotate_evidence(evidence, source_lines, source_file=source_file)
        session.add(
            Finding(
                workspace_id=scan.workspace_id,
                scan_id=scan.id,
                source=source,
                detector_id=finding.detector_id,
                detector_version=RULESET_VERSION,
                category=finding.category,
                title=finding.title,
                description=finding.description,
                severity=finding.severity,
                confidence=finding.confidence,
                status=FindingStatus.NEW,
                evidence_json=evidence,
                limitations=finding.limitations or None,
            )
        )


def _store_artifacts(
    session: Session,
    scan: Scan,
    artifact: BytecodeArtifact,
    disassembly: Disassembly,
    cfg: ControlFlowGraph,
    features: ContractFeatures,
) -> None:
    """Persist the bytecode, disassembly and feature artifacts for a scan."""
    prefix = f"scans/{scan.id}"
    session.execute(delete(ScanArtifact).where(ScanArtifact.scan_id == scan.id))

    code_key = storage.put_bytes(f"{prefix}/bytecode.bin", artifact.code)
    session.add(
        ScanArtifact(
            scan_id=scan.id,
            kind="bytecode",
            content_type="application/octet-stream",
            object_key=code_key,
            byte_size=len(artifact.code),
            sha256=artifact.sha256,
        )
    )

    disassembly_key = storage.put_json(
        f"{prefix}/disassembly.json",
        {
            "fork": disassembly.fork,
            "codeSize": disassembly.code_size,
            "warnings": list(disassembly.warnings),
            "notes": list(disassembly.notes),
            "instructions": [
                {
                    "offset": instr.offset,
                    "opcode": instr.opcode,
                    "name": instr.name,
                    "immediateHex": instr.immediate.hex() if instr.immediate else "",
                    "size": instr.size,
                    "stackIn": instr.stack_in,
                    "stackOut": instr.stack_out,
                }
                for instr in disassembly.instructions
            ],
        },
    )
    session.add(
        ScanArtifact(
            scan_id=scan.id,
            kind="disassembly",
            content_type="application/json",
            object_key=disassembly_key,
        )
    )

    cfg_key = storage.put_json(
        f"{prefix}/cfg.json",
        {
            "entryOffset": cfg.entry_offset,
            "blocks": [
                {
                    "start": block.start,
                    "end": block.end,
                    "terminator": block.terminator,
                    "instructionCount": block.size,
                }
                for block in cfg.blocks.values()
            ],
            "edges": [
                {
                    "source": edge.source,
                    "target": edge.target,
                    "edgeType": edge.edge_type.value,
                    "resolution": edge.resolution.value,
                    "instructionOffset": edge.instruction_offset,
                }
                for edge in cfg.edges
            ],
        },
    )
    session.add(
        ScanArtifact(
            scan_id=scan.id,
            kind="cfg",
            content_type="application/json",
            object_key=cfg_key,
        )
    )

    features_key = storage.put_json(f"{prefix}/features.json", features.as_vector())
    session.add(
        ScanArtifact(
            scan_id=scan.id,
            kind="features",
            content_type="application/json",
            object_key=features_key,
        )
    )


def _pasted_source_artifact(target: ContractTarget) -> SourceArtifact | None:
    """Rebuild the developer's pasted source, when the scan has one.

    A pasted source is not fetched from an explorer: it is read back out
    of the product's own storage, together with the provenance the
    compilation left behind. The compiler version matters -- Slither
    needs the same compiler the bytecode was built with, or it reads a
    different contract than the one that was analysed.
    """
    if target.inline_bytecode_source != "compiled":
        return None
    object_key = target.source_object_key
    if not object_key:
        return None
    try:
        raw = storage.get_bytes(object_key)
    except Exception as exc:  # noqa: BLE001 - a missing source is a skip, not a failure
        log.warning("pasted_source_unreadable", error=str(exc))
        return None

    source = raw.decode("utf-8", errors="replace")
    metadata: dict[str, Any] = {}
    if target.provenance:
        try:
            parsed = json.loads(target.provenance)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            metadata = parsed

    name = str(metadata.get("source_name") or "Contract.sol")
    return SourceArtifact(
        code=source,
        files={name: source},
        language="Solidity",
        compiler_version=str(metadata.get("solc") or ""),
        source_uri="pasted",
        source_kind="pasted",
        verified=False,
    )


#: Source-audit skip reasons that mean "there was nothing to audit", not
#: "the audit could not be done". A contract with no verified source on
#: the explorer has no source to audit, so nothing is missing; a contract
#: whose source could not be fetched, or whose source engine was not
#: available, is a gap in the scan and is reported as one.
BENIGN_SOURCE_SKIPS = frozenset({"no_address", "no_source"})


def _audit_verified_source(
    session: Session,
    scan: Scan,
    chain_id: int,
    address: str,
) -> tuple[list[RuleFinding], str | None]:
    """Run the source engine over a contract's source.

    The source engine is supplementary. A contract whose source cannot be
    fetched, whose Slither is not installed, or which does not compile is
    *skipped*, not failed: the bytecode analysis already ran and its
    results stand on their own.

    Args:
        session: The database session.
        scan: The scan being run.
        chain_id: The EIP-155 chain the contract lives on.
        address: The contract address.

    Returns:
        The source findings, and the reason the audit was skipped when it
        did not run.
    """
    target = scan.target

    artifact = _pasted_source_artifact(target)
    if artifact is None:
        if not address:
            return ([], "no_address")

        try:
            artifact = fetch_verified_source(chain_id, address)
        except Exception as exc:  # noqa: BLE001 - the source engine never fails a scan
            log.warning("scan_source_fetch_failed", scan_id=str(scan.id), error=str(exc))
            return ([], "source_fetch_failed")

    if artifact is None:
        return ([], "no_source")

    # The source is stored whether or not the audit could run. A contract
    # whose source was fetched is worth keeping even when Slither is not
    # installed, because the source is what makes the scan reproducible.
    _store_source_artifact(session, scan, artifact)

    extra_files = {
        path: content for path, content in artifact.files.items() if path != artifact.main_file_name
    }
    audit = audit_source(
        artifact.code,
        contract_name=artifact.main_file_name.removesuffix(".sol") or "Contract",
        compiler_version=artifact.compiler_version,
        # Slither is never imported or vendored here. The runner invokes
        # the unmodified external executable across a process boundary and
        # reads its JSON output (ADR-0013).
        runner=SlitherRunner(
            executable=get_settings().slither_bin or None,
            solc_artifacts=get_settings().solc_artifacts_dir or None,
        ),
        extra_files=extra_files,
    )

    if not audit.ran:
        return ([], audit.skipped)

    log.info(
        "scan_source_audited",
        scan_id=str(scan.id),
        findings=len(audit.findings),
        route=artifact.source_kind,
    )
    return (list(audit.findings), None)


def _store_source_artifact(session: Session, scan: Scan, artifact: SourceArtifact) -> None:
    """Store the verified source as a scan artifact.

    The source is stored as a file tree rather than as a database column,
    so a multi-file project keeps its layout and nothing depends on a
    ``TEXT`` column holding source code.
    """
    prefix = f"scans/{scan.id}"
    files = [
        {
            "path": path,
            "content": content,
        }
        for path, content in sorted(artifact.files.items())
    ]
    key = storage.put_json(
        f"{prefix}/source.json",
        {
            "route": artifact.source_kind,
            "sourceUri": artifact.source_uri,
            "language": artifact.language,
            "compilerVersion": artifact.compiler_version,
            "verified": artifact.verified,
            "files": files,
        },
    )
    session.add(
        ScanArtifact(
            scan_id=scan.id,
            kind="source",
            content_type="application/json",
            object_key=key,
        )
    )


def _compiled_source_lines(
    target: ContractTarget, disassembly: Any
) -> tuple[dict[int, int], str | None]:
    """Map bytecode offsets to source lines, for a compiled source.

    Only a source this server compiled qualifies: there, the source map
    came out of the same compiler run that produced the bytes being
    analysed, so the mapping is true by construction.

    Returns:
        The offset-to-line map (empty when there is no honest mapping)
        and the name of the source file.
    """
    if target.inline_bytecode_source != "compiled" or not target.provenance:
        return ({}, None)
    try:
        metadata = json.loads(target.provenance)
    except json.JSONDecodeError:
        return ({}, None)
    if not isinstance(metadata, dict):
        return ({}, None)

    source_map = metadata.get("source_map")
    object_key = target.source_object_key
    if not isinstance(source_map, str) or not source_map or not object_key:
        return ({}, None)

    try:
        source = storage.get_bytes(object_key).decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 - a missing source is not a failure
        log.warning("compiled_source_unreadable", error=str(exc))
        return ({}, None)

    offsets = [instruction.offset for instruction in disassembly.instructions]
    lines = build_offset_lines(source, source_map, offsets)
    name = metadata.get("source_name")
    return (lines, str(name) if isinstance(name, str) and name else None)


def run_scan(session: Session, scan: Scan) -> ScanOutcome:
    """Execute the full pipeline for ``scan`` and persist the results.

    The function never raises for expected operational failures (missing RPC,
    malformed bytecode): it records the status and error on the scan instead.
    """
    scan.started_at = _now()
    scan.status = ScanStatus.FETCHING_BYTECODE
    session.flush()

    target = scan.target
    address = target.address or ""
    chain_id = target.chain.chain_id

    inline = target.inline_bytecode
    if inline:
        # The user supplied the bytecode: analyse exactly those bytes and
        # contact nothing (design doc section 6.1). Whether those bytes
        # were pasted or compiled from the developer's source is recorded
        # rather than assumed, because a compiled source also carries the
        # source map that puts findings on lines.
        artifact = BytecodeArtifact(
            code=inline,
            source=target.inline_bytecode_source or "upload",
            source_uri=None,
            address=address or None,
        )
    else:
        try:
            artifact = fetch_runtime_bytecode(address, chain_id)
        except BytecodeUnavailableError as exc:
            scan.status = ScanStatus.FAILED
            scan.error_code = exc.code
            scan.error_message_redacted = str(exc)
            scan.completed_at = _now()
            log.warning("scan_bytecode_unavailable", scan_id=str(scan.id), code=exc.code)
            return ScanOutcome(
                scan_id=scan.id,
                status=scan.status,
                finding_count=0,
                error_code=exc.code,
                error_message=str(exc),
            )

    scan.bytecode_source = artifact.source
    scan.parser_version = PARSER_VERSION
    scan.ruleset_version = RULESET_VERSION
    scan.status = ScanStatus.DISASSEMBLING
    session.flush()

    # The fork decides which opcodes exist. A caller may name one; when
    # they do not, it is inferred from the bytecode itself. Either way the
    # decision is recorded, because a scan analysed under the wrong fork
    # does not fail -- it quietly reports real opcodes as invalid.
    requirement = infer_required_fork(artifact.code)
    resolution = resolve_fork(scan.fork or None, requirement)
    scan.fork = resolution.fork
    scan.fork_source = resolution.source
    scan.fork_conflict = resolution.conflict
    if resolution.conflict:
        log.warning(
            "scan_fork_conflict",
            scan_id=str(scan.id),
            fork=resolution.fork,
            source=resolution.source,
            reason=resolution.reason,
        )

    try:
        table = load_fork(scan.fork)
        disassembly = disassemble(artifact.code, table)
    except Exception as exc:  # noqa: BLE001 - any parser failure is a scan failure
        scan.status = ScanStatus.FAILED
        scan.error_code = "disassembly_failed"
        scan.error_message_redacted = f"Disassembly failed: {exc}"
        scan.completed_at = _now()
        log.warning("scan_disassembly_failed", scan_id=str(scan.id), error=str(exc))
        return ScanOutcome(
            scan_id=scan.id,
            status=scan.status,
            finding_count=0,
            error_code="disassembly_failed",
            error_message=str(exc),
        )

    scan.status = ScanStatus.BUILDING_CFG
    session.flush()
    cfg = build_cfg(disassembly)

    scan.status = ScanStatus.EXTRACTING_FEATURES
    session.flush()
    features = extract_features(disassembly, cfg)

    scan.status = ScanStatus.RUNNING_DETECTORS
    session.flush()
    findings = run_rules(disassembly, cfg, features)

    # The model is a triage aid and nothing more. It ranks the
    # findings so the reviewer knows where to look first; it never
    # changes a severity, a confidence or a review status. With no
    # model installed -- or with the experimental model switched
    # off -- a scan runs exactly as it did before the model existed.
    model_skipped: str | None = None
    model_scores: dict[str, float] = {}
    scan_settings = get_settings()
    if scan_settings.enable_experimental_ml:
        try:
            model = load_installed_model(scan_settings)
        except ModelManifestError as exc:
            model = None
            model_skipped = f"model_unreadable: {exc}"
            log.warning("scan_model_unreadable", scan_id=str(scan.id), error=str(exc))
        if model is not None:
            model_scores = score_bytecode(
                model,
                artifact.code,
                contract_id=str(scan.target_id),
                chain=str(chain_id),
            )
            annotate_findings(findings, model_scores)
            scan.model_version = model.version
            scan.model_scores = model_scores or None

    _store_artifacts(session, scan, artifact, disassembly, cfg, features)
    session.add(
        ScanArtifact(
            scan_id=scan.id,
            kind="fork_resolution",
            content_type="application/json",
            object_key=storage.put_json(
                f"scans/{scan.id}/fork_resolution.json", resolution.as_dict()
            ),
        )
    )
    _persist_graph(session, scan.id, disassembly, cfg, features)
    source_lines, source_file = _compiled_source_lines(target, disassembly)
    persist_findings(
        session,
        scan,
        findings,
        source_lines=source_lines,
        source_file=source_file,
    )

    # The source engine is a second opinion on the same contract. It runs
    # after the bytecode analysis, and a failure there never undoes the
    # bytecode results.
    source_findings, source_skipped = _audit_verified_source(session, scan, chain_id, address)
    persist_findings(session, scan, source_findings, source="slither")
    scan.source_audited = source_skipped is None
    scan.source_audit_skipped = source_skipped

    # A scan is partial when something could not be analysed, not when
    # the bytecode is merely dynamic. A jump whose destination is
    # computed at run time is ordinary Solidity -- the function
    # dispatcher is built out of them -- and no static analysis can
    # follow it. Those are counted as coverage below, not counted as a
    # hole in the analysis.
    source_incomplete = source_skipped is not None and source_skipped not in BENIGN_SOURCE_SKIPS
    partial = bool(disassembly.warnings) or bool(cfg.warnings) or source_incomplete
    scan.status = ScanStatus.PARTIAL if partial else ScanStatus.COMPLETED

    # A partial scan says what it could not cover. "Partial" without a
    # reason is a shrug: the reason is what lets a reader judge how much
    # of the contract was actually analysed.
    limitations: dict[str, Any] = {}
    if disassembly.warnings:
        limitations["disassembly_warnings"] = [str(warning) for warning in disassembly.warnings]
    if cfg.warnings:
        limitations["control_flow_warnings"] = [str(warning) for warning in cfg.warnings]
    if source_incomplete:
        limitations["source_audit_skipped"] = source_skipped
    if model_skipped:
        limitations["model_unavailable"] = model_skipped
    scan.limitations = limitations or None

    # Coverage is a measurement, not a gap. It says how much of the
    # contract was decoded and how far the static view reached, so two
    # scans of the same contract can be compared and a reader can weigh
    # the findings against what was actually read.
    scan.coverage = {
        "instructions": len(disassembly.instructions),
        "executable_bytes": disassembly.executable_size,
        "code_bytes": disassembly.code_size,
        "metadata_bytes": disassembly.metadata.length if disassembly.metadata else 0,
        "edges": len(cfg.edges),
        "dynamic_jumps": len(cfg.unresolved_edges),
        "dynamic_jump_ratio": round(
            len(cfg.unresolved_edges) / max(len(cfg.edges), 1),
            4,
        ),
        "unreachable_blocks": len(cfg.unreachable_blocks),
        "notes": [str(note) for note in disassembly.notes] + [str(note) for note in cfg.notes],
    }

    scan.completed_at = _now()
    session.flush()

    if source_skipped is not None:
        log.info(
            "scan_source_skipped",
            scan_id=str(scan.id),
            reason=source_skipped,
        )

    return ScanOutcome(
        scan_id=scan.id,
        status=scan.status,
        finding_count=len(findings) + len(source_findings),
    )


def mark_job(session: Session, job: ScanJob, status: ScanJobStatus, **fields: object) -> None:
    """Update a scan job row with a new status and optional extra fields."""
    job.status = status
    for key, value in fields.items():
        setattr(job, key, value)
    session.flush()


__all__ = [
    "FEATURE_SCHEMA_VERSION",
    "ScanOutcome",
    "mark_job",
    "persist_findings",
    "run_scan",
]
