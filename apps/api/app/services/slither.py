"""Out-of-process Slither runner.

Slither and crytic-compile are AGPL-3.0. Under ADR-0013 they are run as an
unmodified external executable and their JSON output is consumed across the
process boundary. Nothing here imports them, vendors them, or patches them.

This module is therefore deliberately thin:

* it finds an executable on disk;
* it writes the source to a temporary file;
* it runs the executable and reads its JSON;
* it normalises the result into CyberStratum's own finding shape.

Everything that is specific to Slither's output format lives here, so that
when Slither's format changes, exactly one file changes.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

log = logging.getLogger("cyberstratum.slither")

#: Environment variable holding the path to the Slither executable.
SLITHER_BIN_ENV: Final[str] = "SLITHER_BIN"

#: Environment variable holding the directory that holds the solc binaries.
SOLC_ARTIFACTS_ENV: Final[str] = "SOLC_ARTIFACTS_DIR"

#: Where solc-select keeps its downloads, when the variable is not set.
DEFAULT_SOLC_ARTIFACTS: Final[str] = "~/.solc-select/artifacts"

#: A source shorter than this is not worth analysing.
MIN_SOURCE_LENGTH: Final[int] = 50

#: Default wall-clock budget for one Slither run.
DEFAULT_TIMEOUT_SECONDS: Final[int] = 120

#: Slither's own severity names mapped onto CyberStratum's.
SEVERITY_MAP: Final[dict[str, str]] = {
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "informational": "low",
    "optimization": "low",
}

#: Slither detectors mapped onto the shared risk-vector vocabulary.
#:
#: The right-hand side is the same vocabulary the bytecode rules use, so a
#: source-level finding and a bytecode finding of the same class compare
#: equal in the unified findings table.
#:
#: Built against Slither 0.11.6's detector list, with the older names kept
#: so an older Slither still maps correctly.
DETECTOR_TO_VECTOR: Final[dict[str, str]] = {
    "reentrancy_balance": "reentrancy",
    "reentrancy_benign": "reentrancy",
    "reentrancy_eth": "reentrancy",
    "reentrancy_events": "reentrancy",
    "reentrancy_no_eth": "reentrancy",
    "reentrancy_unlimited_gas": "reentrancy",
    "tx_origin": "tx_origin_auth",
    "protected_vars": "accesscontrol",
    "unprotected_upgrade": "accesscontrol",
    "centralization": "centralization_risk",
    "admin_administrated": "centralization_risk",
    "pausable": "centralization_risk",
    "events_access": "accesscontrol",
    "incorrect_modifier": "accesscontrol",
    "proxy_upgrade": "proxy_governance_risk",
    "upgradeable_proxy": "proxy_governance_risk",
    "shadowing_state": "proxy_governance_risk",
    "shadowing_abstract": "proxy_governance_risk",
    "delegatecall_loop": "proxy_governance_risk",
    "controlled_delegatecall": "proxy_governance_risk",
    "reused_constructor": "proxy_governance_risk",
    "suicidal": "selfdestruct",
    "unchecked_lowlevel": "unchecked_call",
    "low_level_calls": "unchecked_call",
    "unchecked_send": "unchecked_call",
    "unchecked_transfer": "unchecked_call",
    "unused_return": "unchecked_call",
    "arbitrary_send": "frontrunning",
    "arbitrary_send_eth": "frontrunning",
    "arbitrary_send_erc20": "frontrunning",
    "arbitrary_send_erc20_permit": "frontrunning",
    "front_running": "frontrunning",
    "return_bomb": "unchecked_call",
    "calls_loop": "dos",
    "costly_loop": "dos",
    "msg_value_loop": "dos",
    "locked_ether": "dos",
    "cyclomatic_complexity": "dos",
    "integer_overflow": "integer_overflow",
    "incorrect_equality": "integer_overflow",
    "divide_before_multiply": "integer_overflow",
    "incorrect_exp": "integer_overflow",
    "incorrect_shift": "integer_overflow",
    "incorrect_unary": "integer_overflow",
    "tautological_compare": "integer_overflow",
    "tautology": "integer_overflow",
    "storage_array": "integer_overflow",
    "incorrect_return": "integer_overflow",
    "return_leave": "integer_overflow",
    "ecrecover": "signature_replay",
    "signature_replay": "signature_replay",
    "weak_prng": "signature_replay",
    "gelato_unprotected_randomness": "signature_replay",
    "timestamp": "signature_replay",
    "flash_loan": "price_manipulation",
    "price_manipulation": "price_manipulation",
    "block_bounding": "price_manipulation",
    "chainlink_feed_registry": "price_manipulation",
    "chronicle_unchecked_price": "price_manipulation",
    "pyth_unchecked_confidence": "price_manipulation",
    "pyth_unchecked_publishtime": "price_manipulation",
    "pyth_deprecated_functions": "price_manipulation",
    "domain_separator_collision": "price_manipulation",
    "out_of_order_retryable": "price_manipulation",
    "uninitialized_state": "uninitialized_storage",
    "uninitialized_storage": "uninitialized_storage",
    "uninitialized_local": "uninitialized_storage",
    "uninitialized_fptr_cst": "uninitialized_storage",
    "assembly": "formal_verification_gaps",
    "constant": "formal_verification_gaps",
    "reused_base": "formal_verification_gaps",
    "constant_function_asm": "formal_verification_gaps",
    "constant_function_state": "formal_verification_gaps",
    "constable_states": "formal_verification_gaps",
    "immutable_states": "formal_verification_gaps",
    "dead_code": "formal_verification_gaps",
    "unused_state": "formal_verification_gaps",
    "redundant_statements": "formal_verification_gaps",
    "missing_inheritance": "formal_verification_gaps",
    "unimplemented_functions": "formal_verification_gaps",
    "void_cst": "formal_verification_gaps",
    "assert_state_change": "formal_verification_gaps",
    "write_after_write": "formal_verification_gaps",
    "missing_zero_check": "formal_verification_gaps",
    "boolean_cst": "formal_verification_gaps",
    "boolean_equal": "formal_verification_gaps",
    "rtlo": "formal_verification_gaps",
    "protected_var": "formal_verification_gaps",
    "missing_zero_address_check": "formal_verification_gaps",
    "incorrect_using_for": "formal_verification_gaps",
    "enum_conversion": "formal_verification_gaps",
    "controlled_array_length": "formal_verification_gaps",
    "cache_array_length": "formal_verification_gaps",
    "array_by_reference": "formal_verification_gaps",
    "mapping_deletion": "formal_verification_gaps",
    "erc20_interface": "formal_verification_gaps",
    "erc721_interface": "formal_verification_gaps",
    "erc20_indexed": "formal_verification_gaps",
    "deprecated_standards": "formal_verification_gaps",
    "unindexed_event_address": "formal_verification_gaps",
    "events_maths": "formal_verification_gaps",
    "multiple_constructors": "formal_verification_gaps",
    "name_reused": "formal_verification_gaps",
    "optimism_deprecation": "formal_verification_gaps",
    "solc_version": "formal_verification_gaps",
    "pragma": "formal_verification_gaps",
    "naming_convention": "formal_verification_gaps",
    "external_function": "formal_verification_gaps",
    "variable_scope": "formal_verification_gaps",
    "shadowing_local": "formal_verification_gaps",
    "shadowing_builtin": "formal_verification_gaps",
    "too_many_digits": "formal_verification_gaps",
    "function_init_state": "formal_verification_gaps",
    "init_state": "formal_verification_gaps",
    "msg_value_in_nonpayable": "formal_verification_gaps",
    "incorrect_shift_type": "formal_verification_gaps",
    "encode_packed_collision": "formal_verification_gaps",
    "abiencoderv2_array": "formal_verification_gaps",
    "public_mappings_nested": "formal_verification_gaps",
    "incorrect_return_type": "formal_verification_gaps",
    "reentrancy_protection": "formal_verification_gaps",
    "var_read_using_this": "formal_verification_gaps",
}

#: Fallback solc versions tried when the contract's own version is unknown.
FALLBACK_SOLC_VERSIONS: Final[tuple[str, ...]] = (
    "0.8.26",
    "0.8.20",
    "0.8.10",
    "0.8.0",
    "0.7.6",
    "0.7.5",
    "0.7.0",
    "0.6.12",
    "0.6.0",
    "0.5.17",
    "0.5.0",
    "0.4.26",
    "0.4.25",
    "0.4.24",
    "0.4.0",
)


class SlitherUnavailableError(RuntimeError):
    """Slither is not installed, or no solc binary could be found."""


@dataclass(frozen=True)
class SlitherFinding:
    """One finding, normalised out of Slither's JSON.

    Attributes:
        detector: Slither's check name, snake-cased.
        severity: ``critical``/``high``/``medium``/``low``.
        confidence: Slither's own confidence.
        description: The finding text, truncated.
        vector: The shared risk-vector name.
        contract_path: The source path Slither reported.
    """

    detector: str
    severity: str
    confidence: str
    description: str
    vector: str
    contract_path: str = ""


@dataclass(frozen=True)
class SlitherResult:
    """The outcome of one Slither run.

    Attributes:
        findings: The normalised findings.
        skipped: Why the run did not happen, if it did not.
    """

    findings: tuple[SlitherFinding, ...]
    skipped: str | None = None

    @property
    def ran(self) -> bool:
        """Whether Slither actually executed."""
        return self.skipped is None


def normalize_detector(raw: str) -> str:
    """Turn a Slither check name into a snake-cased detector name."""
    return raw.strip().lower().replace("-", "_").replace(" ", "_")


def normalize_severity(raw: str) -> str:
    """Map a Slither impact onto CyberStratum's severity scale."""
    return SEVERITY_MAP.get(raw.strip().lower(), "medium")


