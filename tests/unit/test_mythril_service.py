"""Tests for the out-of-process Mythril runner.

Mythril is not installed on the test machine, and it must not be: it is
run out of process from its own environment. These tests therefore never
need it. They assert on the envelope parsing -- the part that carries the
verdict -- and on the command that *would* be run, using a fake
executable where the subprocess boundary has to be exercised.

The measured traps each get a test:

* exit ``1`` means issues were found, not that the engine failed;
* ``success: false`` with an empty issue list is an error, not a clean
  contract;
* creation bytecode analysed as runtime yields a false clean, so it is
  refused.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from app.db.enums import Severity
from app.services.mythril import (
    DEFAULT_MYTHRIL_BINARY,
    GENERIC_CATEGORY,
    MYTHRIL_BIN_ENV,
    SWC_TO_CATEGORY,
    MythrilFinding,
    MythrilResult,
    MythrilRunner,
    MythrilUnavailableError,
    category_for_swc,
    looks_like_creation_bytecode,
    normalize_severity,
    normalize_swc_id,
    parse_mythril_envelope,
    to_rule_finding,
    to_rule_findings,
)

#: The measured envelope of a run that found two issues in the runtime
#: bytecode of the reentrancy fixture. Exit code was ``1``.
FINDINGS_ENVELOPE = {
    "success": True,
    "error": None,
    "issues": [
        {
            "swc-id": "105",
            "swc-title": "Reentrancy",
            "description": "A reachable path to a state-changing function",
            "severity": "High",
            "sourceMap": "1:1:0",
            "function": "withdraw",
            "lineno": 12,
            "code": "balances[msg.sender] -= amount;",
            "tx_sequence": ["send 1 ether to attacker", "call withdraw again"],
        },
        {
            "swc-id": "114",
            "swc-title": "Transaction order dependence (TOD)",
            "description": "The outcome depends on the order of transactions",
            "severity": "Medium",
            "sourceMap": "1:1:0",
            "function": "withdraw",
            "lineno": 12,
            "code": "balances[msg.sender] -= amount;",
        },
    ],
}

#: The measured envelope of a run that failed: well formed, empty issue
#: list, ``success: false``. This is the shape that reads as "clean" to
#: anything that only looks at the issues.
FAILED_ENVELOPE = {
    "success": False,
    "error": "Compiler not found. Make sure that solc is installed and in PATH.",
    "issues": [],
}

#: A run that genuinely found nothing.
CLEAN_ENVELOPE = {"success": True, "error": None, "issues": []}


def _fake_executable(tmp_path: Path, python_body: str, name: str = "myth") -> Path:
    """A runnable stand-in for the Mythril executable.

    On Windows a bare script is not a valid Win32 application, so the
    fake is a Python script behind a ``.cmd`` launcher.
    """
    script = tmp_path / "fake_myth.py"
    script.write_text(python_body, encoding="utf-8")

    if os.name == "nt":
        launcher = tmp_path / f"{name}.cmd"
        launcher.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        launcher = tmp_path / name
        launcher.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8"
        )
        launcher.chmod(0o755)
    return launcher


# -- the inverted exit code ----------------------------------------------


def test_exit_one_with_issues_is_a_result_not_a_failure() -> None:
    """The measured run: exit 1, success true, two issues.

    Mythril exits ``1`` when it finds issues. A runner that maps a
    non-zero exit onto "the engine failed" would throw away every
    genuine result.
    """
    result = parse_mythril_envelope(json.dumps(FINDINGS_ENVELOPE), 1)

    assert len(result.findings) == 2
    assert result.error is None
    assert result.skipped is None
    assert result.ran is True
    assert result.success is True
    assert result.clean is False
    assert result.no_verdict is False


def test_the_exit_code_alone_never_decides_the_verdict() -> None:
    """Exit 0 with issues is still issues; exit 1 is still not a crash."""
    with_issues = parse_mythril_envelope(json.dumps(FINDINGS_ENVELOPE), 0)
    assert len(with_issues.findings) == 2
    assert with_issues.clean is False

    # The same payload with the exit code that "means failure" in most
    # tools still produces the same verdict.
    with_exit_one = parse_mythril_envelope(json.dumps(FINDINGS_ENVELOPE), 1)
    assert len(with_exit_one.findings) == 2
    assert with_exit_one.skipped is None


def test_the_findings_carry_their_swc_id_and_severity() -> None:
    """The issue is normalised, not passed through as raw JSON."""
    result = parse_mythril_envelope(json.dumps(FINDINGS_ENVELOPE), 1)

    first = result.findings[0]
    assert first.swc_id == "105"
    assert first.severity == "high"
    assert first.title == "Reentrancy"
    assert first.function_name == "withdraw"
    assert first.lineno == 12
    assert first.tx_sequence


# -- the envelope is validated before the issues are trusted --------------


def test_a_failed_envelope_is_not_a_clean_contract() -> None:
    """``success: false`` with an empty issue list is an error.

    This is the compiler-not-found trap: the payload is well formed and
    the issue list is empty, so anything that reads only the issues
    records a failed audit as a clean contract.
    """
    result = parse_mythril_envelope(json.dumps(FAILED_ENVELOPE), 0)

    assert result.findings == ()
    assert result.clean is False
    assert result.no_verdict is True
    assert result.success is False
    assert result.skipped == "engine_error"
    assert result.error is not None
    assert "Compiler not found" in result.error


def test_a_successful_run_with_no_issues_is_a_clean_contract() -> None:
    """``success: true`` with an empty issue list is a genuine verdict."""
    result = parse_mythril_envelope(json.dumps(CLEAN_ENVELOPE), 0)

    assert result.findings == ()
    assert result.clean is True
    assert result.no_verdict is False
    assert result.ran is True
    assert result.success is True
    assert result.skipped is None


def test_a_failed_envelope_with_issues_still_is_a_failure() -> None:
    """Issues found before a failure do not make the run complete."""
    payload = dict(FAILED_ENVELOPE)
    payload["issues"] = FINDINGS_ENVELOPE["issues"]
    result = parse_mythril_envelope(json.dumps(payload), 1)

    assert result.success is False
    assert result.clean is False
    assert result.no_verdict is True
    assert result.error is not None


# -- unusable output -----------------------------------------------------


def test_non_json_output_is_no_verdict() -> None:
    """Garbage on stdout is not a clean contract."""
    result = parse_mythril_envelope("not json at all", 1)

    assert result.findings == ()
    assert result.clean is False
    assert result.no_verdict is True
    assert result.skipped == "non_json_output"
    assert result.success is None


def test_empty_output_is_no_verdict() -> None:
    """Silence is not a clean contract."""
    result = parse_mythril_envelope("", 0)

    assert result.findings == ()
    assert result.clean is False
    assert result.no_verdict is True
    assert result.skipped == "no_output"


def test_empty_output_from_a_dying_process_is_reported_as_a_crash() -> None:
    """An exit code outside Mythril's two means the process died."""
    result = parse_mythril_envelope("", 255)

    assert result.skipped == "engine_crash"
    assert result.clean is False
    assert result.no_verdict is True


