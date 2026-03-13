import logging
import time

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Track consecutive failures per service and short-circuit when threshold is hit."""

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 300.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._services: dict[str, _ServiceState] = {}

    def _get(self, service: str) -> "_ServiceState":
        if service not in self._services:
            self._services[service] = _ServiceState()
        return self._services[service]

    def is_open(self, service: str) -> bool:
        state = self._get(service)
        if state.consecutive_failures < self.failure_threshold:
            return False
        elapsed = time.monotonic() - state.opened_at
        if elapsed >= self.cooldown_seconds:
            logger.info(f"Circuit breaker half-open for '{service}' after {self.cooldown_seconds}s cooldown")
            state.consecutive_failures = 0
            state.opened_at = 0.0
            return False
        return True

    def record_success(self, service: str) -> None:
        state = self._get(service)
        if state.consecutive_failures > 0:
            logger.info(f"Circuit breaker reset for '{service}' after success")
        state.consecutive_failures = 0
        state.opened_at = 0.0

    def record_failure(self, service: str) -> None:
        state = self._get(service)
        state.consecutive_failures += 1
        if state.consecutive_failures >= self.failure_threshold and state.opened_at == 0.0:
            state.opened_at = time.monotonic()
            logger.warning(
                f"Circuit breaker OPEN for '{service}' after {state.consecutive_failures} consecutive failures"
            )


class _ServiceState:
    __slots__ = ("consecutive_failures", "opened_at")

    def __init__(self) -> None:
        self.consecutive_failures = 0
        self.opened_at = 0.0
