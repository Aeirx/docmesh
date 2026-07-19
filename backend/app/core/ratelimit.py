"""Hand-rolled token bucket — the Phase-1 reservation, built now that an
endpoint spends real CPU (local LLM inference).

Pure logic + injected clock so the unit test never sleeps. ONE global bucket,
not per-IP: this is a single-user local app and the resource being protected is
the machine's own CPU, not fairness between clients. Tokens are consumed only
when generation actually runs — cache hits and template renders are free (the
scarce resource is inference, and 429ing a user who clicks through ten
already-cached edges would be punitive theater).
"""

import time
from collections.abc import Callable


class TokenBucket:
    def __init__(
        self,
        capacity: int,
        refill_per_minute: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._capacity = float(capacity)
        self._tokens = float(capacity)  # starts full
        self._rate = refill_per_minute / 60.0  # tokens per second
        self._clock = clock
        self._last = clock()

    def try_acquire(self, cost: float = 1.0) -> tuple[bool, float]:
        """(allowed, retry_after_seconds). retry_after is 0.0 when allowed."""
        now = self._clock()
        self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._rate)
        self._last = now
        if self._tokens >= cost:
            self._tokens -= cost
            return True, 0.0
        return False, (cost - self._tokens) / self._rate
