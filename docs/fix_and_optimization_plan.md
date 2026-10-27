# fyuneru-pylib 修复与优化计划

> 历史设计记录，部分方案与命令已过时；当前实现、API 和验证流程以源码、`AGENTS.md` 与 `pre_release.sh` 为准。

## Context

`~/Project/jump-cut/docs/fyuneru_audit.md` 对 fyuneru 0.1.0 做了一次只读审计，列出确认的 bug、设计问题与运维风险。目前 jump-cut 必须在导入 broker 前打 `_fyuneru_patch.py` 才能跑通 worker，否则 redis-py ≥5 下消息被静默吞掉；同时 worker 主循环一条坏消息会让整个进程退出，重试无 backoff，xq 流无回收，可观测性几乎为零。

本计划聚焦 **fyuneru-pylib 仓库**（当前工作目录）的修改。**核心策略：把基础设施摆正，让 bug 作为重构的副产物消失**，而不是在现有结构上反复打补丁。jump-cut 的 `_fyuneru_patch.py` 会在 R-1 重构后自然失效。

---

## 范围与原则

- **设计合理 > 保持 API**：能更清晰就允许破坏向后兼容；本库仍是 0.x，jump-cut 是唯一已知调用方，breaking change 一次性集中发一个 0.2 即可。
- **合理重构 > 优化 > 修复**：优先动结构，让结构本身承载正确性；优化（性能 / 可用性）跟在重构之后；孤立的小修复（文档、错误信息）单独列在最后。
- 触及任务队列语义（重试、ack、xq）的改动必须有测试覆盖；现有 `FakeRedisClient`（`test/test_task_queue.py:82`）需要随之扩展。
- 涉及 jump-cut 的兜底放在最后一节，**不在本仓库的 PR 里做**。

---

## R — 合理重构（最高优先）

### R-1 worker / broker 之间引入显式 Protocol，消除私有方法依赖

- **位置**：`src/fyuneru/task_queue/worker.py` 全文 vs `broker.py`
- **现状**：worker 直接调 `_stream_name` / `_ensure_group` / `_flatten_entries` / `_normalize_stream_fields` / `_actors` / `_xq_stream_name` / `_retry_and_ack` / `_xq_and_ack` —— 八个带下划线的"私有"方法被当公共 API 用。两者必须打包发布、不能独立演进。审计中绝大部分 bug 都长在这条耦合线的接缝处（外层 isinstance 写 `tuple` 而 inner 用解构、Lua 降级无人察觉、worker 直接 raise 拖垮 broker 调用方）。
- **改法**：
  1. 新建 `src/fyuneru/task_queue/protocols.py`，定义 `BrokerOps` Protocol：`read_entries(stream, consumer, block_ms) -> list[Entry]`、`ack(stream, message_id)`、`retry(entry, attempt, eta)`、`xq(entry, error)`、`actor_for(queue, name) -> ActorBinding | None`、`ensure_group(stream)`、`stream_for(queue) -> str`。
  2. `Entry` 用 frozen dataclass 表示已解码的消息（`message_id`、`fields`、`actor_name`、`payload_envelope`、`attempt`、`eta`、`created_at`）—— 把"原始字段解析"和"消费循环"彻底分开。`broker.read_entries` 内部负责所有 isinstance 兼容、字段归一化、JSON 解码，**worker 拿到的就是 `Entry`**。
  3. `TaskQueueBroker` 实现 `BrokerOps`。原 `_flatten_entries` / `_normalize_stream_fields` 等折叠进 `read_entries`，**bug**（原 `isinstance(stream_entries, tuple)`，`broker.py:275`）在重写时直接消失，jump-cut `_fyuneru_patch.py` 不再需要。
  4. worker 改成只依赖 `BrokerOps`，旧的私有方法直接删（0.2 一次性 breaking）。
- **测试**：`FakeRedisClient.xreadgroup` 改成同时覆盖 list / tuple 两种外层结构；新增解码失败、actor 未注册、attempt 非数字等坏 entry 单元测试，断言 `read_entries` 返回的是"已分类的 `Entry` 或 `BadEntry`"而不是直接抛错。

### R-2 worker 主循环加显式错误边界（per-message 隔离）

