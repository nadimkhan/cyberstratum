"""Prove that a source file describes a deployed bytecode.

This is the productised form of ``scripts/live_check_correspondence.py``. The
script proved the idea against a live contract; this module makes the proof a
reusable, stored, first-class piece of evidence.

The chain of reasoning is deliberately narrow, because a disclosure report may
not contain a guess:

1. Fetch the verification record from Sourcify, which carries the exact
   standard-JSON compiler input the contract was verified with.
2. Recompile that exact input with the same ``solc``.
3. Require the recompiled **executable code** to be byte-identical to the
   deployed runtime. The metadata trailer is separated before the comparison,
   because it is non-executable and its content hash legitimately differs
   between two otherwise identical builds.
4. Only then apply the compiler's own source map to the deployed runtime, so
   a bytecode offset can be read off as a file and line.

If step 3 fails, no source line may be claimed. If the compiler cannot be run
at all, then *nothing* was learned, and that is recorded as "unavailable" -
never as a mismatch. A mismatch is an accusation; a broken compiler is not
evidence for one.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.db.enums import CorrespondenceStatus
from evm_analysis import disassemble, load_fork, split_metadata

#: Where Sourcify's per-contract verification records live.
SOURCIFY_URL_TEMPLATE = "https://sourcify.dev/server/v2/contract/{chain}/{address}?fields=all"

#: The output selection this proof needs, injected when Sourcify omits it.
OUTPUT_SELECTION: dict[str, dict[str, list[str]]] = {
    "*": {"*": ["evm.deployedBytecode.object", "evm.deployedBytecode.sourceMap"]}
}

#: The opcodes worth recording, because they are what a finding would report.
INTERESTING_OPCODES = frozenset(
    {
        "CALL",
        "DELEGATECALL",
        "STATICCALL",
        "SELFDESTRUCT",
        "SSTORE",
        "CREATE",
        "CREATE2",
    }
)

#: How long the compiler is given before it is treated as hung.
DEFAULT_COMPILE_TIMEOUT_SECONDS = 600


class RecompileError(RuntimeError):
    """The compiler could not be run, so the check could not be performed.

    This is deliberately distinct from a *mismatch*. A mismatch means the
    check ran and the source does not describe the deployed contract. A
    compiler that hangs or crashes means nothing was learned either way, and
    reporting it as a mismatch would be a false accusation.
    """


@dataclass(frozen=True)
class SourceLocation:
    """A bytecode offset tied to an exact source line.

    Attributes:
        offset: The byte offset in the deployed runtime.
        opcode: The opcode name at that offset.
        file: The source file the compiler mapped it to.
        line: The line number in that file.
        snippet: The source text the compiler mapped it to.
    """

    offset: int
    opcode: str
    file: str
    line: int
    snippet: str


@dataclass(frozen=True)
class CorrespondenceOutcome:
    """The result of a correspondence check.

    The status is the whole point. ``established`` is the only status that
    licenses a source line; ``skipped`` and ``unavailable`` mean nothing was
    proven, and ``mismatch`` means the source demonstrably describes a
    different contract.
    """

    status: CorrespondenceStatus
    detail: str = ""
    skipped: str | None = None
    compiler_version: str | None = None
    source_path: str | None = None
    contract_name: str | None = None
    runtime_sha256: str | None = None
    executable_sha256: str | None = None
    metadata_sha256: str | None = None
    runtime_byte_size: int | None = None
    executable_byte_size: int | None = None
    instruction_count: int | None = None
    mapped_instruction_count: int | None = None
    locations: tuple[SourceLocation, ...] = field(default_factory=tuple)

    @property
    def established(self) -> bool:
        """Whether a source line may be claimed."""
        return self.status is CorrespondenceStatus.ESTABLISHED

    def to_evidence(self) -> dict[str, Any]:
        """Render the outcome as the JSON payload stored with the scan.

        Returns:
            A JSON-serialisable mapping of the outcome.
        """
        return {
            "status": self.status.value,
            "detail": self.detail,
            "skipped": self.skipped,
            "compilerVersion": self.compiler_version,
            "sourcePath": self.source_path,
            "contractName": self.contract_name,
            "runtimeSha256": self.runtime_sha256,
            "executableSha256": self.executable_sha256,
            "metadataSha256": self.metadata_sha256,
            "runtimeByteSize": self.runtime_byte_size,
            "executableByteSize": self.executable_byte_size,
            "instructionCount": self.instruction_count,
            "mappedInstructionCount": self.mapped_instruction_count,
            "locations": [
                {
                    "offset": location.offset,
                    "opcode": location.opcode,
                    "file": location.file,
                    "line": location.line,
                    "snippet": location.snippet,
                }
                for location in self.locations
            ],
        }


def sha256_hex(data: bytes) -> str:
    """Return the lowercase hex SHA-256 of ``data``.

    Args:
        data: The bytes to hash.

    Returns:
        The hex digest.
    """
    return hashlib.sha256(data).hexdigest()


def expand_source_map(entries: list[str]) -> list[tuple[int, int] | None]:
    """Expand solc's compressed source map into a range per instruction.

    An empty field inherits the previous value, and a wholly empty entry
    inherits everything. This was verified empirically against solc's own
    output.

    Args:
        entries: The semicolon-separated source map entries.

    Returns:
        One ``(start, length)`` pair per instruction, or ``None`` where the
        source map says nothing.
    """
    resolved: list[tuple[int, int] | None] = []
    start: int | None = None
    length: int | None = None
    for entry in entries:
        fields = entry.split(":")
        raw_start = fields[0] if fields else ""
        raw_length = fields[1] if len(fields) > 1 else ""
        if raw_start not in {"", "-"}:
            start = int(raw_start)
        if raw_length not in {"", "-"}:
            length = int(raw_length)
        resolved.append(None if start is None or length is None else (start, length))
    return resolved


def compare_runtime(onchain: bytes, recompiled: bytes) -> tuple[bool, str]:
    """Compare two runtimes by executable code.

    The metadata trailer is separated first. It is non-executable, so a
    difference in it does not mean the source describes a different contract;
    the difference is reported rather than hidden.

    Args:
        onchain: The deployed runtime.
        recompiled: The recompiled runtime.

    Returns:
        Whether the executable code matches, and an explanation.
    """
    if onchain == recompiled:
        return True, "whole runtime is byte-identical (metadata included)"

    onchain_exec, onchain_meta = split_metadata(onchain)
    recompiled_exec, recompiled_meta = split_metadata(recompiled)

    if onchain_exec != recompiled_exec:
        first_difference: int | None = None
        for index, (left, right) in enumerate(zip(onchain_exec, recompiled_exec, strict=False)):
            if left != right:
                first_difference = index
                break
        if first_difference is None:
            detail = (
                f"length differs: on-chain {len(onchain_exec)} bytes vs "
                f"recompiled {len(recompiled_exec)} bytes"
            )
        else:
            detail = (
                f"first differing byte at offset 0x{first_difference:x} "
                f"(on-chain 0x{onchain_exec[first_difference]:02x} vs "
                f"recompiled 0x{recompiled_exec[first_difference]:02x}); "
                f"{len(onchain_exec)} vs {len(recompiled_exec)} bytes"
            )
        return False, f"executable code differs -> {detail}"

    note = "executable code identical"
    if (
        onchain_meta is not None
        and recompiled_meta is not None
        and onchain_meta.raw != recompiled_meta.raw
    ):
        note += (
            f"; metadata trailer differs ({len(onchain_meta.raw)} vs "
            f"{len(recompiled_meta.raw)} bytes) - metadata is non-executable, "
            "so this does not break correspondence"
        )
    return True, note


def find_solc(version: str, artifacts_dir: str | None = None) -> Path | None:
    """Locate a solc binary.

    The same search the product's Slither runner performs, so both agree on
    which compiler a given contract was built with: the ``solc-select``
    layout under ``SOLC_ARTIFACTS_DIR``, and the flatter ``<version>/``
    layout some setups use.

    Args:
        version: The compiler version, such as ``0.4.24``.
        artifacts_dir: The compiler artifacts directory. Defaults to the
            ``SOLC_ARTIFACTS_DIR`` environment variable.

    Returns:
        The path to the compiler, or ``None`` when it is not installed.
    """
    root = artifacts_dir or os.environ.get("SOLC_ARTIFACTS_DIR", "~/.solc-select/artifacts")
    artifacts = Path(root).expanduser()
    for directory in (f"solc-{version}", version):
        for name in (f"solc-{version}", f"solc-{version}.exe"):
            candidate = artifacts / directory / name
            if candidate.is_file():
                return candidate
    return None


def recompile(
    std_json: str, solc: Path, timeout: float = DEFAULT_COMPILE_TIMEOUT_SECONDS
) -> dict[str, Any]:
    """Recompile a standard-JSON input.

    Args:
        std_json: The standard-JSON input.
        solc: The compiler to use.
        timeout: How long the compiler is given, in seconds.

    Returns:
        The compiler's JSON output.

    Raises:
        RecompileError: The compiler timed out, crashed, or emitted
            something that is not JSON.
    """
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [str(solc), "--standard-json"],
            input=std_json,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RecompileError(f"solc did not finish within {timeout:g}s") from exc
    except OSError as exc:
        raise RecompileError(f"solc could not be run: {exc}") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        tail = detail[-1] if detail else "no error output"
        raise RecompileError(f"solc exited with {completed.returncode}: {tail}")

    try:
        output = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RecompileError(f"solc did not emit JSON: {exc}") from exc
    if not isinstance(output, dict):
        raise RecompileError("solc returned a non-object")
    return output


def prepare_standard_json(raw_input: Any) -> tuple[str, bool, list[str]]:
    """Turn Sourcify's stored compiler input into one solc will compile.

    Sourcify stores the compiler settings but **no** ``outputSelection``.
    solc then emits no bytecode at all, which looks exactly like a failed
    correspondence check. The selection is injected without touching any
    other setting, so the recompilation still uses the verification's own
    compiler options.

    Args:
        raw_input: The stored ``stdJsonInput``.

    Returns:
        The standard-JSON text, whether the selection had to be injected,
        and the names of any sources that are referenced by URL rather than
        supplied inline.
    """
    document = raw_input if isinstance(raw_input, dict) else json.loads(str(raw_input))
    settings = document.setdefault("settings", {})
    injected = False
    if not settings.get("outputSelection"):
        settings["outputSelection"] = OUTPUT_SELECTION
        injected = True
    fetched = [
        name
        for name, body in (document.get("sources") or {}).items()
        if isinstance(body, dict) and body.get("urls") and not body.get("content")
    ]
    return json.dumps(document), injected, fetched


class CorrespondenceProver:
    """Prove that a source file describes a deployed runtime.

    The class is deliberately free of database and framework dependencies, so
    the proof can be exercised without either. The worker persists the
    outcome; the prover only produces it.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 60.0,
        compile_timeout_seconds: float = DEFAULT_COMPILE_TIMEOUT_SECONDS,
        artifacts_dir: str | None = None,
        user_agent: str = "cyberstratum-verification",
        fork: str = "shanghai",
    ) -> None:
        """Create a prover.

        Args:
            timeout_seconds: How long an HTTP request is given.
            compile_timeout_seconds: How long the compiler is given.
            artifacts_dir: Where compilers live.
            user_agent: The User-Agent sent to Sourcify.
            fork: The EVM fork used to disassemble the runtime.
        """
        self.timeout_seconds = timeout_seconds
        self.compile_timeout_seconds = compile_timeout_seconds
        self.artifacts_dir = artifacts_dir
        self.user_agent = user_agent
        self.fork = fork

    def _fetch_json(self, client: httpx.Client, url: str) -> dict[str, Any]:
        """Fetch and decode a JSON document.

        Args:
            client: The HTTP client.
            url: The URL to fetch.

        Returns:
            The decoded document.
        """
        response = client.get(url, headers={"User-Agent": self.user_agent})
        response.raise_for_status()
        decoded = response.json()
        if not isinstance(decoded, dict):
            raise ValueError("expected a JSON object")
        return decoded

    def _fetch_document(self, address: str, chain_id: str) -> dict[str, Any]:
        """Fetch the verification record for one contract.

        Args:
            address: The contract address.
            chain_id: The chain id, as a string.

        Returns:
            The decoded Sourcify document.
        """
        with httpx.Client(timeout=self.timeout_seconds) as client:
            return self._fetch_json(
                client,
                SOURCIFY_URL_TEMPLATE.format(chain=chain_id, address=address),
            )

    def prove(
        self,
        address: str,
        chain_id: str,
        runtime_bytecode: bytes,
    ) -> CorrespondenceOutcome:
        """Prove, or fail to prove, the correspondence for one contract.

        Args:
            address: The contract address.
            chain_id: The chain id, as a string.
            runtime_bytecode: The deployed runtime bytecode.

        Returns:
            The outcome. Only an ``established`` outcome licenses a source
            line.
        """
        runtime_sha = sha256_hex(runtime_bytecode)
        runtime_exec, runtime_meta = split_metadata(runtime_bytecode)
        executable_sha = sha256_hex(runtime_exec)
        metadata_sha = sha256_hex(runtime_meta.raw) if runtime_meta is not None else None

        try:
            document = self._fetch_document(address, chain_id)
        except (httpx.HTTPError, OSError, ValueError) as exc:
            return CorrespondenceOutcome(
                status=CorrespondenceStatus.UNAVAILABLE,
                skipped="verification_record_unreachable",
                detail=f"The verification record could not be fetched: {exc}"[:300],
                runtime_sha256=runtime_sha,
                executable_sha256=executable_sha,
                metadata_sha256=metadata_sha,
                runtime_byte_size=len(runtime_bytecode),
                executable_byte_size=len(runtime_exec),
            )

        compilation = document.get("compilation") or {}
        compiler_version = str(compilation.get("compilerVersion") or "") or None

        raw_input = document.get("stdJsonInput")
        if not raw_input:
            return CorrespondenceOutcome(
                status=CorrespondenceStatus.SKIPPED,
                skipped="no_standard_json_input",
                detail="The verification record carries no standard-JSON input.",
                compiler_version=compiler_version,
                runtime_sha256=runtime_sha,
                executable_sha256=executable_sha,
                metadata_sha256=metadata_sha,
                runtime_byte_size=len(runtime_bytecode),
                executable_byte_size=len(runtime_exec),
            )

        try:
            std_json, _injected, _fetched = prepare_standard_json(raw_input)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            return CorrespondenceOutcome(
                status=CorrespondenceStatus.UNAVAILABLE,
                skipped="standard_json_unreadable",
                detail=f"The stored compiler input could not be read: {exc}"[:300],
                compiler_version=compiler_version,
                runtime_sha256=runtime_sha,
                executable_sha256=executable_sha,
                metadata_sha256=metadata_sha,
                runtime_byte_size=len(runtime_bytecode),
                executable_byte_size=len(runtime_exec),
            )

        short_version = (compiler_version or "").split("+")[0].strip()
        if not short_version:
            return CorrespondenceOutcome(
                status=CorrespondenceStatus.SKIPPED,
                skipped="no_compiler_version",
                detail="The verification record names no compiler version.",
                runtime_sha256=runtime_sha,
                executable_sha256=executable_sha,
                metadata_sha256=metadata_sha,
                runtime_byte_size=len(runtime_bytecode),
                executable_byte_size=len(runtime_exec),
            )

        solc = find_solc(short_version, self.artifacts_dir)
        if solc is None:
            return CorrespondenceOutcome(
                status=CorrespondenceStatus.SKIPPED,
                skipped="compiler_not_installed",
                detail=f"solc {short_version} is not installed locally.",
                compiler_version=compiler_version,
                runtime_sha256=runtime_sha,
                executable_sha256=executable_sha,
                metadata_sha256=metadata_sha,
                runtime_byte_size=len(runtime_bytecode),
                executable_byte_size=len(runtime_exec),
            )

        try:
            output = recompile(std_json, solc, self.compile_timeout_seconds)
        except RecompileError as exc:
            return CorrespondenceOutcome(
                status=CorrespondenceStatus.UNAVAILABLE,
                skipped="compiler_could_not_run",
                detail=f"The compiler could not be run: {exc}"[:300],
                compiler_version=compiler_version,
                runtime_sha256=runtime_sha,
                executable_sha256=executable_sha,
                metadata_sha256=metadata_sha,
                runtime_byte_size=len(runtime_bytecode),
                executable_byte_size=len(runtime_exec),
            )

        if "contracts" not in output:
            return CorrespondenceOutcome(
                status=CorrespondenceStatus.MISMATCH,
                detail=(
                    "The compiler rejected the verification's own input, so no "
                    "recompilation could be compared."
                ),
                compiler_version=compiler_version,
                runtime_sha256=runtime_sha,
                executable_sha256=executable_sha,
                metadata_sha256=metadata_sha,
                runtime_byte_size=len(runtime_bytecode),
                executable_byte_size=len(runtime_exec),
            )

        matches: list[tuple[str, str, str, str]] = []
        reasons: list[str] = []
        for file_name, contracts in (output.get("contracts") or {}).items():
            for contract_name, body in contracts.items():
                deployed = (body.get("evm") or {}).get("deployedBytecode") or {}
                obj = deployed.get("object")
                if not obj:
                    continue
                corresponds, why = compare_runtime(runtime_bytecode, bytes.fromhex(obj))
                if corresponds:
                    matches.append((file_name, contract_name, deployed.get("sourceMap", ""), why))
                else:
                    reasons.append(f"{file_name}:{contract_name} -> {why}")

        if not matches:
            return CorrespondenceOutcome(
                status=CorrespondenceStatus.MISMATCH,
                detail=(
                    "; ".join(reasons)[:500] or "no contract recompiled to a comparable runtime."
                ),
                compiler_version=compiler_version,
                runtime_sha256=runtime_sha,
                executable_sha256=executable_sha,
                metadata_sha256=metadata_sha,
                runtime_byte_size=len(runtime_bytecode),
                executable_byte_size=len(runtime_exec),
            )

        file_name, contract_name, source_map, why = matches[0]
        entries = source_map.split(";") if source_map else []
        ranges = expand_source_map(entries)

        disassembly = disassemble(runtime_bytecode, table=load_fork(self.fork))
        source_text = self._source_text(document, file_name)
        if not source_text:
            return CorrespondenceOutcome(
                status=CorrespondenceStatus.SKIPPED,
                skipped="no_source_content",
                detail="The verification payload carries no source content.",
                compiler_version=compiler_version,
                source_path=file_name,
                contract_name=contract_name,
                runtime_sha256=runtime_sha,
                executable_sha256=executable_sha,
                metadata_sha256=metadata_sha,
                runtime_byte_size=len(runtime_bytecode),
                executable_byte_size=len(runtime_exec),
                instruction_count=len(disassembly.instructions),
            )

        locations = self._locate(disassembly, ranges, source_text, file_name)

        return CorrespondenceOutcome(
            status=CorrespondenceStatus.ESTABLISHED,
            detail=why,
            compiler_version=compiler_version,
            source_path=file_name,
            contract_name=contract_name,
            runtime_sha256=runtime_sha,
            executable_sha256=executable_sha,
            metadata_sha256=metadata_sha,
            runtime_byte_size=len(runtime_bytecode),
            executable_byte_size=len(runtime_exec),
            instruction_count=len(disassembly.instructions),
            mapped_instruction_count=len(locations),
            locations=tuple(locations),
        )

    @staticmethod
    def _source_text(document: dict[str, Any], file_name: str) -> str:
        """Read the source content for one file out of the verification record.

        Args:
            document: The Sourcify verification document.
            file_name: The file to read.

        Returns:
            The source text, or an empty string when it is not present.
        """
        sources = document.get("sources")
        if not isinstance(sources, dict):
            return ""
        entry = sources.get(file_name)
        if not isinstance(entry, dict):
            return ""
        content = entry.get("content")
        return content if isinstance(content, str) else ""

    @staticmethod
    def _locate(
        disassembly: Any,
        ranges: list[tuple[int, int] | None],
        source_text: str,
        file_name: str,
    ) -> list[SourceLocation]:
        """Map the interesting opcodes of a runtime onto source lines.

        Args:
            disassembly: The disassembly of the deployed runtime.
            ranges: The expanded source map, one entry per instruction.
            source_text: The source content the map indexes into.
            file_name: The source file the map refers to.

        Returns:
            One location per interesting opcode that the source map covers.
        """
        locations: list[SourceLocation] = []
        for index, instruction in enumerate(disassembly.instructions):
            if instruction.name not in INTERESTING_OPCODES:
                continue
            if index >= len(ranges):
                continue
            span = ranges[index]
            if span is None:
                continue
            start, length = span
            line = source_text[:start].count("\n") + 1
            locations.append(
                SourceLocation(
                    offset=instruction.offset,
                    opcode=instruction.name,
                    file=file_name,
                    line=line,
                    snippet=source_text[start : start + length].strip(),
                )
            )
        return locations


__all__ = [
    "CorrespondenceOutcome",
    "CorrespondenceProver",
    "DEFAULT_COMPILE_TIMEOUT_SECONDS",
    "INTERESTING_OPCODES",
    "OUTPUT_SELECTION",
    "RecompileError",
    "SOURCIFY_URL_TEMPLATE",
    "SourceLocation",
    "compare_runtime",
    "expand_source_map",
    "find_solc",
    "prepare_standard_json",
    "recompile",
    "sha256_hex",
]
