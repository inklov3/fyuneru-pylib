"""task_queue 子系统的公共类型与 broker / worker 之间的契约。

设计目标：
- broker 把"从 redis 流读到的一批原始字段"统一解析为 ``Entry``（可投递）或
  ``BadEntry``（坏消息）两类显式类型，worker 不再触碰原始 fields。
- worker 只依赖 ``BrokerOps`` Protocol，不再使用 broker 的私有方法；
  这样 broker 内部 isinstance 兼容、字段归一化、JSON 解码、actor 解析
  等逻辑都收敛在一处，worker 主循环只剩"分发 + 错误边界"。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from fyuneru.task_queue.types import ActorBinding


@dataclass(frozen=True)
class Entry:
    """已成功解析、可直接投递给 handler 的消息。"""

    stream: str
    message_id: str
    queue_name: str
    actor_name: str
    binding: ActorBinding
    payload_envelope: dict[str, Any]
    payload_raw: str
    attempt: int
    eta: float | None
    created_at: float


@dataclass(frozen=True)
class BadEntry:
    """无法投递的消息——坏 JSON、缺字段、actor 未注册、attempt 非数字等。

    broker 把这些消息按统一格式送入 xq；worker 收到后只需要调用
    ``broker.handle_xq_for_bad`` 即可，不必关心具体失败原因。
    """

    stream: str
    message_id: str
    queue_name: str
    raw_fields: dict[str, str]
    actor_name: str | None
    payload_raw: str | None
    attempt: int
    reason: str
    error: Exception


@dataclass(frozen=True)
class ReadOutcome:
    """一次 read_entries 调用的结果。

    - ``entries`` / ``bad_entries`` 任一非空都代表有消息要处理；
    - ``redis_error`` 非 None 表示底层 Redis 调用抛了连接 / 超时异常，
      worker 应当 backoff 后重试，而非退出进程。
    """

    entries: list[Entry] = field(default_factory=list)
    bad_entries: list[BadEntry] = field(default_factory=list)
    redis_error: Exception | None = None

    def is_empty(self) -> bool:
        return not self.entries and not self.bad_entries and self.redis_error is None


@dataclass(frozen=True)
class BrokerHooks:
    """broker / worker 可观测性回调。所有 callback 缺省 None，零开销。

    回调内部抛错不会反过来杀 worker——broker 会捕获并 warning 一次。
    """

    on_enqueue: Callable[[str, str, int], None] | None = None
    on_handle_start: Callable[[str, str, int], None] | None = None
    on_handle_success: Callable[[str, str, int, float], None] | None = None
    on_handle_retry: Callable[[str, str, int, Exception], None] | None = None
    on_handle_xq: Callable[[str, str, int, Exception], None] | None = None
    on_lua_degraded: Callable[[str], None] | None = None
    on_redis_error: Callable[[Exception], None] | None = None


class BrokerOps(Protocol):
    """worker 视角的 broker 接口，所有方法均为公共契约。"""

    group_name: str

    def stream_for(self, queue_name: str) -> str: ...

    def xq_stream_for(self) -> str: ...

    def ensure_group(self, stream: str) -> None: ...

    def read_entries(
        self,
        stream: str,
        queue_name: str,
        consumer_name: str,
        block_ms: int,
    ) -> ReadOutcome: ...

    def actor_for(self, queue_name: str, actor_name: str) -> ActorBinding | None: ...

    def handle_success(self, entry: Entry) -> None: ...

    def handle_retry(self, entry: Entry, error: Exception) -> None: ...

    def handle_defer(self, entry: Entry) -> None: ...

    def handle_xq_for_entry(self, entry: Entry, error: Exception) -> None: ...

    def handle_xq_for_bad(self, bad: BadEntry) -> None: ...

    def notify_hook(self, name: str, *args: Any) -> None: ...
