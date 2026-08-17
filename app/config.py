import os
from dataclasses import dataclass

from dotenv import load_dotenv

from app.rate_limit import DailyCap, RateLimiter

# override=True: this app's own .env must win over any same-named vars a Claude
# Code session happens to have exported ambiently (ANTHROPIC_BASE_URL/AUTH_TOKEN),
# since those are scoped to the CLI's own auth, not this app's.
load_dotenv(override=True)


@dataclass
class Settings:
    # Exactly one of these two should be set in .env: ANTHROPIC_API_KEY for a
    # direct Anthropic Console key (sent as x-api-key), or ANTHROPIC_AUTH_TOKEN
    # for a corporate gateway key like LogiQ's (sent as a Bearer token).
    anthropic_api_key: str | None = os.environ.get("ANTHROPIC_API_KEY")
    anthropic_auth_token: str | None = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    anthropic_base_url: str = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    daily_request_cap: int = int(os.environ.get("DAILY_REQUEST_CAP", "200"))
    rate_limit_per_minute: int = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "10"))
    history_db_path: str = os.environ.get("HISTORY_DB_PATH", "data/history.db")
    vapid_private_key: str | None = os.environ.get("VAPID_PRIVATE_KEY")
    vapid_public_key: str | None = os.environ.get("VAPID_PUBLIC_KEY")
    vapid_claims_sub: str = os.environ.get("VAPID_CLAIMS_SUB", "mailto:admin@example.com")
    push_subscription_path: str = os.environ.get("PUSH_SUBSCRIPTION_PATH", "data/push_subscription.json")


settings = Settings()

rate_limiter = RateLimiter(per_minute=settings.rate_limit_per_minute)
daily_cap = DailyCap(cap=settings.daily_request_cap)