def test_a_payload_that_is_not_an_object_is_unusable() -> None:
    """The envelope shape is part of the contract."""
    result = parse_mythril_envelope("[1, 2, 3]", 0)

    assert result.skipped == "unusable_output"
    assert result.clean is False


def test_a_payload_without_the_envelope_keys_is_unusable() -> None:
    """An envelope without ``success``/``issues`` proves nothing."""
    result = parse_mythril_envelope(json.dumps({"issues": []}), 0)

    assert result.skipped == "unusable_output"
    assert result.clean is False
    assert result.no_verdict is True


def test_bytes_are_accepted() -> None:
    """The parser takes bytes as well as text."""
    result = parse_mythril_envelope(json.dumps(FINDINGS_ENVELOPE).encode("utf-8"), 1)
    assert len(result.findings) == 2


# -- the binary -----------------------------------------------------------


def test_a_missing_binary_is_a_skip_not_an_exception() -> None:
    """Mythril is not installed here, and that is not a failure."""
    runner = MythrilRunner(executable="definitely/not/here/myth")
    assert runner.available is False

    result = runner.run(b"\x60\x60", "Vault")

    assert result.ran is False
    assert result.skipped == "mythril_not_installed"
    assert result.findings == ()
    assert result.clean is False
    assert result.no_verdict is True


