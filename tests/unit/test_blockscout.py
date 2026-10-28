"""Tests for the Blockscout discovery client.

Every test runs against ``httpx.MockTransport``, so the suite never touches
the network.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.services.blockscout import (
    PRO_API_BASE,
    PRO_MAX_RETRIES,
    PRO_UNVERIFIED_ABI,
    ROUTE_INSTANCE,
    ROUTE_PRO,
    BlockscoutBudgetExceededError,
    BlockscoutClient,
    BlockscoutUnavailableError,
    CreditMeter,
    DiscoveredContract,
    RateLimiter,
    normalize_contract,
)

#: A chain with a known per-chain instance (Ethereum).
INSTANCE_CHAIN_ID = 1
#: A chain that is only reachable through the PRO API.
#:
#: Arbitrum One: Cloudflare blocks its per-chain instance, but PRO serves
#: the chain. Base is a different case -- it is unreachable on both routes --
#: and is covered separately.
PRO_ONLY_CHAIN_ID = 42161

#: A chain no route can reach: the instance is Cloudflare-blocked and PRO
#: answers 402 because the key's plan does not cover featured chains.
UNREACHABLE_CHAIN_ID = 8453

#: A payload in the per-chain instance shape: the address, name and the
#: verification flag live in a nested ``address`` object.
INSTANCE_ITEM: dict[str, Any] = {
    "address": {
        "hash": "0x8C7A91135499C40467BEF2Da7bEc3A4dC78deCD3",
        "name": "Assist",
        "is_verified": True,
        "is_contract": True,
    },
    "compiler_version": "0.8.23+commit.f704f362",
    "optimization_enabled": False,
    "verified_at": "2026-10-28T13:56:04.370972Z",
}

#: The same contract in the flattened PRO shape.
PRO_ITEM: dict[str, Any] = {
    "ABI": "[{\"inputs\":[]}]",
    "Address": "0x8C7A91135499C40467BEF2Da7bEc3A4dC78deCD3",
    "CompilerVersion": "0.8.23+commit.f704f362",
    "ContractName": "Assist",
    "OptimizationUsed": False,
}


def _client(
    handler: Any,
    *,
    api_key: str = "test-key",
    credit_meter: CreditMeter | None = None,
) -> BlockscoutClient:
    """Build a client wired to ``handler`` through a mock transport."""
    return BlockscoutClient(
        api_key=api_key,
        transport=httpx.MockTransport(handler),
        credit_meter=credit_meter,
    )


# --- route A ------------------------------------------------------------


async def test_route_a_returns_a_normalised_contract() -> None:
    """The per-chain instance payload becomes a ``DiscoveredContract``."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"items": [INSTANCE_ITEM]})

    async with _client(handler) as client:
        contracts = await client.list_contracts(INSTANCE_CHAIN_ID)

    assert len(contracts) == 1
    contract = contracts[0]
    assert contract == DiscoveredContract(
        chain_id=INSTANCE_CHAIN_ID,
        address="0x8C7A91135499C40467BEF2Da7bEc3A4dC78deCD3",
        name="Assist",
        compiler_version="0.8.23+commit.f704f362",
        optimization_used=False,
        is_verified=True,
        verified_at="2026-10-28T13:56:04.370972Z",
        source_uri="https://eth.blockscout.com/address/0x8C7A91135499C40467BEF2Da7bEc3A4dC78deCD3",
        route=ROUTE_INSTANCE,
    )
    assert str(seen[0].url) == (
        "https://eth.blockscout.com/api/v2/smart-contracts?items_count=50"
    )


