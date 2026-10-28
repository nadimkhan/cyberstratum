"""Tests for the out-of-process Slither runner.

Slither is AGPL-3.0 and is run as an external executable, so these tests
never need Slither installed: they assert on the command that *would* be
run, on the JSON that comes back, and on the boundary itself.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.services.slither import (
    DETECTOR_TO_VECTOR,
    FALLBACK_SOLC_VERSIONS,
    MIN_SOURCE_LENGTH,
    SlitherFinding,
    SlitherRunner,
    SlitherUnavailableError,
    normalize_detector,
    normalize_severity,
    parse_slither_envelope,
    parse_slither_json,
    solc_version_from_string,
    vector_for,
)

SAMPLE_SOURCE = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

contract Vault {
    mapping(address => uint256) public balances;

    function withdraw(uint256 amount) external {
        require(balances[msg.sender] >= amount, "insufficient");
        balances[msg.sender] -= amount;
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok);
    }
}
"""

SLITHER_OUTPUT = {
    "success": True,
    "results": {
        "detectors": [
            {
                "check": "reentrancy-eth",
                "impact": "High",
                "confidence": "Medium",
                "description": (
                    "Reentrancy in Vault.withdraw(uint256):\n"
                    "  - State updated after external call"
                ),
                "contract_path": "Vault.sol",
            },
            {
                "check": "tx-origin",
                "impact": "Medium",
                "confidence": "High",
                "description": "tx.origin is used for authorization",
                "contract_path": "Vault.sol",
            },
            {
                "check": "unused-return",
                "impact": "Informational",
                "confidence": "Medium",
                "description": "Return value of call is not used",
                "contract_path": "Vault.sol",
            },
        ]
    },
}


def _fake_executable(tmp_path: Path, python_body: str) -> Path:
    """A runnable stand-in for the Slither executable.

    On Windows a ``#!/bin/sh`` script is not a valid Win32 application, so the
    fake is a Python script behind a platform-appropriate launcher.
    """
    script = tmp_path / "fake_slither.py"
    script.write_text(python_body, encoding="utf-8")

    if os.name == "nt":
        launcher = tmp_path / "slither.cmd"
        launcher.write_text(
            f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8"
        )
    else:
        launcher = tmp_path / "slither"
        launcher.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8"
        )
        launcher.chmod(0o755)
    return launcher


def _make_solc(tmp_path: Path) -> None:
    """Create a fake solc binary the runner can find."""
    version_dir = tmp_path / "solc-0.8.26"
    version_dir.mkdir(exist_ok=True)
    (version_dir / "solc-0.8.26").write_text("", encoding="utf-8")


# -- normalisation -------------------------------------------------------


def test_a_detector_name_is_snake_cased() -> None:
    """Slither's hyphenated names become snake_case."""
    assert normalize_detector("reentrancy-eth") == "reentrancy_eth"
    assert normalize_detector("tx-origin") == "tx_origin"
    assert normalize_detector("  Divide Before Multiply ") == "divide_before_multiply"


def test_severity_is_mapped_onto_the_shared_scale() -> None:
    """Slither's impacts become the four severities the product uses."""
    assert normalize_severity("Critical") == "critical"
    assert normalize_severity("High") == "high"
    assert normalize_severity("Medium") == "medium"
    assert normalize_severity("Low") == "low"
    # Informational and optimisation are not severities of their own.
    assert normalize_severity("Informational") == "low"
    assert normalize_severity("Optimization") == "low"
    # An unknown impact does not get to invent a severity.
    assert normalize_severity("Whatever") == "medium"


def test_a_detector_maps_onto_a_shared_risk_vector() -> None:
    """Source and bytecode findings of the same class share a vector."""
    assert vector_for("reentrancy_eth") == "reentrancy"
    assert vector_for("tx_origin") == "tx_origin_auth"
    assert vector_for("suicidal") == "selfdestruct"
    # An unmapped detector keeps its own name, so nothing is lost.
    assert vector_for("some_new_detector") == "some_new_detector"


def test_the_detector_map_covers_the_shared_vocabulary() -> None:
    """The vectors used by the bytecode rules exist in the source map too."""
    for vector in ("reentrancy", "selfdestruct", "tx_origin_auth"):
        assert vector in DETECTOR_TO_VECTOR.values()


