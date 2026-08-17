from app.rate_limit import DailyCap, RateLimiter


def test_rate_limiter_allows_up_to_limit():
    limiter = RateLimiter(per_minute=2)
    assert limiter.allow("1.2.3.4") is True
    assert limiter.allow("1.2.3.4") is True
    assert limiter.allow("1.2.3.4") is False


def test_rate_limiter_tracks_keys_independently():
    limiter = RateLimiter(per_minute=1)
    assert limiter.allow("1.1.1.1") is True
    assert limiter.allow("2.2.2.2") is True


def test_daily_cap_fails_closed_once_reached():
    cap = DailyCap(cap=2)
    assert cap.allow() is True
    cap.record()
    assert cap.allow() is True
    cap.record()
    assert cap.allow() is False