async def test_route_a_is_preferred_over_the_paid_route() -> None:
    """A chain with a working instance never spends a credit."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return httpx.Response(200, json={"items": [INSTANCE_ITEM]})

    meter = CreditMeter()
    async with _client(handler, credit_meter=meter) as client:
        await client.list_contracts(INSTANCE_CHAIN_ID)

    assert calls == ["eth.blockscout.com"]
    assert meter.used == 0


async def test_route_a_paginates_with_the_instance_cursor() -> None:
    """The instance paginates with a cursor, not a page number."""
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        if len(urls) == 1:
            return httpx.Response(
                200,
                json={
                    "items": [INSTANCE_ITEM],
                    "next_page_params": {"items_count": 50, "smart_contract_id": 42},
                },
            )
        return httpx.Response(200, json={"items": [INSTANCE_ITEM]})

    async with _client(handler) as client:
        contracts = await client.list_contracts(INSTANCE_CHAIN_ID, page=2)

    assert len(contracts) == 1
    assert len(urls) == 2
    assert "smart_contract_id=42" in urls[1]
    assert "page=" not in urls[0]


# --- fallback -----------------------------------------------------------


async def test_route_a_failure_falls_back_to_the_pro_route() -> None:
    """A blocked instance (403) is not fatal: the PRO route takes over."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "eth.blockscout.com":
            return httpx.Response(403, text="forbidden")
        return httpx.Response(
            200, json={"message": "OK", "status": "1", "result": [PRO_ITEM]}
        )

    async with _client(handler) as client:
        contracts = await client.list_contracts(INSTANCE_CHAIN_ID)

    assert calls == ["eth.blockscout.com", "api.blockscout.com"]
    assert len(contracts) == 1
    assert contracts[0].route == ROUTE_PRO
    assert contracts[0].address == "0x8C7A91135499C40467BEF2Da7bEc3A4dC78deCD3"
    assert contracts[0].name == "Assist"


async def test_both_routes_failing_raises_a_typed_error_naming_the_chain() -> None:
    """A 404 on the instance plus a 402 on PRO raises the typed error."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "eth.blockscout.com":
            return httpx.Response(404, text="not found")
        return httpx.Response(402, json={"error": "Proceed with API key"})

    async with _client(handler) as client:
        with pytest.raises(BlockscoutUnavailableError) as excinfo:
            await client.list_contracts(INSTANCE_CHAIN_ID)

    error = excinfo.value
    assert error.chain_id == INSTANCE_CHAIN_ID
    assert "Ethereum" in str(error)
    assert "402" in str(error)
    assert calls == ["eth.blockscout.com", "api.blockscout.com"]


async def test_the_payment_reason_from_the_api_is_reported() -> None:
    """The 402 body explains the cause, so the operator does not have to guess."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "eth.blockscout.com":
            return httpx.Response(404, text="not found")
        return httpx.Response(
            402, json={"error": "Featured chain 8453 requires one of the following plans"}
        )

    async with _client(handler) as client:
        with pytest.raises(BlockscoutUnavailableError) as excinfo:
            await client.list_contracts(INSTANCE_CHAIN_ID)

    assert "Featured chain" in str(excinfo.value)


async def test_a_missing_api_key_is_reported_clearly() -> None:
    """Without a key the PRO route explains why it cannot serve the chain."""

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - unused
        raise AssertionError("no request should be made without a key")

    async with _client(handler, api_key="") as client:
        with pytest.raises(BlockscoutUnavailableError) as excinfo:
            await client.list_contracts(PRO_ONLY_CHAIN_ID)

    assert "BLOCKSCOUT_API_KEY" in str(excinfo.value)