- **位置**：`src/fyuneru/task_queue/worker.py:26-46`、`_process_message`（`worker.py:101-135`）
- **现状**：`run_worker` 整体被 `@safe` 包裹，循环体内任何异常都把进程退出 —— 一条坏消息 = 整队列停摆，PEL 里的副本反复触发同样的崩溃，靠 K8s 重启兜底。这是审计列的最高运维风险。
- **改法**（依赖 R-1 的 `Entry` / `BadEntry` 分类）：
  1. 主循环结构：`for entry in broker.read_entries(...): _dispatch(entry)`。`_dispatch` 是一个穷尽 match：
     - `Entry` 正常：调用 handler，成功 ack，失败走 retry / xq。
     - `BadEntry`（解码失败 / actor 未注册 / 字段缺失）：通过 `on_handle_xq` hook 上报 + 直接 `broker.xq(entry, error)`。
     - handler 自身抛 → retry-or-xq 路径。
     - `broker.retry` / `broker.xq` 自身抛错 → warning 日志 + 跳过此消息（PEL 副本由 `claim_idle_ms` 救回）。
  2. 去掉 `run_worker` 外层 `@safe`，改为**正常返回**正常退出码（int / SIGNAL）。Redis 连接异常另行处理（见 R-3）。
  3. handler 抛错时附带的 traceback 必须进 xq 字段（沿用 `build_xq_fields`）。
- **测试**：扩 `FakeRedisClient`：actor 抛 RuntimeError、未注册 actor、坏 JSON envelope、`xq` 自身抛错四个场景，断言 worker 不退出、消息状态符合预期。

### R-3 Redis 连接错误隔离 + graceful shutdown

- **位置**：`src/fyuneru/task_queue/worker.py:26-46`、`:91-97`
- **现状**：`xreadgroup` 一次连接错误直接杀 worker；`while True` 不响应 SIGTERM；`xautoclaim` 每轮无脑打一次 RTT。
- **改法**：
  1. `BrokerOps.read_entries` 把 `redis.ConnectionError` / `TimeoutError` 转成一个空 `Entries` 返回值并通过 `on_redis_error` hook 上报，**不抛**。worker 主循环在收到空且上一次是错误时按指数 backoff sleep（base=500ms，max=30s）。
  2. `run_worker(..., should_stop: Callable[[], bool] | None = None)`，主循环每轮先判断。库本身不夺取 SIGTERM，由调用方注入 handler。
  3. `xautoclaim` 退避：连续 N 轮没有可 claim 的就把 claim 间隔翻倍（cap 30s），有新条目时重置。
- **测试**：mock `read_entries` 抛 `ConnectionError`，断言 worker sleep 后继续；`should_stop=lambda: True` 时主循环立刻返回。

### R-4 ~~重试加 backoff，让 `eta` 真正生效~~ (**已废弃**：v0.2 移除 retry/eta 机制)

eta 延迟调度与 attempt/retry 自维护重试已在 2026-05-26 版本彻底移除，改为纯"至少一次消费 + 死信流"语义。handler 抛错直接进 XQ，无内置重试。

### R-5 `bind_source_reader` 闭包拆分

- **位置**：`src/fyuneru/s3_source.py:67-106`
- **现状**：40 行嵌套闭包混了 URI 解析、registry 查找、惰性 client init、reader 缓存四件事，测试与调试都难。
- **改法**：
  1. 顶层四个纯函数：`parse_blob_uri`（已存在）、`lookup_source(registry, bucket_id) -> SourceConfig`、`build_reader_for(source: SourceConfig) -> ObjectStorageReader`、`MultiSourceReader` dataclass 持有 `registry` 与 `readers: dict[str, ObjectStorageReader]` 缓存。
  2. `bind_source_reader` 退化为构造 `MultiSourceReader` 并返回其 `__call__`。
  3. 公开 `MultiSourceReader` 供调用方在需要"预热某个源 / 显式清缓存"时使用。

### R-6 `pickle.load` 改名 + 显式安全契约

- **位置**：`src/fyuneru/converter.py:11-21`
- **现状**：`bytes_to_object` 直接 `pickle.load`，若调用方喂外部字节 = RCE。jump-cut 不用，但作为公共库是脚印。
- **改法**（按"设计合理 > API"原则）：
  1. **直接重命名** `bytes_to_object` → `unsafe_bytes_to_object`、`object_to_bytes` → `unsafe_object_to_bytes`。不留 deprecated alias —— 当前已知调用方只有库内部，明确 breaking 比"温柔过渡"更诚实。
  2. 函数 docstring 显式："仅接受可信内部字节流，外部输入等同 RCE"。GUIDE.md 配套更新。

### R-7 s3 reader 流式接口

