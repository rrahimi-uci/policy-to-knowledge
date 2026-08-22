from concurrent.futures import ThreadPoolExecutor
import time

from utils.adaptive_limiter import AdaptiveRequestLimiter


def test_shared_limiter_blocks_until_a_lease_is_released(tmp_path):
    limiter = AdaptiveRequestLimiter(tmp_path / "limiter.sqlite3", initial_limit=1, maximum_limit=1, poll_seconds=0.01)
    first = limiter.acquire()
    with ThreadPoolExecutor(max_workers=1) as executor:
        waiting = executor.submit(limiter.acquire, 1)
        time.sleep(0.03)
        assert waiting.done() is False
        limiter.release(first, success=True)
        second = waiting.result(timeout=1)
    assert second.wait_seconds >= 0.02
    limiter.release(second, success=True)
    assert limiter.snapshot()["active_leases"] == 0


def test_adaptive_limit_increases_after_success_and_halves_on_throttle(tmp_path):
    limiter = AdaptiveRequestLimiter(tmp_path / "limiter.sqlite3", initial_limit=2, maximum_limit=4, success_window=2, poll_seconds=0.01)
    for _ in range(2):
        lease = limiter.acquire()
        limiter.release(lease, success=True)
    assert limiter.snapshot()["current_limit"] == 3
    lease = limiter.acquire()
    limiter.release(lease, success=False, penalize=True, throttled=True)
    snapshot = limiter.snapshot()
    assert snapshot["current_limit"] == 1
    assert snapshot["total_throttled"] == 1
