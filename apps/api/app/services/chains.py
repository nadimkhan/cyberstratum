"""Chain registry for multi-chain contract discovery.

CyberStratum watches EVM chains for newly deployed contracts. Two things
make a multi-chain sweep awkward:

* There is no single free Blockscout endpoint. The unified
  `Blockscout PRO <https://api.blockscout.com/v2/api>`_ endpoint covers most
  chains we support but needs an API key, spends credits per call, and is
  concurrency-limited.
* Many chains also run a *per-chain* Blockscout instance (a "ChainScout")
  which serves the same data for free, without a key and without spending
  credits.

The registry therefore records, per chain, whether a free per-chain instance
is known and what the PRO route can do. The client in
:mod:`app.services.blockscout` prefers the instance and falls back to PRO.

Every number in this module was measured, not assumed. The probes live in
``scripts/probe_blockscout.py`` and ``scripts/pro_map.py`` and can be re-run at
any time; the conclusions are recorded in ``docs/BLOCKSCOUT-ROUTES.md``.

Key measurements (2026-10-28):

* The PRO API hard-caps a page at **10 items**. Asking for 50 or 100 returns
  10, so paging is the only way to cover more.
* The PRO API is **concurrency-limited**: 4 simultaneous calls succeed, 6
  return HTTP 429. The limit is on concurrency, not on a per-minute quota --
  eight sequential calls with no delay all returned 200.
* ``filter=verified`` costs 12-79 s against 0.4-0.7 s for the same query
  without it. It is never used.
* Per-chain instances answer 58 of the 66 chains. Cloudflare blocks Polygon,
  Base, Arbitrum, Robinhood and Arc; Matchain's instance is down.

Re-measured on 2026-11-12 by probing 4,660 candidate hosts one at a time
(the Blockscout instance registry itself now answers 402 without a paid
plan, so the chain list is found by probing rather than by reading it).
The survey is committed at ``docs/chain-probe/survey.json``, the raw
reports live in ``var/chain-probe/``, and ``scripts/summarise_chain_probe.py``
turns one into the other and cross-checks the result against this
registry.
* PRO answers 402 for chains its plan does not cover (Polygon, Base, zkSync)
  and 404 for chains it does not support (Metis, Stability, Aurora).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

#: Base URL of the unified Blockscout PRO API.
#:
#: This is the legacy ``module``/``action`` shape under ``/v2/api``. The
#: per-instance shape is ``/api/v2/<resource>`` and they are *different APIs*
#: that share a brand; only this one takes a ``chainid``.
PRO_API_BASE: Final[str] = "https://api.blockscout.com/v2/api"

#: Credits consumed by one PRO API call on the free tier.
PRO_CREDITS_PER_CALL: Final[int] = 20

#: Daily credit allowance on the free PRO tier (resets at midnight UTC).
PRO_DAILY_CREDIT_BUDGET: Final[int] = 100_000

#: Maximum number of items the PRO API returns per page.
#:
#: Measured: ``items_count`` of 10, 50 and 100 all return exactly 10 results.
#: The cap is server-side and cannot be raised.
PRO_MAX_ITEMS_PER_PAGE: Final[int] = 10

#: Maximum number of items a per-chain instance returns per page.
#:
#: Measured: instances honour ``items_count`` up to 50 (a request for more
#: returns HTTP 422). Several instances ignore it entirely and always return
#: 50.
INSTANCE_MAX_ITEMS_PER_PAGE: Final[int] = 50

#: Maximum simultaneous PRO requests.
#:
#: Measured: 4 concurrent calls all succeed, 6 return HTTP 429. Three leaves
#: headroom for the retry path.
PRO_MAX_CONCURRENCY: Final[int] = 3

#: Maximum request rate allowed against the PRO API.
PRO_MAX_RPS: Final[int] = 5

#: Blockscout's multichain explorer.
#:
#: The PRO API serves most supported chains, but it has no single
#: chain-scoped web host: ``pro.blockscout.com`` does not exist (it answers
#: 404), and ``api.blockscout.com`` answers 402 for a browser. The
#: multichain explorer is the one URL that resolves for any chain, so PRO
#: records point there unless the chain has a known explorer of its own.
PRO_EXPLORER_WEB: Final[str] = "https://explorer.blockscout.com"

#: The PRO route's status for a chain, as a short string.
PRO_OK: Final[str] = "ok"
PRO_PLAN_REQUIRED: Final[str] = "plan_required"
PRO_UNSUPPORTED: Final[str] = "unsupported"


@dataclass(frozen=True, slots=True)
class Chain:
    """A single supported EVM chain.

    Attributes:
        chain_id: EIP-155 chain identifier.
        name: Human readable chain name.
        slug: Lowercase snake_case identifier, stable across releases.
        explorer_host: Host of the chain's own Blockscout instance, or
            ``None`` when no instance is known for the chain.
        ecosystem: Grouping label (Ethereum, Optimism, Polygon, ...).
        pro_status: What the unified PRO route can do for this chain --
            ``"ok"``, ``"plan_required"`` or ``"unsupported"``.
    """

    chain_id: int
    name: str
    slug: str
    explorer_host: str | None
    ecosystem: str
    pro_status: str = PRO_OK

    @property
    def routes(self) -> tuple[str, ...]:
        """Return the discovery routes available for this chain, best first.

        A per-chain instance is always preferred: it is free, unkeyed and
        unmetered. The PRO route is the fallback.
        """
        available: list[str] = []
        if self.explorer_host is not None:
            available.append("instance")
        if self.pro_status == PRO_OK:
            available.append("pro")
        return tuple(available)

    @property
    def reachable(self) -> bool:
        """Return whether at least one discovery route works for this chain."""
        return bool(self.routes)


#: Per-chain Blockscout instances, verified to answer a real request.
#:
#: Every host here returned HTTP 200 with a well-formed Blockscout v2
#: payload on 2026-10-28. The hosts are not all ``blockscout.com``
#: subdomains: Gnosis runs on ``gnosisscan.io``, OP Mainnet on
#: ``explorer.optimism.io``, Mode on ``explorer.mode.network``, Metis on
#: ``andromeda-explorer.metis.io`` and World Chain on Alchemy's explorer.
#: They all serve the same Blockscout v2 schema, so one parser covers them.
INSTANCE_HOSTS: Final[dict[int, str]] = {
    1: "eth.blockscout.com",
    10: "explorer.optimism.io",
    30: "rootstock.blockscout.com",
    31: "rootstock-testnet.blockscout.com",
    61: "etc.blockscout.com",
    122: "explorer.fuse.io",
    130: "unichain.blockscout.com",
    177: "hsk.blockscout.com",
    239: "explorer.tac.build",
    291: "explorer.orderly.network",
    300: "zksync-sepolia.blockscout.com",
    314: "filecoin.blockscout.com",
    324: "zksync.blockscout.com",
    338: "cronos-testnet.blockscout.com",
    360: "shapescan.xyz",
    411: "pepe.blockscout.com",
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
    1946: "soneium-minato.blockscout.com",
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
    7001: "zetachain-testnet.blockscout.com",
    8021: "numine.blockscout.com",
    97741: "pepuscan.com",
    98866: "explorer.plume.org",
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

#: Chains whose per-chain instance is blocked or down.
#:
#: Cloudflare answers 403 for most of these; Matchain's instance answers
#: 503. None of these blocks is a user-agent problem: the survey of 2026-11-12
#: asked each host with the library's default agent and with a descriptive
#: one, and every host answered the same way, so there is nothing to gain by
#: pretending to be a browser. Gnosis and Immutable were measured this way
#: too: both answer 403 for both agents, so they sit here rather than in
#: the working list above.
BLOCKED_INSTANCE_HOSTS: Final[dict[int, str]] = {
    100: "gnosisscan.io",
    13371: "explorer.immutable.com",
    137: "polygon.blockscout.com",
    42161: "arbitrum.blockscout.com",
    4663: "robinhoodchain.blockscout.com",
    5042: "explorer.arc.io",
    698: "matchscan.io",
    8453: "base.blockscout.com",
}

#: Chains the PRO route will not serve because the key's plan does not cover
#: them. PRO answers HTTP 402 with "requires one of the following plans".
PRO_PLAN_REQUIRED_CHAINS: Final[frozenset[int]] = frozenset({137, 324, 8453})

#: Chains PRO does not support at all. PRO answers HTTP 404.
PRO_UNSUPPORTED_CHAINS: Final[frozenset[int]] = frozenset({1088, 101010, 1313161554})


def _chain(
    chain_id: int,
    name: str,
    slug: str,
    ecosystem: str,
) -> Chain:
    """Build a :class:`Chain`, attaching the measured route information."""
    if chain_id in PRO_PLAN_REQUIRED_CHAINS:
        pro_status = PRO_PLAN_REQUIRED
    elif chain_id in PRO_UNSUPPORTED_CHAINS:
        pro_status = PRO_UNSUPPORTED
    else:
        pro_status = PRO_OK
    return Chain(
        chain_id=chain_id,
        name=name,
        slug=slug,
        explorer_host=INSTANCE_HOSTS.get(chain_id),
        ecosystem=ecosystem,
        pro_status=pro_status,
    )


#: Every chain CyberStratum discovers contracts on, ordered by chain id.
SUPPORTED_CHAINS: Final[tuple[Chain, ...]] = (
    _chain(1, "Ethereum", "ethereum", "Ethereum"),
    _chain(10, "OP Mainnet", "optimism", "Optimism"),
    _chain(30, "Rootstock", "rootstock", "Ethereum"),
    _chain(31, "Rootstock Testnet", "rootstock_testnet", "Ethereum"),
    _chain(61, "Ethereum Classic", "ethereum_classic", "Ethereum"),
    _chain(100, "Gnosis", "gnosis", "Gnosis"),
    _chain(122, "Fuse", "fuse", "Ethereum"),
    _chain(130, "Unichain", "unichain", "Ethereum"),
    _chain(137, "Polygon PoS", "polygon", "Polygon"),
    _chain(177, "HashKey", "hashkey", "Ethereum"),
    _chain(239, "TAC Mainnet", "tac_mainnet", "Ethereum"),
    _chain(291, "Orderly", "orderly", "Ethereum"),
    _chain(300, "zkSync Sepolia Testnet", "zksync_sepolia", "zkSync"),
    _chain(314, "Filecoin Virtual Machine", "filecoin", "Filecoin"),
    _chain(324, "ZKsync Era", "zksync", "zkSync"),
    _chain(338, "Cronos Testnet", "cronos_testnet", "Ethereum"),
    _chain(360, "Shape", "shape", "Ethereum"),
    _chain(411, "Pepe Chain", "pepe", "Ethereum"),
    _chain(42220, "Celo", "celo", "Ethereum"),
    _chain(4326, "MegaETH", "megaeth", "Ethereum"),
    _chain(480, "World Chain", "world_chain", "Ethereum"),
    _chain(488, "BXN", "bxn", "Ethereum"),
    _chain(592, "Astar", "astar", "Polygon"),
    _chain(698, "Matchain", "matchain", "Ethereum"),
    _chain(714, "Eden", "eden", "Ethereum"),
    _chain(747, "Flow Mainnet", "flow", "Ethereum"),
    _chain(869, "World Mobile", "world_mobile", "Ethereum"),
    _chain(957, "Derive Mainnet", "derive", "Ethereum"),
    _chain(102030, "Creditcoin", "creditcoin", "Ethereum"),
    _chain(1135, "Lisk", "lisk", "Ethereum"),
    _chain(1729, "Reya", "reya", "Ethereum"),
    _chain(1829, "Playnance Playblock", "playnance", "Ethereum"),
    _chain(1868, "Soneium", "soneium", "Ethereum"),
    _chain(1890, "LightLink Phoenix Mainnet", "lightlink", "Ethereum"),
    _chain(1946, "Soneium Testnet Minato", "soneium_minato", "Ethereum"),
    _chain(2020, "Ronin Mainnet", "ronin", "Ethereum"),
    _chain(2288, "Moca Chain", "moca", "Ethereum"),
    _chain(2366, "KiteAI Mainnet", "kiteai", "Ethereum"),
    _chain(34443, "Mode", "mode", "Optimism"),
    _chain(42161, "Arbitrum One Nitro", "arbitrum", "Arbitrum"),
    _chain(42170, "Arbitrum Nova", "arbitrum_nova", "Arbitrum"),
    _chain(42793, "Etherlink", "etherlink", "Ethereum"),
    _chain(4663, "Robinhood Chain", "robinhood", "Ethereum"),
    _chain(5042, "Arc Mainnet", "arc", "Ethereum"),
    _chain(529375, "LayerK", "layerk", "Ethereum"),
    _chain(57073, "Ink", "ink", "Ethereum"),
    _chain(6497, "Awaji", "awaji", "Ethereum"),
    _chain(6498, "Mizuhiki", "mizuhiki", "Ethereum"),
    _chain(7000, "ZetaChain", "zetachain", "Ethereum"),
    _chain(7001, "ZetaChain Testnet", "zetachain_testnet", "Ethereum"),
    _chain(8021, "Numine", "numine", "Ethereum"),
    _chain(8453, "Base", "base", "Optimism"),
    _chain(97741, "Pepe Unchained", "pepe_unchained", "Ethereum"),
    _chain(98866, "Plume Mainnet", "plume", "Ethereum"),
    _chain(13371, "Immutable zkEVM", "immutable", "Immutable"),
    _chain(1514, "DATA Network", "data_network", "Ethereum"),
    _chain(190415, "HPP Mainnet", "hpp_mainnet", "Ethereum"),
    _chain(245022934, "Neon", "neon", "Ethereum"),
    _chain(612055, "Cross Mainnet", "cross_mainnet", "Ethereum"),
    _chain(685689, "Gensyn", "gensyn", "Ethereum"),
    _chain(97477, "Doma Mainnet", "doma", "Ethereum"),
    _chain(101010, "Stability Global Trust Network", "stability", "Ethereum"),
    _chain(32769, "Zilliqa 2 Mainnet", "zilliqa2", "Ethereum"),
    _chain(1088, "Metis", "metis", "Ethereum"),
    _chain(1313161554, "Aurora", "aurora", "Ethereum"),
    _chain(534352, "Scroll", "scroll", "Ethereum"),
)


class ChainRegistry:
    """Lookup helpers over the supported chain list.

    The registry is immutable: it is built once from :data:`SUPPORTED_CHAINS`
    and never mutated, so a single module level instance can be shared.
    """

    def __init__(self, chains: tuple[Chain, ...] = SUPPORTED_CHAINS) -> None:
        """Create a registry over ``chains``."""
        self._chains = tuple(sorted(chains, key=lambda chain: chain.chain_id))
        self._by_id: dict[int, Chain] = {chain.chain_id: chain for chain in self._chains}
        self._by_slug: dict[str, Chain] = {chain.slug: chain for chain in self._chains}

    def get(self, chain_id: int) -> Chain | None:
        """Return the chain with ``chain_id``, or ``None`` when unsupported."""
        return self._by_id.get(chain_id)

    def get_by_slug(self, slug: str) -> Chain | None:
        """Return the chain with ``slug``, or ``None`` when unsupported."""
        return self._by_slug.get(slug)

    def all(self) -> list[Chain]:
        """Return every supported chain, ordered by chain id."""
        return list(self._chains)

    def instance_backed(self) -> list[Chain]:
        """Return the chains that have a known per-chain Blockscout instance."""
        return [chain for chain in self._chains if chain.explorer_host is not None]

    def pro_only(self) -> list[Chain]:
        """Return the chains that can only be reached through the PRO API."""
        return [
            chain
            for chain in self._chains
            if chain.explorer_host is None and chain.pro_status == PRO_OK
        ]

    def unreachable(self) -> list[Chain]:
        """Return the chains no discovery route can currently reach.

        On the free PRO key this is Polygon and Base: Cloudflare blocks both
        instances and PRO answers 402 because the key's plan does not cover
        featured chains. They need a paid PRO plan or a different data source.
        """
        return [chain for chain in self._chains if not chain.reachable]

    def supports(self, chain_id: int) -> bool:
        """Return whether ``chain_id`` is a supported chain."""
        return chain_id in self._by_id

    def __len__(self) -> int:
        """Return the number of supported chains."""
        return len(self._chains)


#: The process-wide registry over :data:`SUPPORTED_CHAINS`.
registry: Final[ChainRegistry] = ChainRegistry()


def get_chain(chain_id: int) -> Chain | None:
    """Return the supported chain with ``chain_id``, or ``None``."""
    return registry.get(chain_id)


def all_chains() -> list[Chain]:
    """Return every supported chain, ordered by chain id."""
    return registry.all()


def instance_backed_chains() -> list[Chain]:
    """Return the supported chains that have a per-chain Blockscout instance."""
    return registry.instance_backed()


def pro_only_chains() -> list[Chain]:
    """Return the supported chains that are reachable only through the PRO API."""
    return registry.pro_only()


def unreachable_chains() -> list[Chain]:
    """Return the chains that no discovery route can currently reach."""
    return registry.unreachable()


def supports_chain(chain_id: int) -> bool:
    """Return whether ``chain_id`` is a supported chain."""
    return registry.supports(chain_id)


def explorer_host_for(chain_id: int) -> str | None:
    """Return the known per-chain instance host for ``chain_id``."""
    chain = registry.get(chain_id)
    if chain is not None and chain.explorer_host is not None:
        return chain.explorer_host
    return INSTANCE_HOSTS.get(chain_id)


def pro_available_for(chain_id: int) -> bool:
    """Return whether the PRO route can serve ``chain_id``."""
    chain = registry.get(chain_id)
    return chain is not None and chain.pro_status == PRO_OK


__all__ = [
    "BLOCKED_INSTANCE_HOSTS",
    "INSTANCE_HOSTS",
    "INSTANCE_MAX_ITEMS_PER_PAGE",
    "PRO_API_BASE",
    "PRO_CREDITS_PER_CALL",
    "PRO_DAILY_CREDIT_BUDGET",
    "PRO_MAX_CONCURRENCY",
    "PRO_MAX_ITEMS_PER_PAGE",
    "PRO_MAX_RPS",
    "PRO_OK",
    "PRO_PLAN_REQUIRED",
    "PRO_PLAN_REQUIRED_CHAINS",
    "PRO_UNSUPPORTED",
    "PRO_UNSUPPORTED_CHAINS",
    "SUPPORTED_CHAINS",
    "Chain",
    "ChainRegistry",
    "all_chains",
    "explorer_host_for",
    "get_chain",
    "instance_backed_chains",
    "pro_available_for",
    "pro_only_chains",
    "registry",
    "supports_chain",
    "unreachable_chains",
]
