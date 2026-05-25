"""
Redis store for hot/ephemeral data.

Falls back to an in-process dict when Redis is not configured
(EVENT_REDIS_URL is empty).  This means the service always starts
without requiring external infrastructure.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from config import settings

logger = logging.getLogger(__name__)

_USE_REDIS = bool(settings.redis_url)

if _USE_REDIS:
    try:
        import redis.asyncio as aioredis
        _client = aioredis.from_url(settings.redis_url, decode_responses=True)
        logger.info("Redis connected at %s", settings.redis_url)
    except ImportError:
        logger.warning("redis package not installed — falling back to in-memory store")
        _USE_REDIS = False
        _client = None
else:
    _client = None
    logger.info("No EVENT_REDIS_URL set — using in-memory fallback store")


# ─────────────────────────────────────────────────────────────────────────────
# In-memory fallback
# ─────────────────────────────────────────────────────────────────────────────

class _InMemoryStore:
    """Thread-unsafe but asyncio-safe simple k/v with TTL."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float]] = {}  # key → (value, expires_at)

    def _evict(self) -> None:
        now = time.time()
        expired = [k for k, (_, exp) in self._data.items() if exp < now]
        for k in expired:
            del self._data[k]

    async def set(self, key: str, value: str, ttl: int = 0) -> None:
        self._evict()
        expires_at = time.time() + (ttl if ttl > 0 else settings.redis_ttl_s)
        self._data[key] = (value, expires_at)

    async def get(self, key: str) -> Optional[str]:
        self._evict()
        entry = self._data.get(key)
        if entry is None:
            return None
        value, exp = entry
        if exp < time.time():
            del self._data[key]
            return None
        return value

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def keys(self, pattern: str = "*") -> list[str]:
        self._evict()
        if pattern == "*":
            return list(self._data.keys())
        # Simple prefix match
        prefix = pattern.rstrip("*")
        return [k for k in self._data if k.startswith(prefix)]


_mem_store = _InMemoryStore()


# ─────────────────────────────────────────────────────────────────────────────
# Public helpers — same API regardless of backend
# ─────────────────────────────────────────────────────────────────────────────

async def set_json(key: str, value: Any, ttl: int = 0) -> None:
    raw = json.dumps(value)
    if _USE_REDIS and _client:
        await _client.set(key, raw, ex=ttl or settings.redis_ttl_s)
    else:
        await _mem_store.set(key, raw, ttl=ttl)


async def get_json(key: str) -> Optional[Any]:
    if _USE_REDIS and _client:
        raw = await _client.get(key)
    else:
        raw = await _mem_store.get(key)
    return json.loads(raw) if raw is not None else None


async def delete(key: str) -> None:
    if _USE_REDIS and _client:
        await _client.delete(key)
    else:
        await _mem_store.delete(key)


async def keys(pattern: str = "*") -> list[str]:
    if _USE_REDIS and _client:
        return await _client.keys(pattern)
    return await _mem_store.keys(pattern)
