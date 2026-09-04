"""Rate limiting for external API calls (primarily GitHub).

A minimal, dependency-free limiter enforcing a minimum interval between calls and
a bounded call count. Thread-safe. The GitHub adapters call :meth:`acquire`
before every request so a runaway workflow cannot hammer the API.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional


class RateLimitExceeded(RuntimeError):
    """Raised when the maximum number of calls is exceeded."""


@dataclass
class _State:
    # None until the first call; avoids treating a 0.0 timestamp as "no call yet".
    last_call: Optional[float] = None
    count: int = 0


class RateLimiter:
    def __init__(
        self,
        min_interval_seconds: float = 1.0,
        max_calls: int | None = None,
        *,
        sleep=time.sleep,
        clock=time.monotonic,
    ) -> None:
        self.min_interval = max(0.0, float(min_interval_seconds))
        self.max_calls = max_calls
        self._sleep = sleep
        self._clock = clock
        self._lock = threading.Lock()
        self._state = _State()

    @property
    def call_count(self) -> int:
        return self._state.count

    def acquire(self) -> float:
        """Block until the next call is permitted. Returns seconds waited."""
        with self._lock:
            if self.max_calls is not None and self._state.count >= self.max_calls:
                raise RateLimitExceeded(
                    f"exceeded max_calls={self.max_calls}"
                )
            now = self._clock()
            waited = 0.0
            if self._state.last_call is not None:
                elapsed = now - self._state.last_call
                remaining = self.min_interval - elapsed
                if remaining > 0:
                    self._sleep(remaining)
                    waited = remaining
                    now = self._clock()
            self._state.last_call = now
            self._state.count += 1
            return waited

    def reset(self) -> None:
        with self._lock:
            self._state = _State()
