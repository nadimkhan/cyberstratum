"""Out-of-process Mythril runner (the symbolic engine).

Mythril is MIT-licensed, but it still runs *out of process*. Its pinned
``z3-solver`` has no clean path into this project's Python, so it lives in an
isolated environment (WSL: ``~/venvs/mythril``) and is invoked as an
unmodified external executable. Nothing here imports Mythril, vendors it, or
patches it; the JSON envelope is read across the process boundary. See
ADR-0013 (licensing posture) and ADR-0014 (multi-engine portfolio).

Three measured traps are encoded in this module, because each of them
produces a *confident wrong answer* rather than a visible error:

1. **The exit code is inverted.** Mythril exits ``1`` when it finds issues
   and ``0`` when it finds none. A runner that maps "non-zero exit" onto
   "the engine failed" throws away every genuine result. The verdict lives
   in the JSON envelope. The exit code is used here for exactly one thing:
   noticing that the process died without producing a verdict.

2. **Creation bytecode analysed as runtime yields a silent false clean.**
   ``--bin-runtime`` tells Mythril the input is deployed code. Hand it
   creation code and it analyses the constructor, finds no reachable exploit
   path, and returns ``{"error": null, "issues": [], "success": true}`` with
   exit ``0`` -- right shape, wrong question. The runner therefore takes the
   bytecode kind explicitly and refuses creation bytecode loudly with
   ``skipped="creation_bytecode_supplied"``.

3. **The envelope must be validated before the findings are trusted.**
   ``{"success": false, "error": "...", "issues": []}`` is an error, not a
   clean result. Only ``success: true`` with an empty ``issues`` array means
   "clean". Non-JSON output, a crash, a timeout and a missing binary are all
   "no verdict" -- never "clean".

Mythril is **manual only**. It is never part of the default scan: this
module is a runner that an on-demand action calls.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final

from app.core.logging import get_logger
from app.db.enums import Severity
from app.services.rules import RuleFinding

log = get_logger(__name__)

#: Environment variable holding the path to the Mythril executable.
MYTHRIL_BIN_ENV: Final[str] = "MYTHRIL_BIN"

#: The Mythril console script is ``myth``. There is no ``mythril`` binary in
#: the console-script directory, so ``myth`` is the name searched for.
DEFAULT_MYTHRIL_BINARY: Final[str] = "myth"

#: Default wall-clock budget for one Mythril run.
#:
#: Mythril is a deep-analysis engine: a small fixture takes ~19s, a 40-line
#: source-mode contract ~109s, and production-sized runtime bytecode has
#: been measured exceeding 850s. It is called on demand, with a budget.
DEFAULT_TIMEOUT_SECONDS: Final[int] = 300

#: Default solver budget, in milliseconds, handed to Mythril.
DEFAULT_SOLVER_TIMEOUT_MS: Final[int] = 20_000

#: Default execution budget, in milliseconds, handed to Mythril.
DEFAULT_EXECUTION_TIMEOUT_MS: Final[int] = 60_000

#: The confidence a Mythril finding carries.
#:
#: Mythril reports no confidence of its own. A symbolic-execution result
#: with a proven path is stronger than a static pattern, but the path was
#: not reproduced on the deployed bytecode, so it is not "certain" either.
MYTHRIL_CONFIDENCE: Final[float] = 0.6

#: Mythril's severity names mapped onto the platform's scale.
SEVERITY_MAP: Final[dict[str, str]] = {
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "informational": "info",
    "info": "info",
}

#: SWC identifiers mapped onto the platform's existing category vocabulary.
#:
#: The right-hand side is deliberately made of names that already exist
#: elsewhere in the product -- the bytecode rule categories from
#: :mod:`app.services.rules` and the source-engine risk vectors from
#: :mod:`app.services.source_audit` -- so a symbolic finding and a
#: bytecode finding of the same class compare equal in the unified
#: findings table. No new category names are invented here.
SWC_TO_CATEGORY: Final[dict[str, str]] = {
    "100": "accesscontrol",
    "101": "integer_overflow",
    "102": "formal_verification_gaps",
    "103": "formal_verification_gaps",
    "104": "unchecked_call",
    "105": "reentrancy_candidate",
    "106": "selfdestruct_usage",
    "107": "analysis_limitation",
    "108": "formal_verification_gaps",
    "109": "uninitialized_storage",
    "110": "analysis_limitation",
    "111": "formal_verification_gaps",
    "112": "delegatecall_usage",
    "113": "dos",
    "114": "frontrunning",
    "115": "tx_origin_dependency",
    "116": "unchecked_call",
    "117": "signature_replay",
    "118": "formal_verification_gaps",
    "119": "accesscontrol",
    "120": "price_manipulation",
    "121": "signature_replay",
    "122": "signature_replay",
    "123": "formal_verification_gaps",
    "124": "reentrancy_candidate",
    "125": "formal_verification_gaps",
    "126": "price_manipulation",
    "127": "analysis_limitation",
    "128": "dos",
    "129": "formal_verification_gaps",
    "130": "formal_verification_gaps",
    "131": "formal_verification_gaps",
    "132": "formal_verification_gaps",
    "133": "dos",
    "134": "dos",
    "135": "formal_verification_gaps",
    "136": "formal_verification_gaps",
    "137": "formal_verification_gaps",
    "138": "formal_verification_gaps",
    "139": "formal_verification_gaps",
}

#: The category an unrecognised SWC identifier falls back to.
#:
#: The SWC registry is larger than the table above and Mythril adds
#: identifiers of its own. An unknown id is not an error and must never
#: crash a scan: it is recorded under the existing catch-all category
#: that the source engine already uses for classes with no bytecode
#: counterpart, so the finding is stored and a reviewer can look at it.
GENERIC_CATEGORY: Final[str] = "formal_verification_gaps"

#: Bytecode kinds that mean "this is creation code".
CREATION_BYTECODE_KINDS: Final[frozenset[str]] = frozenset(
    {"creation", "init", "constructor", "deploy", "creation_code"}
)

#: The only bytecode kind Mythril may be given for a raw-runtime run.
RUNTIME_BYTECODE_KIND: Final[str] = "runtime"

#: Bytes that mark a Solidity metadata trailer inside a blob.
#:
#: The trailer carries the text key ``solc`` followed by a three-byte
#: version. Its *position* is the useful part: in runtime code the
#: trailer sits at the very end, while creation code embeds the runtime
#: code (trailer included) and then continues with constructor logic, so
#: the trailer is left behind in the middle of the blob.
_METADATA_SOLC_MARKER: Final[bytes] = b"\x64solc\x43"

#: How far from the end of the blob a metadata trailer may still be and
#: still count as "the trailer of this code".
_METADATA_TAIL_WINDOW: Final[int] = 64

#: The upper bound on a single finding's text, so a pathological payload
#: cannot blow up the findings table.
MAX_TEXT_LENGTH: Final[int] = 2_000


@dataclass(frozen=True, slots=True)
class MythrilFinding:
    """One issue reported by Mythril.

    Attributes:
        swc_id: The SWC identifier, normalised to its digits
            (``"105"`` for ``"SWC-105"``).
        title: The human-readable issue title.
        severity: Mythril's own severity name, lower-cased.
        description: The issue text.
        source_map: Mythril's source map, when it had one.
        code: The offending source snippet, when it had one.
        function_name: The function the issue was found in.
        lineno: The source line, when known.
        filename: The source file the issue was found in.
        tx_sequence: The exploit transaction sequence Mythril proved.
        extra: Every other field Mythril emitted, kept verbatim.
    """

    swc_id: str
    title: str = ""
    severity: str = "medium"
    description: str = ""
    source_map: str = ""
    code: str = ""
    function_name: str = ""
    lineno: int | None = None
    filename: str = ""
    tx_sequence: tuple[str, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MythrilResult:
    """The outcome of one Mythril run.

    The distinction this type exists to protect: *a run that found
    nothing* and *a run that learned nothing* are different facts, and
    only the first one is a clean contract.

    Attributes:
        findings: The issues Mythril reported.
        ran: Whether the Mythril process was actually invoked.
        skipped: The reason there is no verdict. Set whenever the run
            did not produce a usable answer -- a missing binary, a
            timeout, a crash, creation bytecode, a failed envelope.
        success: The envelope's own ``success`` flag, when there was an
            envelope to read.
        error: The engine's error message, when it gave one.
        exit_code: Mythril's exit code, when the process ran.
        duration_ms: How long the run took, in milliseconds.
    """

    findings: tuple[MythrilFinding, ...] = ()
    ran: bool = False
    skipped: str | None = None
    success: bool | None = None
    error: str | None = None
    exit_code: int | None = None
    duration_ms: int | None = None

    @property
    def clean(self) -> bool:
        """Whether Mythril ran and found nothing.

        True only when the process ran, the envelope said ``success``,
        and the issue list was empty. Every other outcome -- a skipped
        run, a failed envelope, a crash -- is *not* clean.
        """
        return self.ran and self.success is True and not self.findings and self.skipped is None

    @property
    def no_verdict(self) -> bool:
        """Whether the run produced no usable answer.

        True for a skipped run, a failed envelope, a crash, a timeout and
        a non-JSON payload. A run that produced issues is a verdict, so
        it is not "no verdict".
        """
        return self.skipped is not None or self.success is not True


def normalize_swc_id(raw: object) -> str:
    """Normalise a Mythril SWC identifier to its digits.

    Mythril emits ``"105"``; some versions emit ``"SWC-105"`` or ``105``.
    All three mean the same thing.

    Args:
        raw: The value Mythril reported.

    Returns:
        The digits of the identifier, or an empty string when there is
        no usable identifier.
    """
    text = str(raw or "").strip().upper()
    if text.startswith("SWC-"):
        text = text[4:]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits


def normalize_severity(raw: object) -> str:
    """Map Mythril's severity name onto the platform's scale.

    Args:
        raw: The severity Mythril reported.

    Returns:
        One of ``critical``/``high``/``medium``/``low``/``info``. An
        unknown severity becomes ``medium``; it does not get to invent
        one.
    """
    return SEVERITY_MAP.get(str(raw or "").strip().lower(), "medium")


def category_for_swc(swc_id: str) -> str:
    """The platform category for a SWC identifier.

    Args:
        swc_id: A SWC identifier, with or without the ``SWC-`` prefix.

    Returns:
        The category name, or the generic category for an identifier
        that is not in the table. Never raises.
    """
    key = normalize_swc_id(swc_id)
    return SWC_TO_CATEGORY.get(key, GENERIC_CATEGORY)


def _severity_for(severity: str) -> Severity:
    """Map a severity name onto the enum, falling back to medium."""
    try:
        return Severity(severity.strip().lower())
    except ValueError:
        return Severity.MEDIUM


def _text(value: object) -> str:
    """A bounded, human-readable string for a JSON value."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    if isinstance(value, Mapping):
        return json.dumps(value, default=str)[:MAX_TEXT_LENGTH]
    return str(value)[:MAX_TEXT_LENGTH]


