"""Tracked-asset services: register an address, attach scans, report progress.

A tracked asset is an address a workspace follows over time. Both product
modes write into it:

* the autonomous path registers a contract it discovered,
* the developer path registers the contract the developer is shipping.

Every scan of that address is attached to the asset, so the asset's history
is the dated record of what was found and when. That record is what lets
a user see progress: "the open findings went from 5 to 1" is only
answerable if the findings of every scan of that address are reachable
from the address itself.

The progress counters are computed, never stored. A cached counter can
disagree with the rows it claims to count, and the one number a user
watches to decide whether their fix worked must never be stale.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.enums import AssetKind, FindingStatus
from app.db.models.assets import TrackedAsset
from app.db.models.identity import Chain, Workspace
from app.db.models.scans import Finding, Scan

HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


class InvalidAddressError(ValueError):
    """The supplied address is not a 20-byte hexadecimal address."""


@dataclass(frozen=True)
class AssetScanSummary:
    """How many scans an asset has, and when it was last scanned."""

    scan_count: int = 0
    last_scanned_at: datetime | None = None


@dataclass(frozen=True)
class AssetFindingSummary:
    """What an asset's scans found, in total and by kind."""

    finding_count: int = 0
    open_finding_count: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    by_severity: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class AssetTimelineRow:
    """One dated scan in an asset's history."""

    scan_id: uuid.UUID
    created_at: datetime
    status: str
    finding_count: int
    by_status: dict[str, int] = field(default_factory=dict)
    by_severity: dict[str, int] = field(default_factory=dict)


def _enum_value(value: object) -> str:
    """Return the stored value of an enum column as a plain string."""
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def normalise_address(address: str) -> str:
    """Return the canonical lower-case ``0x`` form of ``address``.

    Two spellings of the same address must not become two assets, so the
    address is normalised before it is stored or compared.
    """
    value = (address or "").strip()
    if value[:2].lower() == "0x":
        value = value[2:]
    if len(value) != 40 or not set(value) <= HEX_DIGITS:
        raise InvalidAddressError("an address is 20 bytes: 40 hexadecimal characters")
    return "0x" + value.lower()


def upsert_asset(
    session: Session,
    workspace: Workspace,
    chain: Chain,
    address: str,
    *,
    label: str | None = None,
    kind: AssetKind = AssetKind.OWNED,
    notes: str | None = None,
) -> TrackedAsset:
    """Return the workspace's asset for ``address``, creating it if needed.

    Registration is idempotent on (workspace, chain, address). The second
    scan of the same contract must not create a second asset: two rows
    would split the history in half and make the progress count wrong.
    """
    normalised = normalise_address(address)
    existing = session.scalars(
        select(TrackedAsset).where(
            TrackedAsset.workspace_id == workspace.id,
            TrackedAsset.chain_id == chain.id,
            TrackedAsset.address == normalised,
        )
    ).one_or_none()
    if existing is not None:
        if label and existing.label != label:
            existing.label = label
        if notes and existing.notes != notes:
            existing.notes = notes
        return existing

    asset = TrackedAsset(
        workspace_id=workspace.id,
        chain_id=chain.id,
        address=normalised,
        label=label or normalised,
        kind=kind,
        notes=notes,
        first_seen_at=datetime.now(UTC),
    )
    session.add(asset)
    session.flush()
    return asset


def scan_summaries(
    session: Session, asset_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, AssetScanSummary]:
    """Return, per asset, how many scans it has and when it was last scanned.

    One grouped query serves a whole page of assets, so listing does not
    issue a query per row.
    """
    if not asset_ids:
        return {}
    rows = session.execute(
        select(Scan.asset_id, func.count(), func.max(Scan.created_at))
        .where(Scan.asset_id.in_(asset_ids))
        .group_by(Scan.asset_id)
    ).all()
    return {
        cast(uuid.UUID, row[0]): AssetScanSummary(
            scan_count=int(row[1]), last_scanned_at=row[2]
        )
        for row in rows
    }


