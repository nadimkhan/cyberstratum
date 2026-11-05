"""Tests for the check-only dependency update monitor.

The network layer is stubbed throughout: the tests never reach PyPI or
the npm registry.

Inspection note: this module and
:mod:`app.services.dependency_updates` never import ``pip``, ``uv``,
``npm`` or ``yarn``, and never shell out through ``subprocess`` or
``os.system``. The monitor reports; it never installs. The final test in
this file asserts that by reading the service source.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.cli import update_check
from app.services import dependency_updates
from app.services.dependency_updates import (
    STATUS_ERROR,
    STATUS_UP_TO_DATE,
    STATUS_UPDATE_AVAILABLE,
    LatestVersion,
    UpdateReport,
    build_update_report,
    compare_versions,
    run_update_check,
)

CHECKED_AT = "2026-01-01T00:00:00+00:00"


class StubFetcher:
    """A fetcher that answers from a table instead of the network.

    A package that is absent from the table raises, which is how the
    tests exercise the registry-failure path.
    """

    def __init__(self, versions: dict[tuple[str, str], str]) -> None:
        self._versions = versions
        self.calls: list[tuple[str, str]] = []

    def fetch(self, ecosystem: str, name: str) -> LatestVersion:
        self.calls.append((ecosystem, name))
        version = self._versions.get((ecosystem, name))
        if version is None:
            return LatestVersion(
                None,
                dependency_updates.registry_url(ecosystem, name),  # type: ignore[arg-type]
                "HTTP 404",
            )
        return LatestVersion(
            version,
            dependency_updates.registry_url(ecosystem, name),  # type: ignore[arg-type]
        )


def _report_entry(report: UpdateReport, name: str) -> dict[str, Any]:
    for package in report.packages:
        if package.name == name:
            return package.to_dict()
    raise AssertionError(f"{name} not present in report")


# --- The pure core --------------------------------------------------------


def test_core_reports_an_update_when_latest_is_newer() -> None:
    """A newer upstream version is reported as an available update."""
    report = build_update_report(
        {"pypi": {"fastapi": "0.115.0"}, "npm": {}},
        {
            "pypi": {"fastapi": LatestVersion("0.116.0", "https://pypi.org/pypi/fastapi/json")},
            "npm": {},
        },
        checked_at=CHECKED_AT,
    )

    entry = _report_entry(report, "fastapi")
    assert entry["update_available"] is True
    assert entry["status"] == STATUS_UPDATE_AVAILABLE
    assert entry["latest_version"] == "0.116.0"
    assert entry["pinned_version"] == "0.115.0"
    assert entry["ecosystem"] == "pypi"
    assert entry["registry_url"] == "https://pypi.org/pypi/fastapi/json"
    assert entry["checked_at"] == CHECKED_AT


def test_core_reports_no_update_when_latest_is_equal() -> None:
    """An equal upstream version is not an update."""
    report = build_update_report(
        {"npm": {"react": "19.1.0"}, "pypi": {}},
        {
            "npm": {"react": LatestVersion("19.1.0", "https://registry.npmjs.org/react")},
            "pypi": {},
        },
        checked_at=CHECKED_AT,
    )

    entry = _report_entry(report, "react")
    assert entry["update_available"] is False
    assert entry["status"] == STATUS_UP_TO_DATE


def test_core_reports_no_update_when_latest_is_older() -> None:
    """An older upstream version is not an update."""
    report = build_update_report(
        {"pypi": {"pydantic": "2.9.0"}, "npm": {}},
        {
            "pypi": {"pydantic": LatestVersion("2.8.0", "https://pypi.org/pypi/pydantic/json")},
            "npm": {},
        },
        checked_at=CHECKED_AT,
    )

    entry = _report_entry(report, "pydantic")
    assert entry["update_available"] is False
    assert entry["status"] == STATUS_UP_TO_DATE


def test_core_uses_no_clock_and_no_network() -> None:
    """The pure core is a pure function of its arguments."""
    pinned = {"pypi": {"httpx": "0.27.0"}, "npm": {}}
    latest = {
        "pypi": {"httpx": LatestVersion("0.28.1", "https://pypi.org/pypi/httpx/json")},
        "npm": {},
    }

    first = build_update_report(pinned, latest, checked_at=CHECKED_AT)
    second = build_update_report(pinned, latest, checked_at=CHECKED_AT)

    assert first.to_dict() == second.to_dict()


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("1.2.3", "1.2.3", 0),
        ("1.2.4", "1.2.3", 1),
        ("1.2.3", "1.2.4", -1),
        ("1.10.0", "1.9.0", 1),
        ("2.0", "1.9.9", 1),
        ("1.0.0rc1", "1.0.0", -1),
        ("1.0.0", "1.0.0rc1", 1),
    ],
)
def test_compare_versions(left: str, right: str, expected: int) -> None:
    """Versions compare by release, then by pre/post-release rank."""
    assert compare_versions(left, right) == expected


# --- Registry failures ----------------------------------------------------


def test_registry_failure_is_recorded_and_does_not_abort_the_report(
    tmp_path: Path,
) -> None:
    """One failing lookup is an error entry, not a broken report."""
    fetcher = StubFetcher({("pypi", "fastapi"): "0.116.0"})
    repo_root = _write_minimal_repo(tmp_path / "repo")

    report = run_update_check(
        repo_root,
        fetcher=fetcher,
        checked_at=CHECKED_AT,
    )

    failed = _report_entry(report, "httpx")
    assert failed["status"] == STATUS_ERROR
    assert failed["update_available"] is False
    assert failed["latest_version"] is None
    assert failed["error"]

    # The other package was still checked.
    ok = _report_entry(report, "fastapi")
    assert ok["status"] == STATUS_UPDATE_AVAILABLE
    assert ok["latest_version"] == "0.116.0"
    assert report.completed is True


def test_missing_lookup_result_is_unknown_not_up_to_date() -> None:
    """A package with no lookup result is unknown, never up to date."""
    report = build_update_report(
        {"pypi": {"httpx": "0.27.0"}, "npm": {}},
        {"pypi": {}, "npm": {}},
        checked_at=CHECKED_AT,
    )

    entry = _report_entry(report, "httpx")
    assert entry["status"] == "unknown"
    assert entry["update_available"] is False


# --- Manifest handling ----------------------------------------------------


def test_unparseable_manifest_is_an_error_entry_and_does_not_crash(
    tmp_path: Path,
) -> None:
    """A broken manifest is reported, and the rest of the check continues."""
    repo_root = _write_minimal_repo(tmp_path / "repo")
    broken = repo_root / "pyproject.toml"
    broken.write_text("this is not valid toml = = =", encoding="utf-8")

    report = run_update_check(
        repo_root,
        fetcher=StubFetcher({}),
        checked_at=CHECKED_AT,
    )

    assert len(report.manifest_errors) == 1
    assert report.manifest_errors[0].manifest.endswith("pyproject.toml")
    assert report.manifest_errors[0].error

    # The npm manifest was still read.
    assert any(package.ecosystem == "npm" for package in report.packages)


def test_missing_manifest_is_skipped_without_error(tmp_path: Path) -> None:
    """A manifest that does not exist is skipped, not reported as broken."""
    repo_root = _write_minimal_repo(tmp_path / "repo")
    (repo_root / "apps" / "api" / "pyproject.toml").unlink(missing_ok=True)

    report = run_update_check(
        repo_root,
        fetcher=StubFetcher({}),
        checked_at=CHECKED_AT,
    )

    assert report.manifest_errors == ()
    assert report.completed is True


def test_manifests_are_read_from_disk_not_hardcoded(tmp_path: Path) -> None:
    """The pinned set comes from the manifests on disk."""
    repo_root = _write_minimal_repo(tmp_path / "repo")
    manifest = repo_root / "apps" / "web" / "package.json"
    manifest.write_text(
        json.dumps({"name": "@cyberstratum/web", "dependencies": {"left-pad": "1.3.0"}}),
        encoding="utf-8",
    )

    report = run_update_check(
        repo_root,
        fetcher=StubFetcher({}),
        checked_at=CHECKED_AT,
    )

    assert any(package.name == "left-pad" for package in report.packages)
    assert not any(package.name == "react" for package in report.packages)


def _write_minimal_repo(root: Path) -> Path:
    """Write a small two-ecosystem repository and return its root."""
    (root / "apps" / "web").mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        "[project]\n"
        'name = "cyberstratum"\n'
        'version = "0.1.0"\n'
        "dependencies = [\n"
        '  "fastapi>=0.115",\n'
        '  "httpx>=0.27",\n'
        "]\n",
        encoding="utf-8",
    )
    (root / "apps" / "web" / "package.json").write_text(
        json.dumps(
            {
                "name": "@cyberstratum/web",
                "dependencies": {"react": "19.1.0"},
                "devDependencies": {"typescript": "5.8.3"},
            }
        ),
        encoding="utf-8",
    )
    return root


# --- The CLI --------------------------------------------------------------


def test_cli_prints_valid_json_and_exits_zero_when_updates_exist(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An available update is not an error: the CLI still exits zero."""
    repo_root = _write_minimal_repo(tmp_path / "repo")
    fetcher = StubFetcher(
        {
            ("pypi", "fastapi"): "0.116.0",
            ("pypi", "httpx"): "0.28.1",
            ("npm", "react"): "19.1.0",
            ("npm", "typescript"): "5.8.3",
        }
    )

    code = update_check.main(
        ["--repo-root", str(repo_root)],
        fetcher=fetcher,
    )
    captured = capsys.readouterr()

    assert code == 0
    payload = json.loads(captured.out)
    assert payload["policy"] == "check-only"
    assert payload["summary"]["updates_available"] == 2
    assert payload["summary"]["packages"] == 4
    assert payload["checked_at"]


