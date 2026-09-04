"""A minimal in-process event bus.

Workflow events are the audit trail. They are always recorded on the workflow
snapshot (the durable source of truth); the bus additionally lets observers
(logging now, webhooks/metrics later) react without coupling to the orchestrator.
"""

from __future__ import annotations

from typing import Callable

from oss_agent.domain.models import WorkflowEvent
from oss_agent.observability.logging import get_logger

logger = get_logger("events")

Handler = Callable[[WorkflowEvent], None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: list[Handler] = []

    def subscribe(self, handler: Handler) -> None:
        self._handlers.append(handler)

    def publish(self, event: WorkflowEvent) -> None:
        for handler in list(self._handlers):
            try:
                handler(event)
            except Exception as exc:  # an observer must never break the workflow
                logger.warning("event handler failed", extra={"error": str(exc)})


def log_event_handler(event: WorkflowEvent) -> None:
    """Default handler that emits a structured log line per event."""
    logger.info(
        f"event {event.type.value}",
        extra={
            "event": event.type.value,
            "agent": event.agent.value if event.agent else None,
            "state": event.state.value if event.state else None,
            "action": event.action,
            "error": event.error,
        },
    )


def default_bus() -> EventBus:
    bus = EventBus()
    bus.subscribe(log_event_handler)
    return bus
