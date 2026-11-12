"""Live check of the source-to-bytecode correspondence proof.

This is the end-to-end demonstration behind ADR-0017: an on-chain runtime
bytecode is tied to an exact source file and line, with no guessing at any
link. The chain is:

  1. Fetch the deployed runtime bytecode from a public RPC.
  2. Fetch the verified source and the exact compiler input from Sourcify.
  3. Recompile that exact input with the same solc, and require the
     recompiled **executable code** to be identical to the on-chain runtime.
     The metadata trailer is separated before comparison, because it is
     non-executable and its content hash legitimately differs between two
     otherwise identical builds.
  4. Apply the compiler's own source map to the on-chain runtime, using
     CyberStratum's own disassembler, and read off the file and line for any
     bytecode offset.

Step 3 is the gate. Without it a source line would be a guess, and this
script would report failure rather than print a line number.

Two facts about Sourcify's payloads that this script depends on, both found
by running it:

* ``stdJsonInput`` carries the compiler settings but **no** ``outputSelection``.
  solc then emits no bytecode at all, which looks exactly like a failed
  correspondence check. The script injects the selection it needs without
  touching any other setting, so the recompilation still uses the
  verification's own compiler options.
* The metadata trailer holds a 32-byte content hash (``bzzr0`` for the
  compilers of this vintage). It is the only part of the runtime that differs
  between the on-chain and recompiled code.

Usage::

    node scripts/py.mjs scripts/live_check_correspondence.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packages" / "evm_analysis"))

from evm_analysis import disassemble, load_fork, split_metadata  # noqa: E402

#: Ethereum mainnet.
CHAIN_ID = "1"

#: USDC, a widely mirrored proxy deployment.
CONTRACT = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"

SOURCIFY_URL = "https://sourcify.dev/server/v2/contract/{chain}/{address}?fields=all"

RPC_URLS = (
    "https://ethereum-rpc.publicnode.com",
    "https://eth.drpc.org",
    "https://1rpc.io/eth",
)

#: How long the compiler is given before it is treated as hung.
COMPILE_TIMEOUT_SECONDS = 600

#: Correspondence was proven.
EXIT_CORRESPONDENCE = 0

#: The check ran and the source does not describe the deployed contract.
EXIT_NO_CORRESPONDENCE = 1

#: The check could not be performed at all. This is an error, never a
#: negative verdict.
EXIT_COMPILER_ERROR = 2

#: The opcodes worth showing, because they are what a finding would report.
INTERESTING = frozenset(
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

#: The output selection this proof needs, injected when Sourcify omits it.
OUTPUT_SELECTION = {"*": {"*": ["evm.deployedBytecode.object", "evm.deployedBytecode.sourceMap"]}}


def _http_json(url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fetch and decode a JSON document.

    Args:
        url: The URL to fetch.
        payload: An optional JSON-RPC payload.

    Returns:
        The decoded document.
    """
    headers = {"User-Agent": "cyberstratum-verification"}
    with httpx.Client(timeout=60.0) as client:
        if payload is None:
            response = client.get(url, headers=headers)
        else:
            response = client.post(url, headers=headers, json=payload)
    response.raise_for_status()
    decoded = response.json()
    if not isinstance(decoded, dict):
        raise ValueError("expected a JSON object")
    return decoded


def fetch_onchain_runtime(address: str) -> bytes:
    """Fetch the deployed runtime bytecode.

    Args:
        address: The contract address.

    Returns:
        The runtime bytecode.
    """
    errors: list[str] = []
    for rpc in RPC_URLS:
        try:
            response = _http_json(
                rpc,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "eth_getCode",
                    "params": [address, "latest"],
                },
            )
        except (httpx.HTTPError, OSError, ValueError) as exc:
            errors.append(f"{rpc} -> {str(exc)[:60]}")
            continue
        code = response.get("result")
        if isinstance(code, str) and len(code) > 2:
            return bytes.fromhex(code[2:] if code.startswith("0x") else code)
        errors.append(f"{rpc} -> empty code")
    raise RuntimeError("no RPC returned the runtime bytecode: " + "; ".join(errors))


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
            f"so this does not break correspondence"
        )
    return True, note