# -- compiler version ----------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("v0.8.26+commit.8a97fa7a", "0.8.26"),
        ("0.8.20", "0.8.20"),
        ("0.7.6", "0.7.6"),
        ("v0.6", "0.6.0"),
        ("", "0.8.26"),
        ("garbage", "0.8.26"),
    ],
)
def test_a_compiler_version_is_reduced_to_three_parts(
    given: str, expected: str
) -> None:
    """The version string is normalised the way solc-select names it."""
    assert solc_version_from_string(given) == expected


# -- JSON parsing --------------------------------------------------------


def test_slither_json_is_parsed_into_findings() -> None:
    """The standard ``results.detectors`` shape is understood."""
    findings = parse_slither_json(json.dumps(SLITHER_OUTPUT))

    assert len(findings) == 3
    by_detector = {f.detector: f for f in findings}
    assert "reentrancy_eth" in by_detector
    assert by_detector["reentrancy_eth"].severity == "high"
    assert by_detector["reentrancy_eth"].confidence == "medium"
    assert by_detector["reentrancy_eth"].vector == "reentrancy"
    assert "Reentrancy" in by_detector["reentrancy_eth"].description


def test_a_bare_detector_list_is_also_parsed() -> None:
    """Some versions emit the list on its own."""
    findings = parse_slither_json(json.dumps(SLITHER_OUTPUT["results"]["detectors"]))
    assert len(findings) == 3


def test_unusable_json_yields_no_findings() -> None:
    """Garbage in, nothing out -- never an exception."""
    assert parse_slither_json("not json at all") == ()
    assert parse_slither_json("") == ()
    assert parse_slither_json('{"success": false}') == ()


# -- the failure envelope ------------------------------------------------


def test_a_failed_run_is_not_a_clean_contract() -> None:
    """Slither reports internal failures in the envelope, not in the exit code.

    Slither's JSON output is ``{"success": error is None, "error": ...,
    "results": {...}}``. A run that failed part-way through still emits a
    well-formed envelope with no detectors in it, so reading only the
    detectors would record a failed audit as a clean contract.
    """
    payload = json.dumps(
        {
            "success": False,
            "error": "InvalidCompilation: could not compile the target",
            "results": {},
        }
    )
    findings, error = parse_slither_envelope(payload)
    assert findings == ()
    assert error is not None
    assert "InvalidCompilation" in error


def test_a_successful_run_reports_no_error() -> None:
    """A clean run is a verdict, and says so."""
    findings, error = parse_slither_envelope(json.dumps(SLITHER_OUTPUT))
    assert len(findings) == 3
    assert error is None


def test_a_failed_run_that_still_found_something_is_still_a_failure() -> None:
    """Detectors produced before a crash do not make the run complete."""
    payload = json.dumps(
        {
            "success": False,
            "error": "Analysis failed",
            "results": {"detectors": SLITHER_OUTPUT["results"]["detectors"]},
        }
    )
    findings, error = parse_slither_envelope(payload)
    assert error == "Analysis failed"
    # The findings are still parsed, but the caller must not treat this as a
    # completed audit; the runner turns a non-empty error into a skip.
    assert len(findings) == 3


def test_non_json_output_is_reported_as_an_error() -> None:
    """Output that is not JSON is a failure, not a clean result."""
    findings, error = parse_slither_envelope("not json at all")
    assert findings == ()
    assert error == "non_json_output"


def test_the_runner_turns_an_engine_failure_into_a_skip(tmp_path: Path) -> None:
    """End to end: a failed Slither run is a skip, never a clean contract."""
    _make_solc(tmp_path)
    fake = _fake_executable(
        tmp_path,
        "import sys\n"
        "sys.stdout.write('{\"success\": false, \"error\": \"boom\", "
        "\"results\": {}}')\n",
    )

    runner = SlitherRunner(executable=str(fake), solc_artifacts=str(tmp_path))
    result = runner.run(SAMPLE_SOURCE, "Vault")

    assert result.ran is False
    assert result.skipped == "engine_error"
    assert result.findings == ()


def test_the_runner_keeps_a_clean_run_a_verdict(tmp_path: Path) -> None:
    """A successful run with no detectors is genuinely a clean contract."""
    _make_solc(tmp_path)
    fake = _fake_executable(
        tmp_path,
        "import sys\n"
        "sys.stdout.write('{\"success\": true, \"error\": null, "
        "\"results\": {\"detectors\": []}}')\n",
    )

    runner = SlitherRunner(executable=str(fake), solc_artifacts=str(tmp_path))
    result = runner.run(SAMPLE_SOURCE, "Vault")

    assert result.ran is True
    assert result.skipped is None
    assert result.findings == ()


