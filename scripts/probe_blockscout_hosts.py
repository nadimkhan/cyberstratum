#!/usr/bin/env python3
"""Discover Blockscout instances for EVM chains we do not yet cover.

Blockscout's own instance registry now answers ``402 Payment Required``
without a paid plan, so the list of deployments has to be found by
probing. A Blockscout deployment is by definition an EVM chain, which
means the probe doubles as the EVM test: a host that answers the v2 API
*is* an EVM chain with a Blockscout instance.

The probe is deliberately quiet:

* one request per candidate host, one second apart;
* a descriptive User-Agent, so an operator can see who is calling and
  why, and can block us if they would rather we stopped;
* redirects followed, because several deployments redirect to a
  canonical host;
* ``403`` recorded as *unknown* rather than *dead* -- a WAF answering
  is not evidence that the chain is not there;
* ``429`` honoured with a pause, never hammered;
* no credential is ever sent.

Usage::

    .venv/bin/python scripts/probe_blockscout_hosts.py --limit 400
    .venv/bin/python scripts/probe_blockscout_hosts.py --out var/chain-probe/latest.json

The output is a report, not a registry edit. Adding a chain to
``apps/api/app/services/chains.py`` is a human decision, because a host
that answers today can be wrong tomorrow, and the registry is what the
product promises.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

USER_AGENT = (
    "CyberStratum/0.1 (chain-coverage survey; one request per host; "
    "contact: security@cyberstratum.local)"
)

#: The chain registry that lists chains and their slugs. Public, free.
CHAIN_REGISTRY_URL = "https://chainid.network/chains.json"

#: The lightest Blockscout v2 endpoint that proves a deployment is there.
PROBE_PATH = "/api/v2/smart-contracts?items_count=1"

#: How many probes may be in flight at once. One, on purpose.
DEFAULT_CONCURRENCY = 1

#: Seconds between probes.
DEFAULT_RPS = 1.0

#: Per-request timeout.
DEFAULT_TIMEOUT = 12.0


@dataclass
class ProbeResult:
    """The outcome of one probe."""

    host: str
    chain_id: int | None = None
    chain_name: str = ""
    status: str = "unknown"
    http_status: int | None = None
    detail: str = ""
    error: str = ""
    elapsed_ms: int = 0
    redirected_to: str = ""
    sample_contracts: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "chain_id": self.chain_id,
            "chain_name": self.chain_name,
            "status": self.status,
            "http_status": self.http_status,
            "detail": self.detail,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
            "redirected_to": self.redirected_to,
            "sample_contracts": self.sample_contracts,
        }


@dataclass
class Report:
    """Everything the survey learned."""

    started_at: str = ""
    finished_at: str = ""
    candidates: int = 0
    probed: int = 0
    results: list[ProbeResult] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "candidates": self.candidates,
            "probed": self.probed,
            "results": [r.as_dict() for r in self.results],
            "skipped": self.skipped,
        }


def slugify(value: str) -> str:
    """Turn a chain name into a hostname label."""
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def candidate_hosts(chain: dict[str, Any]) -> list[str]:
    """Hostnames that might serve this chain's Blockscout instance.

    Three naming conventions show up in the wild: the registry slug
    (``base`` -> ``base.blockscout.com``), the short name
    (``op`` -> ``op.blockscout.com``), and a short name with separators
    removed (``arbitrum`` -> ``arbitrumone.blockscout.com``). Ethereum
    is the famous exception -- it lives at ``eth.blockscout.com`` -- so
    the common short names are worth trying too.
    """
    hosts: list[str] = []
    for raw in (
        chain.get("slug"),
        chain.get("shortName"),
        chain.get("name"),
    ):
        if not raw:
            continue
        text = str(raw)
        for label in {slugify(text), slugify(text).replace("-", "")}:
            if not label:
                continue
            host = f"{label}.blockscout.com"
            if host not in hosts:
                hosts.append(host)
    for alias in ("eth", "op", "arb", "matic", "avax", "ftm", "manta", "zksync"):
        host = f"{alias}.blockscout.com"
        if host not in hosts:
            hosts.append(host)
    return hosts


def fetch_chain_registry(timeout: float) -> list[dict[str, Any]]:
    """Read the public chain registry."""
    request = urllib.request.Request(
        CHAIN_REGISTRY_URL, headers={"User-Agent": USER_AGENT}
    )
    # The URL is a hard-coded https constant; nothing user-supplied ever
    # reaches this call, which is what S310 is guarding against.
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        payload = json.load(response)
    if isinstance(payload, dict):
        payload = payload.get("chains", [])
    return [c for c in payload if isinstance(c, dict)]


def probe_host(
    host: str,
    chain_id: int | None,
    chain_name: str,
    timeout: float,
) -> ProbeResult:
    """Ask one host whether it serves the Blockscout v2 API."""
    url = f"https://{host}{PROBE_PATH}"
    result = ProbeResult(host=host, chain_id=chain_id, chain_name=chain_name)
    started = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        """Record the redirect target instead of following it silently."""

        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
            result.redirected_to = newurl
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:  # noqa: S310
            body = response.read(2_000_000)
            result.http_status = response.status
    except urllib.error.HTTPError as exc:
        result.http_status = exc.code
        if exc.code == 403:
            # A WAF answered. The chain may well be there.
            result.status = "blocked"
            result.detail = "403 from a WAF; treat as unknown, verify by hand"
            result.elapsed_ms = int((time.monotonic() - started) * 1000)
            return result
        if exc.code == 429:
            result.status = "rate_limited"
            result.detail = "429; the host is busy"
            result.elapsed_ms = int((time.monotonic() - started) * 1000)
            return result
        if exc.code in (301, 302, 307, 308):
            target = exc.headers.get("Location", "") if exc.headers else ""
            result.redirected_to = target or result.redirected_to
            result.status = "redirect"
            result.detail = f"redirects to {result.redirected_to}"
            result.elapsed_ms = int((time.monotonic() - started) * 1000)
            return result
        result.status = "not_found" if exc.code == 404 else "http_error"
        result.detail = f"HTTP {exc.code}"
        result.elapsed_ms = int((time.monotonic() - started) * 1000)
        return result
    except urllib.error.URLError as exc:
        result.status = "unreachable"
        result.error = str(exc.reason)
        result.elapsed_ms = int((time.monotonic() - started) * 1000)
        return result
    except Exception as exc:  # noqa: BLE001 - a probe must never crash the survey
        result.status = "error"
        result.error = str(exc)
        result.elapsed_ms = int((time.monotonic() - started) * 1000)
        return result

    try:
        payload = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        result.status = "not_blockscout"
        result.detail = "answered, but not with the Blockscout v2 schema"
        result.elapsed_ms = int((time.monotonic() - started) * 1000)
        return result

    if isinstance(payload, dict) and "items" in payload:
        result.status = "live"
        result.detail = "Blockscout v2 smart-contracts answered"
        result.sample_contracts = len(payload.get("items") or [])
    elif isinstance(payload, dict) and payload.get("message"):
        result.status = "not_blockscout"
        result.detail = str(payload.get("message"))[:120]
    else:
        result.status = "not_blockscout"
        result.detail = "answered, but not with the Blockscout v2 schema"
    result.elapsed_ms = int((time.monotonic() - started) * 1000)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        default="var/chain-probe/latest.json",
        help="where to write the report (default: var/chain-probe/latest.json)",
    )
    parser.add_argument("--limit", type=int, default=200, help="how many hosts to probe")
    parser.add_argument(
        "--skip-from",
        default="",
        help="a previous report; hosts already probed in it are not probed again",
    )
    parser.add_argument("--rps", type=float, default=DEFAULT_RPS, help="seconds between probes")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="per-request timeout",
    )
    parser.add_argument(
        "--known",
        default="",
        help="comma-separated hosts already in the registry (probed first, as a regression)",
    )
    parser.add_argument(
        "--known-from-registry",
        action="store_true",
        help="probe the hosts already in app.services.chains first, as a regression",
    )
    args = parser.parse_args(argv)

    print(f"reading {CHAIN_REGISTRY_URL}")
    chains = fetch_chain_registry(args.timeout)
    print(f"  {len(chains)} chains in the public registry")

    # Existing hosts first: a registry that no longer answers is a bug to
    # notice immediately, not six months later.
    known = [h.strip() for h in args.known.split(",") if h.strip()]
    if args.known_from_registry:
        repo_root = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(repo_root / "apps" / "api"))
        try:
            from app.services.chains import INSTANCE_HOSTS  # noqa: PLC0415

            known.extend(host for host in INSTANCE_HOSTS.values() if host not in known)
        except Exception as exc:  # noqa: BLE001 - the survey must still run
            print(f"could not read the registry: {exc}")
    print(f"  {len(known)} hosts already in the registry will be probed first")
    plan: list[tuple[str, int | None, str]] = [(h, None, "already in registry") for h in known]

    seen = set(known)
    for chain in chains:
        chain_id = chain.get("chainId")
        try:
            chain_id_int = int(chain_id)
        except (TypeError, ValueError):
            chain_id_int = None
        name = str(chain.get("name") or "")
        for host in candidate_hosts(chain):
            if host in seen:
                continue
            seen.add(host)
            plan.append((host, chain_id_int, name))

    if args.skip_from:
        previous = Path(args.skip_from)
        if previous.exists():
            already = {
                str(item.get("host"))
                for item in json.loads(previous.read_text(encoding="utf-8")).get("results", [])
            }
            before = len(plan)
            plan = [entry for entry in plan if entry[0] not in already]
            print(f"  skipping {before - len(plan)} hosts already probed in {previous}")
        else:
            print(f"  no previous report at {previous}; probing from the start")

    report = Report(started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    report.candidates = len(plan)
    target = plan[: args.limit]

    print(f"probing {len(target)} of {len(plan)} candidate hosts at {args.rps}/s")
    last = time.monotonic()
    for index, (host, chain_id, name) in enumerate(target, start=1):
        wait = args.rps - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        last = time.monotonic()
        result = probe_host(host, chain_id, name, args.timeout)
        report.probed += 1
        report.results.append(result)
        if result.status == "rate_limited":
            time.sleep(5)
        marker = {
            "live": "+",
            "blocked": "?",
            "redirect": ">",
            "unreachable": ".",
        }.get(result.status, "-")
        print(
            f"  [{index:>4}/{len(target)}] {marker} {host:<40} "
            f"{result.status:<14} {result.http_status or '-':<5} "
            f"{result.chain_id if result.chain_id is not None else ''} "
            f"{result.detail[:60]}",
            flush=True,
        )

    report.finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")

    live = [r for r in report.results if r.status == "live"]
    blocked = [r for r in report.results if r.status == "blocked"]
    print()
    print(f"probed        : {report.probed}")
    print(f"live instances: {len(live)}")
    print(f"blocked (403) : {len(blocked)}")
    print(f"report        : {out}")
    if live:
        print()
        print("live hosts (review before adding to the registry):")
        for r in live:
            print(f"  {r.host:<40} chain_id={r.chain_id} {r.chain_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
