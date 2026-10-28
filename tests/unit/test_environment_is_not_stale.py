"""Tests that the environment cannot silently test stale code.

A non-editable install of the project puts a *snapshot* of the ``app``
package into the virtual environment's ``site-packages``. That snapshot
shadows the working tree, so the test suite passes against code that is no
longer the code in the repository -- and every result looks perfectly
healthy.

This has happened for real: on WSL a plain ``uv pip install ".[dev,ml]"``
replaced an editable install with a snapshot, and the suite went on testing
a version of the API that predated several commits. Nothing failed, because
the snapshot was internally consistent.

These tests fail loudly instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The directory the application package must live in.
APP_DIR = REPO_ROOT / "apps" / "api" / "app"


def _app_location() -> Path:
    """Return the path the ``app`` package actually resolves to.

    Returns:
        The resolved path of the imported package.
    """
    import app

    origin = app.__file__
    if origin is None:  # pragma: no cover - a namespace package
        pytest.fail("the app package has no __file__, so it cannot be verified")
    return Path(origin).resolve()


def test_the_app_package_resolves_to_the_working_tree() -> None:
    """The imported application must be the working tree, not a snapshot.

    A snapshot in ``site-packages`` is a copy of the code at install time.
    Once installed, it stops tracking the repository, and the test suite
    then certifies code that no longer exists.
    """
    location = _app_location()
    assert APP_DIR in location.parents, (
        f"the app package resolves to {location}, but the working tree is "
        f"{APP_DIR}. The project is installed non-editable, so a stale "
        f"snapshot is shadowing it. Fix with: uv pip install -e ."
    )


def test_no_copy_of_the_app_package_sits_in_site_packages() -> None:
    """No installed copy of the application may sit in site-packages."""
    location = _app_location()
    if "site-packages" not in location.parts:
        return
    pytest.fail(
        f"a copy of the app package is installed at {location}; it shadows "
        f"the working tree. Fix with: uv pip install -e ."
    )


def test_the_repository_precedes_site_packages_on_the_import_path() -> None:
    """The repository must come before site-packages on the import path.

    Even with an editable install, an installed copy earlier on the path
    would win. This pins the ordering that makes the rest of the suite
    meaningful.
    """
    repo_index = None
    site_index = None
    for index, entry in enumerate(sys.path):
        if not entry:
            continue
        resolved = Path(entry).resolve()
        if repo_index is None and resolved == REPO_ROOT:
            repo_index = index
        if site_index is None and "site-packages" in resolved.parts:
            site_index = index
    if repo_index is None or site_index is None:
        return
    assert repo_index < site_index, (
        f"the repository sits at sys.path[{repo_index}] but site-packages "
        f"sits at sys.path[{site_index}]; an installed copy would win over "
        f"the working tree"
    )
