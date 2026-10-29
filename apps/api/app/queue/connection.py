"""RQ queue wiring.

The API and the worker share one Redis connection factory built from
``Settings``. Queue names follow the ``cyberstratum`` prefix convention.
"""

from __future__ import annotations

from functools import lru_cache

from redis import Redis
from rq import Queue

from app.core.config import get_settings


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    """Return the process-wide Redis client."""
    settings = get_settings()
    return Redis.from_url(settings.redis_url)


def queue_name() -> str:
    """Return the fully-qualified scan queue name."""
    settings = get_settings()
    return f"{settings.queue_prefix}:{settings.scan_queue_name}"


def discovery_queue_name() -> str:
    """Return the fully-qualified discovery queue name."""
    settings = get_settings()
    return f"{settings.queue_prefix}:{settings.discovery_queue_name}"


def mythril_queue_name() -> str:
    """Return the fully-qualified Mythril queue name."""
    settings = get_settings()
    return f"{settings.queue_prefix}:{settings.mythril_queue_name}"


def correspondence_queue_name() -> str:
    """Return the fully-qualified correspondence queue name."""
    settings = get_settings()
    return f"{settings.queue_prefix}:{settings.correspondence_queue_name}"


@lru_cache(maxsize=1)
def get_queue() -> Queue:
    """Return the process-wide scan queue."""
    return Queue(name=queue_name(), connection=get_redis())


@lru_cache(maxsize=1)
def get_discovery_queue() -> Queue:
    """Return the process-wide discovery queue.

    The feed is kept on its own queue so a long discovery sweep cannot
    delay a user-requested scan, and so the two can be scaled separately.
    """
    return Queue(name=discovery_queue_name(), connection=get_redis())


@lru_cache(maxsize=1)
def get_mythril_queue() -> Queue:
    """Return the process-wide Mythril queue.

    Mythril is manual-only and gets its own queue with its own budget. A
    symbolic-execution run can take minutes on a real contract; putting it
    on the scan queue would let a deep analysis delay ordinary scans, and
    would let Mythril's runtime cost leak into the default scan path.
    """
    return Queue(name=mythril_queue_name(), connection=get_redis())


@lru_cache(maxsize=1)
def get_correspondence_queue() -> Queue:
    """Return the process-wide correspondence queue.

    The correspondence proof recompiles a verified contract with its own
    compiler, which is a compiler run rather than a bytecode scan. It
    therefore gets its own queue and its own budget, so a slow recompilation
    can never delay an ordinary scan.
    """
    return Queue(name=correspondence_queue_name(), connection=get_redis())


def reset_queue() -> None:
    """Drop cached Redis/Queue handles (used by tests)."""
    get_queue.cache_clear()
    get_discovery_queue.cache_clear()
    get_mythril_queue.cache_clear()
    get_correspondence_queue.cache_clear()
    get_redis.cache_clear()


__all__ = [
    "correspondence_queue_name",
    "discovery_queue_name",
    "get_correspondence_queue",
    "get_discovery_queue",
    "get_mythril_queue",
    "get_queue",
    "get_redis",
    "mythril_queue_name",
    "queue_name",
    "reset_queue",
]
