"""Session state enum."""

from enum import Enum, auto


class SessionState(Enum):
    IDLE = auto()
    RUNNING = auto()
    INTERRUPTING = auto()
    WAITING_PERMISSION = auto()  # Phase 3 stub — never entered in Phase 2
    STOPPED = auto()
