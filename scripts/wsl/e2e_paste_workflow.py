#!/usr/bin/env python3
"""End-to-end proof of the developer-mode workflow, against the live stack.

Paste Solidity -> compiled on the server -> analysed by the same pipeline ->
findings that point at a line of the developer's own source -> the contract
is tracked so its progress accumulates -> the frontend shows all of it.

Nothing here prints a secret.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path("/home/nadim/projects/cyberstratum")
API = "http://127.0.0.1:8000/api/v1"
WEB = "http://127.0.0.1:3100"

SOURCE = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

contract Vault {
    address public owner;

    constructor() {
        owner = msg.sender;
    }

    function withdraw() public {
        (bool ok, ) = msg.sender.call{value: address(this).balance}("");
        require(ok);
    }

    function originalSender() public view returns (address) {
        return tx.origin;
    }
}
"""


def env_value(name: str, path: Path) -> str:
    for line in path.read_text().splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"missing {name} in {path}")


API_KEY = env_value("API_KEY", ROOT / ".env")

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f" -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)
    return condition


def require_http(url: str) -> str:
    """Refuse anything that is not http.

    The script talks to a local API and a local frontend. Anything else --
    a file:// URL, for instance -- is not something it should ever open.
    """
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"refusing to open {url!r}: only http is allowed")
    return url


def call(method: str, url: str, payload: dict | None = None, timeout: int = 60):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(  # noqa: S310 - require_http() refuses every other scheme
        require_http(url), data=data, method=method
    )
    request.add_header("X-API-Key", API_KEY)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        # noqa is safe here: require_http() above refuses every scheme but http.
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = response.read().decode()
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body


def web(path: str) -> tuple[int, str]:
    try:
        target = require_http(f"{WEB}{path}")
        with urllib.request.urlopen(target, timeout=60) as response:  # noqa: S310
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


print("== 1. submit a pasted Solidity contract ==")
status, body = call("POST", f"{API}/scans", {"source_code": SOURCE, "chain_id": 1})
if not check("the scan is accepted", status == 202, f"HTTP {status} {str(body)[:300]}"):
    raise SystemExit(1)
scan_id = body["id"]
print(f"     scan id {scan_id}")

print("\n== 2. the pipeline runs it ==")
final = None
for _ in range(90):
    status, scan = call("GET", f"{API}/scans/{scan_id}")
    if status != 200:
        raise SystemExit(f"scan fetch failed: HTTP {status}")
    final = scan
    if scan["status"] in {"completed", "partial", "failed"}:
        break
    time.sleep(2)
check(
    "the scan reaches a terminal state",
    final is not None and final["status"] in {"completed", "partial"},
    f"status {final['status'] if final else 'unknown'}",
)
if final.get("limitations"):
    print(f"     limitations: {final['limitations']}")

print("\n== 3. the findings point at the developer's own lines ==")
status, findings = call("GET", f"{API}/scans/{scan_id}/findings")
check("the findings are readable", status == 200, f"HTTP {status}")
items = findings.get("items", findings if isinstance(findings, list) else [])
check("the scan produced findings", len(items) > 0, f"{len(items)} findings")

origin = None
for finding in items:
    evidence = finding.get("evidence") or {}
    detector = (finding.get("detector_id") or "").lower()
    if "origin" in detector or "tx.origin" in json.dumps(evidence):
        origin = finding
        break
if check("a tx.origin finding exists", origin is not None):
    evidence = origin.get("evidence") or {}
    line = evidence.get("source_line")
    check("the finding carries a source line", isinstance(line, int) and line > 0, f"line {line}")
    expected_line = SOURCE.splitlines().index("        return tx.origin;") + 1
    check(
        "the source line is the developer's own line",
        line == expected_line,
        f"reported {line}, expected {expected_line}",
    )

print("\n== 4. the contract is tracked and its history accumulates ==")
status, assets = call("GET", f"{API}/assets?limit=200")
check("the assets are readable", status == 200, f"HTTP {status}")
asset_items = assets.get("items", [])
check("the workspace tracks contracts", len(asset_items) > 0, f"{len(asset_items)} assets")

# The pasted contract has a deterministic address, and the list is
# paginated, so it is looked up by that address rather than by hoping
# it happens to be on the first page.
pasted_address = str((final or {}).get("contract_address") or "").lower()
matching = [item for item in asset_items if item["asset"]["address"].lower() == pasted_address]
if pasted_address and not matching:
    for offset in range(200, 1400, 200):
        status, page = call("GET", f"{API}/assets?limit=200&offset={offset}")
        if status != 200:
            break
        page_items = page.get("items", [])
        if not page_items:
            break
        matching = [
            item for item in page_items if item["asset"]["address"].lower() == pasted_address
        ]
        if matching:
            break
check("the pasted contract is one of them", len(matching) >= 1, pasted_address or "no address")

target = matching[0] if matching else None
if check("the pasted contract has a scan attached", target is not None):
    status, history = call("GET", f"{API}/assets/{target['asset']['id']}/history")
    check("its history is readable", status == 200, f"HTTP {status}")
    timeline = history.get("timeline", [])
    check("the history names this scan", any(e["scan_id"] == scan_id for e in timeline))
    check("the history is dated", all(e.get("created_at") for e in timeline))
    check(
        "the history records the findings of each scan",
        all("finding_count" in e for e in timeline),
    )

print("\n== 5. the frontend shows all of it ==")
status, page = web("/scans/new")
check("the new-scan page renders", status == 200, f"HTTP {status}")
for marker in ("Deployed contract", "Solidity source", "Bytecode"):
    check(f"the form offers the {marker} mode", marker in page)

status, page = web("/assets")
check("the assets page renders", status == 200, f"HTTP {status}")
check("the assets page lists tracked contracts", "Assets" in page)

if target is not None:
    status, page = web(f"/assets/{target['asset']['id']}")
    check("the asset page renders", status == 200, f"HTTP {status}")
    check("the asset page shows the progress", "Progress" in page)
    check("the asset page shows the history", "History" in page)
    check("the asset page offers a rescan", "Scan again" in page)

print("\n== 6. a second scan of the same source grows the history ==")
status, second = call("POST", f"{API}/scans", {"source_code": SOURCE, "chain_id": 1})
check("the second scan is accepted", status == 202, f"HTTP {status}")
for _ in range(90):
    status, scan = call("GET", f"{API}/scans/{second['id']}")
    if scan["status"] in {"completed", "partial", "failed"}:
        break
    time.sleep(2)
if target is not None:
    status, history = call("GET", f"{API}/assets/{target['asset']['id']}/history")
    timeline = history.get("timeline", [])
    check("the history now has two entries", len(timeline) >= 2, f"{len(timeline)} entries")
    check(
        "both scans are in the history",
        {scan_id, second["id"]}.issubset({e["scan_id"] for e in timeline}),
    )

print()
if failures:
    print(f"FAILURES ({len(failures)}): " + "; ".join(failures))
    raise SystemExit(1)
print("ALL CHECKS PASSED")