def vector_for(detector: str) -> str:
    """The shared risk-vector name for a detector."""
    return DETECTOR_TO_VECTOR.get(detector, detector)


def solc_version_from_string(compiler_version: str) -> str:
    """Extract a ``major.minor.patch`` version from a compiler string.

    Args:
        compiler_version: A compiler version as reported by the explorer,
            for example ``v0.8.26+commit.8a97fa7a``.

    Returns:
        The dotted version, or ``0.8.26`` when nothing usable was given.
    """
    cleaned = compiler_version.strip().lstrip("v").split("+")[0]
    parts = cleaned.split(".")
    if len(parts) >= 3 and all(p.isdigit() for p in parts[:3]):
        return f"{parts[0]}.{parts[1]}.{parts[2]}"
    if len(parts) == 2 and all(p.isdigit() for p in parts):
        return f"{parts[0]}.{parts[1]}.0"
    return "0.8.26"


def _candidate_solc_versions(compiler_version: str) -> list[str]:
    """The solc versions worth trying, most specific first."""
    wanted = solc_version_from_string(compiler_version)
    major, minor, patch = (int(p) for p in wanted.split("."))
    candidates = [
        f"{major}.{minor}.{patch}",
        f"{major}.{minor}.{max(0, patch - 1)}",
        f"{major}.{minor}",
    ]
    for version in FALLBACK_SOLC_VERSIONS:
        if version not in candidates:
            candidates.append(version)
    return candidates


