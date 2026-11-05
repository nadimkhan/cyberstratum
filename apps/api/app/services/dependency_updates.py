"""Dependency update monitor for CyberStratum.

Policy
------

This module is **check-only**. It reports which pinned dependencies have a
newer version available upstream; it never installs, upgrades, pins, or
otherwise mutates anything:

* No package manager is ever invoked. ``pip``, ``uv``, ``npm``, ``yarn``
  and friends are never imported and never shelled out to. There is no
  ``subprocess`` call anywhere in this file.
* No lockfile, manifest, virtual environment or installed distribution is
  written to.
* A newer upstream version is *information*, not an action. Production
  dependency upgrades go through gated CI, where they are tested and
  reviewed before they land. This module produces the input for that
  decision; it never makes the decision.

The 24-hour cadence is a *scheduling* concern and lives outside this
module: a scheduler (cron, a CI schedule, a task runner) invokes the
CLI once a day. The module keeps no clock of its own -- the timestamp is
passed in -- so the report is deterministic and testable.

Layout
------

* The **pure core** is :func:`build_update_report`. It takes the pinned
  versions and the latest upstream versions as plain mappings and returns
  the structured report. It has no clock, no network and no randomness.
* The **network layer** is :class:`RegistryFetcher`. It is the only code
  in this module that talks to the outside world, and it is replaceable so
  that the tests never touch the network.
* The **manifest layer** reads the repository's own ``pyproject.toml`` and
  ``package.json`` files at call time, so the monitor cannot drift away
  from what the project actually declares.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, Protocol

import httpx

#: The two ecosystems this monitor knows about.
Ecosystem = Literal["pypi", "npm"]

#: Every ecosystem, in a stable order.
ECOSYSTEMS: Final[tuple[Ecosystem, ...]] = ("pypi", "npm")

#: PyPI's JSON API.
PYPI_BASE_URL: Final[str] = "https://pypi.org/pypi"

#: The public npm registry.
NPM_BASE_URL: Final[str] = "https://registry.npmjs.org"

#: The per-request timeout, in seconds, for registry lookups.
DEFAULT_TIMEOUT: Final[float] = 10.0

#: The report states this policy so a reader of the JSON knows that a
#: newer version listed here is an observation and not an applied change.
POLICY: Final[str] = "check-only"

#: The status of a package whose latest version is known and equal to (or
#: older than) the pinned version.
STATUS_UP_TO_DATE: Final[str] = "up_to_date"

#: The status of a package with a newer upstream version.
STATUS_UPDATE_AVAILABLE: Final[str] = "update_available"

#: The status of a package whose upstream version could not be determined.
STATUS_UNKNOWN: Final[str] = "unknown"

#: The status of a package whose registry lookup failed.
STATUS_ERROR: Final[str] = "error"


# ---------------------------------------------------------------------------
# Pure core
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LatestVersion:
    """The outcome of one upstream version lookup.

    Attributes:
        version: The newest version published upstream, or ``None`` when
            it could not be determined.
        registry_url: The registry endpoint that was consulted.
        error: Why the lookup failed, when it did.
    """

    version: str | None
    registry_url: str
    error: str | None = None


@dataclass(frozen=True)
class PackageUpdate:
    """One package's update status.

    Attributes:
        name: The distribution or package name.
        ecosystem: Which registry the package lives in.
        pinned_version: The version the repository currently pins (the
            lower bound of the declared constraint).
        latest_version: The newest upstream version, when known.
        update_available: Whether a newer upstream version exists.
        registry_url: The registry endpoint consulted for this package.
        checked_at: The timestamp of the check.
        status: One of ``up_to_date``, ``update_available``, ``unknown``
            or ``error``.
        error: Why the package could not be checked, when it could not.
    """

    name: str
    ecosystem: Ecosystem
    pinned_version: str
    latest_version: str | None
    update_available: bool
    registry_url: str
    checked_at: str
    status: str
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable representation."""
        return {
            "name": self.name,
            "ecosystem": self.ecosystem,
            "pinned_version": self.pinned_version,
            "latest_version": self.latest_version,
            "update_available": self.update_available,
            "registry_url": self.registry_url,
            "checked_at": self.checked_at,
            "status": self.status,
            "error": self.error,
        }


