# fyuneru.result — 错误模型

所有 `init_* / bind_* / build_*` 返回的操作函数都把异常包装成 `ResultE[T]`。这是 fyuneru 唯一的错误约定，不要 `try/except` 库函数。

## API

```python
from fyuneru.result import Success, Failure, Result, ResultE, safe, unwrap, is_success, is_failure
```

```python
@dataclass(frozen=True)
class Success(Generic[T]):
    value: T

@dataclass(frozen=True)
class Failure(Generic[E]):
    error: E

Result[T, E]   = Success[T] | Failure[E]
ResultE[T]     = Result[T, Exception]   # 90% 场景用这个

is_success(result) -> bool
is_failure(result) -> bool

@safe
def f(...) -> T: ...
# 装饰后签名变成 (...) -> ResultE[T]

unwrap(result: Result[T, E]) -> T
# Success 时返回 value；Failure 且 error 是 Exception 时直接 raise；
# 否则 raise RuntimeError(error)
```

## 用法范式

```python
from fyuneru.result import unwrap, is_failure
from fyuneru.redis_toolkit import bind_redis_set_writer

writer = bind_redis_set_writer(redis, set_name="seen")

# 1. 直接 unwrap：等价于"出错就抛"
unwrap(writer("key-1"))

# 2. 分支处理
result = writer("key-1")
if is_failure(result):
    log.warning("write failed: %s", result.error)
    return
```

## 关键约束

- `unwrap` 是把 `Result` 转回异常的唯一入口；不要手写 `result.value`
- `@safe` 只兜 `Exception`，`BaseException`（KeyboardInterrupt / SystemExit）会穿透
- `Failure.error` 通常是 `Exception` 实例，但 `Result[T, E]` 允许 `E` 是任意类型——`unwrap` 已处理非异常 error 路径（转 `RuntimeError`）
