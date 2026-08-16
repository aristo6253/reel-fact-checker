import os
from dataclasses import dataclass

from app.rate_limit import DailyCap, RateLimiter


@dataclass
class Settings:
    # None (not "") when unset, so passing this straight to anthropic.Anthropic()
    # lets the SDK fall through to ANTHROPIC_AUTH_TOKEN / an `ant auth login`
    # profile instead of being locked to a literal ANTHROPIC_API_KEY.
    anthropic_api_key: str | None = os.environ.get("ANTHROPIC_API_KEY")
    daily_request_cap: int = int(os.environ.get("DAILY_REQUEST_CAP", "200"))
    rate_limit_per_minute: int = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "10"))


settings = Settings()

rate_limiter = RateLimiter(per_minute=settings.rate_limit_per_minute)
daily_cap = DailyCap(cap=settings.daily_request_cap)
