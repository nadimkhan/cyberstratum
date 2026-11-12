"""Tests for the CORS origin configuration.

The frontend is deployed to Netlify, where each site has its own origin and
preview deploys add more. The API therefore needs to allow a list of browser
origins, not a single one, while still refusing anything not on the list.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings


def _settings(**overrides: str) -> Settings:
    base: dict[str, object] = {
        "APP_ENV": "production",
        "WEB_BASE_URL": "https://cyberstratum.netlify.app",
        "CORS_EXTRA_ORIGINS": "",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_single_origin_is_used_when_no_extras_are_configured() -> None:
    settings = _settings()
    assert settings.cors_origins == ["https://cyberstratum.netlify.app"]


def test_extra_origins_are_appended() -> None:
    settings = _settings(CORS_EXTRA_ORIGINS="https://app.example.com,https://staging.example.com")
    assert settings.cors_origins == [
        "https://cyberstratum.netlify.app",
        "https://app.example.com",
        "https://staging.example.com",
    ]


def test_whitespace_and_trailing_slashes_are_normalised() -> None:
    settings = _settings(CORS_EXTRA_ORIGINS="  https://app.example.com/  ,  ")
    assert settings.cors_origins == [
        "https://cyberstratum.netlify.app",
        "https://app.example.com",
    ]


def test_duplicate_origins_are_collapsed() -> None:
    settings = _settings(
        CORS_EXTRA_ORIGINS="https://cyberstratum.netlify.app,https://app.example.com"
    )
    assert settings.cors_origins == [
        "https://cyberstratum.netlify.app",
        "https://app.example.com",
    ]


def test_an_origin_may_be_listed_in_either_variable() -> None:
    settings = _settings(
        WEB_BASE_URL="https://a.example.com,https://b.example.com",
        CORS_EXTRA_ORIGINS="https://c.example.com",
    )
    assert settings.cors_origins == [
        "https://a.example.com",
        "https://b.example.com",
        "https://c.example.com",
    ]


def test_empty_origins_are_dropped() -> None:
    settings = _settings(WEB_BASE_URL="", CORS_EXTRA_ORIGINS="")
    assert settings.cors_origins == []


def test_the_api_advertises_only_the_configured_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The running app must not widen CORS beyond the configured list."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    settings = _settings()
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)

    app = create_app()
    with TestClient(app) as client:
        allowed = client.options(
            "/api/v1/scans",
            headers={
                "Origin": "https://cyberstratum.netlify.app",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert allowed.status_code == 200
        assert allowed.headers["access-control-allow-origin"] == (
            "https://cyberstratum.netlify.app"
        )

        refused = client.options(
            "/api/v1/scans",
            headers={
                "Origin": "https://not-allowed.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert "access-control-allow-origin" not in refused.headers


@pytest.mark.parametrize("origin", ["http://evil.example.com", "null"])
def test_unlisted_origins_receive_no_cors_grant(
    monkeypatch: pytest.MonkeyPatch, origin: str
) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    settings = _settings()
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)

    app = create_app()
    with TestClient(app) as client:
        response = client.options(
            "/api/v1/scans",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert "access-control-allow-origin" not in response.headers