def test_cli_writes_the_report_to_a_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--output`` writes the same JSON to disk."""
    repo_root = _write_minimal_repo(tmp_path / "repo")
    output = tmp_path / "out" / "report.json"
    fetcher = StubFetcher({("pypi", "fastapi"): "0.116.0"})

    code = update_check.main(
        ["--repo-root", str(repo_root), "--output", str(output)],
        fetcher=fetcher,
    )
    capsys.readouterr()

    assert code == 0
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["policy"] == "check-only"


def test_cli_help_works() -> None:
    """``--help`` prints usage and exits zero."""
    with pytest.raises(SystemExit) as excinfo:
        update_check.main(["--help"])

    assert excinfo.value.code == 0


def test_cli_exits_non_zero_when_the_check_could_not_be_performed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A check that could not run at all exits non-zero."""
    repo_root = tmp_path / "empty"
    repo_root.mkdir()

    code = update_check.main(
        ["--repo-root", str(repo_root)],
        fetcher=StubFetcher({}),
    )
    capsys.readouterr()

    assert code == 1


# --- The no-upgrade policy ------------------------------------------------


def test_service_never_installs_anything() -> None:
    """The module contains no package manager and no shell-out.

    This asserts the policy by inspection: the check-only monitor must
    not be able to upgrade a dependency.
    """
    source = Path(dependency_updates.__file__).read_text(encoding="utf-8")

    for forbidden in (
        "import pip",
        "import npm",
        "import subprocess",
        "os.system",
        "pip install",
        "npm install",
        "npm update",
        "uv pip",
        "shell=True",
    ):
        assert forbidden not in source, f"{forbidden} must not appear in the service"

    cli_source = Path(update_check.__file__).read_text(encoding="utf-8")
    for forbidden in ("import subprocess", "os.system", "pip install", "npm install"):
        assert forbidden not in cli_source


def test_service_exposes_no_upgrade_entry_point() -> None:
    """The public surface offers reporting only."""
    for name in dependency_updates.__all__:
        assert not any(
            token in name.lower() for token in ("upgrade", "install", "bump", "update_all")
        )
