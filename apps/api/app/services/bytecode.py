"""Bytecode acquisition.

Bytecode is normally fetched from a chain RPC endpoint. No public RPC is
reachable from every environment, so this module isolates the fetch behind a
single function that raises :class:`BytecodeUnavailableError` on failure.
Callers (the worker) translate that into a recorded scan status rather than a
crash.

Two sources are supported, in order:

1. **User-supplied bytecode** (design doc section 6.1 lists "bytecode uploaded
   by the user" as a first-class input). When the caller supplies the bytes,
   no network call is made at all and the source is recorded as ``upload``.
2. **A chain RPC**, then a **Sourcify** fallback.

The Sourcify fallback matters in practice: it serves the *verified* deployed
runtime bytecode over plain HTTPS, with no API key, so it works in
environments where the public RPC hosts are blocked.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.chains import explorer_host_for

log = get_logger(__name__)

#: Public RPC endpoints tried when ``EVM_RPC_URL`` is not configured.
#:
#: Several endpoints per chain, because a single public endpoint is a
#: single point of failure: one host that is unreachable, or that
#: answers 429 under load, would otherwise stop the whole automatic
#: fetch. These are free, keyless, and have no stated rate limit that
#: a scan burst would break.
DEFAULT_PUBLIC_RPC_URLS: dict[int, tuple[str, ...]] = {
    1: (
        "https://ethereum-rpc.publicnode.com",
        "https://eth.drpc.org",
        "https://rpc.mevblocker.io",
        "https://eth-mainnet.public.blastapi.io",
    ),
    10: ("https://optimism-rpc.publicnode.com", "https://optimism.drpc.org"),
    56: ("https://bsc-rpc.publicnode.com",),
    100: ("https://gnosis-rpc.publicnode.com",),
    137: ("https://polygon-bor-rpc.publicnode.com", "https://polygon.drpc.org"),
    250: ("https://fantom-rpc.publicnode.com",),
    42161: ("https://arbitrum-one-rpc.publicnode.com",),
    43114: ("https://avalanche-c-chain-rpc.publicnode.com", "https://avalanche.drpc.org"),
    11155111: ("https://ethereum-sepolia-rpc.publicnode.com",),
}

#: How many times a rate-limited or temporarily failing endpoint is tried.
FETCH_ATTEMPTS = 3

#: The wait before the second attempt, in seconds. It grows with every
#: attempt, so a busy endpoint is not hammered.
FETCH_BACKOFF_SECONDS = 1.5

#: Sourcify serves verified contracts for these chains.
SOURCIFY_CHAIN_IDS: frozenset[int] = frozenset({1, 10, 56, 100, 137, 250, 42161, 43114, 11155111})

#: Base URL of the Sourcify server API.
SOURCIFY_BASE_URL = "https://sourcify.dev/server/v2"


class BytecodeUnavailableError(RuntimeError):
    """Raised when runtime bytecode could not be retrieved.

    Attributes:
        code: A stable machine-readable error code stored on the scan.
    """

    def __init__(self, message: str, code: str = "bytecode_unavailable") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class BytecodeArtifact:
    """Runtime bytecode plus its provenance metadata."""

    code: bytes
    source: str
    source_uri: str | None = None
    address: str | None = None

    @property
    def sha256(self) -> str:
        """Hex SHA-256 digest of the bytecode."""
        return hashlib.sha256(self.code).hexdigest()

    @property
    def size(self) -> int:
        """Size of the bytecode in bytes."""
        return len(self.code)


def _rpc_urls(chain_id: int) -> list[str]:
    settings = get_settings()
    urls: list[str] = []
    if settings.evm_rpc_url:
        urls.append(settings.evm_rpc_url)
    urls.extend(DEFAULT_PUBLIC_RPC_URLS.get(chain_id, ()))
    return urls


def _post_json_rpc(
    url: str, payload: dict[str, object], timeout: float
) -> dict[str, object] | None:
    """POST a JSON-RPC request, retrying a rate limit or a server error.

    A public endpoint that answers 429 or 5xx is telling us about the
    moment, not about the contract. Retrying after a short wait turns
    that glitch into an ordinary fetch; a client error is not retried,
    because a 404 is an answer.

    Returns:
        The decoded body, or ``None`` when the endpoint could not be
        used.
    """
    for attempt in range(FETCH_ATTEMPTS):
        try:
            response = httpx.post(url, json=payload, timeout=timeout)
        except httpx.HTTPError as exc:
            log.warning("rpc_request_failed", url=url, error=str(exc))
            return None

        status = response.status_code
        if status == 429 or status >= 500:
            if attempt + 1 < FETCH_ATTEMPTS:
                time.sleep(FETCH_BACKOFF_SECONDS * (attempt + 1))
                continue
            log.warning("rpc_endpoint_unavailable", url=url, status=status)
            return None
        if status >= 400:
            return None

        try:
            body = response.json()
        except ValueError:
            log.warning("rpc_response_not_json", url=url, status=status)
            return None

        if not isinstance(body, dict):
            return None
        error = body.get("error")
        if error is not None:
            # The endpoint answered, but with a JSON-RPC error. That is
            # a failure of this endpoint, not of the contract.
            log.warning("rpc_error_response", url=url, error=str(error)[:200])
            return None
        return body
    return None


def _eth_get_code(rpc_url: str, address: str, timeout: float) -> bytes | None:
    """Fetch runtime bytecode over JSON-RPC.

    Returns the bytecode bytes, an empty ``bytes`` when the address has no
    deployed code, or ``None`` when the endpoint could not be used. The
    distinction matters: "no code at this address" is a fact about the
    contract, while ``None`` is a transport failure.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getCode",
        "params": [address, "latest"],
    }
    body = _post_json_rpc(rpc_url, payload, timeout)
    if body is None:
        return None

    result = body.get("result")
    if not isinstance(result, str):
        return None
    if result == "":
        return None
    if result == "0x":
        # The address holds no deployed code.
        return b""
    try:
        return bytes.fromhex(result[2:] if result.startswith("0x") else result)
    except ValueError:
        log.warning("rpc_result_not_hex", rpc_url=rpc_url)
        return None