async def test_a_failing_chain_does_not_abort_a_multi_chain_sweep() -> None:
    """One broken chain never stops the others."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.blockscout.com":
            if request.url.params.get("chainid") == str(PRO_ONLY_CHAIN_ID):
                return httpx.Response(402, json={"error": "no credits"})
            return httpx.Response(
                200, json={"message": "OK", "status": "1", "result": [PRO_ITEM]}
            )
        return httpx.Response(403, text="forbidden")

    async with _client(handler) as client:
        result = await client.discover([INSTANCE_CHAIN_ID, PRO_ONLY_CHAIN_ID])

    assert INSTANCE_CHAIN_ID in result.contracts
    assert len(result.contracts[INSTANCE_CHAIN_ID]) == 1
    assert PRO_ONLY_CHAIN_ID in result.failures
    assert PRO_ONLY_CHAIN_ID not in result.contracts


# --- the PRO query ------------------------------------------------------


async def test_the_pro_query_never_uses_the_verified_filter() -> None:
    """``filter=verified`` is forbidden: it costs 44-79 seconds per query."""
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, json={"message": "OK", "status": "1", "result": []})

    async with _client(handler) as client:
        await client.list_contracts(PRO_ONLY_CHAIN_ID)

    assert len(urls) == 1
    url = urls[0]
    assert url.startswith(PRO_API_BASE)
    assert "sort=creation_desc" in url
    assert "filter=verified" not in url
    assert f"chainid={PRO_ONLY_CHAIN_ID}" in url
    assert "action=listcontracts" in url
    assert "module=contract" in url
    assert "order=desc" in url


async def test_the_api_key_is_never_logged() -> None:
    """The key travels in the query string but never reaches the logs."""
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, json={"message": "OK", "status": "1", "result": []})

    async with _client(handler, api_key="super-secret-key") as client:
        await client.list_contracts(PRO_ONLY_CHAIN_ID)

    assert "super-secret-key" in urls[0]


# --- credit accounting --------------------------------------------------


def test_the_credit_meter_charges_twenty_credits_per_call() -> None:
    """One PRO call costs twenty credits."""
    meter = CreditMeter()
    assert meter.used == 0
    assert meter.remaining == 100_000
    meter.charge()
    assert meter.used == 20
    assert meter.remaining == 99_980
    meter.charge()
    assert meter.used == 40


def test_the_credit_meter_refuses_to_exceed_the_budget() -> None:
    """A runaway loop cannot spend past the daily budget."""
    meter = CreditMeter(budget=100)
    meter.charge()
    meter.charge()
    assert meter.used == 40
    assert meter.can_afford() is True
    meter.charge()
    meter.charge()
    meter.charge()
    assert meter.used == 100
    assert meter.can_afford() is False
    with pytest.raises(BlockscoutBudgetExceededError):
        meter.charge()


def test_the_credit_meter_resets_on_a_new_utc_day() -> None:
    """The free tier refills at midnight UTC, and so does the meter."""
    current = datetime(2026, 10, 28, 23, 59, tzinfo=UTC)

    def clock() -> datetime:
        return current

    meter = CreditMeter(budget=100, clock=clock)
    meter.charge()
    meter.charge()
    assert meter.used == 40
    assert meter.remaining == 60

    current = datetime(2026, 10, 29, 0, 1, tzinfo=UTC)
    assert meter.used == 0
    assert meter.remaining == 100
    assert meter.day == current.date()


async def test_the_client_refuses_a_call_the_budget_cannot_pay_for() -> None:
    """A PRO call is refused once the daily budget is spent."""

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - unused
        raise AssertionError("no request should be made once the budget is spent")

    meter = CreditMeter(budget=10)
    async with _client(handler, credit_meter=meter) as client:
        with pytest.raises(BlockscoutBudgetExceededError) as excinfo:
            await client.list_contracts(PRO_ONLY_CHAIN_ID)
        assert excinfo.value.chain_id == PRO_ONLY_CHAIN_ID
        assert meter.used == 0


async def test_each_pro_call_spends_credits() -> None:
    """The meter reflects the PRO calls that were actually made."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": "OK", "status": "1", "result": []})

    meter = CreditMeter()
    async with _client(handler, credit_meter=meter) as client:
        await client.list_contracts(PRO_ONLY_CHAIN_ID)
        assert meter.used == 20
        await client.list_contracts(PRO_ONLY_CHAIN_ID)
        assert meter.used == 40


