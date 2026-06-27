"""Unit tests for cache key generation (no live Redis required)."""
import sys
from pathlib import Path

import allure

ASSISTANT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ASSISTANT_ROOT))

from src.cache import CacheManager  # noqa: E402


@allure.feature("Explorer cache")
@allure.story("Key generation")
class TestGenerateKey:
    def setup_method(self):
        # CacheManager degrades gracefully without Redis; _generate_key is pure.
        self.cm = CacheManager()

    @allure.title("Key is a stable p2k-prefixed hash string")
    def test_basic_key(self):
        key = self.cm._generate_key("search", "query", top_k=5)
        assert key.startswith("p2k:search:")
        # Deterministic for identical inputs
        assert key == self.cm._generate_key("search", "query", top_k=5)

    @allure.title("Different args / kwargs produce different keys")
    def test_distinct_keys(self):
        a = self.cm._generate_key("p", "x", top_k=5)
        b = self.cm._generate_key("p", "y", top_k=5)
        c = self.cm._generate_key("p", "x", top_k=6)
        assert len({a, b, c}) == 3

    @allure.title("Non-serializable POSITIONAL args don't crash (repr fallback)")
    def test_nonserializable_args(self):
        key = self.cm._generate_key("p", object())
        assert key.startswith("p2k:p:")

    @allure.title("Non-serializable KEYWORD args don't crash (regression)")
    def test_nonserializable_kwargs(self):
        # Previously json.dumps(sorted(kwargs.items())) raised TypeError here,
        # turning the @cached wrapper into a hard failure.
        key = self.cm._generate_key("p", flag=object())
        assert key.startswith("p2k:p:")


class _FakeRedis:
    """Minimal in-memory stand-in for redis.Redis (decode_responses=True)."""
    def __init__(self):
        self.store = {}
    def get(self, k):
        return self.store.get(k)
    def setex(self, k, ttl, v):
        self.store[k] = v
        return True
    def set(self, k, v):
        self.store[k] = v
        return True
    def delete(self, *keys):
        n = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                n += 1
        return n


@allure.feature("Explorer cache")
@allure.story("Get / set / delete")
class TestCacheGetSet:
    def _manager(self):
        cm = CacheManager()
        cm._redis_client = _FakeRedis()
        cm._available = True
        return cm

    @allure.title("set then get round-trips a JSON-serializable value")
    def test_set_get(self):
        cm = self._manager()
        cm.set("p2k:t:1", {"a": [1, 2], "b": "x"})
        assert cm.get("p2k:t:1") == {"a": [1, 2], "b": "x"}

    @allure.title("get returns None on a miss")
    def test_get_miss(self):
        cm = self._manager()
        assert cm.get("p2k:t:missing") is None

    @allure.title("delete removes a key")
    def test_delete(self):
        cm = self._manager()
        cm.set("p2k:t:2", 123)
        cm.delete("p2k:t:2")
        assert cm.get("p2k:t:2") is None

    @allure.title("Operations are no-ops (and don't raise) when Redis is unavailable")
    def test_unavailable_noop(self):
        cm = CacheManager()
        cm._available = False
        assert cm.set("k", 1) is False
        assert cm.get("k") is None
