"""The whole workflow, proved on the running stack in one command.

This is the end-to-end proof of the product: discovery feeds the scan
queue, the queue runs the analysis, the analysis produces findings, the
findings carry advice, a reviewer settles them, and the settled ones
become the labels the model learns from -- and the model is refused
until there is enough evidence to judge it.

Nothing here settles a real finding. The review step runs in a
workspace that is created and thrown away, because a reviewed label is
a human decision.

    .venv/bin/python scripts/wsl/e2e_full_workflow.py
"""

from __future__ import annotations

import json
import pathlib
import subprocess
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
WEB = "http://127.0.0.1:3100"


def service_key() -> str:
    """The service key, read from the local .env without its line endings."""
    for line in pathlib.Path(".env").read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("=")
        if name.strip() == "API_KEY":
            return value.strip()
    raise SystemExit("no API_KEY in .env")


KEY = service_key()


def call(method: str, path: str, key: str = KEY, payload=None):
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
        with opener(request, timeout=60) as response:
            body = response.read().decode("utf-8")
            return response.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8")
        try:
            return error.code, json.loads(body)
        except json.JSONDecodeError:
            return error.code, body


def step(number: int, title: str) -> None:
    """Print the step so the output reads as a walk through the product."""
    print(f"\n[{number}] {title}")


step(1, "The stack is up")
with urllib.request.urlopen(  # noqa: S310 - the URL is the local API
    "http://127.0.0.1:8000/api/health", timeout=20
) as response:
    print("    api:", response.status)
with urllib.request.urlopen(  # noqa: S310 - the URL is the local web app
    f"{WEB}/findings", timeout=120
) as response:
    print("    web:", response.status)

step(2, "The corpus and its workspaces")
status, workspaces = call("GET", "/workspaces")
print("    workspaces:", [(row["slug"], row["open_findings"]) for row in workspaces])
status, findings = call("GET", "/findings?limit=200")
items = findings.get("items", [])
print("    findings visible:", findings.get("total"), "| first page:", len(items))
if items:
    print("    severities:", sorted({row.get("severity") for row in items}))

step(3, "Every finding in the corpus carries advice")
status, knowledge = call("GET", "/knowledge")
advice = {row["detector_id"] for row in knowledge["items"]}
detectors = {row.get("detector_id") or row.get("detectorId") for row in items}
detectors.discard(None)
missing = sorted(detectors - advice)
print("    advice entries served:", len(advice))
print("    detectors in the first page without advice:", missing or "none")

step(4, "The scan queue produced scans")
with session_scope() as session:
    latest = session.scalars(select(Scan).order_by(Scan.created_at.desc()).limit(1)).first()
    if latest is None:
        print("    no scan has been run yet")
    else:
        print(f"    latest scan {latest.id} status={latest.status.value}")
        print(f"    limitations: {latest.limitations or 'None'}")

step(5, "A reviewer settles findings, one and one group")
label = f"e2e-{uuid.uuid4().hex[:8]}"
raw_key = f"e2e-key-{uuid.uuid4().hex}"
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
        address="0x" + "33" * 20,
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
        bytecode_source="e2e",
    )
    session.add(row)
    session.flush()
    ids = []
    for index in range(2):
        finding = Finding(
            workspace_id=space.id,
            scan_id=row.id,
            detector_id="slither.naming_convention",
            detector_version="0.1.0",
            category="style",
            title=f"e2e finding {index}",
            description="A finding that exists only to prove the review works.",
            severity=Severity.LOW,
            confidence=0.5,
            status=FindingStatus.NEW,
            evidence_json={"offsets": [index]},
        )
        session.add(finding)
        session.flush()
        ids.append(finding.id)
    workspace_id = space.id

status, body = call(
    "POST",
    f"/findings/{ids[0]}/review",
    raw_key,
    {"status": "false_positive", "note": "a style question, not a defect"},
)
print("    one verdict:", status, body.get("status") if isinstance(body, dict) else body)

status, body = call(
    "POST",
    "/findings/review-bulk",
    raw_key,
    {
        "detector_id": "slither.naming_convention",
        "status": "false_positive",
        "note": "the same style question, for every finding of its kind",
    },
)
print(
    "    one verdict for the group:",
    status,
    "applied:",
    body.get("applied") if isinstance(body, dict) else body,
    "skipped:",
    body.get("skipped") if isinstance(body, dict) else "",
)

step(6, "A settled finding is not settled twice")
status, body = call(
    "POST",
    "/findings/review-bulk",
    raw_key,
    {"detector_id": "slither.naming_convention", "status": "confirmed"},
)
print(
    "    a second, different verdict on the same group:",
    status,
    "applied:",
    body.get("applied") if isinstance(body, dict) else body,
    "skipped:",
    body.get("skipped") if isinstance(body, dict) else "",
)

step(7, "The service key cannot act across tenants")
status, body = call(
    "POST",
    "/findings/review-bulk",
    KEY,
    {"detector_id": "slither.naming_convention", "status": "confirmed"},
)
message = body.get("error", {}).get("message") if isinstance(body, dict) else body
print("    without a workspace:", status, message)

step(8, "The proof workspace is removed")
with session_scope() as session:
    space = session.get(Workspace, workspace_id)
    session.delete(space)
    session.flush()
    left = session.scalars(select(Finding).where(Finding.id.in_(ids))).all()
    print("    findings left behind:", len(left))

step(9, "The reviewed labels are what the model may learn from")
with session_scope() as session:
    reviewed = session.scalars(
        select(Finding).where(
            Finding.status.in_([FindingStatus.CONFIRMED, FindingStatus.FALSE_POSITIVE])
        )
    ).all()
    print("    reviewed findings in the live corpus:", len(reviewed))

step(10, "The model is refused until the evidence can judge it")
result = subprocess.run(  # noqa: S603 - the command is fixed and local
    [sys.executable, "-m", "app.cli.learning_cycle"],
    cwd="apps/api",
    capture_output=True,
    text=True,
    timeout=600,
    check=False,
)
tail = [line for line in result.stdout.splitlines() if line.strip()][-6:]
print("    exit code:", result.returncode)
for line in tail:
    print("   ", line)