def _parse_issue(entry: Mapping[str, Any]) -> MythrilFinding | None:
    """Normalise one entry of Mythril's ``issues`` array.

    Args:
        entry: The raw issue mapping.

    Returns:
        The normalised finding, or ``None`` when the entry carries no
        SWC identifier (an issue with no identity is not reportable).
    """
    swc_id = normalize_swc_id(entry.get("swc-id") or entry.get("swcId") or entry.get("swc_id"))
    if not swc_id:
        return None

    title = _text(entry.get("swc-title") or entry.get("swcTitle") or entry.get("title"))
    severity = normalize_severity(entry.get("severity"))

    lineno_value = entry.get("lineno")
    lineno: int | None
    if isinstance(lineno_value, int):
        lineno = lineno_value
    elif isinstance(lineno_value, str) and lineno_value.strip().isdigit():
        lineno = int(lineno_value.strip())
    else:
        lineno = None

    raw_sequence = entry.get("tx_sequence")
    sequence: tuple[str, ...] = ()
    if isinstance(raw_sequence, Sequence) and not isinstance(raw_sequence, (str, bytes)):
        sequence = tuple(_text(item) for item in raw_sequence)

    known = {
        "swc-id",
        "swcId",
        "swc_id",
        "swc-title",
        "swcTitle",
        "title",
        "severity",
        "description",
        "head",
        "sourceMap",
        "source_map",
        "code",
        "function",
        "function_name",
        "lineno",
        "line",
        "filename",
        "file",
        "tx_sequence",
    }
    extra = {key: value for key, value in entry.items() if key not in known}

    return MythrilFinding(
        swc_id=swc_id,
        title=title,
        severity=severity,
        description=_text(entry.get("description") or entry.get("head")),
        source_map=_text(entry.get("sourceMap") or entry.get("source_map")),
        code=_text(entry.get("code")),
        function_name=_text(entry.get("function") or entry.get("function_name")),
        lineno=lineno,
        filename=_text(entry.get("filename") or entry.get("file")),
        tx_sequence=sequence,
        extra=extra,
    )