def test_the_binary_is_looked_up_under_the_name_myth() -> None:
    """The console script is ``myth``; there is no ``mythril`` binary."""
    assert DEFAULT_MYTHRIL_BINARY == "myth"


def test_the_binary_path_is_configurable_by_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """``MYTHRIL_BIN`` points the runner at the executable."""
    monkeypatch.setenv(MYTHRIL_BIN_ENV, "somewhere/myth")
    runner = MythrilRunner()
    assert runner.find_executable() is None  # the path does not exist


def test_the_command_names_an_executable_not_a_module() -> None:
    """The boundary: Mythril is run, never imported."""
    runner = MythrilRunner(executable="definitely/not/here/myth")
    with pytest.raises(MythrilUnavailableError):
        runner.build_command("/tmp/Vault.hex")


def test_the_command_asks_for_raw_runtime_json(tmp_path: Path) -> None:
    """The argv is fully determined by the runner's configuration."""
    fake = tmp_path / "myth"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")

    runner = MythrilRunner(executable=str(fake))
    command = runner.build_command("/tmp/Vault.hex")

    assert command[0] == str(fake)
    assert "analyze" in command
    assert "--bin-runtime" in command
    assert "-o" in command
    assert "json" in command
    # It runs the executable; it never says "python -m mythril".
    assert not any("mythril" in part for part in command)


# -- the creation-bytecode trap ------------------------------------------


def test_creation_bytecode_is_refused_loudly() -> None:
    """Creation code analysed as runtime yields a false clean.

    The refusal must be distinct and must never read as "clean".
    """
    runner = MythrilRunner(executable="definitely/not/here/myth")
    result = runner.run(b"\x60\x60", "Vault", bytecode_kind="creation")

    assert result.ran is False
    assert result.skipped == "creation_bytecode_supplied"
    assert result.findings == ()
    assert result.clean is False
    assert result.no_verdict is True
    assert result.error is not None


def test_every_creation_kind_is_refused() -> None:
    """The kind argument is honoured whatever word it uses."""
    runner = MythrilRunner(executable="definitely/not/here/myth")
    for kind in ("creation", "init", "constructor", "deploy"):
        result = runner.run(b"\x60\x60", "Vault", bytecode_kind=kind)
        assert result.skipped == "creation_bytecode_supplied"


def test_creation_bytecode_is_detected_from_its_shape() -> None:
    """The heuristic notices creation code even when the caller says runtime.

    Creation code embeds the runtime code -- metadata trailer included --
    and then appends a trailer of its own, so the ``solc`` marker appears
    twice. Runtime code carries exactly one, near the end.
    """
    # A runtime blob whose metadata marker sits at the very end.
    runtime = b"\x60\x80" + b"\x64solc\x43\x00\x08\x00" + b"\x00" * 8
    assert looks_like_creation_bytecode(runtime) is False

    # The same runtime embedded in creation code, which adds a trailer
    # of its own.
    creation = b"\x60\x80\x60\x40" + runtime + b"\x39\x60\xf3"
    creation += b"\x64solc\x43\x00\x08\x00" + b"\x00" * 8
    assert looks_like_creation_bytecode(creation) is True


def test_a_length_mismatch_is_treated_as_creation_code() -> None:
    """Creation code is longer than the runtime it embeds."""
    runtime = b"\x60\x80" * 10
    assert looks_like_creation_bytecode(runtime, deployed_runtime_length=len(runtime)) is False
    assert looks_like_creation_bytecode(runtime, deployed_runtime_length=5) is True