def test_a_description_is_truncated() -> None:
    """A pathological description cannot blow up the findings table."""
    payload = {
        "results": {
            "detectors": [
                {"check": "x", "impact": "High", "description": "y" * 5000}
            ]
        }
    }
    findings = parse_slither_json(json.dumps(payload))
    assert len(findings[0].description) == 500


# -- the executable ------------------------------------------------------


def test_the_runner_reports_a_missing_slither() -> None:
    """A missing tool is a skip, not a crash."""
    runner = SlitherRunner(executable="definitely/not/here/slither")
    assert runner.available is False
    result = runner.run(SAMPLE_SOURCE, "Vault")
    assert result.ran is False
    assert result.skipped == "slither_not_installed"
    assert result.findings == ()


def test_a_source_that_is_too_short_is_skipped() -> None:
    """A stub source is not worth a Slither run."""
    runner = SlitherRunner(executable="definitely/not/here/slither")
    result = runner.run("x" * (MIN_SOURCE_LENGTH - 1), "Vault")
    assert result.skipped == "source_too_short"


def test_the_command_names_an_executable_not_a_module() -> None:
    """The boundary: Slither is run, never imported."""
    runner = SlitherRunner(executable="definitely/not/here/slither")
    with pytest.raises(SlitherUnavailableError):
        runner.build_command("/tmp/Vault.sol", None)


def test_the_command_asks_for_json_and_pins_solc(tmp_path: Path) -> None:
    """The command is fully determined by the runner's configuration."""
    fake = tmp_path / "slither"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")

    runner = SlitherRunner(executable=str(fake))
    command = runner.build_command("/tmp/Vault.sol", "/opt/solc-0.8.26")

    assert command[0] == str(fake)
    assert command[1] == "/tmp/Vault.sol"
    assert "--json" in command
    assert "--disable-color" in command
    assert "--solc=/opt/solc-0.8.26" in command
    # It runs the executable; it never says "python -m slither".
    assert not any("slither." in part for part in command)


def test_solc_is_found_by_version(tmp_path: Path) -> None:
    """The solc binary is looked up under the artifacts directory.

    This is solc-select's real layout: ``artifacts/solc-0.8.26/solc-0.8.26``.
    """
    version_dir = tmp_path / "solc-0.8.26"
    version_dir.mkdir()
    binary = version_dir / "solc-0.8.26"
    binary.write_text("", encoding="utf-8")

    runner = SlitherRunner(solc_artifacts=str(tmp_path))
    assert runner.find_solc("v0.8.26+commit.8a97fa7a") == str(binary)


def test_a_flat_solc_layout_is_also_understood(tmp_path: Path) -> None:
    """Some setups use ``artifacts/0.8.26/solc-0.8.26.exe``."""
    version_dir = tmp_path / "0.8.26"
    version_dir.mkdir()
    binary = version_dir / "solc-0.8.26.exe"
    binary.write_text("", encoding="utf-8")

    runner = SlitherRunner(solc_artifacts=str(tmp_path))
    assert runner.find_solc("0.8.26") == str(binary)


def test_a_missing_solc_is_reported_not_guessed(tmp_path: Path) -> None:
    """No solc means the run is skipped, never run with the wrong compiler."""
    runner = SlitherRunner(solc_artifacts=str(tmp_path))
    assert runner.find_solc("0.8.26") is None


def test_the_fallback_versions_are_tried_in_order() -> None:
    """The fallback list is ordered newest-first."""
    assert FALLBACK_SOLC_VERSIONS[0] == "0.8.26"
    assert len(FALLBACK_SOLC_VERSIONS) == len(set(FALLBACK_SOLC_VERSIONS))


# -- running against a fake executable -----------------------------------


def test_a_run_parses_the_executables_json(tmp_path: Path) -> None:
    """A fake executable stands in for Slither and its JSON is read."""
    fake = _fake_executable(
        tmp_path,
        "import sys\n"
        "sys.stdout.write(" + repr(json.dumps(SLITHER_OUTPUT)) + ")\n",
    )
    _make_solc(tmp_path)

    runner = SlitherRunner(executable=str(fake), solc_artifacts=str(tmp_path))
    result = runner.run(SAMPLE_SOURCE, "Vault", "v0.8.26+commit.8a97fa7a")

    assert result.ran is True
    assert len(result.findings) == 3
    assert result.findings[0].vector == "reentrancy"