def _sourcify_code(chain_id: int, address: str, timeout: float) -> bytes | None:
    """Fetch the verified deployed runtime bytecode from Sourcify.

    Sourcify answers with the on-chain bytecode under
    ``runtimeBytecode.onchainBytecode``. A contract that is not verified
    there yields no bytecode.
    """
    url = f"{SOURCIFY_BASE_URL}/contract/{chain_id}/{address}?fields=all"
    try:
        response = httpx.get(url, timeout=timeout, headers={"Accept": "application/json"})
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("sourcify_fetch_failed", url=url, error=str(exc))
        return None

    if not isinstance(body, dict):
        return None
    runtime = body.get("runtimeBytecode")
    if not isinstance(runtime, dict):
        return None
    code = runtime.get("onchainBytecode")
    if not isinstance(code, str) or not code:
        return None
    if code.startswith(("0x", "0X")):
        code = code[2:]
    try:
        return bytes.fromhex(code)
    except ValueError:
        log.warning("sourcify_result_not_hex", url=url)
        return None


def _blockscout_code(chain_id: int, address: str, timeout: float) -> bytes | None:
    """Fetch deployed runtime bytecode from the chain's Blockscout instance.

    Every Blockscout instance proxies the Ethereum JSON-RPC API at
    ``/api/eth-rpc``, so the instance that already answered the
    discovery query can also serve the contract's bytecode. That route
    matters: the public RPC endpoints for a chain are often unreachable
    from a small server, and a contract that is verified on the chain's
    own explorer must still be analysable.

    Returns:
        The bytecode, or ``None`` when the instance is unknown,
        unreachable, or answers with something other than code.
    """
    host = explorer_host_for(chain_id)
    if not host:
        return None

    url = f"https://{host}/api/eth-rpc"
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_getCode",
        "params": [address, "latest"],
        "id": 1,
    }
    body = _post_json_rpc(url, payload, timeout)
    if body is None:
        return None

    result = body.get("result")
    if not isinstance(result, str) or not result.startswith("0x"):
        return None
    if result == "0x":
        return b""
    try:
        return bytes.fromhex(result[2:])
    except ValueError:
        log.warning("blockscout_result_not_hex", url=url)
        return None


def fetch_runtime_bytecode(
    address: str,
    chain_id: int = 1,
    *,
    timeout: float = 10.0,
) -> BytecodeArtifact:
    """Fetch deployed runtime bytecode for ``address``.

    Three routes are tried, in order of authority:

    1. the chain's public RPC endpoints, which report what is actually
       deployed right now;
    2. Sourcify, which serves the deployed bytecode of a verified
       contract;
    3. the chain's Blockscout instance, which proxies ``eth_getCode``.

    Raises:
        BytecodeUnavailableError: when no route can serve the code, or the
            contract has no deployed code.
    """
    urls = _rpc_urls(chain_id)
    if not urls and chain_id not in SOURCIFY_CHAIN_IDS:
        blockscout_host = explorer_host_for(chain_id)
        if not blockscout_host:
            raise BytecodeUnavailableError(
                "No RPC endpoint is configured and no default endpoint exists for this chain.",
                code="rpc_not_configured",
            )

    for rpc_url in urls:
        code = _eth_get_code(rpc_url, address, timeout)
        if code is None:
            continue
        if not code:
            raise BytecodeUnavailableError(
                "The contract has no deployed code at the requested address.",
                code="bytecode_empty",
            )
        return BytecodeArtifact(code=code, source="rpc", source_uri=rpc_url, address=address)

    sourcify_tried = chain_id in SOURCIFY_CHAIN_IDS
    if sourcify_tried:
        code = _sourcify_code(chain_id, address, timeout)
        if code:
            return BytecodeArtifact(
                code=code,
                source="sourcify",
                source_uri=f"{SOURCIFY_BASE_URL}/contract/{chain_id}/{address}",
                address=address,
            )

    # The chain's own explorer is the last route: it is where the
    # contract was discovered, and it proxies eth_getCode, so a chain
    # whose public RPC endpoints are unreachable is still analysable.
    code = _blockscout_code(chain_id, address, timeout)
    if code is not None:
        if not code:
            raise BytecodeUnavailableError(
                "The contract has no deployed code at the requested address.",
                code="bytecode_empty",
            )
        return BytecodeArtifact(
            code=code,
            source="blockscout",
            source_uri=f"https://{explorer_host_for(chain_id)}/api/eth-rpc",
            address=address,
        )

    if sourcify_tried:
        raise BytecodeUnavailableError(
            "The contract could not be retrieved from Sourcify or from the "
            "chain's explorer; it may not be verified there.",
            code="sourcify_unavailable",
        )

    raise BytecodeUnavailableError(
        "Could not reach any RPC endpoint to retrieve contract bytecode.",
        code="rpc_unreachable",
    )


__all__ = [
    "BytecodeArtifact",
    "BytecodeUnavailableError",
    "DEFAULT_PUBLIC_RPC_URLS",
    "FETCH_ATTEMPTS",
    "SOURCIFY_BASE_URL",
    "SOURCIFY_CHAIN_IDS",
    "fetch_runtime_bytecode",
]
