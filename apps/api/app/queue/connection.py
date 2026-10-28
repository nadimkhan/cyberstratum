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


@lru_cache(maxsize=1)
def get_queue() -> Queue:
    """Return the process-wide scan queue."""
    return Queue(name=queue_name(), connection=get_redis())


def reset_queue() -> None:
    """Drop cached Redis/Queue handles (used by tests)."""
    get_queue.cache_clear()
    get_redis.cache_clear()


__all__ = ["get_queue", "get_redis", "queue_name", "reset_queue"]
