"""Runtime utilities: in-process cache and per-corridor circuit breakers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any


class TTLRateCache:
    """Simple in-process TTL cache for response reuse."""

    def __init__(self, ttl_seconds: int = 86400) -> None:
        self.ttl_seconds = ttl_seconds
        self._store: dict[str, tuple[datetime, dict[str, Any]]] = {}
        self._hits = 0
        self._misses = 0
        self._lock = Lock()

    def get(self, key: str) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        with self._lock:
            item = self._store.get(key)
            if not item:
                self._misses += 1
                return None
            expires_at, payload = item
            if expires_at <= now:
                self._store.pop(key, None)
                self._misses += 1
                return None
            self._hits += 1
            return dict(payload)

    def set(self, key: str, payload: dict[str, Any], ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self.ttl_seconds
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl)
        with self._lock:
            self._store[key] = (expires_at, dict(payload))

    def metrics(self) -> dict[str, float | int]:
        with self._lock:
            hits = self._hits
            misses = self._misses
        total = hits + misses
        hit_rate = (hits / total * 100.0) if total else 0.0
        return {"hits": hits, "misses": misses, "hit_rate_pct": round(hit_rate, 2)}


class CircuitBreaker:
    """Minimal rolling-window circuit breaker."""

    def __init__(
        self,
        *,
        failure_threshold: int,
        failure_window_seconds: int,
        probe_timeout_seconds: int,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.failure_window_seconds = failure_window_seconds
        self.probe_timeout_seconds = probe_timeout_seconds

        self._state = "closed"
        self._failures: list[datetime] = []
        self._opened_at: datetime | None = None
        self._lock = Lock()

    def _prune(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.failure_window_seconds)
        self._failures = [ts for ts in self._failures if ts >= cutoff]

    def allow_request(self) -> bool:
        now = datetime.now(UTC)
        with self._lock:
            self._prune(now)
            if self._state == "open":
                assert self._opened_at is not None
                if (now - self._opened_at).total_seconds() >= self.probe_timeout_seconds:
                    self._state = "half-open"
                    return True
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            self._state = "closed"
            self._failures.clear()
            self._opened_at = None

    def record_failure(self) -> None:
        now = datetime.now(UTC)
        with self._lock:
            self._prune(now)
            self._failures.append(now)

            if self._state == "half-open" or len(self._failures) >= self.failure_threshold:
                self._state = "open"
                self._opened_at = now

    def snapshot(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self._lock:
            self._prune(now)
            opened_at = self._opened_at.isoformat() if self._opened_at else None
            return {
                "state": self._state,
                "recent_failures": len(self._failures),
                "opened_at": opened_at,
                "failure_threshold": self.failure_threshold,
            }
