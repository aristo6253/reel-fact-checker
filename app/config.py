import os
from dataclasses import dataclass


@dataclass
class Settings:
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    daily_request_cap: int = int(os.environ.get("DAILY_REQUEST_CAP", "200"))
    rate_limit_per_minute: int = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "10"))


settings = Settings()