def test_a_creation_shaped_blob_is_refused_by_the_runner() -> None:
    """The runner refuses before it invokes anything."""
    runtime = b"\x60\x80" + b"\x64solc\x43\x00\x08\x00" + b"\x00" * 8
    creation = b"\x60\x80\x60\x40" + runtime + b"\x39\x60\xf3"
    creation += b"\x64solc\x43\x00\x08\x00" + b"\x00" * 8

    runner = MythrilRunner(executable="definitely/not/here/myth")
    result = runner.run(creation, "Vault")

    assert result.ran is False
    assert result.skipped == "creation_bytecode_supplied"
    assert result.clean is False


def test_empty_bytecode_is_refused() -> None:
    """Nothing to analyse is not a clean contract."""
    runner = MythrilRunner(executable="definitely/not/here/myth")
    result = runner.run(b"", "Vault")

    assert result.skipped == "empty_bytecode"
    assert result.clean is False


# -- running against a fake executable ------------------------------------


def test_a_run_reads_the_executables_envelope(tmp_path: Path) -> None:
    """A fake executable stands in for Mythril and its JSON is read."""
    fake = _fake_executable(
        tmp_path,
        "import sys\nsys.stdout.write(" + repr(json.dumps(FINDINGS_ENVELOPE)) + ")\nsys.exit(1)\n",
    )

    runner = MythrilRunner(executable=str(fake))
    result = runner.run(b"\x60\x80", "Vault")

    assert result.ran is True
    assert len(result.findings) == 2
    assert result.exit_code == 1
    assert result.success is True
    assert result.clean is False
    assert result.duration_ms is not None


def test_the_bytecode_is_written_as_pure_hex(tmp_path: Path) -> None:
    """The file Mythril reads is hex, and nothing else.

    A ``0x`` prefix or a trailing newline once made Mythril analyse
    nothing at all, which looks exactly like a clean result.
    """
    marker = tmp_path / "written.hex"
    fake = _fake_executable(
        tmp_path,
        "import shutil, sys\n"
        f"shutil.copyfile(sys.argv[sys.argv.index('-f') + 1], r'{marker}')\n"
        'sys.stdout.write(\'{"success": true, "error": null, "issues": []}\')\n',
    )

    runner = MythrilRunner(executable=str(fake))
    runner.run(b"\x60\x80\x61", "Vault")

    assert marker.exists()
    content = marker.read_text(encoding="utf-8")
    assert content == "608061"
    assert not content.startswith("0x")
    assert content == content.strip()


def test_a_timeout_is_reported_as_no_verdict(tmp_path: Path) -> None:
    """A hanging Mythril is a skip, not a crash."""
    fake = _fake_executable(tmp_path, "import time\ntime.sleep(30)\n")

    runner = MythrilRunner(executable=str(fake))
    result = runner.run(b"\x60\x80", "Vault", timeout_seconds=1)

    assert result.skipped == "timeout"
    assert result.clean is False
    assert result.no_verdict is True
    assert result.findings == ()


def test_a_failed_run_through_the_runner_is_not_clean(tmp_path: Path) -> None:
    """End to end: a failed envelope is a skip, never a clean contract."""
    fake = _fake_executable(
        tmp_path,
        "import sys\nsys.stdout.write(" + repr(json.dumps(FAILED_ENVELOPE)) + ")\nsys.exit(0)\n",
    )

    runner = MythrilRunner(executable=str(fake))
    result = runner.run(b"\x60\x80", "Vault")

    assert result.ran is True
    assert result.skipped == "engine_error"
    assert result.clean is False
    assert result.no_verdict is True
    assert result.error is not None
    assert "Compiler not found" in result.error


def test_a_clean_run_through_the_runner_stays_a_verdict(tmp_path: Path) -> None:
    """A successful run with no issues is genuinely a clean contract."""
    fake = _fake_executable(
        tmp_path,
        "import sys\nsys.stdout.write(" + repr(json.dumps(CLEAN_ENVELOPE)) + ")\nsys.exit(0)\n",
    )

    runner = MythrilRunner(executable=str(fake))
    result = runner.run(b"\x60\x80", "Vault")

    assert result.ran is True
    assert result.skipped is None
    assert result.clean is True
    assert result.no_verdict is False


# -- normalisation --------------------------------------------------------