- **位置**：`src/fyuneru/s3_toolkit.py`
- **现状**：裸 `StreamingBody` 或懒 `Iterator[bytes]` 会让读取期错误逃逸 `ResultE` 边界。
- **改法**：
  1. `bind_s3_reader` 改为受控消费式 API：`reader(key, consume) -> ResultE[T]`。
  2. `get_object`、`consume(body)`、`body.close()` 都在 `@safe` 内执行。
  3. 不提供默认 lazy chunk reader；需要按块读取时在 `consume` 内循环 `body.read(chunk_size)`。

---

## O — 优化（不破结构，纯性能 / 可用性）

### O-1 broker / worker 可观测性 hook

- **位置**：`broker.py`、`worker.py`，与 R-1 的 `BrokerOps` 一起设计
- **改法**：`TaskQueueBroker` 接受一组可选 callback（缺省 None，零开销）：

  ```python
  on_enqueue:          (queue) -> None
  on_handle_start:     (queue) -> None
  on_handle_success:   (queue, elapsed) -> None
  on_handle_xq:        (queue, error) -> None
  on_lua_degraded:     (reason: str) -> None
  on_redis_error:      (error) -> None
  ```

  worker 在 R-2 的关键节点同步调用；callback 自身抛错被 try/except 吞掉并 warning 一次，**绝不反过来杀 worker**。同时 broker 在 Lua 注册降级时主动 `on_lua_degraded(...)` + `loguru.warning`，解决审计的"静默降级"问题。

### O-2 xq_stream 加 MAXLEN trim

- **位置**：`broker.py` xq 写入路径、`lua/xq_and_ack.lua`、`build_broker`
- **改法**：`build_broker(xq_maxlen: int | None = None)`。Lua / fallback 两路都加 `XADD ... MAXLEN ~ <xq_maxlen>`（近似 trim）。缺省 None 保留旧行为，jump-cut 在 config 里显式设上限。

### O-3 `enqueue_many` 用 redis pipeline

- **位置**：`broker.py:74-85`
- **改法**：按 `stream_for(queue_name)` 分桶，每桶用 `redis_client.pipeline()` 批量 `xadd`，`execute()` 后按顺序映射回 `ResultE[str]`。cluster 模式同桶不跨槽，故按 stream 分桶天然安全。1000 条入队 RTT 从 1000 降到 N（N = 不同 stream 数）。

### O-4 `to_json_object` 扩展支持类型

- **位置**：`src/fyuneru/converter.py:33-59`
- **改法**：在 `_asdict` 分支前依次判断 `datetime / date` → `isoformat()`、`bytes` → `base64`、`decimal.Decimal` → `str(...)`、`UUID` → `str(...)`、`pathlib.Path` → `str(...)`。不改 raise 行为，仅扩支持类型。

---

## F — 孤立修复 / 文档（最低优先）

### F-1 `list_objects` 分页防御

`src/fyuneru/s3_toolkit.py:163-165`：`continuation_token = response.get("NextContinuationToken")`；缺失但 `IsTruncated=True` 时 `raise RuntimeError(f"S3 list_objects_v2 报告 IsTruncated=True 但未返回 NextContinuationToken (prefix={prefix})")`。

### F-2 GUIDE.md 钉死 at-least-once + 幂等要求

`docs/api_reference.md` task_queue 段新增"语义保证"小节：fyuneru task_queue 是 at-least-once，handler 在异常 / Redis 故障 / Lua 降级三种情况下可能被重复执行。推荐用 `redis_toolkit.calculate_checkpoint_key` + `bind_redis_set_reader/writer` 做 per-payload-key 幂等检查（jump-cut 现成的 `is_past_checkpoint` / `advance_checkpoint` 就是这种模式）。

### F-3 ~~`attempt` 字段语义文档化~~ (**已废弃**：attempt 字段已随 retry/eta 机制一并移除)

### F-4 `configure_logger` 文档幂等性

`src/fyuneru/logger.py:24-46`：函数顶部 `logger.remove()` 已经清掉所有 handler，行为本身没问题；GUIDE.md 显式说"重复调用会重置所有 handler，不是叠加"。

### F-5 s3 client / workspace 校验差异说明

`s3_toolkit.py:66-79` vs `:81-112`：`init_client_from_config` 不校验 bucket，`init_workspace_from_config` 校验。行为合理，GUIDE.md 补一句"client 层不需要 bucket，workspace 层强制"。

---

## jump-cut 侧的兜底（不在本仓库 PR 内）