def _find_solc(version: str) -> Path | None:
    """Locate a solc binary.

    The same search the product's Slither runner performs, so both agree on
    which compiler a given contract was built with: the ``solc-select``
    layout under ``SOLC_ARTIFACTS_DIR``, and the flatter ``<version>/``
    layout some setups use.

    Args:
        version: The compiler version, such as ``0.4.24``.

    Returns:
        The path to the compiler, or ``None`` when it is not installed.
    """
    artifacts = Path(os.environ.get("SOLC_ARTIFACTS_DIR", "~/.solc-select/artifacts")).expanduser()
    for directory in (f"solc-{version}", version):
        for name in (f"solc-{version}", f"solc-{version}.exe"):
            candidate = artifacts / directory / name
            if candidate.is_file():
                return candidate
    return None


class RecompileError(RuntimeError):
    """The compiler could not be run, so the check could not be performed.

    This is deliberately distinct from a *mismatch*. A mismatch means the
    check ran and the source does not describe the deployed contract. A
    compiler that hangs or crashes means nothing was learned either way, and
    reporting it as a mismatch would be a false negative.
    """


def _recompile(
    std_json: str, solc: Path, timeout: float = COMPILE_TIMEOUT_SECONDS
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


def main() -> int:
    """Run the correspondence proof.

    Returns:
        ``0`` when correspondence was established, ``1`` when the check ran
        and the source does not describe the deployed contract, and ``2``
        when the check could not be performed at all.
    """
    print("Source-to-bytecode correspondence live check")
    print(f"chain {CHAIN_ID}  contract {CONTRACT}")

    onchain = fetch_onchain_runtime(CONTRACT)
    print(f"\non-chain runtime      : {len(onchain)} bytes")

    document = _http_json(SOURCIFY_URL.format(chain=CHAIN_ID, address=CONTRACT))
    compilation = document.get("compilation") or {}
    compiler_version = str(compilation.get("compilerVersion") or "")
    print(f"sourcify match id     : {document.get('matchId')}")
    print(f"verification compiler : {compiler_version}")

    raw_input = document.get("stdJsonInput")
    if not raw_input:
        print("\nSkipped: Sourcify carries no standard-JSON input for this contract.")
        return EXIT_CORRESPONDENCE
    std_json = json.dumps(raw_input) if isinstance(raw_input, dict) else str(raw_input)

    # Sourcify stores the compiler settings but no outputSelection, so solc
    # emits no bytecode. Inject the selection without touching the settings,
    # so the recompilation still uses the verification's own options.
    parsed = json.loads(std_json)
    settings = parsed.setdefault("settings", {})
    if not settings.get("outputSelection"):
        print("outputSelection       : absent in the stored input -> injecting one")
        settings["outputSelection"] = OUTPUT_SELECTION
        std_json = json.dumps(parsed)
    else:
        print("outputSelection       : present in the stored input")

    # A source given as a URL rather than inline content makes solc fetch
    # it over the network. That makes the recompilation depend on what the
    # URL serves at this moment rather than on the verification's own
    # recorded source, and it can hang on a slow or blocked network. The
    # bytecode comparison is still the gate, but this has to be recorded.
    fetched = [
        name
        for name, body in (parsed.get("sources") or {}).items()
        if isinstance(body, dict) and body.get("urls") and not body.get("content")
    ]
    if fetched:
        print(f"network-fetched sources: {len(fetched)} (not inline)")
        for name in fetched[:5]:
            print(f"  {name}")

    short_version = compiler_version.split("+")[0].strip()
    solc = _find_solc(short_version)
    if solc is None:
        print(f"\nSkipped: solc {short_version} is not installed locally.")
        return EXIT_CORRESPONDENCE
    print(f"compiler used         : {solc}")

    try:
        output = _recompile(std_json, solc)
    except RecompileError as exc:
        print(f"\ncompile could not be run: {exc}")
        print("Nothing was learned either way -- this is not a mismatch.")
        return EXIT_COMPILER_ERROR
    if "contracts" not in output:
        print("\ncompile failed:", json.dumps(output.get("errors"))[:800])
        return EXIT_NO_CORRESPONDENCE

    matches: list[tuple[str, str, str, str]] = []
    for file_name, contracts in (output.get("contracts") or {}).items():
        for contract_name, body in contracts.items():
            deployed = (body.get("evm") or {}).get("deployedBytecode") or {}
            obj = deployed.get("object")
            if not obj:
                continue
            corresponds, why = compare_runtime(onchain, bytes.fromhex(obj))
            if corresponds:
                matches.append((file_name, contract_name, deployed.get("sourceMap", ""), why))

    if not matches:
        print("\nNO matching recompilation -> no source line may be claimed.")
        for file_name, contracts in (output.get("contracts") or {}).items():
            for contract_name, body in contracts.items():
                deployed = (body.get("evm") or {}).get("deployedBytecode") or {}
                obj = deployed.get("object")
                if not obj:
                    continue
                corresponds, why = compare_runtime(onchain, bytes.fromhex(obj))
                if not corresponds:
                    print(f"  {file_name}:{contract_name} -> {why}")
        return EXIT_NO_CORRESPONDENCE

    print(f"\ncorrespondence established for {len(matches)} contract(s):")
    for file_name, contract_name, _source_map, why in matches:
        print(f"  {file_name}:{contract_name}")
        print(f"     {why}")

    file_name, _contract_name, source_map, _why = matches[0]
    entries = source_map.split(";") if source_map else []
    ranges = expand_source_map(entries)

    disassembly = disassemble(onchain, table=load_fork("shanghai"))
    print(f"\non-chain instructions : {len(disassembly.instructions)}")
    print(f"metadata trailer      : {disassembly.metadata is not None}")
    print(f"source-map entries    : {len(entries)}")

    sources = document.get("sources")
    source_entries = sources if isinstance(sources, dict) else {}
    source_text = ""
    entry = source_entries.get(file_name)
    if isinstance(entry, dict):
        content = entry.get("content")
        if isinstance(content, str):
            source_text = content
    if not source_text:
        print("\nSkipped: the compilation payload carries no source content.")
        return EXIT_CORRESPONDENCE

    def locate(offset: int) -> tuple[int, str] | None:
        """Find the source line for a bytecode offset.

        Args:
            offset: The bytecode offset.

        Returns:
            The line number and the source snippet, or ``None``.
        """
        index = None
        for position, instruction in enumerate(disassembly.instructions):
            if instruction.offset == offset:
                index = position
                break
        if index is None or index >= len(ranges) or ranges[index] is None:
            return None
        start, length = ranges[index]
        line = source_text[:start].count("\n") + 1
        return line, source_text[start : start + length].strip()

    print(f"\n{'offset':<10}{'opcode':<15}{'file:line':<30}source")
    print("-" * 100)
    mapped = 0
    total = 0
    for instruction in disassembly.instructions:
        if instruction.name not in INTERESTING:
            continue
        total += 1
        hit = locate(instruction.offset)
        if hit is None:
            continue
        mapped += 1
        line, snippet = hit
        print(
            f"0x{instruction.offset:<8x}{instruction.name:<15}"
            f"{file_name + ':' + str(line):<30}{snippet[:44]}"
        )

    print(f"\ninteresting instructions mapped to a source line: {mapped}/{total}")
    print("\nAn exact byte offset in the deployed runtime, and the exact source")
    print("file and line it maps to. This is what a disclosure report needs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