@dataclass(frozen=True)
class ManifestError:
    """A manifest that could not be read or parsed.

    Attributes:
        manifest: The path of the offending manifest.
        error: What went wrong.
    """

    manifest: str
    error: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable representation."""
        return {"manifest": self.manifest, "error": self.error}


@dataclass(frozen=True)
class UpdateReport:
    """The complete result of one dependency update check.

    Attributes:
        checked_at: The timestamp of the check.
        packages: One entry per checked package.
        manifest_errors: Manifests that could not be parsed.
        manifests_scanned: The number of manifests that were read
            successfully.
    """

    checked_at: str
    packages: tuple[PackageUpdate, ...]
    manifest_errors: tuple[ManifestError, ...] = ()
    manifests_scanned: int = 0

    @property
    def updates_available(self) -> tuple[PackageUpdate, ...]:
        """The packages with a newer upstream version."""
        return tuple(package for package in self.packages if package.update_available)

    @property
    def completed(self) -> bool:
        """Whether the check produced a usable result.

        A check that found nothing because no manifest could be read has
        not been performed, and callers must treat it as a failure rather
        than as "everything is up to date".
        """
        if self.packages:
            return True
        if self.manifest_errors:
            return False
        return self.manifests_scanned > 0

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable representation of the report."""
        return {
            "checked_at": self.checked_at,
            "policy": POLICY,
            "packages": [package.to_dict() for package in self.packages],
            "manifest_errors": [error.to_dict() for error in self.manifest_errors],
            "summary": {
                "packages": len(self.packages),
                "updates_available": len(self.updates_available),
                "unknown": sum(1 for p in self.packages if p.status == STATUS_UNKNOWN),
                "errors": sum(1 for p in self.packages if p.status == STATUS_ERROR),
                "manifest_errors": len(self.manifest_errors),
                "manifests_scanned": self.manifests_scanned,
            },
        }


def build_update_report(
    pinned: Mapping[str, Mapping[str, str]],
    latest: Mapping[str, Mapping[str, LatestVersion]],
    *,
    checked_at: str,
) -> UpdateReport:
    """Compare pinned versions with upstream versions.

    This is the pure core of the monitor: no clock, no network, no
    randomness. The caller supplies both the timestamp and the upstream
    versions.

    Args:
        pinned: The pinned versions, keyed by ecosystem and then by
            package name.
        latest: The upstream versions, keyed by ecosystem and then by
            package name. A package missing from this mapping, or mapped
            to a :class:`LatestVersion` without a version, is reported as
            unknown rather than as up to date.
        checked_at: The timestamp of the check, recorded on every package.

    Returns:
        The report.
    """
    packages: list[PackageUpdate] = []
    for ecosystem in ECOSYSTEMS:
        ecosystem_pinned = pinned.get(ecosystem, {})
        ecosystem_latest = latest.get(ecosystem, {})
        for name in sorted(ecosystem_pinned):
            packages.append(
                _compare_one(
                    ecosystem=ecosystem,
                    name=name,
                    pinned_version=ecosystem_pinned[name],
                    latest=ecosystem_latest.get(name),
                    checked_at=checked_at,
                )
            )
    return UpdateReport(checked_at=checked_at, packages=tuple(packages))


