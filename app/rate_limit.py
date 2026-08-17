# ponytail: in-memory single-instance state — move to Redis if the service
# ever runs more than one instance (design spec §7 explicitly scopes this
# to a single-instance v1).
import time
from collections import defaultdict
from datetime import datetime, timezone


class RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        window_start = now - 60
        hits = [t for t in self._hits[key] if t > window_start]
        if len(hits) >= self.per_minute:
            self._hits[key] = hits
            return False
        hits.append(now)
        self._hits[key] = hits
        return True


class DailyCap:
    def __init__(self, cap: int):
        self.cap = cap
        self._count = 0
        self._day = self._today()

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _reset_if_new_day(self) -> None:
        today = self._today()
        if today != self._day:
            self._day = today
            self._count = 0

    def allow(self) -> bool:
        self._reset_if_new_day()
        return self._count < self.cap

    def record(self) -> None:
        self._reset_if_new_day()
        self._count += 1