def parse_mythril_envelope(payload: str | bytes, exit_code: int | None) -> MythrilResult:
    """Parse Mythril's JSON envelope into a result.

    This is the heart of the module and is deliberately a *pure*
    function: it takes the raw stdout and the exit code and says what
    was learned. It never runs Mythril, so every branch of it is
    unit-testable without Mythril installed.

    The rules it encodes, in order:

    * the envelope is validated *before* the issues are trusted;
    * ``success: false`` with an error is an error, even when the issue
      list is empty -- an empty list is not a clean contract unless the
      envelope said ``success``;
    * ``success: true`` with an empty issue list is a genuine clean
      verdict;
    * a non-JSON payload, an empty payload, or a payload that is not an
      object is "no verdict";
    * the exit code is **not** a verdict. Exit ``1`` means issues were
      found, and exit ``0`` does not mean the contract is clean. The
      exit code is only ever used to notice that the process died.

    Args:
        payload: The raw stdout of the Mythril process.
        exit_code: Mythril's exit code, when the process ran.

    Returns:
        The parsed result. Never raises.
    """
    if isinstance(payload, bytes | bytearray):
        text = payload.decode("utf-8", errors="replace")
    else:
        text = payload or ""

    stripped = text.strip()
    if not stripped:
        # Nothing at all came back. Exit 0 and exit 1 both mean Mythril
        # had something to say; any other code means it died.
        reason = "no_output" if exit_code in (None, 0, 1) else "engine_crash"
        return MythrilResult(
            findings=(),
            ran=True,
            skipped=reason,
            success=None,
            error=None,
            exit_code=exit_code,
        )

    try:
        parsed: Any = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        log.warning("mythril returned non-JSON output")
        return MythrilResult(
            findings=(),
            ran=True,
            skipped="non_json_output",
            success=None,
            error=None,
            exit_code=exit_code,
        )

    if not isinstance(parsed, Mapping):
        return MythrilResult(
            findings=(),
            ran=True,
            skipped="unusable_output",
            success=None,
            error=None,
            exit_code=exit_code,
        )

    raw_error = parsed.get("error")
    error = _text(raw_error) if raw_error else None

    if "success" not in parsed or "issues" not in parsed:
        # Not the documented envelope shape. Nothing may be inferred
        # from it.
        return MythrilResult(
            findings=(),
            ran=True,
            skipped="unusable_output",
            success=None,
            error=error,
            exit_code=exit_code,
        )

    success = bool(parsed.get("success"))

    if not success:
        # The engine said it failed. This is the "compiler not found"
        # trap from ADR-0014: a well-formed envelope with an empty issue
        # list, which reads as "clean" to anything that only looks at
        # the issues. It is an error, and the error is surfaced.
        return MythrilResult(
            findings=(),
            ran=True,
            skipped="engine_error",
            success=False,
            error=error or "mythril reported failure without a message",
            exit_code=exit_code,
        )

    raw_issues = parsed.get("issues")
    if not isinstance(raw_issues, Sequence) or isinstance(raw_issues, (str, bytes)):
        return MythrilResult(
            findings=(),
            ran=True,
            skipped="unusable_output",
            success=None,
            error=error,
            exit_code=exit_code,
        )

    findings: list[MythrilFinding] = []
    for entry in raw_issues:
        if not isinstance(entry, Mapping):
            continue
        parsed_finding = _parse_issue(entry)
        if parsed_finding is not None:
            findings.append(parsed_finding)

    return MythrilResult(
        findings=tuple(findings),
        ran=True,
        skipped=None,
        success=True,
        error=error,
        exit_code=exit_code,
    )


