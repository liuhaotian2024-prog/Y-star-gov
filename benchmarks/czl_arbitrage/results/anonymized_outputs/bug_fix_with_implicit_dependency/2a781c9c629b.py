# trial_id: 2a781c9c629b
# (arm name redacted for blind review)

# === session_manager.py ===
from typing import Optional


class SessionManager:
    """Tracks active sessions: session_id -> user_id."""

    def __init__(self) -> None:
        self._sessions: dict = {}

    def login(self, session_id: str, user_id: int) -> None:
        self._sessions[session_id] = user_id

    def logout(self, session_id: str) -> bool:
        """Return True iff a session existed before this call."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    def get_user(self, session_id: str) -> Optional[int]:
        return self._sessions.get(session_id)

    def active_session_count(self) -> int:
        return len(self._sessions)


# === test_user_service.py ===
from session_manager import SessionManager
from user_service import UserService


def _make():
    return UserService(SessionManager())


def test_login_then_current_user():
    svc = _make()
    svc.login_user('s1', 42)
    assert svc.current_user('s1') == 42


def test_logout_clears_current_user():
    svc = _make()
    svc.login_user('s1', 42)
    svc.logout_user('s1')
    assert svc.current_user('s1') is None


def test_online_count_decreases_on_logout():
    svc = _make()
    svc.login_user('s1', 42)
    svc.login_user('s2', 43)
    assert svc.online_count() == 2
    svc.logout_user('s1')
    assert svc.online_count() == 1


def test_logout_returns_true_first_time_false_after():
    svc = _make()
    svc.login_user('s1', 42)
    assert svc.logout_user('s1') is True
    assert svc.logout_user('s1') is False


# === user_service.py ===
from typing import Optional

from session_manager import SessionManager


class UserService:
    def __init__(self, session_mgr: SessionManager) -> None:
        self.sessions = session_mgr

    def login_user(self, session_id: str, user_id: int) -> None:
        self.sessions.login(session_id, user_id)

    def logout_user(self, session_id: str) -> bool:
        return self.sessions.logout(session_id)

    def current_user(self, session_id: str) -> Optional[int]:
        return self.sessions.get_user(session_id)

    def online_count(self) -> int:
        return self.sessions.active_session_count()
