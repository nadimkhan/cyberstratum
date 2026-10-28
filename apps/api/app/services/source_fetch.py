"""Fetching a contract's verified source.

The bytecode engine analyses deployed bytes whether or not the contract is
verified. The source engine needs the source itself, so this module goes
and gets it.

Two routes are used, in this order:

1. The chain's own Blockscout instance, which serves ``source_code`` and
   the compiler settings for a verified contract.
2. Sourcify, which serves the individual source files and therefore
   handles a multi-file project properly.

Neither route is required. A contract whose source cannot be fetched is
not an error: the bytecode analysis still runs, and the source audit is
simply skipped. That is the common case for the majority of deployed
contracts, most of which are never verified.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.logging import get_logger
from app.services.bytecode import SOURCIFY_BASE_URL
from app.services.chains import explorer_host_for

log = get_logger(__name__)

#: The per-request timeout, in seconds.
DEFAULT_TIMEOUT: float = 20.0

#: The source kinds this module can return.
KIND_INSTANCE = "blockscout_instance"
KIND_SOURCIFY = "sourcify"


@dataclass(frozen=True)
class SourceArtifact:
    """A contract's verified source.

    Attributes:
        code: The main source file's contents.
        files: Every source file, keyed by its path in the project. A
            single-file contract has exactly one entry, whose key is the
            file name.
        language: The source language, normally ``Solidity``.
        compiler_version: The compiler version the contract was built
            with, when the route reports it.
        source_uri: Where the source came from.
        source_kind: Which route produced it.
        verified: Whether the route considered the contract verified.
    """

    code: str
    files: Mapping[str, str] = field(default_factory=dict)
    language: str = "Solidity"
    compiler_version: str = ""
    source_uri: str = ""
    source_kind: str = KIND_INSTANCE
    verified: bool = True

    @property
    def main_file_name(self) -> str:
        """The name of the main source file.

        The largest file is the main one in almost every project: it is
        the contract, and the others are its imports.
        """
        if not self.files:
            return "Contract.sol"
        return max(self.files.items(), key=lambda item: len(item[1]))[0]


def _clean_version(raw: str | None) -> str:
    """Normalise a compiler version string.

    Routes report versions in several shapes -- ``0.8.26``,
    ``v0.8.26``, ``0.8.26+commit.8a97fa7a`` -- and the solc lookup wants
    the plain ``0.8.26`` form.
    """
    if not raw:
        return ""
    text = raw.strip().lstrip("vV")
    for separator in ("+", " "):
        if separator in text:
            text = text.split(separator, 1)[0]
    return text.strip()


def _instance_url(chain_id: int, address: str) -> str | None:
    """The Blockscout instance URL for a contract, if the chain has one."""
    host = explorer_host_for(chain_id)
    if host is None:
        return None
    return f"https://{host}/api/v2/smart-contracts/{address}"


def _from_instance(payload: Mapping[str, Any], uri: str) -> SourceArtifact | None:
    """Build an artifact from a Blockscout instance payload.

    Args:
        payload: The decoded JSON response.
        uri: The URL the payload came from.

    Returns:
        The artifact, or ``None`` when the payload carries no source.
    """
    source = payload.get("source_code") or payload.get("sourceCode") or ""
    if not isinstance(source, str) or not source.strip():
        return None

    files: dict[str, str] = {}
    name = payload.get("name") or payload.get("file_path") or "Contract.sol"
    files[str(name)] = source

    # Blockscout also serves the imported files, keyed by path.
    additional = payload.get("additional_sources")
    if isinstance(additional, list):
        for entry in additional:
            if not isinstance(entry, Mapping):
                continue
            path = entry.get("file_name") or entry.get("path")
            content = entry.get("source_code") or entry.get("sourceCode")
            if isinstance(path, str) and isinstance(content, str) and content.strip():
                files[path] = content

    return SourceArtifact(
        code=source,
        files=files,
        language=str(payload.get("language") or "Solidity"),
        compiler_version=_clean_version(payload.get("compiler_version")),
        source_uri=uri,
        source_kind=KIND_INSTANCE,
        verified=bool(payload.get("is_verified", True)),
    )


def _from_sourcify(payload: Mapping[str, Any], uri: str) -> SourceArtifact | None:
    """Build an artifact from a Sourcify payload.

    Args:
        payload: The decoded JSON response.
        uri: The URL the payload came from.

    Returns:
        The artifact, or ``None`` when the payload carries no source.
    """
    sources = payload.get("sources")
    if not isinstance(sources, Mapping) or not sources:
        return None

    files: dict[str, str] = {}
    for path, entry in sources.items():
        if not isinstance(path, str) or not isinstance(entry, Mapping):
            continue
        content = entry.get("content")
        if isinstance(content, str) and content.strip():
            files[path] = content
    if not files:
        return None

    compilation = payload.get("compilation")
    compiler_version = ""
    if isinstance(compilation, Mapping):
        compiler_version = _clean_version(compilation.get("compiler_version"))

    main = max(files.items(), key=lambda item: len(item[1]))[0]
    return SourceArtifact(
        code=files[main],
        files=files,
        compiler_version=compiler_version,
        source_uri=uri,
        source_kind=KIND_SOURCIFY,
        verified=True,
    )


def fetch_verified_source(
    chain_id: int,
    address: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> SourceArtifact | None:
    """Fetch a contract's verified source.

    Args:
        chain_id: The EIP-155 chain the contract lives on.
        address: The contract address.
        timeout: The per-request timeout in seconds.

    Returns:
        The source, or ``None`` when no route could serve it. ``None`` is
        the normal answer for an unverified contract, and is never an
        error.
    """
    if not address:
        return None

    instance_url = _instance_url(chain_id, address)
    if instance_url is not None:
        try:
            response = httpx.get(
                instance_url,
                timeout=timeout,
                follow_redirects=True,
                headers={"Accept": "application/json"},
            )
            if response.status_code == 200:
                artifact = _from_instance(response.json(), instance_url)
                if artifact is not None:
                    log.info(
                        "source_fetched",
                        route="instance",
                        address=address,
                        chain_id=chain_id,
                    )
                    return artifact
            else:
                log.info(
                    "instance_source_unavailable",
                    status=response.status_code,
                    address=address,
                    chain_id=chain_id,
                )
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("instance_source_fetch_failed", url=instance_url, error=str(exc))

    sourcify_url = f"{SOURCIFY_BASE_URL}/contract/{chain_id}/{address}?fields=all"
    try:
        response = httpx.get(
            sourcify_url,
            timeout=timeout,
            follow_redirects=True,
            headers={"Accept": "application/json"},
        )
        if response.status_code == 200:
            artifact = _from_sourcify(response.json(), sourcify_url)
            if artifact is not None:
                log.info(
                    "source_fetched",
                    route="sourcify",
                    address=address,
                    chain_id=chain_id,
                )
                return artifact
        else:
            log.info(
                "sourcify_source_unavailable",
                status=response.status_code,
                address=address,
                chain_id=chain_id,
            )
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("sourcify_source_fetch_failed", url=sourcify_url, error=str(exc))

    return None


__all__ = [
    "DEFAULT_TIMEOUT",
    "KIND_INSTANCE",
    "KIND_SOURCIFY",
    "SourceArtifact",
    "fetch_verified_source",
]