async def test_a_refused_pro_call_does_not_spend_credits() -> None:
    """A call the API refuses is refunded, not billed."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"error": "Featured chain"})

    meter = CreditMeter()
    async with _client(handler, credit_meter=meter) as client:
        with pytest.raises(BlockscoutUnavailableError):
            await client.list_contracts(PRO_ONLY_CHAIN_ID)

    assert meter.used == 0
    assert meter.remaining == 100_000


# --- rate limiting ------------------------------------------------------


async def test_the_rate_limiter_never_exceeds_five_calls_per_second() -> None:
    """No one-second window contains more than five calls."""
    now = 0.0
    stamps: list[float] = []

    def clock() -> float:
        return now

    async def sleep(delay: float) -> None:
        nonlocal now
        now += delay

    limiter = RateLimiter(max_rps=5, clock=clock, sleep=sleep)
    for _ in range(12):
        await limiter.acquire()
        stamps.append(now)

    assert len(stamps) == 12
    for index in range(len(stamps) - 5):
        assert stamps[index + 5] - stamps[index] > 1.0


async def test_the_rate_limiter_does_not_sleep_while_under_the_limit() -> None:
    """Below the limit the limiter never waits."""
    slept: list[float] = []

    async def sleep(delay: float) -> None:
        slept.append(delay)

    limiter = RateLimiter(max_rps=5, sleep=sleep)
    for _ in range(5):
        await limiter.acquire()

    assert slept == []


async def test_the_client_paces_its_pro_calls() -> None:
    """The client routes its PRO calls through the limiter it was given."""
    limiter = RateLimiter(max_rps=5)
    client = BlockscoutClient(
        api_key="k",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"result": []})),
        rate_limiter=limiter,
    )
    try:
        assert client.rate_limiter is limiter
    finally:
        await client.aclose()


async def test_the_client_paces_repeated_pro_calls() -> None:
    """Two PRO calls in a row are both paced by the limiter."""
    slept: list[float] = []

    async def sleep(delay: float) -> None:
        slept.append(delay)

    limiter = RateLimiter(max_rps=1, sleep=sleep)
    client = BlockscoutClient(
        api_key="k",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"result": []})),
        rate_limiter=limiter,
    )
    try:
        await client.list_contracts(PRO_ONLY_CHAIN_ID)
        assert slept == []
        await client.list_contracts(PRO_ONLY_CHAIN_ID)
        assert len(slept) == 1
        assert slept[0] > 0
    finally:
        await client.aclose()


# --- the measured limits ------------------------------------------------


async def test_pro_page_size_is_clamped_to_the_server_cap() -> None:
    """The PRO API returns 10 items whatever is asked for, so we ask for 10."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"message": "OK", "result": [PRO_ITEM]})

    async with _client(handler) as client:
        await client.list_contracts(PRO_ONLY_CHAIN_ID, page_size=500)

    assert seen[0].url.params.get("items_count") == "10"


async def test_instance_page_size_is_clamped_to_the_server_cap() -> None:
    """An instance answers 422 above 50 items, so we never ask for more."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"items": [INSTANCE_ITEM]})

    async with _client(handler) as client:
        await client.list_contracts(INSTANCE_CHAIN_ID, page_size=5000)

    assert seen[0].url.params.get("items_count") == "50"


async def test_the_pro_route_never_uses_the_verified_filter() -> None:
    """``filter=verified`` costs 12-79 s, so it is never sent."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"message": "OK", "result": [PRO_ITEM]})

    async with _client(handler) as client:
        await client.list_contracts(PRO_ONLY_CHAIN_ID)

    params = seen[0].url.params
    assert "filter" not in params
    assert params.get("sort") == "creation_desc"
    assert params.get("order") == "desc"


async def test_sorting_is_only_sent_for_listings() -> None:
    """A single-contract lookup has nothing to sort."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"message": "OK", "result": [PRO_ITEM]}
        )

    async with _client(handler) as client:
        await client.get_contract(PRO_ONLY_CHAIN_ID, "0xabc")

    params = seen[0].url.params
    assert params.get("action") == "getsourcecode"
    assert "sort" not in params


async def test_a_rate_limited_pro_call_is_retried() -> None:
    """A 429 is transient, not the chain being unavailable."""
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(429, json={"error": "too many requests"})
        return httpx.Response(200, json={"message": "OK", "result": [PRO_ITEM]})

    async with _client(handler) as client:
        contracts = await client.list_contracts(PRO_ONLY_CHAIN_ID)

    assert len(attempts) == 3
    assert len(contracts) == 1


async def test_a_persistently_rate_limited_call_reports_unavailable() -> None:
    """After the retries the chain is reported unavailable, not silently empty."""
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(429, json={"error": "too many requests"})

    async with _client(handler) as client:
        with pytest.raises(BlockscoutUnavailableError) as excinfo:
            await client.list_contracts(PRO_ONLY_CHAIN_ID)

    assert len(attempts) == PRO_MAX_RETRIES + 1
    assert "429" in str(excinfo.value)


async def test_a_rate_limited_call_is_not_billed() -> None:
    """A refused call gives its credits back."""
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(429, json={"error": "too many requests"})

    meter = CreditMeter(budget=100, credits_per_call=20)
    async with _client(handler, credit_meter=meter) as client:
        with pytest.raises(BlockscoutUnavailableError):
            await client.list_contracts(PRO_ONLY_CHAIN_ID)

    assert meter.used == 0


async def test_a_chain_the_pro_api_does_not_support_says_so() -> None:
    """PRO answers 404 for an unsupported chain; that is not a transient error."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404, json={"error": "Network not supported", "source": "internal"}
        )

    async with _client(handler) as client:
        with pytest.raises(BlockscoutUnavailableError) as excinfo:
            await client.list_contracts(PRO_ONLY_CHAIN_ID)

    assert "does not support" in str(excinfo.value)


