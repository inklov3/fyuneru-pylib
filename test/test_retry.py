"""测试 retry 模块的有界退避语义。"""

from fyuneru.result import is_failure, is_success, unwrap
from fyuneru.retry import RetryPolicy, bind_retrying, retry_call


class Transient(RuntimeError):
    pass


class Permanent(RuntimeError):
    pass


def _recorder() -> tuple[list[float], object]:
    slept: list[float] = []

    def sleeper(delay: float) -> None:
        slept.append(delay)

    return slept, sleeper


def test_policy_validation() -> None:
    for kwargs in (
        {"attempts": 0},
        {"base_seconds": 0},
        {"max_seconds": 0.1, "base_seconds": 1.0},
        {"jitter": 1.5},
    ):
        try:
            RetryPolicy(**kwargs)
        except ValueError:
            continue
        raise AssertionError(f"期望 ValueError: {kwargs}")


def test_delay_is_capped_and_monotonic_without_jitter() -> None:
    policy = RetryPolicy(base_seconds=1.0, max_seconds=4.0, jitter=0)
    assert policy.delay_for(1) == 1.0
    assert policy.delay_for(2) == 2.0
    assert policy.delay_for(3) == 4.0
    assert policy.delay_for(9) == 4.0, "超出上限后必须被截断"


def test_succeeds_without_sleeping() -> None:
    slept, sleeper = _recorder()
    calls = {"n": 0}

    def operation() -> str:
        calls["n"] += 1
        return "ok"

    result = retry_call(operation, sleeper=sleeper)  # type: ignore[arg-type]
    assert result == "ok"
    assert calls["n"] == 1
    assert slept == [], "首次成功不应退避"


def test_retries_then_succeeds() -> None:
    slept, sleeper = _recorder()
    calls = {"n": 0}

    def operation() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise Transient("429")
        return "ok"

    policy = RetryPolicy(attempts=5, base_seconds=0.01, jitter=0)
    result = retry_call(
        operation,
        policy=policy,
        retry_on=(Transient,),
        sleeper=sleeper,  # type: ignore[arg-type]
    )
    assert result == "ok"
    assert calls["n"] == 3
    assert len(slept) == 2, f"期望 2 次退避，实际 {len(slept)}"


def test_non_retryable_error_passes_through_immediately() -> None:
    slept, sleeper = _recorder()
    calls = {"n": 0}

    def operation() -> str:
        calls["n"] += 1
        raise Permanent("400")

    try:
        retry_call(
            operation,
            policy=RetryPolicy(attempts=5, base_seconds=0.01, jitter=0),
            retry_on=(Transient,),
            sleeper=sleeper,  # type: ignore[arg-type]
        )
    except Permanent:
        pass
    else:
        raise AssertionError("永久错误必须立即透传")
    assert calls["n"] == 1, "永久错误不得重试"
    assert slept == []


def test_exhausted_budget_raises_last_error() -> None:
    slept, sleeper = _recorder()
    calls = {"n": 0}

    def operation() -> str:
        calls["n"] += 1
        raise Transient(f"attempt-{calls['n']}")

    try:
        retry_call(
            operation,
            policy=RetryPolicy(attempts=3, base_seconds=0.01, jitter=0),
            retry_on=(Transient,),
            sleeper=sleeper,  # type: ignore[arg-type]
        )
    except Transient as error:
        assert str(error) == "attempt-3", f"应抛最后一次异常，得到 {error}"
    else:
        raise AssertionError("预算耗尽必须抛出异常")
    assert calls["n"] == 3
    assert len(slept) == 2, "最后一次失败后不应再睡"


def test_bind_retrying_wraps_into_result() -> None:
    execute = bind_retrying(
        policy=RetryPolicy(attempts=2, base_seconds=0.01, jitter=0),
        retry_on=(Transient,),
    )

    ok = execute(lambda: 42)
    assert is_success(ok)
    assert unwrap(ok) == 42

    def failing() -> int:
        raise Transient("boom")

    bad = execute(failing)
    assert is_failure(bad), "耗尽预算应返回 Failure"


def main() -> None:
    test_policy_validation()
    test_delay_is_capped_and_monotonic_without_jitter()
    test_succeeds_without_sleeping()
    test_retries_then_succeeds()
    test_non_retryable_error_passes_through_immediately()
    test_exhausted_budget_raises_last_error()
    test_bind_retrying_wraps_into_result()
    print("test_retry: 全部通过")


if __name__ == "__main__":
    main()
