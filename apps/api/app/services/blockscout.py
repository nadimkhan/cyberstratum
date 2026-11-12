"""Async Blockscout client used for multi-chain contract discovery.

Two routes reach the same data, and the client picks per chain:

**Route A -- per-chain instance.** Each chain may run its own Blockscout
(``https://eth.blockscout.com/api/v2/...``). The route is free, needs no API
key, and returns richer payloads (including verification state). It is not
available for every chain, and some hosts sit behind a CDN that answers
``403`` from some networks, so the route must be allowed to fail.

**Route B -- unified PRO API.** ``https://api.blockscout.com/v2/api`` serves
every supported chain behind a single API key and bills a fixed number of
credits per call.

The client prefers route A and falls back to route B automatically. A chain
whose instance is unreachable is therefore never an error by itself; it only
becomes an error when the PRO route is unavailable too (missing key, HTTP
402, exhausted credit budget).

Why ``filter=verified`` is never used
-------------------------------------

Measured on chain 1 today::

    module=contract&action=listcontracts&items_count=50             -> 0.6 s
    ... + sort=creation_desc&order=desc                             -> 0.4 s
    ... + filter=verified                                           -> 44.4 s
    filter=verified AND sort=creation_desc                          -> 78.7 s

The verified filter is the entire cost of the query, and it cannot be
replaced by a client-side filter: the PRO ``listcontracts`` payload does not
carry ``IsVerified`` or ``VerifiedAt``. So the filter is dropped and the
newest contracts are fetched with ``sort=creation_desc`` only.

Budget safety
-------------

The free PRO tier allows 100,000 credits per UTC day at 20 credits per call,
and 5 requests per second. :class:`CreditMeter` refuses calls once the daily
budget would be exceeded and :class:`RateLimiter` paces requests, so a
runaway loop cannot burn the quota or get the key throttled.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Final

import httpx
from pydantic import BaseModel, ConfigDict

from app.core.logging import get_logger
from app.services.chains import (
    INSTANCE_MAX_ITEMS_PER_PAGE,
    PRO_API_BASE,
    PRO_CREDITS_PER_CALL,
    PRO_DAILY_CREDIT_BUDGET,
    PRO_EXPLORER_WEB,
    PRO_MAX_CONCURRENCY,
    PRO_MAX_ITEMS_PER_PAGE,
    PRO_MAX_RPS,
    explorer_host_for,
    registry,
)

log = get_logger(__name__)

#: Route identifiers recorded on every :class:`DiscoveredContract`.
ROUTE_INSTANCE: Final[str] = "instance"
ROUTE_PRO: Final[str] = "pro"

#: Environment variable holding the Blockscout PRO API key.
BLOCKSCOUT_API_KEY_ENV: Final[str] = "BLOCKSCOUT_API_KEY"

#: The agent this client identifies as.
#:
#: httpx sends ``python-httpx/<version>`` by default, which is how a
#: scraper looks to the operator of a public explorer. Saying what this
#: is and why it is asking is both politer and more useful to whoever
#: wants to block us.
USER_AGENT: Final[str] = (
    "CyberStratum/0.1 (smart-contract analysis; one request per host; "
    "contact: security@cyberstratum.local)"
)

#: Default request timeout, in seconds.
DEFAULT_TIMEOUT: Final[float] = 30.0

#: Default number of contracts requested per page.
#:
#: This is the *instance* page size. The PRO route caps a page at 10 items no
#: matter what is asked for, so the client clamps per route rather than
#: sending 50 and silently receiving 10.
DEFAULT_PAGE_SIZE: Final[int] = INSTANCE_MAX_ITEMS_PER_PAGE

#: How many times a PRO request is retried after a 429.
#:
#: The PRO API limits *concurrency*, not a per-minute quota: four
#: simultaneous calls succeed, six answer 429, and eight sequential calls
#: with no delay all answer 200. A 429 is therefore transient and is retried
#: rather than being reported as the chain being unavailable.
PRO_MAX_RETRIES: Final[int] = 3

#: Base delay, in seconds, for the exponential backoff between retries.
PRO_RETRY_BASE_DELAY: Final[float] = 0.5


class BlockscoutError(RuntimeError):
    """Base class for every error raised by this module."""


class BlockscoutUnavailableError(BlockscoutError):
    """Raised when no route could serve a chain.

    Attributes:
        chain_id: The chain that could not be served.
        reason: Human readable explanation, for example a missing API key.
    """

    def __init__(self, chain_id: int, reason: str) -> None:
        """Build the error for ``chain_id`` with ``reason``."""
        chain = registry.get(chain_id)
        label = chain.name if chain is not None else f"chain {chain_id}"
        super().__init__(f"Blockscout unavailable for {label} ({chain_id}): {reason}")
        self.chain_id = chain_id
        self.reason = reason


class BlockscoutBudgetExceededError(BlockscoutError):
    """Raised when the daily PRO credit budget would be exceeded.

    Attributes:
        chain_id: The chain whose request was refused.
        used: Credits already spent on the current UTC day.
        requested: Credits the refused call would have cost.
    """

    def __init__(self, chain_id: int, used: int, requested: int) -> None:
        """Build the error for ``chain_id`` with the credit counters."""
        super().__init__(
            f"Blockscout PRO daily credit budget exhausted after {used} credits; "
            f"refusing a {requested}-credit call for chain {chain_id}"
        )
        self.chain_id = chain_id
        self.used = used
        self.requested = requested


class DiscoveredContract(BaseModel):
    """A contract discovered on a chain, normalised across both routes.

    The two Blockscout routes use different key conventions and different
    levels of detail. This model is the single shape the rest of the code
    sees; fields that a route does not carry are ``None`` rather than absent.

    Attributes:
        chain_id: EIP-155 chain the contract lives on.
        address: Contract address.
        name: Contract name, when the explorer knows one.
        compiler_version: Compiler version string, when known.
        optimization_used: Whether the optimiser was enabled, when known.
        is_verified: Verification state, when the route reports it.
        verified_at: Verification timestamp, when the route reports it.
        created_at: Deployment timestamp, when the route reports it.
        source_code: Contract source, when the route serves it.
        source_uri: Link to the contract on a block explorer.
        route: Which route produced this record (``instance`` or ``pro``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    chain_id: int
    address: str
    name: str | None = None
    compiler_version: str | None = None
    optimization_used: bool | None = None
    is_verified: bool | None = None
    verified_at: str | None = None
    created_at: str | None = None
    source_code: str | None = None
    source_uri: str | None = None
    route: str


def _nested_address(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the nested ``address`` object of a route A payload, if any."""
    nested = raw.get("address")
    if isinstance(nested, Mapping):
        return nested
    return {}


def _first_str(raw: Mapping[str, Any], nested: Mapping[str, Any], *keys: str) -> str | None:
    """Return the first non-empty string found under ``keys``.

    The top-level payload is searched first, then the nested ``address``
    object used by the per-chain instance route.
    """
    for source in (raw, nested):
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _first_bool(raw: Mapping[str, Any], nested: Mapping[str, Any], *keys: str) -> bool | None:
    """Return the first boolean-ish value found under ``keys``.

    Blockscout encodes some flags as booleans and others as ``0``/``1``
    strings, so both are accepted.
    """
    for source in (raw, nested):
        for key in keys:
            if key not in source:
                continue
            value = source[key]
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"true", "1", "yes"}:
                    return True
                if lowered in {"false", "0", "no"}:
                    return False
            if isinstance(value, int):
                return bool(value)
    return None


def normalize_contract(
    chain_id: int,
    raw: Mapping[str, Any],
    *,
    route: str,
    source_uri: str | None = None,
    address: str | None = None,
) -> DiscoveredContract:
    """Normalise a raw Blockscout record into a :class:`DiscoveredContract`.

    Both route shapes are accepted:

    * the per-chain instance shape, where the address, name and verification
      flags live in a nested ``address`` object;
    * the PRO shape, where the same fields are flattened to ``Address``,
      ``ContractName`` and ``OptimizationUsed``.

    Args:
        chain_id: The chain the record belongs to.
        raw: The decoded JSON object.
        route: The route that produced the record.
        source_uri: Link to the contract on a block explorer.
        address: The address to use when the payload itself carries none.
            The per-chain instance omits it from its single-contract
            response, because it is already in the request path.

    Returns:
        The normalised contract.

    Raises:
        ValueError: If the payload carries no usable address.
    """
    nested = _nested_address(raw)
    found = _first_str(raw, nested, "Address", "address_hash", "hash") or address
    if found is None:
        raise ValueError("Blockscout payload contains no contract address")
    return DiscoveredContract(
        chain_id=chain_id,
        address=found,
        name=_first_str(raw, nested, "ContractName", "name"),
        compiler_version=_first_str(raw, nested, "CompilerVersion", "compiler_version"),
        optimization_used=_first_bool(
            raw, nested, "OptimizationUsed", "optimization_enabled", "OptimizationEnabled"
        ),
        is_verified=_verification_state(raw, nested),
        verified_at=_first_str(raw, nested, "VerifiedAt", "verified_at"),
        created_at=_first_str(raw, nested, "CreatedAt", "created_at", "CreationTime"),
        source_code=_first_str(raw, nested, "SourceCode", "source_code"),
        source_uri=source_uri,
        route=route,
    )


#: The literal the PRO API puts in the ``ABI`` field of an unverified
#: contract. It is the only verification signal the PRO ``listcontracts``
#: payload carries.
PRO_UNVERIFIED_ABI: Final[str] = "Contract source code not verified"


def _verification_state(
    raw: Mapping[str, Any], nested: Mapping[str, Any]
) -> bool | None:
    """Return the verification state of a record, when the route reports one.

    The per-chain instance reports it explicitly as ``is_verified``. The PRO
    ``listcontracts`` payload does not carry the flag at all -- instead it
    puts a literal sentence in the ``ABI`` field when the contract has no
    verified source. Both are honoured here so the two routes produce the
    same normalised record.
    """
    explicit = _first_bool(raw, nested, "IsVerified", "is_verified")
    if explicit is not None:
        return explicit
    abi = raw.get("ABI")
    if isinstance(abi, str):
        if abi.strip() == PRO_UNVERIFIED_ABI:
            return False
        if abi.strip().startswith("["):
            return True
    return None


def _utc_now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(UTC)


@dataclass
class CreditMeter:
    """Tracks PRO API credit consumption against the daily budget.

    The budget resets at midnight UTC, which is when the free tier refills.
    The meter refuses a call that would exceed the budget, so a runaway loop
    stops instead of quietly spending the quota.

    Attributes:
        budget: Credits available on the current UTC day.
        credits_per_call: Credits charged for one PRO call.
        day: The UTC day the counter belongs to.
        clock: Source of the current time; injectable so tests can move the
            meter across a day boundary.
    """

    budget: int = PRO_DAILY_CREDIT_BUDGET
    credits_per_call: int = PRO_CREDITS_PER_CALL
    day: date = field(default_factory=lambda: _utc_now().date())
    clock: Callable[[], datetime] = _utc_now
    _used: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        """Validate the configuration and align the day with the clock."""
        if self.budget < 0:
            raise ValueError("credit budget must not be negative")
        if self.credits_per_call <= 0:
            raise ValueError("credits per call must be positive")
        self.day = self.clock().date()

    def _now(self) -> date:
        """Return the current UTC day."""
        return self.clock().date()

    def _roll_day(self) -> None:
        """Reset the counter when the UTC day changed."""
        today = self._now()
        if today != self.day:
            log.info("blockscout_credit_budget_reset", day=str(today))
            self.day = today
            self._used = 0

    @property
    def used(self) -> int:
        """Return the credits consumed on the current UTC day."""
        self._roll_day()
        return self._used

    @property
    def remaining(self) -> int:
        """Return the credits still available on the current UTC day."""
        self._roll_day()
        return max(0, self.budget - self._used)

    def can_afford(self, credits: int | None = None) -> bool:
        """Return whether a call of ``credits`` (default: one call) fits in the budget."""
        self._roll_day()
        cost = self.credits_per_call if credits is None else credits
        return self._used + cost <= self.budget

    def charge(self, credits: int | None = None, *, chain_id: int = 0) -> int:
        """Charge credits for one PRO call and return the new total.

        Args:
            credits: Credits to charge; defaults to one call's worth.
            chain_id: The chain the call serves, used for the error message.

        Returns:
            The number of credits used on the current UTC day.

        Raises:
            BlockscoutBudgetExceededError: If the charge would exceed the budget.
        """
        self._roll_day()
        cost = self.credits_per_call if credits is None else credits
        if self._used + cost > self.budget:
            raise BlockscoutBudgetExceededError(chain_id, self._used, cost)
        self._used += cost
        return self._used

    def refund(self, credits: int | None = None) -> int:
        """Give back credits for a call that did not deliver a result.

        A request the API refuses -- a 402 for a chain that needs a paid plan,
        for instance -- is not billed as a normal call, so the reservation is
        released rather than left on the counter.

        Args:
            credits: Credits to give back; defaults to one call's worth.

        Returns:
            The number of credits used on the current UTC day.
        """
        self._roll_day()
        cost = self.credits_per_call if credits is None else credits
        self._used = max(0, self._used - cost)
        return self._used


class RateLimiter:
    """Paces requests so that no one-second window exceeds ``max_rps`` calls.

    The limiter keeps the timestamps of the recent calls and sleeps for the
    remainder of the window when the limit is reached. Both the clock and the
    sleep function are injectable so tests can drive it deterministically.

    Attributes:
        max_rps: Maximum number of calls allowed per one-second window.
    """

    def __init__(
        self,
        max_rps: int = PRO_MAX_RPS,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        """Create a limiter allowing ``max_rps`` calls per second."""
        if max_rps <= 0:
            raise ValueError("max_rps must be positive")
        self.max_rps = max_rps
        self._clock = clock
        self._sleep = sleep
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a call may be made, then record it."""
        async with self._lock:
            now = self._clock()
            self._expire(now)
            if len(self._calls) >= self.max_rps:
                delay = 1.0 - (now - self._calls[0]) + 1e-6
                await self._sleep(delay)
                now = self._clock()
                self._expire(now)
            self._calls.append(now)

    def _expire(self, now: float) -> None:
        """Drop the calls that fell out of the one-second window."""
        while self._calls and now - self._calls[0] >= 1.0:
            self._calls.popleft()


@dataclass
class ChainDiscoveryResult:
    """Outcome of a discovery sweep over several chains.

    A failing chain never aborts the sweep: its contracts are simply absent
    from ``contracts`` and its reason is recorded in ``failures``.

    Attributes:
        contracts: Contracts found, keyed by chain id.
        failures: Failure reasons, keyed by chain id.
    """

    contracts: dict[int, list[DiscoveredContract]] = field(default_factory=dict)
    failures: dict[int, str] = field(default_factory=dict)


class BlockscoutClient:
    """Async client for contract discovery across the supported chains.

    The client owns an :class:`httpx.AsyncClient` and should be used as an
    async context manager, or closed explicitly with :meth:`aclose`.

    Args:
        api_key: Blockscout PRO API key. When ``None`` the key is read from
            the ``BLOCKSCOUT_API_KEY`` environment variable; an empty value
            means the PRO route is unavailable.
        timeout: Per-request timeout in seconds.
        transport: Optional HTTP transport, so tests can inject
            ``httpx.MockTransport`` instead of touching the network.
        credit_meter: Credit accounting for the PRO route.
        rate_limiter: Request pacer for the PRO route.
    """

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        credit_meter: CreditMeter | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        """Create a client with the given key, timeout and transport."""
        if api_key is None:
            api_key = os.environ.get(BLOCKSCOUT_API_KEY_ENV, "")
        self._api_key = api_key or ""
        self._timeout = timeout
        # Redirects are followed on purpose: several of the per-chain hosts
        # (optimism, gnosis, scroll) answer 301 towards the explorer that
        # hosts them, and that host serves the same v2 API.
        self._client = httpx.AsyncClient(
            timeout=timeout,
            transport=transport,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        self.credits = credit_meter if credit_meter is not None else CreditMeter()
        self.rate_limiter = rate_limiter if rate_limiter is not None else RateLimiter()
        # The PRO API limits *concurrency*: four simultaneous calls succeed,
        # six answer 429. The rate limiter bounds the rate, not how many
        # requests are in flight at once, so the two are separate controls.
        self._pro_semaphore = asyncio.Semaphore(PRO_MAX_CONCURRENCY)

    @property
    def has_api_key(self) -> bool:
        """Return whether a PRO API key is available."""
        return bool(self._api_key)

    async def __aenter__(self) -> BlockscoutClient:
        """Enter the async context manager."""
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Close the underlying HTTP client."""
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # -- route A: per-chain instance -------------------------------------

    def _instance_url(self, chain_id: int, path: str) -> str:
        """Build an instance URL for ``chain_id``.

        Raises:
            BlockscoutUnavailableError: If no instance host is known.
        """
        host = explorer_host_for(chain_id)
        if host is None:
            raise BlockscoutUnavailableError(chain_id, "no per-chain instance is known")
        return f"https://{host}{path}"

    async def _instance_list(
        self, chain_id: int, *, page: int, page_size: int
    ) -> list[DiscoveredContract]:
        """Fetch one page of contracts from the per-chain instance.

        The per-chain instance does not accept a ``page`` parameter. It hands
        out a ``next_page_params`` cursor instead, so reaching page *n* means
        following the cursor *n - 1* times. The cursor is followed here so
        callers can keep asking for "page 3" and get page 3.
        """
        url = self._instance_url(chain_id, "/api/v2/smart-contracts")
        # Measured: an instance answers 422 for items_count above 50, and
        # several ignore the parameter entirely and always return 50.
        params: dict[str, Any] = {
            "items_count": min(page_size, INSTANCE_MAX_ITEMS_PER_PAGE)
        }
        items: list[Any] = []
        host = explorer_host_for(chain_id)
        for _ in range(page):
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
            items = payload.get("items")
            if not isinstance(items, list):
                raise ValueError("instance response has no 'items' list")
            # The host may have redirected to the explorer that serves this
            # chain; the resolved host is the one that shows the contract.
            host = response.url.host
            next_params = payload.get("next_page_params")
            if not isinstance(next_params, dict) or not next_params:
                break
            params = dict(next_params)
        contracts: list[DiscoveredContract] = []
        for raw in items:
            if not isinstance(raw, Mapping):
                continue
            address = _first_str(raw, _nested_address(raw), "Address", "address_hash", "hash")
            source_uri = f"https://{host}/address/{address}" if address else None
            contracts.append(
                normalize_contract(chain_id, raw, route=ROUTE_INSTANCE, source_uri=source_uri)
            )
        return contracts

    async def _instance_contract(self, chain_id: int, address: str) -> DiscoveredContract | None:
        """Fetch a single contract from the per-chain instance.

        Any failure -- including a 404 -- is raised so the caller can fall
        back to the PRO route, which may know the contract even when the
        instance does not.
        """
        url = self._instance_url(chain_id, f"/api/v2/smart-contracts/{address}")
        response = await self._client.get(url)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise ValueError("instance response is not an object")
        host = response.url.host
        return normalize_contract(
            chain_id,
            payload,
            route=ROUTE_INSTANCE,
            source_uri=f"https://{host}/address/{address}",
            address=address,
        )

    # -- route B: unified PRO API ----------------------------------------

    def _pro_params(self, chain_id: int, **extra: Any) -> dict[str, Any]:
        """Build the PRO API query parameters for ``chain_id``.

        ``filter=verified`` is deliberately absent: it costs 44-79 seconds
        per query and the payload it returns cannot be filtered client side.
        """
        params: dict[str, Any] = {
            "chainid": chain_id,
            "module": "contract",
            "action": "listcontracts",
            "apikey": self._api_key,
        }
        params.update(extra)
        if params.get("action") == "listcontracts":
            # Newest first. Sorting is what makes the feed incremental
            # rather than a blind re-listing of the oldest contracts.
            # A single-contract lookup has nothing to sort, so it does not
            # carry the parameters.
            params["sort"] = "creation_desc"
            params["order"] = "desc"
        return params

    @staticmethod
    def _payment_reason(response: httpx.Response) -> str:
        """Explain why the PRO API answered 402.

        The API distinguishes "no key" from "this featured chain needs a paid
        plan", and the operator needs to see which one applies.
        """
        try:
            payload = response.json()
        except ValueError:
            return "no reason given"
        if isinstance(payload, Mapping):
            error = payload.get("error")
            if isinstance(error, str) and error:
                return error
        return "no reason given"

    async def _pro_get(self, chain_id: int, params: dict[str, Any]) -> Any:
        """Perform one paced, metered PRO API request.

        Raises:
            BlockscoutUnavailableError: If no key is configured or the API
                answers with a payment-required status.
            BlockscoutBudgetExceededError: If the daily budget is exhausted.
        """
        if not self._api_key:
            raise BlockscoutUnavailableError(
                chain_id, f"{BLOCKSCOUT_API_KEY_ENV} is not set"
            )
        await self.rate_limiter.acquire()
        try:
            self.credits.charge(chain_id=chain_id)
        except BlockscoutBudgetExceededError as exc:
            raise BlockscoutBudgetExceededError(chain_id, exc.used, exc.requested) from exc

        last_status = 0
        for attempt in range(PRO_MAX_RETRIES + 1):
            try:
                async with self._pro_semaphore:
                    response = await self._client.get(PRO_API_BASE, params=params)
            except httpx.HTTPError as exc:
                self.credits.refund()
                raise BlockscoutUnavailableError(
                    chain_id, f"the PRO API could not be reached: {exc}"
                ) from exc

            if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                # Transient. The API is refusing the burst, not the chain.
                last_status = response.status_code
                if attempt >= PRO_MAX_RETRIES:
                    break
                delay = PRO_RETRY_BASE_DELAY * (2**attempt)
                log.warning(
                    "blockscout_pro_rate_limited",
                    chain_id=chain_id,
                    attempt=attempt + 1,
                    delay=delay,
                )
                await asyncio.sleep(delay)
                continue

            if response.status_code == httpx.codes.PAYMENT_REQUIRED:
                self.credits.refund()
                raise BlockscoutUnavailableError(
                    chain_id, f"the PRO API answered 402: {self._payment_reason(response)}"
                )
            if response.status_code == httpx.codes.NOT_FOUND:
                # PRO answers 404 for a chain it does not support. That is a
                # permanent, per-chain fact, not a transient failure.
                self.credits.refund()
                raise BlockscoutUnavailableError(
                    chain_id, "the PRO API does not support this chain"
                )
            try:
                response.raise_for_status()
            except httpx.HTTPError as exc:
                self.credits.refund()
                raise BlockscoutUnavailableError(
                    chain_id, f"the PRO API answered HTTP {response.status_code}"
                ) from exc
            try:
                return response.json()
            except ValueError as exc:
                self.credits.refund()
                raise BlockscoutUnavailableError(
                    chain_id, "the PRO API answered a body that is not JSON"
                ) from exc

        self.credits.refund()
        raise BlockscoutUnavailableError(
            chain_id,
            f"the PRO API answered HTTP {last_status} after {PRO_MAX_RETRIES} retries",
        )

    async def _pro_list(
        self, chain_id: int, *, page: int, page_size: int
    ) -> list[DiscoveredContract]:
        """Fetch one page of contracts from the PRO API."""
        payload = await self._pro_get(
            chain_id,
            self._pro_params(
                chain_id,
                # Measured: the PRO API returns exactly 10 items whatever
                # items_count asks for. Asking for more only hides the cap.
                items_count=min(page_size, PRO_MAX_ITEMS_PER_PAGE),
                page=page,
                action="listcontracts",
            ),
        )
        if not isinstance(payload, Mapping):
            raise BlockscoutUnavailableError(chain_id, "the PRO response is not an object")
        result = payload.get("result")
        if not isinstance(result, list):
            raise BlockscoutUnavailableError(
                chain_id, "the PRO response has no 'result' list"
            )
        contracts: list[DiscoveredContract] = []
        for raw in result:
            if not isinstance(raw, Mapping):
                continue
            address = _first_str(raw, {}, "Address", "address_hash", "hash")
            source_uri = self._source_uri(chain_id, address)
            contracts.append(
                normalize_contract(chain_id, raw, route=ROUTE_PRO, source_uri=source_uri)
            )
        return contracts

    async def _pro_contract(self, chain_id: int, address: str) -> DiscoveredContract | None:
        """Fetch a single contract from the PRO API."""
        payload = await self._pro_get(
            chain_id, self._pro_params(chain_id, address=address, action="getsourcecode")
        )
        record: Any = None
        if isinstance(payload, Mapping):
            result = payload.get("result")
            if isinstance(result, list):
                record = result[0] if result and isinstance(result[0], Mapping) else None
            elif isinstance(result, Mapping):
                record = result
        if record is None:
            return None
        source_uri = self._source_uri(chain_id, address)
        return normalize_contract(chain_id, record, route=ROUTE_PRO, source_uri=source_uri)

    @staticmethod
    def _source_uri(chain_id: int, address: str | None) -> str | None:
        """Build a link to a contract on a block explorer.

        A chain with a known explorer gets a chain-scoped link. Every other
        chain gets the multichain explorer, which is the only Blockscout web
        host that resolves for chains the PRO API serves but that have no
        instance of their own.
        """
        if address is None:
            return None
        host = explorer_host_for(chain_id)
        if host is not None:
            return f"https://{host}/address/{address}"
        return f"{PRO_EXPLORER_WEB}/address/{address}"

    # -- public API -------------------------------------------------------

    async def list_contracts(
        self,
        chain_id: int,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> list[DiscoveredContract]:
        """List contracts on ``chain_id``, newest first.

        The per-chain instance is tried first and the PRO API is used as a
        fallback.

        Args:
            chain_id: The chain to query.
            page: One-based page number.
            page_size: Number of contracts per page.

        Returns:
            The contracts on that page.

        Raises:
            BlockscoutUnavailableError: If neither route could serve the chain.
            BlockscoutBudgetExceededError: If the PRO budget is exhausted.
        """
        if page < 1:
            raise ValueError("page must be >= 1")
        if page_size < 1:
            raise ValueError("page_size must be >= 1")

        if explorer_host_for(chain_id) is not None:
            try:
                return await self._instance_list(chain_id, page=page, page_size=page_size)
            except (httpx.HTTPError, ValueError) as exc:
                log.warning(
                    "blockscout_instance_failed",
                    chain_id=chain_id,
                    error=str(exc),
                )
        return await self._pro_list(chain_id, page=page, page_size=page_size)

    async def get_contract(self, chain_id: int, address: str) -> DiscoveredContract | None:
        """Fetch a single contract by address.

        Args:
            chain_id: The chain the contract lives on.
            address: The contract address.

        Returns:
            The contract, or ``None`` when the chain does not know it.

        Raises:
            BlockscoutUnavailableError: If neither route could serve the chain.
            BlockscoutBudgetExceededError: If the PRO budget is exhausted.
        """
        if explorer_host_for(chain_id) is not None:
            try:
                return await self._instance_contract(chain_id, address)
            except (httpx.HTTPError, ValueError) as exc:
                log.warning(
                    "blockscout_instance_failed",
                    chain_id=chain_id,
                    address=address,
                    error=str(exc),
                )
        return await self._pro_contract(chain_id, address)

    async def discover(
        self,
        chain_ids: list[int],
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> ChainDiscoveryResult:
        """Discover contracts on several chains without letting one fail abort the rest.

        Args:
            chain_ids: The chains to query.
            page: One-based page number.
            page_size: Number of contracts per page.

        Returns:
            The contracts found per chain, plus the failure reason per chain.
        """
        result = ChainDiscoveryResult()
        for chain_id in chain_ids:
            try:
                result.contracts[chain_id] = await self.list_contracts(
                    chain_id, page=page, page_size=page_size
                )
            except BlockscoutError as exc:
                log.warning("blockscout_chain_failed", chain_id=chain_id, error=str(exc))
                result.failures[chain_id] = str(exc)
            except Exception as exc:  # pragma: no cover - defensive, never abort a sweep
                log.error(
                    "blockscout_chain_failed", chain_id=chain_id, error=str(exc), exc_info=True
                )
                result.failures[chain_id] = str(exc)
        return result


__all__ = [
    "BLOCKSCOUT_API_KEY_ENV",
    "DEFAULT_PAGE_SIZE",
    "DEFAULT_TIMEOUT",
    "PRO_API_BASE",
    "PRO_MAX_RETRIES",
    "PRO_RETRY_BASE_DELAY",
    "PRO_UNVERIFIED_ABI",
    "ROUTE_INSTANCE",
    "ROUTE_PRO",
    "BlockscoutBudgetExceededError",
    "BlockscoutClient",
    "BlockscoutError",
    "BlockscoutUnavailableError",
    "ChainDiscoveryResult",
    "CreditMeter",
    "DiscoveredContract",
    "RateLimiter",
    "normalize_contract",
]
