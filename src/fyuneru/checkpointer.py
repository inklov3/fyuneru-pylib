from typing import Protocol

from returns.result import safe


class AdvanceCheckpoint(Protocol):
    @safe
    def __call__(self, checkpoint_uid: str) -> None: ...


class IsPastCheckpoint(Protocol):
    @safe
    def __call__(self, checkpoint_uid: str) -> bool: ...


class DelCheckpoint(Protocol):
    @safe
    def __call__(self, checkpoint_uid: str) -> None: ...


class InitCheckpointer(Protocol):
    def __call__(
        self, checkpoint_name: str
    ) -> tuple[AdvanceCheckpoint, IsPastCheckpoint, DelCheckpoint]: ...
