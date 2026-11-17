"""The third-party notices.

The notices exist to make the licence posture checkable rather than
merely stated. These tests hold them to that: every component carries a
licence, the copyleft components are named, and no copyleft component is
imported, modified, or handed to a customer.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services.notices import load_notices


@pytest.fixture()
def notices():
    return load_notices()


def test_every_component_carries_a_licence_and_a_version(notices) -> None:
    assert notices.components, "the product is built on something"
    for component in notices.components:
        assert component.get("name")
        assert component.get("version")
        assert component.get("spdx_id")
        assert component.get("license_url", "").startswith("http")


def test_every_component_says_how_it_is_used(notices) -> None:
    for component in notices.components:
        assert component.get("usage")
        for fact in ("imported", "modified", "conveyed_to_customers"):
            assert isinstance(component.get(fact), bool), f"{component['name']} does not say {fact}"


def test_the_copyleft_components_are_named(notices) -> None:
    assert "Slither" in notices.copyleft_components


def test_no_copyleft_component_breaks_the_boundary(notices) -> None:
    assert notices.unsafe_components == ()


def test_the_datasets_carry_their_licence_and_terms(notices) -> None:
    assert notices.datasets, "the product intends to draw on corpora"
    for dataset in notices.datasets:
        assert dataset.get("dataset")
        assert dataset.get("spdx_id")
        assert dataset.get("upstream_url", "").startswith("http")
        assert dataset.get("note")
        assert isinstance(dataset.get("derived_artifacts_may_be_redistributed"), bool)


def test_an_unaudited_dataset_is_not_treated_as_resolved(notices) -> None:
    web3bugs = next(item for item in notices.datasets if item["dataset"] == "Web3Bugs")
    assert web3bugs["per_repository_audit_required"] is True
    assert web3bugs["derived_artifacts_may_be_redistributed"] is False


def test_the_endpoint_serves_the_notices_to_a_caller(
    client: TestClient, api_headers: dict[str, str]
) -> None:
    response = client.get("/api/v1/notices", headers=api_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["version"]
    assert payload["components"], "the notices served nothing"
    names = {item["name"] for item in payload["components"]}
    assert "Slither" in names
    assert "Mythril" in names
    assert payload["datasets"]
