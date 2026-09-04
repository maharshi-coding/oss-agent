"""Bounded retry with exponential backoff.

Used to wrap flaky external operations (GitHub calls, network). Attempts are
always bounded; loops never run forever. Failures are re-raised after the last
attempt so nothing is hidden.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Type, TypeVar

from oss_agent.observability.logging import get_logger

logger = get_logger("execution.retry")

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    multiplier: float = 2.0
    retry_on: tuple[Type[BaseException], ...] = (Exception,)

    def delay_for(self, attempt: int) -> float:
        """Delay before the given (1-based) attempt number."""
        if attempt <= 1:
            return 0.0
        delay = self.base_delay * (self.multiplier ** (attempt - 2))
        return min(delay, self.max_delay)


def retry_call(
    fn: Callable[[], T],
    policy: RetryPolicy = RetryPolicy(),
    *,
    sleep: Callable[[float], None] = time.sleep,
    on_error: Optional[Callable[[int, BaseException], None]] = None,
) -> T:
    """Call ``fn`` with bounded retries. Re-raises the final exception."""
    last_exc: Optional[BaseException] = None
    for attempt in range(1, policy.max_attempts + 1):
        delay = policy.delay_for(attempt)
        if delay:
            sleep(delay)
        try:
            return fn()
        except policy.retry_on as exc:  # type: ignore[misc]
            last_exc = exc
            if on_error:
                on_error(attempt, exc)
            logger.warning(
                "operation failed; will retry" if attempt < policy.max_attempts
                else "operation failed; no attempts left",
                extra={"attempt": attempt, "max": policy.max_attempts, "error": str(exc)},
            )
    assert last_exc is not None
    raise last_exc