R-1 / R-2 发版前 jump-cut 已经在用 `_fyuneru_patch.py`，可以再在 worker 入口套一层 supervisor：

```python
while True:
    result = broker.run_worker(...)
    if isinstance(result, Failure):
        logger.exception("worker 退出，3 秒后重启", exc_info=result.failure())
        time.sleep(3)
        continue
    break
```

R-1 合并并发 0.2 后，jump-cut 一次性升级：删除 `_fyuneru_patch.py` 与 `registry.py:16` 的强制导入；supervisor 可保留为兜底（成本几乎为零）。

---

## 落地顺序

按"重构 → 优化 → 修复"的整体方向，但 R 内部仍有序——后做的 R 可以依赖前面 R 的接口形态：

1. **R-1**：定义 `BrokerOps` Protocol + `Entry` 数据类型 + 重写 `read_entries`。 _flatten_entries bug 在此消失，jump-cut 可删补丁。
2. **R-2**：在 R-1 的基础上重写 worker 主循环，加错误边界。
3. **R-3**：Redis 连接错误隔离 + graceful shutdown，依赖 R-1 的 hook 位。
4. **R-4**：~~backoff + eta~~（已废弃，见 R-4 节）。
5. **R-5 / R-6 / R-7**：彼此独立，可并行。
6. **O-1 ~ O-4**：在 R 系列稳定后逐项落地，O-1 与 R-1/R-2 联调最自然，可考虑随 R-2 一起做。
7. **F-1 ~ F-5**：最后清扫。

每一档独立可发；R-1 + R-2 合并并发 0.2，后续小步迭代。

---

## 关键文件清单

- `src/fyuneru/task_queue/broker.py` — R-1, R-2, R-3, R-4, O-1, O-2, O-3
- `src/fyuneru/task_queue/worker.py` — R-1, R-2, R-3, R-4, O-1
- `src/fyuneru/task_queue/protocols.py`（**新增**） — R-1
- `src/fyuneru/task_queue/types.py` — R-1, R-4, F-3
- `src/fyuneru/task_queue/actor.py` — R-4, F-3
- `src/fyuneru/task_queue/lua/` — O-2（改 xq_and_ack.lua）、R-4（新增 defer_and_ack.lua）
- `src/fyuneru/s3_toolkit.py` — R-7, F-1
- `src/fyuneru/s3_source.py` — R-5
- `src/fyuneru/converter.py` — R-6, O-4
- `src/fyuneru/logger.py` — F-4（仅文档）
- `docs/api_reference.md` — R-6, R-7, F-2, F-3, F-4, F-5
- `test/test_task_queue.py` — R-1, R-2, R-3, R-4, O-2 全面扩测

---

## 验证

1. **R-1**：`uv run python test/test_task_queue.py` 全套通过；新增测试覆盖 xreadgroup 返回 list / tuple、坏 JSON、缺字段、未注册 actor 各场景；jump-cut 装本仓库后**不打补丁**也能消费消息。
2. **R-2**：构造 actor 抛 RuntimeError、未注册 actor、`broker.xq` 自身抛错三个场景，跑 `run_worker_once_for_test`，断言进程不退出且消息状态符合预期。
3. **R-3**：mock `read_entries` 抛 `ConnectionError`，断言 worker sleep 后继续；`should_stop=lambda: True` 时主循环立刻返回。
4. **R-4**：已废弃；队列不再支持 attempt、eta 或内置重试。
5. **R-5**：拆分后所有顶层函数有单元测试；`bind_source_reader` 行为不变（回归用例）。
6. **R-6**：grep 全仓 + jump-cut 仓库确认无 `bytes_to_object` / `object_to_bytes` 残留调用。
7. **R-7**：用 `bind_s3_reader` 的 `consume` 按块读 100MB 对象，监控进程 RSS 不超过 chunk_size × 2。
8. **O-1**：每个 hook 都有单测，包括 callback 抛错不影响主流程。
9. **O-2**：100 条永远失败消息跑完，`XLEN xq` ≤ `xq_maxlen + 容差`。
10. **O-3**：真 redis-py enqueue 1000 条，对比 pipeline 前后耗时。
11. **O-4**：`to_json_object(datetime.now())` 等各类型返回正确字符串。
12. **集成**：在 jump-cut 仓库 `uv pip install -e ~/fyuneru-pylib`，删除 `_fyuneru_patch.py` 与 `registry.py:16` 的导入，跑 `script/enqueue.py` + `worker/detect.py + cut.py` 端到端，确认链路正常。