class SlitherRunner:
    """Runs Slither as an external executable.

    The executable is never imported. It is located on disk and invoked with
    ``subprocess``, which is what keeps CyberStratum's own source outside
    Slither's AGPL copyleft.

    Attributes:
        executable: The path to the Slither executable, or ``None`` to
            search ``PATH`` and the environment.
        solc_artifacts: The directory holding the solc binaries.
        timeout: The wall-clock budget for one run.
    """

    def __init__(
        self,
        executable: str | None = None,
        solc_artifacts: str | None = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._executable = executable or os.environ.get(SLITHER_BIN_ENV) or ""
        self._solc_artifacts = Path(
            solc_artifacts
            or os.environ.get(SOLC_ARTIFACTS_ENV)
            or DEFAULT_SOLC_ARTIFACTS
        ).expanduser()
        self._timeout = timeout

    # -- discovery -------------------------------------------------------

    def find_executable(self) -> str | None:
        """Locate the Slither executable.

        Returns:
            The path, or ``None`` when it cannot be found. The
            ``SLITHER_BIN`` environment variable wins, then ``PATH``.
        """
        if self._executable:
            candidate = Path(self._executable)
            if candidate.is_file():
                return str(candidate)
            log.warning("SLITHER_BIN points at %s, which does not exist", candidate)
            return None
        return shutil.which("slither")

    @property
    def available(self) -> bool:
        """Whether Slither can be run at all."""
        return self.find_executable() is not None

    def find_solc(self, compiler_version: str = "") -> str | None:
        """Find a solc binary matching the contract's compiler version.

        solc-select stores each compiler in its own versioned directory::

            ~/.solc-select/artifacts/solc-0.8.26/solc-0.8.26

        Some setups use a flatter ``artifacts/0.8.26/`` layout, so both are
        searched.

        Args:
            compiler_version: The version the contract was compiled with.

        Returns:
            The path to the solc binary, or ``None`` when none is installed.
        """
        for version in _candidate_solc_versions(compiler_version):
            for directory in (f"solc-{version}", version):
                for name in (f"solc-{version}", f"solc-{version}.exe"):
                    candidate = self._solc_artifacts / directory / name
                    if candidate.is_file():
                        return str(candidate)
        return None

    # -- running ---------------------------------------------------------

    def build_command(
        self, source_path: str, solc_binary: str | None
    ) -> list[str]:
        """The argv used to run Slither.

        Kept separate so a test can assert the boundary holds: the command
        runs an executable and reads JSON, and never names a Python module
        of Slither's package.

        Args:
            source_path: The temporary file holding the source.
            solc_binary: The solc binary to use, if one was found.

        Returns:
            The argument vector.
        """
        executable = self.find_executable()
        if executable is None:
            raise SlitherUnavailableError("the Slither executable was not found")
        command = [executable, source_path, "--json", "-", "--disable-color"]
        if solc_binary:
            command.append(f"--solc={solc_binary}")
        return command

    def run(
        self,
        source_code: str,
        contract_name: str = "",
        compiler_version: str = "",
        extra_files: Mapping[str, str] | None = None,
    ) -> SlitherResult:
        """Analyse one contract's source.

        A missing Slither, a missing solc, or a source too short to be
        worth analysing are all reported as a skipped run rather than as
        an error: the caller has other work to do and a missing optional
        tool is not a failure of the contract.

        Args:
            source_code: The Solidity source.
            contract_name: The contract's name, used only in logs.
            compiler_version: The compiler version, used to pick solc.
            extra_files: The rest of the project, keyed by path. A contract
                that imports another file will not compile without them.

        Returns:
            The findings, or the reason the run was skipped.
        """
        if not source_code or len(source_code.strip()) < MIN_SOURCE_LENGTH:
            return SlitherResult(findings=(), skipped="source_too_short")

        executable = self.find_executable()
        if executable is None:
            return SlitherResult(findings=(), skipped="slither_not_installed")

        solc_binary = self.find_solc(compiler_version)
        if solc_binary is None:
            return SlitherResult(findings=(), skipped="solc_not_found")

        with tempfile.TemporaryDirectory(prefix="cyberstratum-slither-") as tmp:
            root = Path(tmp)
            source_path = root / f"{_safe_name(contract_name)}.sol"
            source_path.write_text(source_code, encoding="utf-8")

            # The imported files have to sit next to the main one, at the
            # paths the imports name, or the project will not compile.
            for path, content in (extra_files or {}).items():
                if not path or path == source_path.name:
                    continue
                try:
                    destination = (root / path).resolve()
                    destination.relative_to(root.resolve())
                except (ValueError, OSError):
                    # A path that escapes the temporary directory is
                    # refused rather than written.
                    log.warning("skipping a source file outside the project: %s", path)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding="utf-8")

            command = self.build_command(str(source_path), solc_binary)

            env = dict(os.environ)
            # crytic-compile finds solc through PATH.
            env["PATH"] = str(Path(solc_binary).parent) + os.pathsep + env.get("PATH", "")

            try:
                completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
                    command,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                    cwd=tmp,
                    env=env,
                )
            except subprocess.TimeoutExpired:
                log.warning("Slither timed out after %ss on %s", self._timeout, contract_name)
                return SlitherResult(findings=(), skipped="timeout")

        if not completed.stdout.strip():
            # No JSON at all. The common cause is a source that does not
            # compile -- slither then fails before it can report anything.
            # That is worth telling apart from "the contract is clean",
            # because one is a defect in the contract and the other is not.
            stderr = (completed.stderr or "").strip()
            if _looks_like_a_compilation_failure(stderr):
                log.info(
                    "Slither could not compile %s: %s",
                    contract_name,
                    stderr[:300],
                )
                return SlitherResult(findings=(), skipped="compilation_failed")
            log.info(
                "Slither produced no output for %s (exit %s): %s",
                contract_name,
                completed.returncode,
                stderr[:200],
            )
            return SlitherResult(findings=(), skipped="no_output")

        findings = parse_slither_json(completed.stdout)
        return SlitherResult(findings=findings)


