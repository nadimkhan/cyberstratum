"""Compiling a developer's pasted Solidity.

The developer tool takes source; the analysis engine reads bytes. This
module is the bridge between them: it compiles the source with a real
``solc``, out of process and time-boxed, and returns the runtime
bytecode together with the source map that maps instructions back to
lines.

The source map is worth more here than anywhere else in the product.
For a deployed contract the mapping from bytecode to source has to be
*proven* by recompiling and comparing, because the source may describe
a different contract. Here we compiled the code ourselves, so the
mapping is true by construction: the bytes we analyse are the bytes
the compiler produced from the lines the developer can see.

The compiler is never given a shell, never given a file path it can
escape, and is killed when it outstays its welcome. A developer's
source is untrusted input, and the compiler is the first thing it
reaches.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.services.correspondence import RecompileError, find_solc, recompile

log = get_logger(__name__)

#: How long the compiler is given, in seconds.
DEFAULT_COMPILE_TIMEOUT_SECONDS = 60.0

#: The largest source the product will compile, in bytes. A contract
#: that does not fit in this is not a contract.
MAX_SOURCE_BYTES = 512 * 1024

#: The file name the pasted source is compiled under.
DEFAULT_SOURCE_NAME = "Contract.sol"


class CompilationError(RuntimeError):
    """The developer's source did not compile.

    The message is the compiler's own, because the developer's next
    action is to read it.
    """


@dataclass(frozen=True)
class CompiledSource:
    """The result of compiling a developer's source.

    Attributes:
        runtime_bytecode: The deployed runtime bytecode.
        source_map: solc's compressed source map for the runtime code.
        contract_name: The name of the contract that was compiled.
        solc_version: The compiler that was used.
        abi: The contract's ABI, as JSON.
        source_name: The file name the source was compiled under.
        warnings: The compiler's warnings, verbatim.
        creation_bytecode: The creation bytecode, when the compiler
            emitted it.
    """

    runtime_bytecode: bytes
    source_map: str = ""
    contract_name: str = "Contract"
    solc_version: str = ""
    abi: str = ""
    source_name: str = DEFAULT_SOURCE_NAME
    warnings: tuple[str, ...] = ()
    creation_bytecode: bytes = b""


@dataclass(frozen=True)
class CompileOutcome:
    """A successful compilation and the diagnostics that came with it."""

    compiled: CompiledSource
    raw_output: dict[str, Any] = field(default_factory=dict)


def pasted_address(source_code: str) -> str:
    """Return the stable address a pasted source is filed under.

    A pasted contract has no address on any chain, but it still needs an
    identity: the developer comes back with a fixed version of their
    contract and wants to see the findings of the previous one next to
    it. The identity is therefore derived from the source itself, so the
    same source is always the same target and its history accumulates.

    The address is not a real one -- nothing is deployed there -- and it
    is marked as such by the target's provenance.
    """
    digest = hashlib.sha256(source_code.encode("utf-8")).hexdigest()
    return "0x" + digest[:40]


def _installed_solvers(artifacts_dir: str | None = None) -> list[Path]:
    """Return the installed solc binaries, newest version first."""
    root = Path(
        artifacts_dir or os.environ.get("SOLC_ARTIFACTS_DIR", "~/.solc-select/artifacts")
    ).expanduser()
    if not root.is_dir():
        return []
    found: list[Path] = []
    for directory in sorted(root.iterdir()):
        if not directory.is_dir():
            continue
        for name in (directory.name, f"{directory.name}.exe"):
            candidate = directory / name
            if candidate.is_file():
                found.append(candidate)
                break
    return found


def _version_of(path: Path) -> tuple[tuple[int, ...], str]:
    """Return a comparable version for a solc binary's name."""
    raw = path.parent.name
    if raw.startswith("solc-"):
        raw = raw[len("solc-") :]
    parts: list[int] = []
    for piece in raw.split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    return tuple(parts), raw


def resolve_solc(
    version: str | None = None, artifacts_dir: str | None = None
) -> tuple[Path, str]:
    """Find the compiler to use.

    Args:
        version: The requested version, such as ``0.8.26``. When unset,
            the newest installed compiler is used.
        artifacts_dir: The compiler artifacts directory.

    Returns:
        The compiler's path and the version it reports.

    Raises:
        CompilationError: when no compiler is installed, or when the
            requested version is not the one that is installed.
    """
    if version:
        found = find_solc(version, artifacts_dir)
        if found is None:
            raise CompilationError(
                f"solc {version} is not installed on this server. "
                "Install it, or omit solc_version to use the newest compiler "
                "that is installed."
            )
        return found, version

    installed = _installed_solvers(artifacts_dir)
    if not installed:
        raise CompilationError(
            "No solc compiler is installed on this server, so source cannot "
            "be compiled. Paste the runtime bytecode instead, or install solc."
        )
    best = max(installed, key=lambda path: _version_of(path))
    return best, _version_of(best)[1]


def build_standard_json(
    source_code: str,
    *,
    source_name: str = DEFAULT_SOURCE_NAME,
) -> str:
    """Build the standard-JSON input that compiles one source file.

    The output selection asks for the deployed bytecode and its source
    map, the creation bytecode and the ABI. The source map is what makes
    a finding point at a line rather than at an offset.
    """
    document = {
        "language": "Solidity",
        "sources": {source_name: {"content": source_code}},
        "settings": {
            "optimizer": {"enabled": False, "runs": 200},
            "outputSelection": {
                "*": {
                    "*": [
                        "abi",
                        "evm.bytecode.object",
                        "evm.bytecode.sourceMap",
                        "evm.deployedBytecode.object",
                        "evm.deployedBytecode.sourceMap",
                    ]
                }
            },
        },
    }
    return json.dumps(document)


