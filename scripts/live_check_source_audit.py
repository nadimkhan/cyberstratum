"""Live check of the source-audit path.

Runs the real Slither executable as an external tool, against real Solidity
source, and reports what came back. Slither is not installed in
CyberStratum's own virtual environment -- that is the point. It is an
external tool, invoked across a process boundary, exactly as ADR-0013
requires.

The Slither executable is located from ``SLITHER_BIN`` or from a sibling
Watchdog checkout. Nothing from either is imported.

Usage::

    SLITHER_BIN=E:/projects/watchdog/.venv/Scripts/slither.exe \\
        node scripts/py.mjs scripts/live_check_source_audit.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.services.slither import SlitherRunner  # noqa: E402
from app.services.source_audit import audit_source  # noqa: E402

VULNERABLE = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

contract VulnerableVault {
    mapping(address => uint256) public balances;

    function deposit() external payable {
        balances[msg.sender] += msg.value;
    }

    function withdraw(uint256 amount) external {
        require(balances[msg.sender] >= amount, "insufficient");
        balances[msg.sender] -= amount;
        (bool sent, ) = msg.sender.call{value: amount}("");
        require(sent, "transfer failed");
    }

    function ownerOnly() external view returns (uint256) {
        require(tx.origin == address(0x1234), "not owner");
        return balances[tx.origin];
    }
}
"""

CLEAN = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

contract CleanCounter {
    uint256 private count;

    function increment() external {
        count += 1;
    }

    function get() external view returns (uint256) {
        return count;
    }
}
"""


def _find_slither() -> str | None:
    """Locate a Slither executable without importing anything from it."""
    env = os.environ.get("SLITHER_BIN", "").strip()
    if env and Path(env).is_file():
        return env
    for candidate in (
        Path("E:/projects/watchdog/.venv/Scripts/slither.exe"),
        Path("E:/projects/watchdog/.venv/bin/slither"),
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def _detector_coverage(executable: str) -> tuple[list[str], list[str]]:
    """Compare the map against the detectors this Slither actually has.

    Args:
        executable: The Slither executable.

    Returns:
        The detectors the map does not cover, and the map's own size.
    """
    import subprocess

    from app.services.slither import DETECTOR_TO_VECTOR

    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [executable, "--list-detectors"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    names: list[str] = []
    for line in completed.stdout.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4:
            continue
        name = parts[2]
        if not name or name == "Check" or name.isdigit():
            continue
        names.append(name.replace("-", "_"))

    uncovered = sorted({n for n in names if n not in DETECTOR_TO_VECTOR})
    return uncovered, sorted(DETECTOR_TO_VECTOR)


def main() -> int:
    executable = _find_slither()
    print("Source-audit live check")
    print(f"Slither executable: {executable or 'NOT FOUND'}")
    print(f"solc artifacts    : {Path.home() / '.solc-select' / 'artifacts'}")

    if not executable:
        print("\nSkipped: no Slither executable to test against.")
        return 0

    runner = SlitherRunner(executable=executable)
    print(f"runner available  : {runner.available}")
    print(f"solc for 0.8.26   : {runner.find_solc('v0.8.26+commit.8a97fa7a')}")

    uncovered, mapped = _detector_coverage(executable)
    print(f"detectors mapped  : {len(mapped)}")
    print(f"uncovered         : {len(uncovered)}")
    if uncovered:
        print(f"  {', '.join(uncovered)}")

    vulnerable = audit_source(VULNERABLE, "VulnerableVault", "0.8.26", runner=runner)
    print("\n--- VulnerableVault ---")
    if not vulnerable.ran:
        print(f"  skipped: {vulnerable.skipped}")
    else:
        print(f"  findings: {len(vulnerable.findings)}")
        for finding in vulnerable.findings:
            print(
                f"    {finding.detector_id:<42} {finding.severity:<9} "
                f"{finding.category:<22} conf={finding.confidence}"
            )

    clean = audit_source(CLEAN, "CleanCounter", "0.8.26", runner=runner)
    print("\n--- CleanCounter ---")
    if not clean.ran:
        print(f"  skipped: {clean.skipped}")
    else:
        print(f"  findings: {len(clean.findings)}")
        for finding in clean.findings:
            print(f"    {finding.detector_id:<42} {finding.severity:<9} {finding.category}")

    found = bool(vulnerable.ran and vulnerable.findings)
    print("\n=== verdict ===")
    print(f"  the source engine ran      : {vulnerable.ran}")
    print(f"  it found the vulnerable one : {found}")
    print(f"  the clean one              : {len(clean.findings)} finding(s)")
    return 0 if vulnerable.ran else 1


if __name__ == "__main__":
    raise SystemExit(main())
