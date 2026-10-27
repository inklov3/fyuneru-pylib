# fyuneru.retry

有界重试：指数退避 + 抖动，只重试显式声明的异常类型。

## 为什么需要

`task_queue` 与 Ray 都只提供"整条任务重放"级别的重试，粒度过粗：一次 429 不应该让已经下载并转码完成的单元从头再来。本模块补上调用级别的有界重试，语义刻意收窄：

- 只重试 `retry_on` 列出的异常；其余异常立即透传（永久失败快速暴露）；
- 尝试次数有上限，耗尽后抛出最后一次异常本身，不包装成新类型；
- 退避带抖动，避免多 worker 同时撞同一个上游配额窗口。

## 核心 API

```python
from fyuneru.retry import RetryPolicy, retry_call, bind_retrying

policy = RetryPolicy(
    attempts=3,          # 总尝试次数（含首次）
    base_seconds=1.0,    # 首次退避基准
    max_seconds=30.0,    # 单次退避上限
    jitter=0.25,         # 抖动幅度 [0, 1]
)

# 直接重试
result = retry_call(
    operation=lambda: fetch_data(),
    policy=policy,
    retry_on=(TransientError,),
    label="fetch_data",
)

# 包装成 ResultE
execute = bind_retrying(
    policy=policy,
    retry_on=(TransientError,),
    label="fetch_data",
)
result = execute(lambda: fetch_data())  # ResultE[T]
```

## RetryPolicy

```python
@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    base_seconds: float = 1.0
    max_seconds: float = 30.0
    jitter: float = 0.25

    def delay_for(self, attempt: int) -> float:
        """返回第 attempt 次失败后的等待秒数。"""
```

退避公式：`min(base_seconds * 2^(attempt-1), max_seconds) * [1-jitter, 1+jitter]`

## retry_call

```python
def retry_call(
    operation: Callable[[], T],
    policy: RetryPolicy | None = None,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    label: str = "operation",
    sleeper: Callable[[float], None] = sleep,
) -> T:
```

- `operation` 失败时，只有 `retry_on` 内的异常会触发退避；
- 耗尽预算后抛出最后一次捕获的异常；
- `sleeper` 可注入用于测试。

## bind_retrying

```python
def bind_retrying(
    policy: RetryPolicy | None = None,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    label: str = "operation",
) -> Callable[[Callable[[], T]], ResultE[T]]:
```

返回一个执行器，把 `retry_call` 的结果包成 `ResultE`。

## 典型场景

### 1. 上游 API 限流

```python
from fyuneru.gemini_toolkit import GeminiTransientError
from fyuneru.retry import RetryPolicy, retry_call

policy = RetryPolicy(attempts=5, base_seconds=2.0, max_seconds=60.0, jitter=0.3)
response = retry_call(
    operation=lambda: captioner(prompt, source),
    policy=policy,
    retry_on=(GeminiTransientError,),
    label="gemini_caption",
)
```

### 2. S3 网关抖动

```python
from minio.error import S3Error
from fyuneru.result import unwrap
from fyuneru.retry import RetryPolicy, retry_call

class RetryableS3Error(RuntimeError):
    pass

def upload():
    try:
        # 每次重试重新打开输入流，避免复用已消费的流。
        with file_path.open("rb") as body:
            return unwrap(writer(key, body))
    except S3Error as error:
        if error.code in {"SlowDown", "InternalError", "ServiceUnavailable"}:
            raise RetryableS3Error() from error
        raise

result = retry_call(
    operation=upload,
    policy=RetryPolicy(attempts=3, base_seconds=0.5),
    retry_on=(RetryableS3Error,),
    label="s3_upload",
)
```

实际可重试的错误码和网络异常应按对象存储服务明确配置。

### 3. 与 Result 错误模型集成

```python
from fyuneru.result import unwrap
from fyuneru.retry import bind_retrying

execute = bind_retrying(
    policy=RetryPolicy(attempts=3, base_seconds=1.0),
    retry_on=(TransientError,),
)

result = execute(lambda: fetch())
if is_failure(result):
    logger.error(f"fetch failed after retries: {result.error}")
    raise result.error
data = unwrap(result)
```

## 与 task_queue / Ray 的分工

- `fyuneru.retry`：调用级别，显式分类瞬时/永久异常，只重试瞬时；
- `task_queue` / Ray：任务级别，整条任务重放，用于进程崩溃或 worker 不可用等基础设施失败。

二者叠加：调用内先本地退避，耗尽后抛异常让任务失败，任务级重试再给一次机会。

## 关键约束

- `retry_on` 必须显式列举：默认 `(Exception,)` 会吞掉所有错误，包括永久失败；
- 永久失败应立即透传，不进重试循环；
- 最后一次失败抛原异常，不包装，调用方据此分类。