def _compiler_errors(output: dict[str, Any]) -> list[str]:
    """Return the compiler's errors, if it reported any."""
    errors = output.get("errors")
    if not isinstance(errors, list):
        return []
    messages: list[str] = []
    for entry in errors:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("severity") or "").lower() != "error":
            continue
        message = str(entry.get("formattedMessage") or entry.get("message") or "").strip()
        if message:
            messages.append(message)
    return messages


def _compiler_warnings(output: dict[str, Any]) -> tuple[str, ...]:
    """Return the compiler's warnings, if it reported any."""
    warnings = output.get("errors")
    if not isinstance(warnings, list):
        return ()
    messages: list[str] = []
    for entry in warnings:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("severity") or "").lower() != "warning":
            continue
        message = str(entry.get("formattedMessage") or entry.get("message") or "").strip()
        if message:
            messages.append(message)
    return tuple(messages)


def _select_contract(
    output: dict[str, Any], source_name: str
) -> tuple[str, dict[str, Any]]:
    """Pick the contract to analyse out of the compiler's output.

    A file can hold several contracts. The one with the largest runtime
    bytecode is the one that does the work; the others are interfaces,
    libraries or base contracts.
    """
    contracts = output.get("contracts")
    if not isinstance(contracts, dict):
        return "", {}
    by_file = contracts.get(source_name)
    if not isinstance(by_file, dict):
        return "", {}

    best_name = ""
    best_size = -1
    best: dict[str, Any] = {}
    for name, entry in by_file.items():
        if not isinstance(entry, dict):
            continue
        deployed = entry.get("evm", {}).get("deployedBytecode", {})
        bytecode = deployed.get("object") if isinstance(deployed, dict) else ""
        size = len(bytecode) if isinstance(bytecode, str) else 0
        if size > best_size:
            best_name, best, best_size = name, entry, size
    return best_name, best


def compile_source(
    source_code: str,
    *,
    solc_version: str | None = None,
    source_name: str = DEFAULT_SOURCE_NAME,
    timeout: float = DEFAULT_COMPILE_TIMEOUT_SECONDS,
    artifacts_dir: str | None = None,
) -> CompileOutcome:
    """Compile a developer's source into the bytes the engine analyses.

    Args:
        source_code: The Solidity source.
        solc_version: The compiler to use. The newest installed compiler
            is used when this is unset.
        source_name: The file name to compile the source under.
        timeout: How long the compiler is given, in seconds.
        artifacts_dir: The compiler artifacts directory.

    Returns:
        The compiled source and the compiler's raw output.

    Raises:
        CompilationError: when the source is too large, no compiler is
            installed, the source does not compile, or it compiles to
            nothing deployable.
    """
    if not source_code.strip():
        raise CompilationError("The source is empty.")
    encoded = source_code.encode("utf-8")
    if len(encoded) > MAX_SOURCE_BYTES:
        raise CompilationError(
            f"The source is {len(encoded)} bytes, which is over the "
            f"{MAX_SOURCE_BYTES} byte limit."
        )

    solc, version = resolve_solc(solc_version, artifacts_dir)

    standard_json = build_standard_json(source_code, source_name=source_name)
    try:
        output = recompile(standard_json, solc, timeout)
    except RecompileError as exc:
        raise CompilationError(str(exc)) from exc

    errors = _compiler_errors(output)
    if errors:
        raise CompilationError("\n".join(errors))

    contract_name, entry = _select_contract(output, source_name)
    if not contract_name:
        raise CompilationError(
            "The source compiled, but it holds no contract with deployable "
            "bytecode. A library, an interface or an abstract contract "
            "cannot be analysed as a deployed contract."
        )

    evm = entry.get("evm", {})
    deployed = evm.get("deployedBytecode", {}) if isinstance(evm, dict) else {}
    creation = evm.get("bytecode", {}) if isinstance(evm, dict) else {}
    runtime_hex = deployed.get("object") if isinstance(deployed, dict) else ""
    if not isinstance(runtime_hex, str) or not runtime_hex:
        raise CompilationError(
            f"The contract {contract_name} produced no runtime bytecode."
        )
    runtime_hex = runtime_hex.removeprefix("0x")
    try:
        runtime = bytes.fromhex(runtime_hex)
    except ValueError as exc:
        raise CompilationError(f"The compiler emitted invalid bytecode: {exc}") from exc

    creation_hex = creation.get("object") if isinstance(creation, dict) else ""
    creation_bytes = b""
    if isinstance(creation_hex, str) and creation_hex:
        try:
            creation_bytes = bytes.fromhex(creation_hex.removeprefix("0x"))
        except ValueError:
            creation_bytes = b""

    abi = entry.get("abi")
    abi_json = json.dumps(abi) if abi is not None else ""

    compiled = CompiledSource(
        runtime_bytecode=runtime,
        source_map=str(deployed.get("sourceMap") or "") if isinstance(deployed, dict) else "",
        contract_name=contract_name,
        solc_version=version,
        abi=abi_json,
        source_name=source_name,
        warnings=_compiler_warnings(output),
        creation_bytecode=creation_bytes,
    )
    log.info(
        "source_compiled",
        contract=contract_name,
        solc=version,
        runtime_bytes=len(runtime),
    )
    return CompileOutcome(compiled=compiled, raw_output=output)


__all__ = [
    "MAX_SOURCE_BYTES",
    "CompilationError",
    "CompileOutcome",
    "CompiledSource",
    "build_standard_json",
    "compile_source",
    "pasted_address",
    "resolve_solc",
]
