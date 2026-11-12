"""A live proof of the bulk review, on a workspace that is thrown away.

No real finding is settled: a reviewed label is a human decision, and
this script is not a human. It creates its own workspace, puts three
findings in it, settles them with one action, shows the answer, and
deletes the workspace again.
"""

import json
import pathlib
import sys
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, "apps/api")

from sqlalchemy import select  # noqa: E402

from app.core.security import hash_api_key  # noqa: E402
from app.db.enums import FindingStatus, ScanStatus, Severity  # noqa: E402
from app.db.models.identity import (  # noqa: E402
    ApiKey,
    Chain,
    ContractTarget,
    User,
    Workspace,
    WorkspaceMember,
)
from app.db.models.scans import Finding, Scan  # noqa: E402
from app.db.session import session_scope  # noqa: E402

BASE = "http://127.0.0.1:8000/api/v1"


def service_key() -> str:
    """The service key, read from the local .env without its line endings."""
    for line in pathlib.Path(".env").read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("=")
        if name.strip() == "API_KEY":
            return value.strip()
    raise SystemExit("no API_KEY in .env")


def call(method: str, path: str, key: str, payload=None):
    """One call to the API, without a third-party client."""
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 - the URL is the local API
        f"{BASE}{path}",
        data=data,
        method=method,
    )
    request.add_header("X-API-Key", key)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        opener = urllib.request.urlopen  # noqa: S310 - the URL is the local API
        with opener(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


label = f"proof-{uuid.uuid4().hex[:8]}"
ids = []
raw_key = f"proof-key-{uuid.uuid4().hex}"

with session_scope() as session:
    user = User(email=f"{label}@example.test", display_name=label)
    session.add(user)
    session.flush()
    space = Workspace(name=label, slug=label, created_by=user.id)
    session.add(space)
    session.flush()
    session.add(WorkspaceMember(workspace_id=space.id, user_id=user.id, role="owner"))
    session.flush()

    session.add(
        ApiKey(
            user_id=user.id,
            workspace_id=space.id,
            name=f"{label} key",
            key_hash=hash_api_key(raw_key),
            key_prefix=raw_key[:12],
        )
    )
    session.flush()

    chain = session.scalars(select(Chain).limit(1)).one()
    target = ContractTarget(
        workspace_id=space.id,
        chain_id=chain.id,
        address="0x" + "11" * 20,
        label=label,
        bytecode_type="runtime",
        authorization_status="unknown",
    )
    session.add(target)
    session.flush()
    row = Scan(
        workspace_id=space.id,
        target_id=target.id,
        status=ScanStatus.COMPLETED,
        fork="cancun",
        bytecode_source="proof",
    )
    session.add(row)
    session.flush()

    for index in range(3):
        finding = Finding(
            workspace_id=space.id,
            scan_id=row.id,
            detector_id="slither.naming_convention",
            detector_version="0.1.0",
            category="style",
            title=f"proof finding {index}",
            description="A finding that exists only to prove the action works.",
            severity=Severity.LOW,
            confidence=0.5,
            status=FindingStatus.NEW,
            evidence_json={"offsets": [index]},
        )
        session.add(finding)
        session.flush()
        ids.append(finding.id)

    workspace_id = space.id

print("--- the workspace the reviewer works in ---")
status_code, body = call("GET", "/workspaces", raw_key)
print("status:", status_code, "workspaces:", [(row["slug"], row["open_findings"]) for row in body])

print("--- one action settles the three findings of that workspace ---")
status_code, body = call(
    "POST",
    "/findings/review-bulk",
    raw_key,
    {
        "detector_id": "slither.naming_convention",
        "status": "false_positive",
        "note": "the proof workspace: these rows exist only for the proof",
    },
)
print("status:", status_code, "applied:", body.get("applied"), "skipped:", body.get("skipped"))

print("--- the service key has to name the workspace it acts in ---")
status_code, body = call(
    "POST",
    "/findings/review-bulk",
    service_key(),
    {"detector_id": "slither.naming_convention", "status": "confirmed"},
)
print("status:", status_code, "message:", body.get("error", {}).get("message"))

print("--- and then it acts only in the workspace it named ---")
status_code, body = call(
    "POST",
    f"/findings/review-bulk?workspace_id={workspace_id}",
    service_key(),
    {"detector_id": "slither.naming_convention", "status": "confirmed"},
)
print("status:", status_code, "applied:", body.get("applied"), "skipped:", body.get("skipped"))

print("--- the proof findings are labelled ---")
with session_scope() as session:
    for row in session.scalars(select(Finding).where(Finding.id.in_(ids))).all():
        print(f"  {row.detector_id} status={row.status.value} note={row.review_note!r}")

print("--- the proof workspace is removed ---")
with session_scope() as session:
    space = session.get(Workspace, workspace_id)
    session.delete(space)
    session.flush()
    left = session.scalars(select(Finding).where(Finding.id.in_(ids))).all()
    print("  findings left behind:", len(left))
