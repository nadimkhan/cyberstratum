"""Tests for fetching a contract's verified source.

The routes are stubbed at the HTTP layer so the suite never touches the
network.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.services import source_fetch
from app.services.source_fetch import (
    KIND_INSTANCE,
    KIND_SOURCIFY,
    SourceArtifact,
    fetch_verified_source,
)


class FakeResponse:
    """A minimal stand-in for an httpx response."""

    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        """Return the decoded payload."""
        if self._payload is None:
            raise ValueError("no JSON body")
        return self._payload


@pytest.fixture()
def routes(monkeypatch: pytest.MonkeyPatch) -> dict[str, FakeResponse]:
    """Stub the two source routes."""
    table: dict[str, FakeResponse] = {}

    def fake_get(url: str, **_kwargs: object) -> FakeResponse:
        for fragment, response in table.items():
            if fragment in url:
                return response
        return FakeResponse(404)

    monkeypatch.setattr(source_fetch.httpx, "get", fake_get)
    return table


def test_the_instance_route_is_preferred(routes: dict[str, FakeResponse]) -> None:
    """A chain with its own instance does not need Sourcify."""
    routes["/api/v2/smart-contracts/"] = FakeResponse(
        200,
        {
            "source_code": "contract A {}",
            "name": "A.sol",
            "compiler_version": "v0.8.26+commit.8a97fa7a",
            "is_verified": True,
        },
    )

    artifact = fetch_verified_source(1, "0x" + "11" * 20)

    assert artifact is not None
    assert artifact.source_kind == KIND_INSTANCE
    assert artifact.code == "contract A {}"
    assert artifact.compiler_version == "0.8.26"
    assert artifact.verified is True
    assert artifact.files == {"A.sol": "contract A {}"}


def test_the_instance_additional_sources_are_kept(routes: dict[str, FakeResponse]) -> None:
    """The imported files are kept, so a multi-file project can compile."""
    routes["/api/v2/smart-contracts/"] = FakeResponse(
        200,
        {
            "source_code": 'import "./Lib.sol"; contract A {}',
            "name": "A.sol",
            "additional_sources": [
                {"file_name": "Lib.sol", "source_code": "library L {}"},
                {"file_name": "empty.sol", "source_code": "   "},
            ],
        },
    )

    artifact = fetch_verified_source(1, "0x" + "22" * 20)

    assert artifact is not None
    assert artifact.files == {
        "A.sol": 'import "./Lib.sol"; contract A {}',
        "Lib.sol": "library L {}",
    }
    # The largest file is the main one.
    assert artifact.main_file_name == "A.sol"


def test_sourcify_is_the_fallback(routes: dict[str, FakeResponse]) -> None:
    """When the instance has nothing, Sourcify is tried."""
    routes["/api/v2/smart-contracts/"] = FakeResponse(404)
    routes["sourcify.dev"] = FakeResponse(
        200,
        {
            "sources": {
                "contracts/A.sol": {"content": "contract A {}"},
                "contracts/Lib.sol": {"content": "library L {}"},
            },
            "compilation": {"compiler_version": "0.8.24"},
        },
    )

    artifact = fetch_verified_source(1, "0x" + "33" * 20)

    assert artifact is not None
    assert artifact.source_kind == KIND_SOURCIFY
    assert artifact.compiler_version == "0.8.24"
    assert set(artifact.files) == {"contracts/A.sol", "contracts/Lib.sol"}


def test_an_unverified_contract_yields_nothing(routes: dict[str, FakeResponse]) -> None:
    """No source anywhere means no source, and that is not an error."""
    routes["/api/v2/smart-contracts/"] = FakeResponse(
        200, {"source_code": "", "is_verified": False}
    )
    routes["sourcify.dev"] = FakeResponse(404)

    assert fetch_verified_source(1, "0x" + "44" * 20) is None


def test_a_failing_route_yields_nothing(routes: dict[str, FakeResponse]) -> None:
    """A 500 on both routes means no source."""
    routes["/api/v2/smart-contracts/"] = FakeResponse(500)
    routes["sourcify.dev"] = FakeResponse(500)

    assert fetch_verified_source(1, "0x" + "55" * 20) is None


def test_an_empty_address_yields_nothing() -> None:
    """There is nothing to look up without an address."""
    assert fetch_verified_source(1, "") is None


def test_a_chain_without_an_instance_goes_straight_to_sourcify(
    routes: dict[str, FakeResponse],
) -> None:
    """A chain with no instance still gets its source from Sourcify."""
    routes["sourcify.dev"] = FakeResponse(
        200, {"sources": {"A.sol": {"content": "contract A {}"}}}
    )

    artifact = fetch_verified_source(999999, "0x" + "66" * 20)

    assert artifact is not None
    assert artifact.source_kind == KIND_SOURCIFY


def test_a_network_error_is_contained(
    monkeypatch: pytest.MonkeyPatch, routes: dict[str, FakeResponse]
) -> None:
    """A transport failure is a missing source, not a crash."""

    def boom(*_a: object, **_k: object) -> FakeResponse:
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(source_fetch.httpx, "get", boom)

    assert fetch_verified_source(1, "0x" + "77" * 20) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0.8.26", "0.8.26"),
        ("v0.8.26", "0.8.26"),
        ("0.8.26+commit.8a97fa7a", "0.8.26"),
        ("0.8.26 (commit.8a97fa7a)", "0.8.26"),
        ("", ""),
        (None, ""),
    ],
)
def test_the_compiler_version_is_normalised(raw: str | None, expected: str) -> None:
    """Every route's version shape becomes the plain form solc wants."""
    assert source_fetch._clean_version(raw) == expected


def test_the_artifact_names_a_main_file() -> None:
    """An artifact with no files still names a main file."""
    artifact = SourceArtifact(code="contract A {}")
    assert artifact.main_file_name == "Contract.sol"


def test_the_httpx_client_is_not_shared() -> None:
    """The module uses the module-level helpers, not a shared client."""
    assert hasattr(source_fetch.httpx, "get")