def test_a_swc_id_is_normalised_to_its_digits() -> None:
    """Mythril and the SWC registry disagree about the prefix."""
    assert normalize_swc_id("105") == "105"
    assert normalize_swc_id("SWC-105") == "105"
    assert normalize_swc_id(105) == "105"
    assert normalize_swc_id("swc-105") == "105"
    assert normalize_swc_id("") == ""
    assert normalize_swc_id(None) == ""


def test_severity_is_mapped_onto_the_shared_scale() -> None:
    """Mythril's severities become the platform's severities."""
    assert normalize_severity("High") == "high"
    assert normalize_severity("Medium") == "medium"
    assert normalize_severity("Low") == "low"
    assert normalize_severity("Critical") == "critical"
    # An unknown severity does not get to invent one.
    assert normalize_severity("Whatever") == "medium"


def test_the_swc_map_covers_the_shared_vocabulary() -> None:
    """The categories used are the ones the platform already has."""
    assert SWC_TO_CATEGORY["105"] == "reentrancy_candidate"
    assert SWC_TO_CATEGORY["114"] == "frontrunning"
    assert SWC_TO_CATEGORY["115"] == "tx_origin_dependency"
    assert SWC_TO_CATEGORY["106"] == "selfdestruct_usage"
    assert SWC_TO_CATEGORY["112"] == "delegatecall_usage"


def test_an_unknown_swc_id_falls_back_without_raising() -> None:
    """Mythril adds identifiers; an unknown one must not crash a scan."""
    category = category_for_swc("999")

    assert isinstance(category, str)
    assert category
    # It is not one of the mapped classes, so it lands on the generic
    # category rather than being forced into an unrelated one.
    assert category == GENERIC_CATEGORY
    assert "999" not in SWC_TO_CATEGORY


# -- the shared finding shape ---------------------------------------------


def test_to_rule_finding_produces_the_shared_shape() -> None:
    """A Mythril issue becomes a finding the unified table can hold."""
    finding = MythrilFinding(
        swc_id="105",
        title="Reentrancy",
        severity="high",
        description="A reachable path to a state-changing function",
        source_map="1:1:0",
        code="balances[msg.sender] -= amount;",
        function_name="withdraw",
        lineno=12,
    )

    rule_finding = to_rule_finding(finding)

    assert rule_finding.detector_id.startswith("mythril.")
    assert rule_finding.detector_id == "mythril.swc_105"
    assert rule_finding.category == "reentrancy_candidate"
    assert rule_finding.severity is Severity.HIGH
    assert rule_finding.title == "Reentrancy"
    assert rule_finding.evidence["swcId"] == "105"
    assert rule_finding.evidence["sourceEngine"] == "mythril"
    assert rule_finding.evidence["code"] == "balances[msg.sender] -= amount;"


def test_the_limitations_state_what_was_not_proven() -> None:
    """A symbolic result is not proof of exploitability."""
    rule_finding = to_rule_finding(
        MythrilFinding(swc_id="105", title="Reentrancy", severity="high")
    )

    limitations = rule_finding.limitations.lower()
    assert "symbolic" in limitations
    assert "reachab" in limitations
    assert "not independently" in limitations


def test_an_unknown_swc_id_produces_a_finding_without_raising() -> None:
    """An unknown id is stored, not dropped and not fatal."""
    rule_finding = to_rule_finding(
        MythrilFinding(swc_id="999", title="Something new", severity="medium")
    )

    assert rule_finding.detector_id.startswith("mythril.")
    assert rule_finding.category
    assert rule_finding.severity is Severity.MEDIUM


def test_a_batch_of_findings_is_converted() -> None:
    """The batch helper keeps the order."""
    result = parse_mythril_envelope(json.dumps(FINDINGS_ENVELOPE), 1)
    findings = to_rule_findings(result.findings)

    assert len(findings) == 2
    assert findings[0].detector_id == "mythril.swc_105"
    assert findings[1].detector_id == "mythril.swc_114"


def test_the_result_defaults_are_safe() -> None:
    """A result built by hand is never clean and never a verdict."""
    result = MythrilResult()

    assert result.clean is False
    assert result.no_verdict is True
    assert result.ran is False
    assert result.findings == ()
