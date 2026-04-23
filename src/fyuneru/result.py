from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Generic, ParamSpec, TypeAlias, TypeVar

T = TypeVar("T")
E = TypeVar("E")
P = ParamSpec("P")


@dataclass(frozen=True)
class Success(Generic[T]):
    value: T


@dataclass(frozen=True)
class Failure(Generic[E]):
    error: E


Result: TypeAlias = Success[T] | Failure[E]
ResultE: TypeAlias = Result[T, Exception]


def is_success(result: Result[T, E]) -> bool:
    return isinstance(result, Success)


def is_failure(result: Result[T, E]) -> bool:
    return isinstance(result, Failure)


def safe(function: Callable[P, T]) -> Callable[P, ResultE[T]]:
    @wraps(function)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> ResultE[T]:
        try:
            return Success(function(*args, **kwargs))
        except Exception as error:
            return Failure(error)

    return wrapper


def unwrap(result: Result[T, E]) -> T:
    if isinstance(result, Success):
        return result.value

    error = result.error
    if isinstance(error, Exception):
        raise error
    raise RuntimeError(error)