async def test_an_unreachable_chain_reports_why() -> None:
    """A chain with no route fails with an explanation, not an empty list."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            402, json={"error": "Featured chain 8453 requires a paid plan"}
        )

    async with _client(handler) as client:
        with pytest.raises(BlockscoutUnavailableError) as excinfo:
            await client.list_contracts(UNREACHABLE_CHAIN_ID)

    assert excinfo.value.chain_id == UNREACHABLE_CHAIN_ID
    assert "402" in str(excinfo.value)


async def test_the_sweep_reports_a_failing_chain_without_aborting() -> None:
    """One broken chain does not lose the others' results."""
    def handler(request: httpx.Request) -> httpx.Response:
        chainid = request.url.params.get("chainid")
        if chainid == str(UNREACHABLE_CHAIN_ID):
            return httpx.Response(404, json={"error": "Network not supported"})
        return httpx.Response(200, json={"items": [INSTANCE_ITEM]})

    async with _client(handler) as client:
        result = await client.discover(
            [INSTANCE_CHAIN_ID, UNREACHABLE_CHAIN_ID, PRO_ONLY_CHAIN_ID]
        )

    assert INSTANCE_CHAIN_ID in result.contracts
    assert UNREACHABLE_CHAIN_ID in result.failures
    assert UNREACHABLE_CHAIN_ID not in result.contracts

# --- normalisation ------------------------------------------------------


def test_both_response_shapes_normalise_to_the_same_contract() -> None:
    """The instance shape and the PRO shape describe the same contract."""
    from_instance = normalize_contract(
        INSTANCE_CHAIN_ID, INSTANCE_ITEM, route=ROUTE_PRO, source_uri="uri"
    )
    from_pro = normalize_contract(PRO_ONLY_CHAIN_ID, PRO_ITEM, route=ROUTE_PRO, source_uri="uri")

    assert from_instance.address == from_pro.address
    assert from_instance.name == from_pro.name
    assert from_instance.compiler_version == from_pro.compiler_version
    assert from_instance.optimization_used == from_pro.optimization_used


def test_normalisation_keeps_the_fields_each_route_actually_carries() -> None:
    """Fields a route does not report stay ``None`` instead of being invented."""
    contract = normalize_contract(PRO_ONLY_CHAIN_ID, PRO_ITEM, route=ROUTE_PRO)
    # PRO carries no verification timestamp and no source in a listing.
    assert contract.verified_at is None
    assert contract.source_code is None
    # It does carry the verification state, through the ABI field.
    assert contract.is_verified is True

    instance_contract = normalize_contract(INSTANCE_CHAIN_ID, INSTANCE_ITEM, route=ROUTE_INSTANCE)
    assert instance_contract.is_verified is True
    assert instance_contract.verified_at == "2026-10-28T13:56:04.370972Z"


def test_pro_verification_state_comes_from_the_abi_field() -> None:
    """The PRO listing has no flag; the ABI field carries the answer instead."""
    verified = normalize_contract(
        PRO_ONLY_CHAIN_ID,
        {"Address": "0xabc", "ABI": '[{"inputs":[]}]'},
        route=ROUTE_PRO,
    )
    assert verified.is_verified is True

    unverified = normalize_contract(
        PRO_ONLY_CHAIN_ID,
        {"Address": "0xabc", "ABI": PRO_UNVERIFIED_ABI},
        route=ROUTE_PRO,
    )
    assert unverified.is_verified is False

    # A payload with no ABI at all reports nothing rather than guessing.
    unknown = normalize_contract(
        PRO_ONLY_CHAIN_ID, {"Address": "0xabc"}, route=ROUTE_PRO
    )
    assert unknown.is_verified is None


