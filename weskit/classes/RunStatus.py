import enum
from typing import TypeVar

T = TypeVar('T', bound='RunStatus')
class RunStatus(enum.Enum):
    UNKNOWN = 0
    QUEUED = 1
    INITIALIZING = 2
    RUNNING = 3
    PAUSED = 4
    COMPLETE = 5
    EXECUTOR_ERROR = 6
    SYSTEM_ERROR = 7
    CANCELED = 8
    CANCELING = 9

    def __repr__(self) -> str:
        return self.name

    def fromString(name: str) -> T:
        return RunStatus[name]
