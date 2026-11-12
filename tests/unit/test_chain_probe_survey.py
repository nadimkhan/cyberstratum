"""The registry and the survey that justifies it must agree.

The chain registry is hand-maintained code. The survey that says which
instances actually answer is run output. Without a check between them,
the registry drifts: a chain stays listed after its instance dies, or a
chain the survey found live never gets added, and nothing complains.

The survey record is committed at ``docs/chain-probe/survey.json``. It
is the small, useful half of the probe reports -- the hosts that carry
a decision -- with the dead hostnames counted rather than listed.

What these tests assert
------------------------

* Every chain the registry points at a working instance for was seen
  live by the survey.
* Every chain the survey saw live is in the registry.
* Every chain the registry has marked as blocked was *not* seen live,
  so the "blocked" list cannot quietly grow into a lie.
* The survey's own totals add up.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.chains import (
    BLOCKED_INSTANCE_HOSTS,
    INSTANCE_HOSTS,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SURVEY_PATH = REPO_ROOT / "docs" / "chain-probe" / "survey.json"


@pytest.fixture(scope="module")
def survey() -> dict:
    """The committed survey record."""
    if not SURVEY_PATH.exists():
        pytest.fail(
            f"{SURVEY_PATH} is missing. The survey record is what justifies "
            "the chain registry, so it belongs in the repository."
        )
    with SURVEY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def live_by_host(survey: dict) -> dict[str, dict]:
    """The hosts the survey saw live.

    The registry stores hosts, and the survey's entries are keyed by
    host too. The chain id is only recorded for a chain the probe
    *discovered*; a host that was already in the registry was recorded
    without one, which is why the comparison is by host.
    """
    return {entry["host"]: entry for entry in survey["chains"] if entry["status"] == "live"}


def test_the_survey_totals_add_up(survey: dict) -> None:
    totals = survey["totals"]
    assert sum(totals["by_status"].values()) == totals["probed"]


def test_every_registry_instance_was_seen_live(live_by_host: dict[str, dict]) -> None:
    """The registry must not claim an instance the survey never saw."""
    missing = [
        f"{chain_id} ({host})"
        for chain_id, host in sorted(INSTANCE_HOSTS.items())
        if host not in live_by_host
    ]
    assert missing == [], f"chains in the registry with no live survey entry: {missing}"


def test_every_discovered_chain_is_in_the_registry(survey: dict) -> None:
    """A chain the survey found must be scanned by the product."""
    missing = [
        f"{entry['chain_id']} ({entry['host']})"
        for entry in survey["chains"]
        if entry["status"] == "live"
        and entry.get("chain_id") is not None
        and entry["chain_id"] not in INSTANCE_HOSTS
    ]
    assert missing == [], f"chains the survey saw live but the registry does not carry: {missing}"


def test_a_blocked_chain_was_not_also_seen_live(live_by_host: dict[str, dict]) -> None:
    """The blocked list must not quietly become a claim of working."""
    wrong = [
        f"{chain_id} ({host})"
        for chain_id, host in sorted(BLOCKED_INSTANCE_HOSTS.items())
        if host in live_by_host
    ]
    assert wrong == [], f"chains marked blocked that the survey saw live: {wrong}"