def looks_like_creation_bytecode(
    bytecode: bytes, deployed_runtime_length: int | None = None
) -> bool:
    """Whether a blob looks like creation code rather than runtime code.

    **This is a heuristic and heuristics are heuristics.** It is used to
    refuse the one input that produces a silent false clean, and it is
    deliberately biased towards refusing a run over analysing the wrong
    code. A false refusal costs a re-run; a false clean is a lie about
    a contract.

    Two signals are used:

    * *Length.* Creation code embeds the runtime code and adds the
      constructor on top, so it is longer. Measured on the platform's
      reentrancy fixture: 910 hex characters of creation code against
      854 of runtime code. When the deployed runtime length is known,
      a blob of a different length is not that runtime.
    * *Metadata position.* Solidity appends a CBOR metadata trailer to
      runtime code, and creation code embeds that runtime code -- trailer
      and all -- before the constructor logic that follows it, and then
      appends a trailer of its own. So in creation code the ``solc``
      metadata marker appears twice (once for the embedded runtime's
      trailer, once for creation code's own); in runtime code it appears
      once, in the last few dozen bytes.

    Args:
        bytecode: The blob to inspect.
        deployed_runtime_length: The length of the deployed runtime, when
            the caller knows it.

    Returns:
        ``True`` when the blob looks like creation code.
    """
    if not bytecode:
        return False

    if deployed_runtime_length is not None and len(bytecode) != deployed_runtime_length:
        return True

    markers = _metadata_marker_offsets(bytecode)
    if len(markers) >= 2:
        # Creation code carries the runtime code -- metadata trailer
        # included -- inside it, and then appends a trailer of its own.
        # Runtime code carries exactly one.
        return True
    if not markers:
        # No metadata trailer at all. That is normal for hand-written or
        # stripped code, so it says nothing on its own.
        return False

    trailing = len(bytecode) - (markers[0] + len(_METADATA_SOLC_MARKER))
    return trailing > _METADATA_TAIL_WINDOW


