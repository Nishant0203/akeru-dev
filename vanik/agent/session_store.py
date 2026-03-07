"""In-memory session store for chat gateway v1."""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from queue import Queue
from threading import Lock
from typing import Any


@dataclass(slots=True)
class SessionState:
    session_id: str
    seed: dict[str, Any]
    user_id: str | None
    created_at: str
    state: str = "created"
    messages: list[dict[str, str]] = field(default_factory=list)
    pending_gate: dict[str, Any] | None = None
    last_response_events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=500))
    history_turn_count: int = 0
    last_active: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_queue: Queue[dict[str, Any]] = field(default_factory=Queue)
    events_lock: Any = field(default_factory=Lock, repr=False)
    sse_lock: Any = field(default_factory=Lock, repr=False)
    has_active_sse: bool = False
    is_closed: bool = False


class InMemorySessionStore:
    """Simple in-process state store with idle expiry."""

    def __init__(self, idle_ttl_minutes: int = 60) -> None:
        self.idle_ttl = timedelta(minutes=idle_ttl_minutes)
        self._items: dict[str, SessionState] = {}
        self._lock = Lock()

    def _purge_expired_locked(self) -> None:
        now = datetime.now(UTC)
        expired: list[str] = []
        for session_id, state in self._items.items():
            if now - state.last_active > self.idle_ttl:
                expired.append(session_id)

        for session_id in expired:
            session = self._items.pop(session_id)
            session.state = "expired"

    def create(self, seed: dict[str, Any] | None = None) -> SessionState:
        with self._lock:
            self._purge_expired_locked()
            session_id = str(uuid.uuid4())
            now = datetime.now(UTC)
            state = SessionState(
                session_id=session_id,
                seed=seed or {},
                user_id=(seed or {}).get("user_id"),
                created_at=now.isoformat(),
                last_active=now,
            )
            self._items[session_id] = state
            return state

    def get(self, session_id: str) -> SessionState | None:
        with self._lock:
            self._purge_expired_locked()
            state = self._items.get(session_id)
            if state is None:
                return None
            state.last_active = datetime.now(UTC)
            return state

    def delete(self, session_id: str) -> SessionState | None:
        with self._lock:
            state = self._items.pop(session_id, None)
            if state:
                state.state = "closing"
                state.is_closed = True
            return state

    def set_state(self, session_id: str, value: str) -> None:
        with self._lock:
            state = self._items.get(session_id)
            if state is None:
                return
            state.state = value
            state.last_active = datetime.now(UTC)

    def append_message(self, session_id: str, role: str, content: str) -> None:
        with self._lock:
            state = self._items.get(session_id)
            if state is None:
                return
            state.messages.append({"role": role, "content": content})
            state.history_turn_count += 1
            state.last_active = datetime.now(UTC)

    def list_sessions(self) -> list[SessionState]:
        with self._lock:
            self._purge_expired_locked()
            return list(self._items.values())


store = InMemorySessionStore()