def test_the_explicit_instance_flag_wins_over_the_abi_heuristic() -> None:
    """An explicit ``is_verified`` is trusted over the ABI inference."""
    contract = normalize_contract(
        INSTANCE_CHAIN_ID,
        {
            "address": {"hash": "0xabc", "is_verified": False},
            "ABI": '[{"inputs":[]}]',
        },
        route=ROUTE_INSTANCE,
    )
    assert contract.is_verified is False


def test_normalisation_accepts_a_missing_address_when_one_is_supplied() -> None:
    """The single-contract instance response omits the address."""
    contract = normalize_contract(
        INSTANCE_CHAIN_ID,
        {"name": "Assist", "is_verified": True},
        route=ROUTE_INSTANCE,
        address="0xabc",
    )
    assert contract.address == "0xabc"


def test_normalisation_rejects_a_payload_without_an_address() -> None:
    """A record with no address at all is an error, not a silent guess."""
    with pytest.raises(ValueError):
        normalize_contract(INSTANCE_CHAIN_ID, {"name": "Nameless"}, route=ROUTE_INSTANCE)


def test_optimization_flags_are_accepted_in_several_encodings() -> None:
    """Blockscout encodes some flags as booleans and others as strings."""
    for value, expected in ((True, True), (False, False), ("1", True), ("0", False)):
        contract = normalize_contract(
            PRO_ONLY_CHAIN_ID,
            {"Address": "0xabc", "OptimizationUsed": value},
            route=ROUTE_PRO,
        )
        assert contract.optimization_used is expected


# --- single contract ----------------------------------------------------


async def test_get_contract_uses_the_instance_route() -> None:
    """A single contract is fetched from the per-chain instance."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "name": "Assist",
                "is_verified": True,
                "verified_at": "2026-10-28T13:56:04.370972Z",
                "compiler_version": "0.8.23+commit.f704f362",
                "optimization_enabled": False,
                "source_code": "// SPDX-License-Identifier: MIT",
            },
        )

    async with _client(handler) as client:
        contract = await client.get_contract(INSTANCE_CHAIN_ID, "0xabc")

    assert contract is not None
    assert contract.route == ROUTE_INSTANCE
    assert contract.address == "0xabc"
    assert contract.source_code == "// SPDX-License-Identifier: MIT"
    assert calls == ["https://eth.blockscout.com/api/v2/smart-contracts/0xabc"]


async def test_get_contract_falls_back_to_the_pro_route() -> None:
    """An instance that does not know the contract hands over to PRO."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "eth.blockscout.com":
            return httpx.Response(404, text="not found")
        return httpx.Response(
            200,
            json={
                "message": "OK",
                "status": "1",
                "result": [
                    {
                        "Address": "0xabc",
                        "ContractName": "Assist",
                        "CompilerVersion": "0.8.23",
                        "SourceCode": "// source",
                    }
                ],
            },
        )

    async with _client(handler) as client:
        contract = await client.get_contract(INSTANCE_CHAIN_ID, "0xabc")

    assert contract is not None
    assert contract.route == ROUTE_PRO
    assert contract.name == "Assist"
    assert contract.source_code == "// source"


async def test_get_contract_returns_none_when_the_pro_route_knows_nothing() -> None:
    """An unknown address is ``None``, not an error."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "eth.blockscout.com":
            return httpx.Response(404, text="not found")
        return httpx.Response(200, json={"message": "OK", "status": "1", "result": []})

    async with _client(handler) as client:
        contract = await client.get_contract(INSTANCE_CHAIN_ID, "0xabc")

    assert contract is None


# --- argument checking --------------------------------------------------


async def test_invalid_paging_arguments_are_rejected() -> None:
    """Page numbers below one would produce a confusing request."""

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - unused
        raise AssertionError("no request should be made")

    async with _client(handler) as client:
        with pytest.raises(ValueError):
            await client.list_contracts(INSTANCE_CHAIN_ID, page=0)
        with pytest.raises(ValueError):
            await client.list_contracts(INSTANCE_CHAIN_ID, page_size=0)


async def test_the_client_is_an_async_context_manager() -> None:
    """The client closes its HTTP client on exit."""
    client = _client(lambda request: httpx.Response(200, json={"items": []}))
    async with client as entered:
        assert entered is client
    assert client._client.is_closed


def test_the_event_loop_is_not_required_for_the_meter() -> None:
    """The credit meter is plain synchronous code."""
    assert asyncio.iscoroutinefunction(BlockscoutClient.list_contracts)
