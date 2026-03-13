import time
from unittest.mock import patch

from app.circuit_breaker import CircuitBreaker


def test_starts_closed():
    cb = CircuitBreaker(failure_threshold=3)
    assert not cb.is_open("svc")


def test_stays_closed_below_threshold():
    cb = CircuitBreaker(failure_threshold=3)
    cb.record_failure("svc")
    cb.record_failure("svc")
    assert not cb.is_open("svc")


def test_opens_at_threshold():
    cb = CircuitBreaker(failure_threshold=3)
    for _ in range(3):
        cb.record_failure("svc")
    assert cb.is_open("svc")


def test_success_resets_failures():
    cb = CircuitBreaker(failure_threshold=3)
    cb.record_failure("svc")
    cb.record_failure("svc")
    cb.record_success("svc")
    cb.record_failure("svc")
    assert not cb.is_open("svc")


def test_cooldown_resets_circuit():
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=1.0)
    cb.record_failure("svc")
    cb.record_failure("svc")
    assert cb.is_open("svc")
    # Simulate time passing beyond cooldown
    cb._get("svc").opened_at = time.monotonic() - 2.0
    assert not cb.is_open("svc")
    # State should be reset after cooldown
    assert cb._get("svc").consecutive_failures == 0


def test_independent_services():
    cb = CircuitBreaker(failure_threshold=2)
    cb.record_failure("a")
    cb.record_failure("a")
    assert cb.is_open("a")
    assert not cb.is_open("b")


def test_open_circuit_stays_open_within_cooldown():
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=300.0)
    cb.record_failure("svc")
    cb.record_failure("svc")
    assert cb.is_open("svc")
    # Still within cooldown
    assert cb.is_open("svc")