def _metadata_marker_offsets(bytecode: bytes) -> list[int]:
    """Every offset at which the Solidity metadata marker appears.

    Args:
        bytecode: The blob to scan.

    Returns:
        The offsets of the marker, in order.
    """
    offsets: list[int] = []
    start = 0
    while True:
        index = bytecode.find(_METADATA_SOLC_MARKER, start)
        if index == -1:
            return offsets
        offsets.append(index)
        start = index + len(_METADATA_SOLC_MARKER)


class MythrilUnavailableError(RuntimeError):
    """Mythril is not installed, or the executable could not be found."""


class MythrilRunner:
    """Runs Mythril as an external executable.

    The executable is never imported. It is located on disk and invoked
    with ``subprocess``, which is what keeps Mythril's environment (and
    its pinned z3) out of this application's interpreter.

    Attributes:
        executable: The path to the Mythril executable, or ``None`` to
            search ``PATH`` for ``myth``.
        timeout: The wall-clock budget for one run.
        solver_timeout_ms: The solver budget handed to Mythril.
        execution_timeout_ms: The execution budget handed to Mythril.
    """

    def __init__(
        self,
        executable: str | None = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        solver_timeout_ms: int = DEFAULT_SOLVER_TIMEOUT_MS,
        execution_timeout_ms: int = DEFAULT_EXECUTION_TIMEOUT_MS,
    ) -> None:
        self._executable = executable or os.environ.get(MYTHRIL_BIN_ENV) or ""
        self._timeout = timeout
        self._solver_timeout_ms = solver_timeout_ms
        self._execution_timeout_ms = execution_timeout_ms

    # -- discovery -------------------------------------------------------

    def find_executable(self) -> str | None:
        """Locate the Mythril executable.

        The console script is ``myth``. There is no ``mythril`` binary,
        so that name is never searched for: pointing the runner at
        ``bin/mythril`` is a missing-file error, and a missing tool is a
        skip, not a crash.

        Returns:
            The path, or ``None`` when it cannot be found. The
            ``MYTHRIL_BIN`` environment variable wins, then ``PATH``.
        """
        if self._executable:
            candidate = Path(self._executable).expanduser()
            if candidate.is_file():
                return str(candidate)
            log.warning(
                "mythril_bin points at %s, which does not exist",
                str(candidate),
            )
            return None
        return shutil.which(DEFAULT_MYTHRIL_BINARY)

    @property
    def available(self) -> bool:
        """Whether Mythril can be run at all."""
        return self.find_executable() is not None

    # -- running ---------------------------------------------------------

    def build_command(
        self,
        bytecode_path: str,
        solver_timeout_ms: int | None = None,
        execution_timeout_ms: int | None = None,
    ) -> list[str]:
        """The argv used to run Mythril.

        Kept separate so a test can assert the boundary holds: the
        command runs an executable and reads JSON, and never names a
        Python module of Mythril's package.

        Args:
            bytecode_path: The temporary file holding the runtime
                bytecode, as pure hex.
            solver_timeout_ms: The solver budget, when it differs from
                the runner's default.
            execution_timeout_ms: The execution budget, when it differs
                from the runner's default.

        Returns:
            The argument vector.

        Raises:
            MythrilUnavailableError: When the executable cannot be
                found.
        """
        executable = self.find_executable()
        if executable is None:
            raise MythrilUnavailableError("the myth executable was not found")
        solver = self._solver_timeout_ms if solver_timeout_ms is None else solver_timeout_ms
        execution = (
            self._execution_timeout_ms if execution_timeout_ms is None else execution_timeout_ms
        )
        return [
            executable,
            "analyze",
            "-f",
            bytecode_path,
            "--bin-runtime",
            "--solver-timeout",
            str(solver),
            "--execution-timeout",
            str(execution),
            "--no-onchain-data",
            "-o",
            "json",
        ]

    def run(
        self,
        runtime_bytecode: bytes,
        contract_name: str = "",
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        solver_timeout_ms: int = DEFAULT_SOLVER_TIMEOUT_MS,
        bytecode_kind: str = RUNTIME_BYTECODE_KIND,
        deployed_runtime_length: int | None = None,
    ) -> MythrilResult:
        """Analyse one contract's *runtime* bytecode.

        Args:
            runtime_bytecode: The deployed runtime bytecode.
            contract_name: The contract's name, used only in logs and
                for naming the temporary file.
            timeout_seconds: The wall-clock budget for this run.
            solver_timeout_ms: The solver budget handed to Mythril.
            bytecode_kind: What the supplied bytes are. Anything other
                than ``"runtime"`` is refused: analysing creation code
                as runtime yields a silent false clean.
            deployed_runtime_length: The length of the deployed runtime,
                when the caller knows it. Used as an extra creation-code
                check.

        Returns:
            The result. A missing binary, a timeout, a crash, creation
            bytecode and a failed envelope all come back as a result
            with no verdict; nothing raises out of here.
        """
        kind = str(bytecode_kind or "").strip().lower()
        if kind in CREATION_BYTECODE_KINDS:
            log.warning("mythril refused creation bytecode for %s", contract_name or "<unnamed>")
            return MythrilResult(
                findings=(),
                ran=False,
                skipped="creation_bytecode_supplied",
                success=None,
                error=(
                    "creation bytecode was supplied; mythril must be given the "
                    "deployed runtime bytecode"
                ),
            )
        if kind != RUNTIME_BYTECODE_KIND:
            return MythrilResult(
                findings=(),
                ran=False,
                skipped="unsupported_bytecode_kind",
                success=None,
                error=f"unsupported bytecode kind: {bytecode_kind!r}",
            )

        if not runtime_bytecode:
            return MythrilResult(
                findings=(),
                ran=False,
                skipped="empty_bytecode",
                success=None,
                error="no bytecode was supplied",
            )

        if looks_like_creation_bytecode(runtime_bytecode, deployed_runtime_length):
            log.warning(
                "mythril refused bytecode for %s: it looks like creation code",
                contract_name or "<unnamed>",
            )
            return MythrilResult(
                findings=(),
                ran=False,
                skipped="creation_bytecode_supplied",
                success=None,
                error=(
                    "the supplied bytecode looks like creation code; analysing it "
                    "as runtime would produce a false clean result"
                ),
            )

        executable = self.find_executable()
        if executable is None:
            return MythrilResult(
                findings=(),
                ran=False,
                skipped="mythril_not_installed",
                success=None,
                error=None,
            )

        with tempfile.TemporaryDirectory(prefix="cyberstratum-mythril-") as tmp:
            root = Path(tmp)
            bytecode_path = root / f"{_safe_name(contract_name)}.hex"
            # Pure hex: no "0x" prefix, no trailing newline, no other
            # text. A stray prefix or trailing characters once made
            # Mythril analyse nothing at all.
            bytecode_path.write_text(runtime_bytecode.hex(), encoding="ascii")

            command = self.build_command(
                str(bytecode_path),
                solver_timeout_ms=solver_timeout_ms,
            )

            env = dict(os.environ)
            started = time.monotonic()
            try:
                completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
                    command,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    cwd=tmp,
                    env=env,
                )
            except subprocess.TimeoutExpired:
                duration_ms = int((time.monotonic() - started) * 1000)
                log.warning(
                    "mythril timed out after %ss on %s",
                    timeout_seconds,
                    contract_name or "<unnamed>",
                )
                return MythrilResult(
                    findings=(),
                    ran=True,
                    skipped="timeout",
                    success=None,
                    error=None,
                    exit_code=None,
                    duration_ms=duration_ms,
                )
            except OSError as exc:
                duration_ms = int((time.monotonic() - started) * 1000)
                log.warning(
                    "mythril could not be executed on %s: %s",
                    contract_name or "<unnamed>",
                    exc,
                )
                return MythrilResult(
                    findings=(),
                    ran=False,
                    skipped="engine_error",
                    success=None,
                    error=str(exc),
                    exit_code=None,
                    duration_ms=duration_ms,
                )

        duration_ms = int((time.monotonic() - started) * 1000)
        result = parse_mythril_envelope(completed.stdout, completed.returncode)
        return replace(result, duration_ms=duration_ms)


