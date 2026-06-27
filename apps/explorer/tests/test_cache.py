"""Cover the Redis cache layer with an in-memory fake client (no live Redis)."""
import sys
from pathlib import Path

import allure
import pytest

ASSISTANT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ASSISTANT_ROOT))

from src import cache as cache_mod  # noqa: E402


class _FakeRedis:
    """Minimal in-memory stand-in for redis.Redis (decode_responses=True)."""
    def __init__(self):
        self.store = {}

    def ping(self):
        return True

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value
        return True

    def delete(self, *keys):
        n = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                n += 1
        return n

    def keys(self, pattern):
        prefix = pattern.rstrip("*")
        return [k for k in self.store if k.startswith(prefix)]

    def flushdb(self):
        self.store.clear()
        return True


@pytest.fixture
def cm():
    """An available CacheManager backed by the fake client."""
    c = cache_mod.CacheManager.__new__(cache_mod.CacheManager)
    c._redis_client = _FakeRedis()
    c._available = True
    return c


@allure.feature("Explorer cache")
@allure.story("Available path")
class TestAvailable:
    @allure.title("set then get round-trips a JSON value")
    def test_set_get(self, cm):
        assert cm.set("k1", {"a": 1}) is True
        assert cm.get("k1") == {"a": 1}

    @allure.title("get returns None on a miss")
    def test_miss(self, cm):
        assert cm.get("nope") is None

    @allure.title("set rejects non-serializable values gracefully")
    def test_set_unserializable(self, cm):
        assert cm.set("bad", {1, 2, 3}) is False

    @allure.title("delete removes a key")
    def test_delete(self, cm):
        cm.set("d", 1)
        assert cm.delete("d") is True
        assert cm.get("d") is None

    @allure.title("clear_pattern deletes matching keys and returns the count")
    def test_clear_pattern(self, cm):
        cm.set("p2k:graph:1", 1)
        cm.set("p2k:graph:2", 2)
        cm.set("p2k:other:3", 3)
        assert cm.clear_pattern("p2k:graph:*") == 2
        assert cm.get("p2k:graph:1") is None
        assert cm.get("p2k:other:3") == 3

    @allure.title("flush_all empties the store")
    def test_flush(self, cm):
        cm.set("x", 1)
        assert cm.flush_all() is True
        assert cm.get("x") is None

    @allure.title("is_available reflects state")
    def test_available(self, cm):
        assert cm.is_available() is True


@allure.feature("Explorer cache")
@allure.story("Key generation")
class TestKeyGen:
    @allure.title("_generate_key is deterministic and prefix-scoped")
    def test_key(self, cm):
        k1 = cm._generate_key("vertex", 1, "a", flag=True)
        k2 = cm._generate_key("vertex", 1, "a", flag=True)
        assert k1 == k2 and "vertex" in k1

    @allure.title("_generate_key tolerates non-serializable args via repr()")
    def test_key_unserializable(self, cm):
        k = cm._generate_key("mprefix", object(), s={1, 2})
        assert "mprefix" in k


@allure.feature("Explorer cache")
@allure.story("Degraded path (Redis unavailable)")
class TestDegraded:
    @pytest.fixture
    def down(self):
        c = cache_mod.CacheManager.__new__(cache_mod.CacheManager)
        c._redis_client = _FakeRedis()
        c._available = False
        return c

    @allure.title("All ops degrade gracefully when Redis is unavailable")
    def test_degraded(self, down):
        assert down.get("k") is None
        assert down.set("k", 1) is False
        assert down.delete("k") is False
        assert down.clear_pattern("x:*") == 0
        assert down.flush_all() is False
        assert down.is_available() is False


@allure.feature("Explorer cache")
@allure.story("Decorator + singleton")
class TestDecorator:
    @allure.title("get_cache returns a process-wide singleton")
    def test_singleton(self, monkeypatch):
        monkeypatch.setattr(cache_mod, "_cache_manager", None)
        a = cache_mod.get_cache()
        b = cache_mod.get_cache()
        assert a is b

    @allure.title("@cached computes once, then serves from cache")
    def test_cached_decorator(self, monkeypatch, cm):
        monkeypatch.setattr(cache_mod, "_cache_manager", cm)
        calls = {"n": 0}

        @cache_mod.cached("compute", ttl=60)
        def expensive(x):
            calls["n"] += 1
            return x * 2

        assert expensive(21) == 42
        assert expensive(21) == 42      # served from cache
        assert calls["n"] == 1