def finding_summaries(
    session: Session, asset_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, AssetFindingSummary]:
    """Return, per asset, its finding counts by status and by severity.

    "Open" means not dismissed: a finding the reviewer marked as a false
    positive is closed. The open count is the number that moves when a
    fix ships, so it is derived here rather than tracked separately.
    """
    if not asset_ids:
        return {}
    rows = session.execute(
        select(
            Scan.asset_id,
            Finding.status,
            Finding.severity,
            func.count(),
        )
        .join(Scan, Scan.id == Finding.scan_id)
        .where(Scan.asset_id.in_(asset_ids))
        .group_by(Scan.asset_id, Finding.status, Finding.severity)
    ).all()

    totals: dict[uuid.UUID, int] = {}
    by_status: dict[uuid.UUID, dict[str, int]] = {}
    by_severity: dict[uuid.UUID, dict[str, int]] = {}
    for row_asset_id, status_value, severity_value, count in rows:
        asset_id = cast(uuid.UUID, row_asset_id)
        amount = int(count)
        totals[asset_id] = totals.get(asset_id, 0) + amount
        status_key = _enum_value(status_value)
        severity_key = _enum_value(severity_value)
        status_counts = by_status.setdefault(asset_id, {})
        status_counts[status_key] = status_counts.get(status_key, 0) + amount
        severity_counts = by_severity.setdefault(asset_id, {})
        severity_counts[severity_key] = severity_counts.get(severity_key, 0) + amount

    false_positive = FindingStatus.FALSE_POSITIVE.value
    summary: dict[uuid.UUID, AssetFindingSummary] = {}
    for asset_id, total in totals.items():
        summary[asset_id] = AssetFindingSummary(
            finding_count=total,
            open_finding_count=total - by_status.get(asset_id, {}).get(false_positive, 0),
            by_status=by_status.get(asset_id, {}),
            by_severity=by_severity.get(asset_id, {}),
        )
    return summary


def asset_timeline(
    session: Session,
    asset: TrackedAsset,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[AssetTimelineRow]:
    """Return the dated history of an asset's scans, oldest first.

    Each entry carries the scan's date, its outcome and what it found, so
    the history reads as a progress log rather than a list of ids.

    The query is newest-first so that the pagination window covers the
    most recent scans, and the result is then reversed: a progress log
    that reads backwards is not a progress log.

    ``created_at`` is a database ``now()``, which is the *transaction*
    timestamp, so two scans created in one transaction share it. The
    ordering therefore falls through to ``queued_at``, which the
    application stamps per call and which is therefore the real
    creation order. The scan id is the last resort: it is a random
    UUID and says nothing about order.
    """
    scans = list(
        session.execute(
            select(Scan.id, Scan.status, Scan.created_at)
            .where(Scan.asset_id == asset.id)
            .order_by(Scan.created_at.desc(), Scan.queued_at.desc(), Scan.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    )
    scans.reverse()
    if not scans:
        return []

    scan_ids = [row[0] for row in scans]
    rows = session.execute(
        select(Finding.scan_id, Finding.status, Finding.severity, func.count())
        .where(Finding.scan_id.in_(scan_ids))
        .group_by(Finding.scan_id, Finding.status, Finding.severity)
    ).all()

    totals: dict[uuid.UUID, int] = {}
    by_status: dict[uuid.UUID, dict[str, int]] = {}
    by_severity: dict[uuid.UUID, dict[str, int]] = {}
    for row_scan_id, status_value, severity_value, count in rows:
        scan_id = row_scan_id
        amount = int(count)
        totals[scan_id] = totals.get(scan_id, 0) + amount
        status_key = _enum_value(status_value)
        severity_key = _enum_value(severity_value)
        status_counts = by_status.setdefault(scan_id, {})
        status_counts[status_key] = status_counts.get(status_key, 0) + amount
        severity_counts = by_severity.setdefault(scan_id, {})
        severity_counts[severity_key] = severity_counts.get(severity_key, 0) + amount

    timeline: list[AssetTimelineRow] = []
    for scan_id, scan_status_value, created_at in scans:
        timeline.append(
            AssetTimelineRow(
                scan_id=scan_id,
                created_at=created_at,
                status=_enum_value(scan_status_value),
                finding_count=totals.get(scan_id, 0),
                by_status=by_status.get(scan_id, {}),
                by_severity=by_severity.get(scan_id, {}),
            )
        )
    return timeline