def test_a_timeout_is_reported_as_a_skip(tmp_path: Path) -> None:
    """A hanging Slither is a skip, not a crash."""
    fake = _fake_executable(tmp_path, "import time\ntime.sleep(30)\n")
    _make_solc(tmp_path)

    runner = SlitherRunner(
        executable=str(fake), solc_artifacts=str(tmp_path), timeout=1
    )
    result = runner.run(SAMPLE_SOURCE, "Vault", "0.8.26")

    assert result.ran is False
    assert result.skipped == "timeout"


def test_silence_is_reported_as_a_skip(tmp_path: Path) -> None:
    """An executable that says nothing produced no findings."""
    fake = _fake_executable(tmp_path, "pass\n")
    _make_solc(tmp_path)

    runner = SlitherRunner(executable=str(fake), solc_artifacts=str(tmp_path))
    result = runner.run(SAMPLE_SOURCE, "Vault", "0.8.26")

    assert result.ran is False
    assert result.skipped == "no_output"


def test_the_source_is_written_to_a_temporary_file(tmp_path: Path) -> None:
    """The source is written out for the executable to read."""
    marker = tmp_path / "written.sol"
    fake = _fake_executable(
        tmp_path,
        "import shutil, sys\n"
        f"shutil.copyfile(sys.argv[1], r'{marker}')\n"
        "sys.stdout.write('{\"results\": {\"detectors\": []}}')\n",
    )
    _make_solc(tmp_path)

    runner = SlitherRunner(executable=str(fake), solc_artifacts=str(tmp_path))
    runner.run(SAMPLE_SOURCE, "Vault", "0.8.26")

    assert marker.exists()
    assert "contract Vault" in marker.read_text(encoding="utf-8")


def test_the_running_is_a_real_subprocess(tmp_path: Path) -> None:
    """The runner really does fork a process, not call into Python."""
    fake = _fake_executable(
        tmp_path,
        "import sys\n"
        "sys.stdout.write('{\"results\": {\"detectors\": []}}')\n",
    )
    _make_solc(tmp_path)

    runner = SlitherRunner(executable=str(fake), solc_artifacts=str(tmp_path))
    result = runner.run(SAMPLE_SOURCE, "Vault", "0.8.26")

    assert result.ran is True
    assert isinstance(result.findings, tuple)


def test_a_finding_carries_the_vector_it_was_mapped_to() -> None:
    """A finding is self-describing, so it can be stored without a lookup."""
    finding = SlitherFinding(
        detector="suicidal",
        severity="high",
        confidence="medium",
        description="Contract can be destructed",
        vector=vector_for("suicidal"),
    )
    assert finding.vector == "selfdestruct"


def test_subprocess_is_used_without_a_shell() -> None:
    """The runner never goes through a shell."""
    source = (
        Path(__file__).resolve().parents[2] / "apps" / "api" / "app" / "services" / "slither.py"
    ).read_text(encoding="utf-8")
    assert "subprocess.run" in source
    assert "shell=True" not in source
    assert isinstance(subprocess.run, object)


# -- the detector map ---------------------------------------------------


