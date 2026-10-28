"""Local object-storage adapter.

Design doc section 23.1 requires a storage adapter so local filesystem and an
S3 bucket share one interface. Only the local driver is implemented; the
interface keeps the pipeline free of direct filesystem calls.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


class ObjectStorageError(RuntimeError):
    """Raised when an artifact cannot be persisted."""


def _root() -> Path:
    root = Path(get_settings().object_storage_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def put_bytes(object_key: str, payload: bytes) -> str:
    """Store ``payload`` under ``object_key`` and return the key.

    Raises:
        ObjectStorageError: when the artifact cannot be written.
    """
    target = _root() / object_key
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.write_bytes(payload)
    except OSError as exc:  # pragma: no cover - filesystem failure
        raise ObjectStorageError(f"Failed to store artifact {object_key!r}: {exc}") from exc
    return object_key


def put_json(object_key: str, payload: Any) -> str:
    """Serialise ``payload`` as JSON and store it under ``object_key``."""
    data = json.dumps(payload, indent=2, sort_keys=True, default=str).encode("utf-8")
    return put_bytes(object_key, data)


def get_bytes(object_key: str) -> bytes:
    """Read an artifact back.

    Raises:
        ObjectStorageError: when the artifact is missing or unreadable.
    """
    target = _root() / object_key
    try:
        return target.read_bytes()
    except OSError as exc:
        raise ObjectStorageError(f"Failed to read artifact {object_key!r}: {exc}") from exc


def sha256_hex(payload: bytes) -> str:
    """Return the hex SHA-256 digest of ``payload``."""
    return hashlib.sha256(payload).hexdigest()


__all__ = ["ObjectStorageError", "get_bytes", "put_bytes", "put_json", "sha256_hex"]