def to_rule_finding(finding: MythrilFinding) -> RuleFinding:
    """Convert one Mythril issue into the shared finding shape.

    Args:
        finding: The normalised Mythril issue.

    Returns:
        The same issue, in the shape the bytecode rule engine and the
        source engine produce, so the unified findings table can hold
        all three side by side.
    """
    category = category_for_swc(finding.swc_id)
    detector = f"swc_{finding.swc_id}" if finding.swc_id else "swc_unknown"

    title = finding.title or f"Mythril {finding.swc_id or 'finding'}"
    description = finding.description or title

    evidence: dict[str, Any] = {
        "swcId": finding.swc_id,
        "sourceEngine": "mythril",
        "category": category,
    }
    if finding.source_map:
        evidence["sourceMap"] = finding.source_map
    if finding.code:
        evidence["code"] = finding.code
    if finding.function_name:
        evidence["function"] = finding.function_name
    if finding.lineno is not None:
        evidence["lineno"] = finding.lineno
    if finding.filename:
        evidence["filename"] = finding.filename
    if finding.tx_sequence:
        evidence["txSequence"] = list(finding.tx_sequence)
    if finding.extra:
        evidence["mythrilFields"] = dict(finding.extra)

    return RuleFinding(
        detector_id=f"mythril.{detector}",
        category=category,
        title=title,
        description=description,
        severity=_severity_for(normalize_severity(finding.severity)),
        confidence=MYTHRIL_CONFIDENCE,
        evidence=evidence,
        limitations=(
            "Symbolic-execution result from Mythril. The exploit path was not "
            "independently reproduced on the deployed bytecode, and reachability "
            "was not proven against the deployed state."
        ),
    )


