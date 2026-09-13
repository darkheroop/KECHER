from bot.security.ratelimit import SlidingWindowLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_allows_under_limit() -> None:
    limiter = SlidingWindowLimiter(3, window=60, clock=FakeClock())
    assert all(limiter.allow(1) for _ in range(3))


def test_blocks_over_limit() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(2, window=60, clock=clock)
    assert limiter.allow(1)
    assert limiter.allow(1)
    assert limiter.allow(1) is False


def test_window_slides() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(2, window=60, clock=clock)
    assert limiter.allow(1)
    assert limiter.allow(1)
    assert limiter.allow(1) is False
    clock.now = 61.0
    assert limiter.allow(1) is True


def test_isolated_per_key() -> None:
    limiter = SlidingWindowLimiter(1, window=60, clock=FakeClock())
    assert limiter.allow(1)
    assert limiter.allow(2)
    assert limiter.allow(1) is False


def test_zero_limit_disables() -> None:
    limiter = SlidingWindowLimiter(0, window=60, clock=FakeClock())
    assert all(limiter.allow(1) for _ in range(100))


def test_retry_after() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(1, window=60, clock=clock)
    assert limiter.allow(1)
    assert limiter.retry_after(1) == 60.0
    clock.now = 30.0
    assert limiter.retry_after(1) == 30.0
    clock.now = 61.0
    assert limiter.retry_after(1) == 0.0


def test_reset() -> None:
    limiter = SlidingWindowLimiter(1, window=60, clock=FakeClock())
    assert limiter.allow(1)
    assert limiter.allow(1) is False
    limiter.reset(1)
    assert limiter.allow(1) is True