#: Fragments that identify a compiler error in Slither's stderr.
_COMPILATION_FAILURE_MARKERS = (
    "compilation failed",
    "compilation error",
    "error: expected",
    "parsererror",
    "syntaxerror",
    "solc exited",
    "invalid solc",
    "solc was not found",
)


def _looks_like_a_compilation_failure(stderr: str) -> bool:
    """Whether Slither's stderr describes a compiler failure.

    Args:
        stderr: Slither's standard error.

    Returns:
        ``True`` when the source did not compile.
    """
    lowered = stderr.lower()
    return any(marker in lowered for marker in _COMPILATION_FAILURE_MARKERS)


def _safe_name(name: str) -> str:
    """A file-system-safe stem for a contract name."""
    cleaned = "".join(c if c.isalnum() or c in "_-" else "_" for c in name.strip())
    return cleaned[:80] or "contract"


def parse_slither_json(payload: str) -> tuple[SlitherFinding, ...]:
    """Normalise Slither's JSON output.

    Slither's format is ``{"success": true, "results": {"detectors": [...]}}``.
    A bare list of detectors is also accepted, because some versions and
    some failure modes emit that instead.

    Args:
        payload: The raw stdout.

    Returns:
        The normalised findings, empty when the payload is not usable.
    """
    try:
        parsed: Any = json.loads(payload)
    except json.JSONDecodeError:
        log.warning("Slither returned non-JSON output")
        return ()

    detectors: Any = parsed
    if isinstance(parsed, Mapping):
        results = parsed.get("results")
        if isinstance(results, Mapping):
            detectors = results.get("detectors", [])
        elif "success" in parsed:
            detectors = []
        else:
            detectors = parsed.get("detectors", [])
    if not isinstance(detectors, Sequence) or isinstance(detectors, (str, bytes)):
        return ()

    findings: list[SlitherFinding] = []
    for entry in detectors:
        if not isinstance(entry, Mapping):
            continue
        detector = normalize_detector(str(entry.get("check") or ""))
        if not detector:
            continue
        severity = normalize_severity(str(entry.get("impact") or "medium"))
        confidence = str(entry.get("confidence") or "medium").strip().lower()
        description = str(entry.get("description") or "")[:500]
        contract_path = str(entry.get("contract_path") or entry.get("check") or "")
        findings.append(
            SlitherFinding(
                detector=detector,
                severity=severity,
                confidence=confidence,
                description=description,
                vector=vector_for(detector),
                contract_path=contract_path,
            )
        )
    return tuple(findings)
