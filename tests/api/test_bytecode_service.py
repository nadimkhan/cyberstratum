"""Tests for the bytecode acquisition service.

The network is never contacted: ``httpx`` is stubbed so each source can be
exercised in isolation.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.services import bytecode as bytecode_service
from app.services.bytecode import BytecodeUnavailableError, fetch_runtime_bytecode

ADDRESS = "0x" + "ab" * 20
CODE = bytes.fromhex("6000556000")


def _json_response(payload: Any, status_code: int = 200) -> httpx.Response:
    """Build an httpx response carrying ``payload`` as JSON."""
    return httpx.Response(
        status_code=status_code,
        json=payload,
        request=httpx.Request("GET", "https://example.test"),
    )


def test_fetch_returns_rpc_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """A working RPC yields the bytecode with the ``rpc`` source."""
    seen: list[str] = []

    def fake_post(url: str, *, json: Any, timeout: float) -> httpx.Response:
        seen.append(url)
        return _json_response({"jsonrpc": "2.0", "id": 1, "result": "0x" + CODE.hex()})

    monkeypatch.setattr(bytecode_service.httpx, "post", fake_post)
    artifact = fetch_runtime_bytecode(ADDRESS, 1)

    assert artifact.code == CODE
    assert artifact.source == "rpc"
    assert artifact.sha256 and len(artifact.sha256) == 64
    assert artifact.size == len(CODE)
    assert seen


def test_fetch_falls_back_to_sourcify(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the RPC is unreachable, the Sourcify fallback supplies the code."""
    monkeypatch.setattr(
        bytecode_service.httpx,
        "post",
        lambda *a, **k: _raise(httpx.ConnectError("blocked")),
    )
    requested: list[str] = []

    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        requested.append(url)
        return _json_response(
            {
                "runtimeBytecode": {
                    "onchainBytecode": "0x" + CODE.hex(),
                }
            }
        )

    monkeypatch.setattr(bytecode_service.httpx, "get", fake_get)
    artifact = fetch_runtime_bytecode(ADDRESS, 1)

    assert artifact.code == CODE
    assert artifact.source == "sourcify"
    assert requested and "sourcify.dev" in requested[0]


def test_fetch_raises_when_no_source_has_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unreachable RPC and an unverified Sourcify contract raise."""
    monkeypatch.setattr(
        bytecode_service.httpx,
        "post",
        lambda *a, **k: _raise(httpx.ConnectError("blocked")),
    )
    monkeypatch.setattr(
        bytecode_service.httpx,
        "get",
        lambda *a, **k: _json_response({"runtimeBytecode": {}}),
    )

    with pytest.raises(BytecodeUnavailableError) as excinfo:
        fetch_runtime_bytecode(ADDRESS, 1)
    assert excinfo.value.code == "sourcify_unavailable"


def test_fetch_raises_on_empty_contract_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """A contract with no deployed code is reported distinctly."""

    def fake_post(url: str, *, json: Any, timeout: float) -> httpx.Response:
        return _json_response({"jsonrpc": "2.0", "id": 1, "result": "0x"})

    monkeypatch.setattr(bytecode_service.httpx, "post", fake_post)
    monkeypatch.setattr(
        bytecode_service.httpx,
        "get",
        lambda *a, **k: _json_response({"runtimeBytecode": {}}),
    )
    with pytest.raises(BytecodeUnavailableError) as excinfo:
        fetch_runtime_bytecode(ADDRESS, 1)
    assert excinfo.value.code == "bytecode_empty"


def test_fetch_raises_for_chain_without_any_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """A chain with neither an RPC nor Sourcify coverage is refused up front."""
    monkeypatch.setattr(bytecode_service, "_rpc_urls", lambda chain_id: [])
    with pytest.raises(BytecodeUnavailableError) as excinfo:
        fetch_runtime_bytecode(ADDRESS, 999999)
    assert excinfo.value.code == "rpc_not_configured"


def test_sourcify_url_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Sourcify request asks for the fields that carry the bytecode."""
    monkeypatch.setattr(
        bytecode_service.httpx,
        "post",
        lambda *a, **k: _raise(httpx.ConnectError("blocked")),
    )
    requested: list[str] = []

    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        requested.append(url)
        return _json_response({"runtimeBytecode": {"onchainBytecode": "0x" + CODE.hex()}})

    monkeypatch.setattr(bytecode_service.httpx, "get", fake_get)
    fetch_runtime_bytecode(ADDRESS, 1)
    assert requested[0].endswith(f"/contract/1/{ADDRESS}?fields=all")


def _raise(exc: Exception) -> httpx.Response:
    """Raise ``exc``; used to simulate transport failures."""
    raise exc
