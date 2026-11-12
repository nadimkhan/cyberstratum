"""Undo the bulk action the proof made.

The proof used the administrative service key, which acts across every
tenant, so the bulk action reached findings that were not the proof's
to settle. This puts them back the way they were and removes the audit
events the action wrote.
"""

import sys
from collections import Counter

sys.path.insert(0, "apps/api")

from sqlalchemy import select  # noqa: E402

from app.db.enums import FindingStatus  # noqa: E402
from app.db.models.identity import AuditEvent  # noqa: E402
from app.db.models.scans import Finding  # noqa: E402
from app.db.session import session_scope  # noqa: E402

MARKER = "the proof workspace: these rows exist only for the proof"

with session_scope() as session:
    print("--- the status of every finding, before the undo ---")
    counts = Counter(row.status.value for row in session.scalars(select(Finding)).all())
    print(counts)

    touched = session.scalars(select(Finding).where(Finding.review_note == MARKER)).all()
    print("findings the proof settled:", len(touched))

    for finding in touched:
        finding.status = FindingStatus.NEW
        finding.reviewed_by = None
        finding.reviewed_at = None
        finding.review_note = None
    session.flush()

    events = session.scalars(
        select(AuditEvent).where(AuditEvent.action == "finding.reviewed")
    ).all()
    bulk_events = [
        event
        for event in events
        if isinstance(event.metadata_redacted, dict) and event.metadata_redacted.get("bulk") is True
    ]
    for event in bulk_events:
        session.delete(event)
    session.flush()

    print("audit events written by the bulk action:", len(bulk_events))
    print("audit events for reviews that remain:", len(events) - len(bulk_events))

with session_scope() as session:
    print("--- the status of every finding, after the undo ---")
    counts = Counter(row.status.value for row in session.scalars(select(Finding)).all())
    print(counts)
    reviewed = session.scalars(
        select(Finding).where(Finding.review_note.is_not(None))
    ).all()
    print("findings that still carry a review:", len(reviewed))
    for finding in reviewed:
        print("  ", finding.detector_id, finding.status.value, repr(finding.review_note))