def _compare_one(
    *,
    ecosystem: Ecosystem,
    name: str,
    pinned_version: str,
    latest: LatestVersion | None,
    checked_at: str,
) -> PackageUpdate:
    """Build the report entry for a single package."""
    if latest is None:
        return PackageUpdate(
            name=name,
            ecosystem=ecosystem,
            pinned_version=pinned_version,
            latest_version=None,
            update_available=False,
            registry_url=registry_url(ecosystem, name),
            checked_at=checked_at,
            status=STATUS_UNKNOWN,
            error="no upstream lookup result",
        )

    if latest.version is None:
        return PackageUpdate(
            name=name,
            ecosystem=ecosystem,
            pinned_version=pinned_version,
            latest_version=None,
            update_available=False,
            registry_url=latest.registry_url,
            checked_at=checked_at,
            status=STATUS_ERROR,
            error=latest.error or "upstream version unavailable",
        )

    if not pinned_version:
        return PackageUpdate(
            name=name,
            ecosystem=ecosystem,
            pinned_version=pinned_version,
            latest_version=latest.version,
            update_available=False,
            registry_url=latest.registry_url,
            checked_at=checked_at,
            status=STATUS_UNKNOWN,
            error="pinned version could not be determined",
        )

    newer = compare_versions(latest.version, pinned_version) > 0
    return PackageUpdate(
        name=name,
        ecosystem=ecosystem,
        pinned_version=pinned_version,
        latest_version=latest.version,
        update_available=newer,
        registry_url=latest.registry_url,
        checked_at=checked_at,
        status=STATUS_UPDATE_AVAILABLE if newer else STATUS_UP_TO_DATE,
        error=None,
    )


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------

#: The kind of a parsed version, ordered by release precedence.
_KIND_ORDER: Final[dict[str, int]] = {
    "dev": -3,
    "alpha": -2,
    "beta": -1,
    "rc": 0,
    "final": 1,
    "post": 2,
}

#: The label of a parsed version and its kind.
_LABEL_KIND: Final[dict[str, str]] = {
    "dev": "dev",
    "alpha": "alpha",
    "a": "alpha",
    "beta": "beta",
    "b": "beta",
    "c": "rc",
    "rc": "rc",
    "pre": "rc",
    "preview": "rc",
    "post": "post",
    "rev": "post",
    "r": "post",
}

_RELEASE_RE: Final[re.Pattern[str]] = re.compile(r"^(?P<release>\d+(?:\.\d+)*)")
_TAIL_RE: Final[re.Pattern[str]] = re.compile(r"^[-_.]?(?P<label>[A-Za-z]+)[-_.]?(?P<number>\d*)$")
_VERSION_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"\d+(?:\.\w+)*")


def parse_version(version: str) -> tuple[tuple[int, ...], str, int] | None:
    """Parse a version string into a comparable form.

    The parser understands the release segment plus an optional
    pre-release or post-release label, which covers the version shapes
    that appear in PyPI and npm manifests.

    Args:
        version: The version string.

    Returns:
        ``(release, kind, number)`` or ``None`` when the string cannot be
        parsed.
    """
    text = version.strip()
    if not text:
        return None
    text = text.lstrip("vV")
    # Drop the local version segment and any epoch, both of which do not
    # affect the ordering of the releases that matter here.
    text = text.split("+", 1)[0]
    if "!" in text:
        text = text.split("!", 1)[1]

    match = _RELEASE_RE.match(text)
    if match is None:
        return None
    release = tuple(int(part) for part in match.group("release").split("."))
    tail = text[match.end() :].strip()

    if not tail:
        return release, "final", 0

    tail_match = _TAIL_RE.match(tail)
    if tail_match is None:
        return release, "final", 0
    label = tail_match.group("label").lower()
    kind = _LABEL_KIND.get(label)
    if kind is None:
        return release, "final", 0
    number_text = tail_match.group("number")
    number = int(number_text) if number_text else 0
    return release, kind, number


def compare_versions(left: str, right: str) -> int:
    """Compare two version strings.

    Args:
        left: The first version.
        right: The second version.

    Returns:
        ``1`` when ``left`` is newer than ``right``, ``-1`` when it is
        older, and ``0`` when the two are equal or cannot be compared.
    """
    parsed_left = parse_version(left)
    parsed_right = parse_version(right)
    if parsed_left is None or parsed_right is None:
        return 0

    release_left, kind_left, number_left = parsed_left
    release_right, kind_right, number_right = parsed_right

    length = max(len(release_left), len(release_right))
    for index in range(length):
        value_left = release_left[index] if index < len(release_left) else 0
        value_right = release_right[index] if index < len(release_right) else 0
        if value_left != value_right:
            return 1 if value_left > value_right else -1

    order_left = _KIND_ORDER.get(kind_left, 1)
    order_right = _KIND_ORDER.get(kind_right, 1)
    if order_left != order_right:
        return 1 if order_left > order_right else -1
    if number_left != number_right:
        return 1 if number_left > number_right else -1
    return 0


