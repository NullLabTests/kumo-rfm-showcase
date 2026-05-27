import time

import pytest

from cache import cached, cleanup, get, invalidate, set, stats


@pytest.fixture(autouse=True)
def clear_cache():
    invalidate()
    yield


class TestCacheBasics:
    def test_get_missing_returns_none(self):
        assert get("nonexistent") is None

    def test_set_and_get(self):
        set("key", "value", ttl=60)
        assert get("key") == "value"

    def test_get_after_ttl_expiry(self):
        set("key", "value", ttl=0.01)
        time.sleep(0.02)
        assert get("key") is None

    def test_overwrite_value(self):
        set("key", "first")
        set("key", "second")
        assert get("key") == "second"

    def test_invalidate_all(self):
        set("a", 1, ttl=60)
        set("b", 2, ttl=60)
        invalidate()
        assert get("a") is None
        assert get("b") is None

    def test_invalidate_prefix(self):
        set("graph:online_shopping", "data")
        set("predict:abc", "data")
        set("templates", "data")
        invalidate("graph:")
        assert get("graph:online_shopping") is None
        assert get("predict:abc") is not None
        assert get("templates") is not None

    def test_stats_tracking(self):
        assert stats()["hits"] == 0
        assert stats()["misses"] == 0
        get("x")  # miss
        assert stats()["misses"] == 1
        set("y", 1)
        get("y")  # hit
        assert stats()["hits"] == 1


class TestCacheEdgeCases:
    def test_stats_after_invalidate_all(self):
        set("a", 1)
        get("a")
        invalidate()
        s = stats()
        assert s["hits"] == 0
        assert s["misses"] == 0

    def test_stats_size(self):
        set("k1", 1)
        set("k2", 2)
        set("k3", 3)
        assert stats()["size"] == 3

    def test_invalidate_with_star_works(self):
        set("graph:a", 1)
        set("graph:b", 2)
        invalidate("graph:*")
        assert get("graph:a") is None
        assert get("graph:b") is None

    def test_cleanup_removes_expired(self):
        set("expired", "x", ttl=0.01)
        set("valid", "y", ttl=60)
        time.sleep(0.02)
        removed = cleanup()
        assert removed >= 1
        assert get("expired") is None
        assert get("valid") == "y"

    def test_cleanup_with_none_expired(self):
        set("a", 1, ttl=60)
        set("b", 2, ttl=60)
        removed = cleanup()
        assert removed == 0

    def test_zero_ttl_expires_immediately(self):
        set("now", "x", ttl=0)
        assert get("now") is None

    def test_large_value_roundtrip(self):
        big = list(range(10000))
        set("big", big)
        assert get("big") == big

    def test_none_value(self):
        set("none", None)
        assert get("none") is None

    def test_stats_disk_size_key_exists(self):
        s = stats()
        assert "disk_size" in s


class TestCachedDecorator:
    def test_caches_result(self):
        call_count = [0]

        @cached(ttl=60)
        def compute_a(x):
            call_count[0] += 1
            return x * 2

        assert compute_a(5) == 10
        assert compute_a(5) == 10
        assert call_count[0] == 1

    def test_different_args_not_cached(self):
        call_count = [0]

        @cached(ttl=60)
        def compute_b(x):
            call_count[0] += 1
            return x * 2

        assert compute_b(1) == 2
        assert compute_b(2) == 4
        assert call_count[0] == 2

    def test_cache_expires(self):
        call_count = [0]

        @cached(ttl=0.01)
        def compute_c(x):
            call_count[0] += 1
            return x

        assert compute_c(1) == 1
        assert call_count[0] == 1
        time.sleep(0.02)
        assert compute_c(1) == 1
        assert call_count[0] == 2

    def test_cached_decorator_with_kwargs(self):
        call_count = [0]

        @cached(ttl=60)
        def compute_d(a, b=10):
            call_count[0] += 1
            return a + b

        assert compute_d(5, b=10) == 15
        assert compute_d(5, b=10) == 15
        assert call_count[0] == 1

    def test_cached_decorator_different_kwargs(self):
        call_count = [0]

        @cached(ttl=60)
        def compute_e(a, b=10):
            call_count[0] += 1
            return a + b

        assert compute_e(5, b=10) == 15
        assert compute_e(5, b=20) == 25
        assert call_count[0] == 2