def to_rule_findings(findings: Iterable[MythrilFinding]) -> tuple[RuleFinding, ...]:
    """Convert a batch of Mythril issues into the shared finding shape.

    Args:
        findings: The normalised Mythril issues.

    Returns:
        The findings, in the shared shape.
    """
    return tuple(to_rule_finding(finding) for finding in findings)


def _safe_name(name: str) -> str:
    """A file-system-safe stem for a contract name."""
    cleaned = "".join(c if c.isalnum() or c in "_-" else "_" for c in name.strip())
    return cleaned[:80] or "contract"


__all__ = [
    "CREATION_BYTECODE_KINDS",
    "DEFAULT_EXECUTION_TIMEOUT_MS",
    "DEFAULT_MYTHRIL_BINARY",
    "DEFAULT_SOLVER_TIMEOUT_MS",
    "DEFAULT_TIMEOUT_SECONDS",
    "GENERIC_CATEGORY",
    "MYTHRIL_BIN_ENV",
    "MYTHRIL_CONFIDENCE",
    "RUNTIME_BYTECODE_KIND",
    "SEVERITY_MAP",
    "SWC_TO_CATEGORY",
    "MythrilFinding",
    "MythrilResult",
    "MythrilRunner",
    "MythrilUnavailableError",
    "category_for_swc",
    "looks_like_creation_bytecode",
    "normalize_severity",
    "normalize_swc_id",
    "parse_mythril_envelope",
    "to_rule_finding",
    "to_rule_findings",
]
