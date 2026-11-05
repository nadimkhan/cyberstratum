"""Report newer upstream dependency versions. Never upgrades anything.

Run with::

    python -m app.cli.update_check
    python -m app.cli.update_check --output var/dependency-updates.json

The check is **check-only**: it reads the repository's manifests, asks
the public registries for the newest published versions and prints a JSON
report. It never installs, upgrades or pins a dependency, and it never
writes to a manifest or a lockfile.

The exit code is ``0`` whenever the check completed -- whether or not
updates were found, because an available update is not an error. A
non-zero exit code means the check could not be performed at all.

The 24-hour cadence is a scheduling concern and lives outside this
module: a scheduler invokes this command once a day.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from app.services import dependency_updates
from app.services.dependency_updates import UpdateReport, VersionFetcher


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the command."""
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.update_check",
        description=(
            "Check the pinned dependencies against the public registries and "
            "report newer upstream versions. Check-only: nothing is installed "
            "or upgraded."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the JSON report to this path as well as printing it.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="The repository root to read manifests from. Defaults to the "
        "repository this package lives in.",
    )
    return parser


def render(report: UpdateReport) -> str:
    """Render a report as an indented JSON document."""
    return json.dumps(report.to_dict(), indent=2, sort_keys=False)


def main(
    argv: Sequence[str] | None = None,
    *,
    fetcher: VersionFetcher | None = None,
) -> int:
    """Run the update check and print the report.

    Args:
        argv: The command-line arguments, excluding the program name.
            Defaults to ``sys.argv[1:]``.
        fetcher: The network layer. Defaults to the module's default
            fetcher; the tests pass a stub so that they never touch the
            network.

    Returns:
        ``0`` when the check completed, ``1`` when it could not be
        performed at all.
    """
    args = build_parser().parse_args(argv)

    report = dependency_updates.run_update_check(
        args.repo_root,
        fetcher=fetcher,
    )

    payload = render(report)
    print(payload)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")

    return 0 if report.completed else 1


if __name__ == "__main__":
    sys.exit(main())
