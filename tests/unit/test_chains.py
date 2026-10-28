"""Tests for the multi-chain registry."""

from __future__ import annotations

import pytest

from app.services.chains import (
    BLOCKED_INSTANCE_HOSTS,
    INSTANCE_HOSTS,
    INSTANCE_MAX_ITEMS_PER_PAGE,
    PRO_API_BASE,
    PRO_CREDITS_PER_CALL,
    PRO_DAILY_CREDIT_BUDGET,
    PRO_MAX_CONCURRENCY,
    PRO_MAX_ITEMS_PER_PAGE,
    PRO_MAX_RPS,
    PRO_OK,
    PRO_PLAN_REQUIRED,
    PRO_PLAN_REQUIRED_CHAINS,
    PRO_UNSUPPORTED,
    SUPPORTED_CHAINS,
    Chain,
    ChainRegistry,
    all_chains,
    explorer_host_for,
    get_chain,
    instance_backed_chains,
    pro_available_for,
    pro_only_chains,
    registry,
    supports_chain,
    unreachable_chains,
)

#: The 59 chain ids CyberStratum is scoped to.
EXPECTED_CHAIN_IDS = frozenset(
    {
        1,
        10,
        30,
        61,
        100,
        122,
        130,
        137,
        177,
        239,
        291,
        314,
        324,
        360,
        42220,
        4326,
        480,
        488,
        592,
        698,
        714,
        747,
        869,
        957,
        102030,
        1135,
        1729,
        1829,
        1868,
        1890,
        2020,
        2288,
        2366,
        34443,
        42161,
        42170,
        42793,
        4663,
        5042,
        529375,
        57073,
        6497,
        6498,
        7000,
        8021,
        8453,
        97741,
        98866,
        13371,
        1514,
        190415,
        245022934,
        612055,
        685689,
        97477,
        101010,
        32769,
        1088,
        1313161554,
        534352,
    }
)

#: The per-chain instances that were verified to answer a real request.
#:
#: Measured on 2026-10-28 against the Blockscout registry. Every one of
#: these hosts returned HTTP 200 with a well-formed Blockscout v2 payload.
EXPECTED_INSTANCE_HOSTS = {
    1: "eth.blockscout.com",
    10: "explorer.optimism.io",
    30: "rootstock.blockscout.com",
    61: "etc.blockscout.com",
    100: "gnosisscan.io",
    122: "explorer.fuse.io",
    130: "unichain.blockscout.com",
    177: "hsk.blockscout.com",
    239: "explorer.tac.build",
    291: "explorer.orderly.network",
    314: "filecoin.blockscout.com",
    324: "zksync.blockscout.com",
    360: "shapescan.xyz",
    42220: "celo.blockscout.com",
    4326: "megaeth.blockscout.com",
    480: "worldchain-mainnet.explorer.alchemy.com",
    488: "blackfortscan.com",
    592: "astar.blockscout.com",
    714: "eden.blockscout.com",
    747: "evm.flow.com",
    869: "explorer.worldmobile.io",
    957: "explorer.derive.xyz",
    102030: "creditcoin.blockscout.com",
    1135: "blockscout.lisk.com",
    1729: "explorer.reya.network",
    1829: "explorer.playblock.io",
    1868: "soneium.blockscout.com",
    1890: "phoenix.lightlink.io",
    2020: "explorer.roninchain.com",
    2288: "scan.mocachain.org",
    2366: "kitescan.ai",
    34443: "explorer.mode.network",
    42170: "arbitrum-nova.blockscout.com",
    42793: "explorer.etherlink.com",
    529375: "explorer.layerk.com",
    57073: "explorer.inkonchain.com",
    6497: "awaji.blockscout.com",
    6498: "mizuhiki.blockscout.com",
    7000: "zetascan.com",
    8021: "numine.blockscout.com",
    97741: "pepuscan.com",
    98866: "explorer.plume.org",
    13371: "explorer.immutable.com",
    1514: "www.datanetscan.io",
    190415: "explorer.hpp.io",
    245022934: "neon.blockscout.com",
    612055: "www.crossscan.io",
    685689: "gensyn-mainnet.explorer.alchemy.com",
    97477: "explorer.doma.xyz",
    101010: "explorer.stabilityprotocol.com",
    32769: "zilliqa.blockscout.com",
    1088: "andromeda-explorer.metis.io",
    1313161554: "explorer.mainnet.aurora.dev",
    534352: "scrollscan.com",
}

