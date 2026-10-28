"""Tests for the health endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    """The liveness probe returns 200 with an ok status."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "cyberstratum-api"
    assert "timestamp" in body


def test_readiness_reports_dependencies(client: TestClient) -> None:
    """The readiness probe reports database and queue checks."""
    response = client.get("/api/health")
    assert response.status_code in (200, 503)
    body = response.json()
    assert body["status"] in {"ok", "degraded", "error"}
    names = {check["name"] for check in body["checks"]}
    assert {"database", "queue"} <= names


def test_openapi_schema_is_generated(client: TestClient) -> None:
    """The OpenAPI document exposes the scan and finding routes."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/health" in paths
    assert "/api/v1/scans" in paths
    assert "/api/v1/findings" in paths