# ---------------------------------------------------------------------------
# Network layer
# ---------------------------------------------------------------------------


class VersionFetcher(Protocol):
    """The interface the monitor uses to reach a registry.

    Implementations return the newest upstream version, or a
    :class:`LatestVersion` without a version when the lookup failed. A
    failed lookup is never reported as "no update available".
    """

    def fetch(self, ecosystem: Ecosystem, name: str) -> LatestVersion:
        """Look up the newest upstream version of a package."""
        ...


def registry_url(ecosystem: Ecosystem, name: str) -> str:
    """Return the registry endpoint for a package.

    Args:
        ecosystem: Which registry to address.
        name: The package name.

    Returns:
        The URL that will be consulted.
    """
    if ecosystem == "pypi":
        return f"{PYPI_BASE_URL}/{normalize_pypi_name(name)}/json"
    return f"{NPM_BASE_URL}/{name.replace('/', '%2F')}"


def normalize_pypi_name(name: str) -> str:
    """Normalise a distribution name the way PyPI does."""
    return re.sub(r"[-_.]+", "-", name).lower()


class RegistryFetcher:
    """Fetches the latest published version of a package.

    This is the only network-aware code in the module. It uses ``httpx``
    with an explicit timeout and treats every failure -- a timeout, a
    connection error, a non-200 status, a malformed body -- as
    *unknown*, never as "no update".
    """

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        """Store the per-request timeout.

        Args:
            timeout: The per-request timeout in seconds.
        """
        self._timeout = timeout

    def fetch(self, ecosystem: Ecosystem, name: str) -> LatestVersion:
        """Look up the newest upstream version of a package.

        Args:
            ecosystem: Which registry to address.
            name: The package name.

        Returns:
            The lookup outcome. A failure carries the error message and
            no version.
        """
        url = registry_url(ecosystem, name)
        try:
            response = httpx.get(
                url,
                timeout=self._timeout,
                follow_redirects=True,
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            return LatestVersion(None, url, f"{type(exc).__name__}: {exc}")

        if response.status_code != 200:
            return LatestVersion(None, url, f"HTTP {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            return LatestVersion(None, url, f"invalid JSON: {exc}")

        version = _extract_version(ecosystem, payload)
        if version is None:
            return LatestVersion(None, url, "no version in registry response")
        return LatestVersion(version, url, None)


def _extract_version(ecosystem: Ecosystem, payload: object) -> str | None:
    """Pull the latest version out of a registry response."""
    if ecosystem == "pypi":
        raw = _dig(payload, "info", "version")
    else:
        raw = _dig(payload, "dist-tags", "latest")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _dig(payload: object, *path: str) -> object:
    """Walk a nested mapping, returning ``None`` when the path is absent."""
    current: object = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


#: The default network layer. Tests replace it.
DEFAULT_FETCHER: VersionFetcher = RegistryFetcher()


# ---------------------------------------------------------------------------
# Manifest layer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ManifestScan:
    """What one manifest declares.

    Attributes:
        ecosystem: Which registry the declared packages live in.
        dependencies: The declared package names mapped to the lower
            bound of their version constraint.
        local_names: The names of distributions built from this
            repository itself, which are never looked up upstream.
    """

    ecosystem: Ecosystem
    dependencies: Mapping[str, str]
    local_names: frozenset[str]


def python_manifest_paths(repo_root: Path) -> list[Path]:
    """Return the Python manifests of the repository.

    The root project, the API application (when it carries its own
    manifest) and every workspace package under ``packages/``.
    """
    paths = [
        repo_root / "pyproject.toml",
        repo_root / "apps" / "api" / "pyproject.toml",
    ]
    packages_dir = repo_root / "packages"
    if packages_dir.is_dir():
        paths.extend(sorted(packages_dir.glob("*/pyproject.toml")))
    return paths


def npm_manifest_paths(repo_root: Path) -> list[Path]:
    """Return the npm manifests of the repository."""
    return [
        repo_root / "package.json",
        repo_root / "apps" / "web" / "package.json",
    ]


def scan_python_manifest(path: Path) -> ManifestScan:
    """Parse a ``pyproject.toml`` into its declared dependencies.

    Args:
        path: The manifest to read.

    Returns:
        The declared dependencies.

    Raises:
        OSError: The manifest could not be read.
        ValueError: The manifest could not be parsed.
    """
    text = path.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    project = _project_section(data)

    dependencies: dict[str, str] = {}
    for spec in _as_string_list(project.get("dependencies")):
        name, floor = _split_requirement(spec)
        if name:
            dependencies.setdefault(name, floor)

    optional = project.get("optional-dependencies")
    if isinstance(optional, dict):
        for group in optional.values():
            for spec in _as_string_list(group):
                name, floor = _split_requirement(spec)
                if name:
                    dependencies.setdefault(name, floor)

    local = _project_name(project)
    return ManifestScan(
        ecosystem="pypi",
        dependencies=dependencies,
        local_names=frozenset({local} if local else set()),
    )


def scan_npm_manifest(path: Path) -> ManifestScan:
    """Parse a ``package.json`` into its declared dependencies.

    Both ``dependencies`` and ``devDependencies`` are read: the monitor
    reports on what the project declares, whatever its role.

    Args:
        path: The manifest to read.

    Returns:
        The declared dependencies.

    Raises:
        OSError: The manifest could not be read.
        ValueError: The manifest could not be parsed.
    """
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("package.json is not an object")

    dependencies: dict[str, str] = {}
    for section in ("dependencies", "devDependencies"):
        entries = data.get(section)
        if not isinstance(entries, dict):
            continue
        for name, version in entries.items():
            if isinstance(name, str) and isinstance(version, str):
                dependencies.setdefault(name, floor_version(version))

    local = data.get("name")
    local_names = {local} if isinstance(local, str) and local else set()
    return ManifestScan(
        ecosystem="npm",
        dependencies=dependencies,
        local_names=frozenset(local_names),
    )


def _project_section(data: Mapping[str, object]) -> Mapping[str, object]:
    """Return the ``[project]`` table of a pyproject, or an empty mapping."""
    section = data.get("project")
    if isinstance(section, dict):
        return section
    return {}


def _project_name(project: Mapping[str, object]) -> str:
    """Return the distribution name declared by a pyproject."""
    name = project.get("name")
    if isinstance(name, str):
        return name
    return ""


def _as_string_list(value: object) -> list[str]:
    """Return a value as a list of strings, ignoring anything else."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


_REQUIREMENT_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(?P<spec>.*)$"
)


def _split_requirement(spec: str) -> tuple[str, str]:
    """Split a requirement string into its name and lower bound."""
    match = _REQUIREMENT_RE.match(spec)
    if match is None:
        return "", ""
    return match.group("name"), floor_version(match.group("spec"))


def floor_version(constraint: str) -> str:
    """Return the lower bound of a version constraint.

    ``>=1.2.3`` yields ``1.2.3``, ``^2.0.0`` yields ``2.0.0`` and an
    exact pin yields itself. A constraint without a version yields the
    empty string.
    """
    match = _VERSION_TOKEN_RE.search(constraint)
    if match is None:
        return ""
    return match.group(0)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def default_repo_root() -> Path:
    """Return the repository root as seen from this file's location."""
    return Path(__file__).resolve().parents[4]


def collect_pinned_dependencies(
    repo_root: Path,
) -> tuple[dict[str, dict[str, str]], list[ManifestError], set[str], int]:
    """Read the repository's manifests and collect the pinned packages.

    A candidate manifest that does not exist is skipped: the layout is
    discovered, not assumed. A manifest that exists but cannot be parsed
    is reported as an error entry instead of crashing the check.

    Args:
        repo_root: The repository root.

    Returns:
        The pinned versions by ecosystem and package name, the manifest
        errors, the names of the distributions this repository builds
        itself (which are never looked up upstream), and the number of
        manifests that were read successfully.
    """
    pinned: dict[str, dict[str, str]] = {"pypi": {}, "npm": {}}
    manifest_errors: list[ManifestError] = []
    local_names: set[str] = set()
    scanned = 0

    scans: list[tuple[Path, Ecosystem]] = [
        (path, "pypi") for path in python_manifest_paths(repo_root)
    ] + [(path, "npm") for path in npm_manifest_paths(repo_root)]

    for path, ecosystem in scans:
        if not path.is_file():
            continue
        try:
            scan = scan_python_manifest(path) if ecosystem == "pypi" else scan_npm_manifest(path)
        except (OSError, ValueError) as exc:
            manifest_errors.append(
                ManifestError(manifest=str(path), error=f"{type(exc).__name__}: {exc}")
            )
            continue
        scanned += 1
        local_names.update(scan.local_names)
        target = pinned[ecosystem]
        for name, version in scan.dependencies.items():
            target.setdefault(name, version)

    return pinned, manifest_errors, local_names, scanned


def _is_local(name: str, local_names: set[str]) -> bool:
    """Whether a package is built from this repository itself."""
    if name in local_names:
        return True
    return any(normalize_pypi_name(local) == normalize_pypi_name(name) for local in local_names)


def run_update_check(
    repo_root: Path | None = None,
    *,
    fetcher: VersionFetcher | None = None,
    checked_at: str | None = None,
) -> UpdateReport:
    """Run one dependency update check.

    The check reads the repository's manifests, asks the registries for
    the latest published versions and returns the report. Nothing is
    installed, upgraded or written.

    Args:
        repo_root: The repository root. Defaults to the repository this
            module lives in.
        fetcher: The network layer. Defaults to :data:`DEFAULT_FETCHER`.
        checked_at: The timestamp of the check. Defaults to the current
            time; the pure core always receives it explicitly.

    Returns:
        The report.
    """
    root = repo_root if repo_root is not None else default_repo_root()
    pinned, manifest_errors, local_names, scanned = collect_pinned_dependencies(root)

    active: dict[str, dict[str, str]] = {}
    for ecosystem in ECOSYSTEMS:
        active[ecosystem] = {
            name: version
            for name, version in pinned.get(ecosystem, {}).items()
            if not _is_local(name, local_names)
        }

    the_fetcher = fetcher if fetcher is not None else DEFAULT_FETCHER

    latest: dict[str, dict[str, LatestVersion]] = {ecosystem: {} for ecosystem in ECOSYSTEMS}
    for ecosystem in ECOSYSTEMS:
        for name in sorted(active[ecosystem]):
            latest[ecosystem][name] = the_fetcher.fetch(ecosystem, name)

    stamp = checked_at if checked_at is not None else datetime.now(UTC).isoformat()
    report = build_update_report(active, latest, checked_at=stamp)
    return UpdateReport(
        checked_at=report.checked_at,
        packages=report.packages,
        manifest_errors=tuple(manifest_errors),
        manifests_scanned=scanned,
    )


__all__: Sequence[str] = (
    "DEFAULT_FETCHER",
    "DEFAULT_TIMEOUT",
    "ECOSYSTEMS",
    "NPM_BASE_URL",
    "POLICY",
    "PYPI_BASE_URL",
    "STATUS_ERROR",
    "STATUS_UNKNOWN",
    "STATUS_UPDATE_AVAILABLE",
    "STATUS_UP_TO_DATE",
    "LatestVersion",
    "ManifestError",
    "ManifestScan",
    "PackageUpdate",
    "RegistryFetcher",
    "UpdateReport",
    "VersionFetcher",
    "build_update_report",
    "collect_pinned_dependencies",
    "compare_versions",
    "default_repo_root",
    "floor_version",
    "normalize_pypi_name",
    "npm_manifest_paths",
    "parse_version",
    "python_manifest_paths",
    "registry_url",
    "run_update_check",
    "scan_npm_manifest",
    "scan_python_manifest",
)