#: Chains whose instance is blocked by Cloudflare (403) or down (503).
EXPECTED_BLOCKED_HOSTS = {
    137: "polygon.blockscout.com",
    42161: "arbitrum.blockscout.com",
    4663: "robinhoodchain.blockscout.com",
    5042: "explorer.arc.io",
    698: "matchscan.io",
    8453: "base.blockscout.com",
}


def test_registry_covers_the_full_chain_scope() -> None:
    """The registry covers Watchdog's 59 chains plus Scroll."""
    assert len(SUPPORTED_CHAINS) == 60
    assert {chain.chain_id for chain in SUPPORTED_CHAINS} == EXPECTED_CHAIN_IDS


def test_chain_ids_are_unique() -> None:
    """No chain id appears twice."""
    ids = [chain.chain_id for chain in SUPPORTED_CHAINS]
    assert len(ids) == len(set(ids))


def test_slugs_are_unique_and_snake_case() -> None:
    """Slugs identify a chain uniquely and use lowercase snake case."""
    slugs = [chain.slug for chain in SUPPORTED_CHAINS]
    assert len(slugs) == len(set(slugs))
    for slug in slugs:
        assert slug == slug.lower()
        assert " " not in slug
        assert slug.replace("_", "").isalnum()


def test_ethereum_base_metis_and_aurora_are_present() -> None:
    """The chains called out explicitly by name are registered."""
    ethereum = get_chain(1)
    assert ethereum is not None
    assert ethereum.slug == "ethereum"
    assert ethereum.name == "Ethereum"
    base = get_chain(8453)
    assert base is not None
    assert base.slug == "base"
    assert get_chain(1088) is not None
    assert get_chain(1088).slug == "metis"  # type: ignore[union-attr]
    assert get_chain(1313161554) is not None
    assert get_chain(1313161554).slug == "aurora"  # type: ignore[union-attr]


def test_explorer_host_is_set_for_the_verified_instances_only() -> None:
    """Only the verified per-chain instances carry a host."""
    hosted = {
        chain.chain_id: chain.explorer_host
        for chain in SUPPORTED_CHAINS
        if chain.explorer_host is not None
    }
    assert hosted == EXPECTED_INSTANCE_HOSTS
    assert len(hosted) == 54
    # A blocked instance is recorded as blocked, not as a working host.
    for chain_id in BLOCKED_INSTANCE_HOSTS:
        assert chain_id not in hosted


def test_instance_hosts_mapping_matches_the_measured_set() -> None:
    """The host mapping is exactly the set that was probed successfully."""
    assert INSTANCE_HOSTS == EXPECTED_INSTANCE_HOSTS
    assert explorer_host_for(534352) == "scrollscan.com"


def test_blocked_instances_are_recorded_separately() -> None:
    """The blocked hosts are known, so a failure can be explained."""
    assert BLOCKED_INSTANCE_HOSTS == EXPECTED_BLOCKED_HOSTS
    # None of them is offered as a working instance.
    for chain_id in BLOCKED_INSTANCE_HOSTS:
        assert explorer_host_for(chain_id) is None


def test_get_returns_none_for_unknown_chain() -> None:
    """An unknown chain id yields ``None`` rather than raising."""
    assert get_chain(999_999) is None
    assert registry.get(999_999) is None
    assert get_chain(0) is None


def test_all_is_sorted_by_chain_id() -> None:
    """The chain list is ordered by chain id."""
    chains = all_chains()
    assert [chain.chain_id for chain in chains] == sorted(
        chain.chain_id for chain in chains
    )


def test_the_three_route_categories_partition_the_registry() -> None:
    """Every chain is instance-backed, PRO-only, or unreachable -- never both."""
    instance_backed = instance_backed_chains()
    pro_only = pro_only_chains()
    unreachable = unreachable_chains()

    assert len(instance_backed) + len(pro_only) + len(unreachable) == len(
        SUPPORTED_CHAINS
    )
    assert {chain.chain_id for chain in instance_backed}.isdisjoint(
        {chain.chain_id for chain in pro_only}
    )
    assert {chain.chain_id for chain in instance_backed}.isdisjoint(
        {chain.chain_id for chain in unreachable}
    )
    assert {chain.chain_id for chain in pro_only}.isdisjoint(
        {chain.chain_id for chain in unreachable}
    )
    assert all(chain.explorer_host is not None for chain in instance_backed)
    assert all(chain.explorer_host is None for chain in pro_only)
    assert all(chain.explorer_host is None for chain in unreachable)