def test_the_map_covers_slither_0_11_detectors() -> None:
    """Every detector Slither 0.11.6 ships is mapped to a risk vector.

    This list was taken from ``slither --list-detectors`` on 0.11.6. A
    detector that is missing from the map would silently fall back to its
    own name and stop matching the bytecode engine's vocabulary.
    """
    slither_0_11_detectors = {
        "abiencoderv2_array",
        "arbitrary_send_erc20",
        "arbitrary_send_erc20_permit",
        "arbitrary_send_eth",
        "array_by_reference",
        "assembly",
        "assert_state_change",
        "boolean_cst",
        "boolean_equal",
        "cache_array_length",
        "calls_loop",
        "chainlink_feed_registry",
        "chronicle_unchecked_price",
        "constable_states",
        "constant_function_asm",
        "constant_function_state",
        "controlled_array_length",
        "controlled_delegatecall",
        "costly_loop",
        "cyclomatic_complexity",
        "dead_code",
        "delegatecall_loop",
        "deprecated_standards",
        "divide_before_multiply",
        "domain_separator_collision",
        "encode_packed_collision",
        "enum_conversion",
        "erc20_indexed",
        "erc20_interface",
        "erc721_interface",
        "events_access",
        "events_maths",
        "external_function",
        "function_init_state",
        "gelato_unprotected_randomness",
        "immutable_states",
        "incorrect_equality",
        "incorrect_exp",
        "incorrect_modifier",
        "incorrect_return",
        "incorrect_shift",
        "incorrect_unary",
        "incorrect_using_for",
        "locked_ether",
        "low_level_calls",
        "mapping_deletion",
        "missing_inheritance",
        "missing_zero_check",
        "msg_value_in_nonpayable",
        "msg_value_loop",
        "multiple_constructors",
        "name_reused",
        "naming_convention",
        "optimism_deprecation",
        "out_of_order_retryable",
        "pragma",
        "protected_vars",
        "public_mappings_nested",
        "pyth_deprecated_functions",
        "pyth_unchecked_confidence",
        "pyth_unchecked_publishtime",
        "redundant_statements",
        "reentrancy_balance",
        "reentrancy_benign",
        "reentrancy_eth",
        "reentrancy_events",
        "reentrancy_no_eth",
        "reentrancy_unlimited_gas",
        "return_bomb",
        "return_leave",
        "reused_constructor",
        "rtlo",
        "shadowing_abstract",
        "shadowing_builtin",
        "shadowing_local",
        "shadowing_state",
        "solc_version",
        "storage_array",
        "suicidal",
        "tautological_compare",
        "tautology",
        "timestamp",
        "too_many_digits",
        "tx_origin",
        "unchecked_lowlevel",
        "unchecked_send",
        "unchecked_transfer",
        "unimplemented_functions",
        "unindexed_event_address",
        "uninitialized_fptr_cst",
        "uninitialized_local",
        "uninitialized_state",
        "uninitialized_storage",
        "unprotected_upgrade",
        "unused_return",
        "unused_state",
        "variable_scope",
        "var_read_using_this",
        "void_cst",
        "weak_prng",
        "write_after_write",
    }

    uncovered = sorted(
        d for d in slither_0_11_detectors if d not in DETECTOR_TO_VECTOR
    )
    assert not uncovered, f"these detectors have no risk vector: {uncovered}"


def test_the_legacy_detector_names_are_still_mapped() -> None:
    """An older Slither still maps onto the shared vocabulary."""
    assert DETECTOR_TO_VECTOR["unchecked_lowlevel"] == "unchecked_call"
    assert DETECTOR_TO_VECTOR["tx_origin"] == "tx_origin_auth"
    assert DETECTOR_TO_VECTOR["suicidal"] == "selfdestruct"
    assert DETECTOR_TO_VECTOR["shadowing_state"] == "proxy_governance_risk"
    assert DETECTOR_TO_VECTOR["reentrancy_eth"] == "reentrancy"


def test_the_modern_names_map_onto_the_same_vectors() -> None:
    """Slither renamed several detectors; the vectors did not change."""
    assert DETECTOR_TO_VECTOR["low_level_calls"] == (
        DETECTOR_TO_VECTOR["unchecked_lowlevel"]
    )
    assert DETECTOR_TO_VECTOR["reentrancy_balance"] == (
        DETECTOR_TO_VECTOR["reentrancy_eth"]
    )


# -- a source that does not compile --------------------------------------


def test_a_compilation_failure_is_told_apart_from_silence(tmp_path: Path) -> None:
    """A source that does not compile is not the same as a clean contract."""
    fake = _fake_executable(
        tmp_path,
        "import sys\n"
        "sys.stderr.write('Compilation failed: Error: expected identifier')\n"
        "sys.exit(1)\n",
    )
    _make_solc(tmp_path)

    runner = SlitherRunner(executable=str(fake), solc_artifacts=str(tmp_path))
    result = runner.run(SAMPLE_SOURCE, "Vault", "0.8.26")

    assert result.ran is False
    assert result.skipped == "compilation_failed"


def test_silence_is_still_reported_as_silence(tmp_path: Path) -> None:
    """An executable that says nothing is not a compilation failure."""
    fake = _fake_executable(tmp_path, "pass\n")
    _make_solc(tmp_path)

    runner = SlitherRunner(executable=str(fake), solc_artifacts=str(tmp_path))
    result = runner.run(SAMPLE_SOURCE, "Vault", "0.8.26")

    assert result.skipped == "no_output"
