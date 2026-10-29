"""Tests that the artifact storage root does not depend on the working directory.

The API, the scan worker and the deep-analysis workers do not run from the
same working directory: the launcher starts the API from the repository
root and the workers from ``apps/api``. A relative ``OBJECT_STORAGE_ROOT``
therefore points at a different directory for each process. The pipeline
writes its artifacts into one of them and the workers look for them in
another, and every artifact read fails as if the file had never been
stored.

This has happened for real: the Mythril and correspondence workers both
reported ``bytecode_artifact_missing`` for scans whose runtime bytecode
had been written successfully minutes earlier.

These tests fail loudly instead.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = REPO_ROOT / "apps" / "api"

_PROBE = "from app.core.config import get_settings;print(get_settings().object_storage_root)"


def _storage_root_from(cwd: Path) -> str:
    """Return the configured storage root as seen from a working directory.

    Args:
        cwd: The working directory to run the probe in.

    Returns:
        The configured path, as the process itself prints it.
    """
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(f"the storage-root probe failed in {cwd}:\n{completed.stderr}")
    return completed.stdout.strip().splitlines()[-1]


def test_the_storage_root_is_absolute() -> None:
    """The configured root must be absolute, whatever the environment says."""
    root = _storage_root_from(REPO_ROOT)
    assert Path(root).is_absolute(), (
        f"the artifact storage root is {root!r}, which is relative. A relative "
        "root resolves differently for every process, so artifacts written by "
        "one process cannot be read by another."
    )


def test_the_storage_root_does_not_depend_on_the_working_directory() -> None:
    """Two processes in different directories must agree on the root."""
    from_root = _storage_root_from(REPO_ROOT)
    from_api = _storage_root_from(API_DIR)
    assert from_root == from_api, (
        f"the artifact storage root is {from_root!r} from the repository root "
        f"but {from_api!r} from apps/api. The workers read their artifacts "
        "from a different directory than the API writes them to."
    )