def test_only_polygon_and_base_are_unreachable() -> None:
    """On the free PRO key, exactly two chains have no working route."""
    unreachable = {chain.chain_id for chain in unreachable_chains()}
    assert unreachable == {137, 8453}
    # Both are blocked at the instance and plan-gated at PRO.
    for chain_id in unreachable:
        assert chain_id in BLOCKED_INSTANCE_HOSTS
        assert chain_id in PRO_PLAN_REQUIRED_CHAINS


def test_pro_availability_matches_the_measured_map() -> None:
    """The PRO route's per-chain status is the measured one."""
    assert pro_available_for(1) is True
    assert pro_available_for(137) is False
    assert pro_available_for(324) is False
    assert pro_available_for(1088) is False
    polygon = get_chain(137)
    assert polygon is not None
    assert polygon.pro_status == PRO_PLAN_REQUIRED
    metis = get_chain(1088)
    assert metis is not None
    assert metis.pro_status == PRO_UNSUPPORTED
    ethereum = get_chain(1)
    assert ethereum is not None
    assert ethereum.pro_status == PRO_OK


def test_route_preference_is_instance_first() -> None:
    """A chain with an instance lists the instance route first."""
    ethereum = get_chain(1)
    assert ethereum is not None
    assert ethereum.routes[0] == "instance"
    assert ethereum.reachable is True
    # A chain with neither route is not reachable.
    base = get_chain(8453)
    assert base is not None
    assert base.routes == ()
    assert base.reachable is False


def test_supports_matches_the_registry() -> None:
    """``supports`` agrees with ``get`` for every known chain."""
    for chain in SUPPORTED_CHAINS:
        assert supports_chain(chain.chain_id) is True
    assert supports_chain(999_999) is False


def test_get_by_slug_resolves_a_chain() -> None:
    """Chains can also be looked up by their slug."""
    chain = registry.get_by_slug("polygon")
    assert chain is not None
    assert chain.chain_id == 137
    assert registry.get_by_slug("nope") is None


def test_registry_can_be_built_from_an_explicit_subset() -> None:
    """A registry over a custom chain list behaves like the default one."""
    ethereum = get_chain(1)
    assert ethereum is not None
    subset = ChainRegistry((ethereum,))
    assert len(subset) == 1
    assert subset.get(1) == ethereum
    assert subset.get(137) is None
    assert subset.instance_backed() == [ethereum]
    assert subset.pro_only() == []


def test_chains_are_immutable() -> None:
    """The chain records cannot be mutated after creation."""
    chain = get_chain(1)
    assert chain is not None
    with pytest.raises((AttributeError, TypeError)):
        chain.name = "Not Ethereum"  # type: ignore[misc]


def test_pro_constants_match_the_measured_limits() -> None:
    """The route constants encode what was measured, not what was assumed."""
    assert PRO_API_BASE == "https://api.blockscout.com/v2/api"
    assert PRO_CREDITS_PER_CALL == 20
    assert PRO_DAILY_CREDIT_BUDGET == 100_000
    assert PRO_MAX_RPS == 5
    # Measured: 4 concurrent PRO calls succeed, 6 answer 429.
    assert PRO_MAX_CONCURRENCY == 3
    # Measured: PRO returns exactly 10 items whatever items_count asks for.
    assert PRO_MAX_ITEMS_PER_PAGE == 10
    # Measured: an instance answers 422 above 50 items.
    assert INSTANCE_MAX_ITEMS_PER_PAGE == 50


def test_chain_records_expose_the_expected_fields() -> None:
    """Each chain carries the metadata the discovery layer needs."""
    for chain in SUPPORTED_CHAINS:
        assert isinstance(chain, Chain)
        assert chain.name
        assert chain.ecosystem
        assert chain.explorer_host is None or "." in chain.explorer_host
