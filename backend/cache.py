"""TTL-based multi-tier cache with hit/miss tracking.

Provides both a functional API (``get``/``set``/``invalidate``) and a
``@cached`` decorator. Supports an optional disk backend for persistence
across restarts.

Usage::

    from cache import get, set, invalidate, cached

    # Manual
    set("my-key", expensive_result, ttl=300)
    cached_val = get("my-key")

    # Decorator
    @cached(ttl=60)
    def fetch_data(param):
        return expensive_computation(param)

    # Invalidation
    invalidate()           # clear all
    invalidate("graph:*")  # clear keys starting with "graph:"
"""

from __future__ import annotations

import hashlib
import os
import pickle
import threading
import time
from functools import wraps
from pathlib import Path

from settings import settings

_cache: dict[str, tuple[float, object]] = {}
_stats: dict[str, int] = {"hits": 0, "misses": 0}
_lock = threading.Lock()

_DISK_DIR = Path("/tmp/kumo_cache")
_DISK_ENABLED = False


def _ensure_disk() -> None:
    global _DISK_ENABLED
    if _DISK_ENABLED or not settings.cache_disk_enabled:
        return
    try:
        _DISK_DIR.mkdir(parents=True, exist_ok=True)
        _DISK_ENABLED = True
    except OSError:
        _DISK_ENABLED = False


_ensure_disk()


def _disk_path(key: str) -> Path:
    h = hashlib.sha256(key.encode()).hexdigest()[:32]
    return _DISK_DIR / h


def _disk_get(key: str) -> object | None:
    if not _DISK_ENABLED:
        return None
    path = _disk_path(key)
    try:
        data = pickle.loads(path.read_bytes())
        expires, value = data
        if time.time() < expires:
            return value
        path.unlink(missing_ok=True)
    except (FileNotFoundError, pickle.UnpicklingError, EOFError):
        pass
    return None


def _disk_set(key: str, value: object, ttl: float) -> None:
    if not _DISK_ENABLED:
        return
    path = _disk_path(key)
    try:
        path.write_bytes(pickle.dumps((time.time() + ttl, value)))
    except OSError:
        pass


def _disk_delete(key: str) -> None:
    if not _DISK_ENABLED:
        return
    _disk_path(key).unlink(missing_ok=True)


def _disk_clear() -> None:
    if not _DISK_ENABLED:
        return
    for p in _DISK_DIR.iterdir():
        p.unlink(missing_ok=True)


def get(key: str) -> object | None:
    with _lock:
        entry = _cache.get(key)
        if entry is not None:
            expires, value = entry
            if time.monotonic() <= expires:
                _stats["hits"] += 1
                return value
            del _cache[key]

    val = _disk_get(key)
    if val is not None:
        with _lock:
            _stats["hits"] += 1
        return val

    with _lock:
        _stats["misses"] += 1
    return None


def set(key: str, value: object, ttl: float = 60.0) -> None:
    with _lock:
        _cache[key] = (time.monotonic() + ttl, value)
    _disk_set(key, value, ttl)


def invalidate(pattern: str | None = None) -> None:
    if pattern is None:
        with _lock:
            _cache.clear()
            _stats["hits"] = 0
            _stats["misses"] = 0
        _disk_clear()
        return
    prefix = pattern.rstrip("*")
    with _lock:
        for k in list(_cache):
            if k.startswith(prefix):
                del _cache[k]
    if _DISK_ENABLED:
        _disk_clear()


def stats() -> dict:
    with _lock:
        s = dict(_stats)
        s["size"] = len(_cache)
    s["disk_size"] = len(list(_DISK_DIR.iterdir())) if _DISK_ENABLED and _DISK_DIR.exists() else 0
    return s


def cleanup() -> int:
    removed = 0
    with _lock:
        now = time.monotonic()
        for k in list(_cache):
            expires, _ = _cache[k]
            if now > expires:
                del _cache[k]
                removed += 1
    if _DISK_ENABLED and _DISK_DIR.exists():
        now_abs = time.time()
        for p in _DISK_DIR.iterdir():
            try:
                data = pickle.loads(p.read_bytes())
                expires, _ = data
                if now_abs >= expires:
                    p.unlink(missing_ok=True)
                    removed += 1
            except Exception:
                p.unlink(missing_ok=True)
                removed += 1
    return removed


def cached(ttl: float = 60.0):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = f"{fn.__name__}:{args}:{tuple(sorted(kwargs.items()))}"
            hit = get(key)
            if hit is not None:
                return hit
            result = fn(*args, **kwargs)
            set(key, result, ttl)
            return result
        return wrapper
    return decorator
