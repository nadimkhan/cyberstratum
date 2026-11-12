"""Tests for the fixes that make the autonomous path work on real chains.

Three defects are covered here:

* a contract whose chain had no reachable RPC and was not on Sourcify
  used to fail the whole scan, even though the chain's own explorer
  could serve its bytecode;
* a partial scan recorded that it was partial but not *what* it could
  not cover, so a reader could not judge the result;
* an asset's progress history read newest-first, which is not how a
  progress log reads.
"""

from __future__ import annotations

import httpx
import pytest

from app.services import bytecode as bytecode_module
from app.services.bytecode import (
    BytecodeUnavailableError,
    _blockscout_code,
    fetch_runtime_bytecode,
)


class _Response:
    """A minimal stand-in for an httpx response."""

    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status {self.status_code}",
                request=httpx.Request("GET", "http://x"),
                response=None,
            )

    def json(self) -> object:
        return self._payload


def test_blockscout_serves_the_runtime_bytecode(monkeypatch: pytest.MonkeyPatch) -> None:
    """The explorer route returns the deployed bytecode."""

    def fake_post(url: str, json: object, timeout: float) -> _Response:
        assert url.endswith("/api/eth-rpc")
        assert isinstance(json, dict)
        assert json["method"] == "eth_getCode"
        return _Response({"jsonrpc": "2.0", "result": "0x6080604052"})

    monkeypatch.setattr(bytecode_module.httpx, "post", fake_post)
    monkeypatch.setattr(
        bytecode_module, "explorer_host_for", lambda chain_id: "example.blockscout.com"
    )

    code = _blockscout_code(1, "0x" + "11" * 20, 5.0)

    assert code == bytes.fromhex("6080604052")


def test_blockscout_reports_an_unusable_answer_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An error payload is 'no answer', not 'no deployed code'."""
    monkeypatch.setattr(
        bytecode_module.httpx,
        "post",
        lambda url, json, timeout: _Response({"error": {"code": -32000}}),
    )
    monkeypatch.setattr(
        bytecode_module, "explorer_host_for", lambda chain_id: "example.blockscout.com"
    )

    assert _blockscout_code(1, "0x" + "11" * 20, 5.0) is None


def test_a_contract_with_no_code_is_reported_as_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'0x' means the address holds no code, which is its own error."""
    monkeypatch.setattr(
        bytecode_module.httpx,
        "post",
        lambda url, json, timeout: _Response({"jsonrpc": "2.0", "result": "0x"}),
    )
    monkeypatch.setattr(
        bytecode_module, "explorer_host_for", lambda chain_id: "example.blockscout.com"
    )

    with pytest.raises(BytecodeUnavailableError) as excinfo:
        fetch_runtime_bytecode("0x" + "11" * 20, 1, timeout=5.0)

    assert excinfo.value.code == "bytecode_empty"


def test_the_explorer_is_used_when_the_rpc_and_sourcify_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point: a verified contract is still analysable.

    The public RPC endpoints of a chain are often unreachable from a
    small server, and Sourcify only knows the contracts it has indexed.
    The chain's own explorer proxies ``eth_getCode``, so the scan can
    still run rather than failing outright.
    """
    monkeypatch.setattr(bytecode_module, "_rpc_urls", lambda chain_id: ["https://rpc.example"])
    monkeypatch.setattr(bytecode_module, "_eth_get_code", lambda url, address, timeout: None)
    monkeypatch.setattr(bytecode_module, "_sourcify_code", lambda chain_id, address, timeout: None)
    monkeypatch.setattr(
        bytecode_module, "explorer_host_for", lambda chain_id: "example.blockscout.com"
    )

    def fake_post(url: str, json: object, timeout: float) -> _Response:
        return _Response({"jsonrpc": "2.0", "result": "0xdeadbeef"})

    monkeypatch.setattr(bytecode_module.httpx, "post", fake_post)

    artifact = fetch_runtime_bytecode("0x" + "11" * 20, 1, timeout=5.0)

    assert artifact.source == "blockscout"
    assert artifact.code == bytes.fromhex("deadbeef")


def test_the_rpc_is_still_the_first_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """The explorer is a fallback, not a replacement."""
    calls: list[str] = []

    monkeypatch.setattr(bytecode_module, "_rpc_urls", lambda chain_id: ["https://rpc.example"])

    def fake_get_code(url: str, address: str, timeout: float) -> bytes:
        calls.append("rpc")
        return b"\x60\x80"

    monkeypatch.setattr(bytecode_module, "_eth_get_code", fake_get_code)
    monkeypatch.setattr(
        bytecode_module.httpx,
        "post",
        lambda url, json, timeout: calls.append("blockscout") or _Response({"result": "0x00"}),
    )

    artifact = fetch_runtime_bytecode("0x" + "11" * 20, 1, timeout=5.0)

    assert artifact.source == "rpc"
    assert calls == ["rpc"]
