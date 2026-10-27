# 流式对象读取 API 设计备忘

## 背景

在 `pipeline-ant-video-multitrack` 的 supplier 解压 worker 中，当前链路需要从 `blob://...` 源对象读取压缩包，解压后再把产物上传到目标 S3。原始实现把源压缩包和解压产物都读成 `bytes`，大文件场景会带来明显内存风险。

本轮讨论先尝试把 `fyuneru-pylib` 的 S3 reader 改成返回 `StreamingBody`，writer 改成接收 `BinaryIO` 并使用 `upload_fileobj`。这个方向能降低内存占用，但 review 后确认存在一个关键设计问题：只要把裸 `StreamingBody` 或懒 `Iterator[bytes]` 返回给调用方，真正的网络读取错误会发生在 `@safe` / `ResultE` 边界之外，无法被 fyuneru 的统一错误模型捕获。

本文件记录后续 agent 处理该问题时应遵守的上下文、用户要求和推荐方案。

## 用户要求

1. 这次修改不是为了 `pipeline-ant-video-multitrack` 单个项目定制，必须作为 `fyuneru-pylib` 的通用基础设施 API 设计。
2. 不需要保持向后兼容，可以接受 breaking change，但接口要清晰、可维护。
3. 流式读取仍然必须尽量保持 fyuneru 的错误模型：读取期网络错误、调用方消费错误、本地写入错误都应落在 `ResultE` 内，而不是在调用方后续裸抛。
4. 不要把核心 reader 抽象改成 `download_fileobj(key, output)` 这类只适合“下载到文件”的接口；它对当前解压 worker 够用，但不够通用。
5. `ObjectStorageReader` 当前可以作为 `source_reader` 的一种实现。后续可能增加 file reader 等其他实现，但暂时不必单独改出 `SourceReader` Protocol；需要把这个语义写清楚。
6. 下游 `SupplierUnpackManifest` 中已删除的 `source_id`、`supplier_key`、`archive_suffix` 字段不需要恢复。
7. `pipeline-ant-video-multitrack/deploy/supplier-unpack-worker.yml` 当前含真实凭据，不得提交；如需提交部署示例，新增不含密钥的 example pod yaml。

## 核心问题

### 裸流返回会逃逸 `ResultE` 边界

如果 reader API 是：

```python
reader(key: str) -> ResultE[StreamingBody]
```

那么 `get_object` 失败可以被 `@safe` 包住，但下面这些错误不会被包住：

- `body.read()` 时网络中断；
- `body.iter_chunks()` 迭代中异常；
- 调用方把流复制到本地文件时写入失败；
- 调用方解码或处理流内容时抛错。

这违背了 fyuneru 的核心约定：基础设施 I/O 能力应通过 `ResultE` 显式表达失败。

### 懒 iterator 有同样问题

如果 `bind_s3_chunked_reader` 返回 `ResultE[Iterator[bytes]]`，错误同样会在调用方后续迭代时发生。除非迭代过程发生在 `@safe` 包裹的函数内部，否则不能保证 `ResultE` 语义。

### `download_fileobj` 不应成为核心抽象

`download_fileobj(key, output)` 能覆盖“下载到本地文件”场景，也能把读取错误包在 `ResultE` 内，但它把 reader 过早绑定到文件写入动作，不适合作为通用库的核心读取抽象。通用库应该允许调用方在受控边界内完成复制、校验、解码、分块处理等不同消费行为。

## 推荐方案：受控消费流 API

核心思路：fyuneru 不直接把裸流交出 `ResultE` 边界，而是让调用方提供一个同步消费函数。`get_object`、调用 `consume`、关闭流全部发生在 `@safe` 内。

建议 API 形态：

```python
from collections.abc import Callable
from typing import Protocol, TypeVar

from fyuneru.result import ResultE

T = TypeVar("T")


class ReadableBinaryStream(Protocol):
    def read(self, amt: int | None = None) -> bytes: ...
    def close(self) -> None: ...


class ObjectStorageReader(Protocol):
    def __call__(
        self,
        key: str,
        consume: Callable[[ReadableBinaryStream], T],
    ) -> ResultE[T]: ...
```

`bind_s3_reader` 的实现语义：

```python
@safe
def read_object(
    key: str,
    consume: Callable[[ReadableBinaryStream], T],
) -> T:
    response = client.get_object(Bucket=bucket, Key=key)
    body = response["Body"]
    try:
        return consume(body)
    finally:
        body.close()
```

这样可以保证：

- `get_object` 异常进入 `Failure`；
- `consume(body)` 内部 `read()` 触发的网络异常进入 `Failure`；
- `consume(body)` 内部本地文件写入、解码、校验异常进入 `Failure`；
- 成功或失败都会关闭底层流。

调用方约束：`consume` 必须同步消费流，不应把 `body` 保存到外部或作为返回值继续使用。文档中应明确这一点。

## Chunked reader 的处理建议

如果保留 chunked 读取，也应避免返回懒 iterator 给调用方长期持有。可选方案：

### 方案 A：用同一个 `ObjectStorageReader`

只保留 `read(body)` 流接口，由调用方在 `consume` 内自行按 chunk 读取：

```python
def consume(body: ReadableBinaryStream) -> int:
    total = 0
    while True:
        chunk = body.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
    return total
```

这是最小 API，推荐优先采用。

### 方案 B：提供受控 chunk consumer

如果仍希望封装 chunk 大小，可增加独立接口：

```python
class ObjectStorageChunkReader(Protocol):
    def __call__(
        self,
        key: str,
        consume: Callable[[bytes], None],
    ) -> ResultE[None]: ...
```

实现内部循环读取 chunk，并在 `@safe` 内调用 `consume(chunk)`。这种 push-style API 最能保证错误边界，但返回值表达能力弱一些。

如果选择 `Callable[[Iterator[bytes]], T]`，必须在文档里要求调用方在 callback 内同步消费 iterator，不能把 iterator 返回出去；否则仍会逃逸错误边界。

## Writer 侧建议

`ObjectStorageWriter` 接收 `BinaryIO` 并调用 `upload_fileobj` 是合理的：

```python
class ObjectStorageWriter(Protocol):
    def __call__(self, key: str, body: BinaryIO) -> ResultE[None]: ...
```

原因：`upload_fileobj` 会在 `@safe` 包裹的函数内部消费输入流，因此输入流读取错误、S3 上传错误都能进入 `Failure`。小对象场景可以由调用方用 `io.BytesIO` 包装。

## `source_reader` 语义说明

当前 `fyuneru.worker.WorkerEnv.source_reader` 可以继续使用 `ObjectStorageReader` 作为实现类型，但文档需要说清楚：

- `s3_reader` 的 key 语义是目标 S3 bucket 内的 object key；
- `source_reader` 的 key 语义是源 URI，例如 `blob://source-id/path/to/object`；
- 当前 `source_reader` 由 `s3_source.bind_source_reader` 基于 `ObjectStorageReader` 组合实现；
- 后续如增加 `file://`、本地文件、HTTP 等来源，可以再引入更通用的 `SourceReader` Protocol；
- 暂时不为这个语义差异扩大改动面。

## Escape hatch

如确实需要把原生 `StreamingBody` 交给第三方库，可提供明确命名的逃生口，例如：

```python
unsafe_open_s3_stream(key: str) -> ResultE[StreamingBody]
```

必须在文档中明确：

- 这个接口只保证打开流阶段的错误进入 `ResultE`；
- 后续读取、迭代、关闭期间的错误由调用方负责；
- 不应作为 `WorkerEnv` 默认暴露能力；
- 名称中必须带 `unsafe` 或同等强提示。

## 对 `pipeline-ant-video-multitrack` 的迁移形态

下游解压 worker 的下载逻辑可改成把复制动作放入 `consume` 内：

```python
def copy_archive(body: ReadableBinaryStream) -> None:
    with archive_path.open("wb") as archive_file:
        shutil.copyfileobj(body, archive_file)

unwrap(source_reader(supplier_blob_uri, copy_archive))
```

上传逻辑继续使用流式 writer：

```python
with file_path.open("rb") as output_file:
    unwrap(target_writer(target_key, output_file))
```

这样压缩包下载和解压产物上传都不再全量进入内存，同时读取期错误仍能被 `ResultE` 捕获。

## 部署示例文件要求

`pipeline-ant-video-multitrack/deploy/supplier-unpack-worker.yml` 当前包含真实凭据，不得纳入提交。后续需要提交部署模板时，应新增示例文件，例如：

```text
deploy/supplier-unpack-worker.example.yml
```

示例文件只能包含 `<placeholder>`，不得包含真实 endpoint、access key、secret key、token、Mongo URI、Redis 地址或镜像 digest 中的私有敏感信息。

## 建议改动清单

### fyuneru-pylib

- `src/fyuneru/s3_toolkit.py`
  - 改 `ObjectStorageReader` 为受控消费流 API。
  - `bind_s3_reader` 在 `@safe` 内执行 `consume(body)` 并负责关闭 body。
  - 删除或重做返回懒 iterator 的 chunked reader。
  - 保留 `ObjectStorageWriter(key, BinaryIO)` + `upload_fileobj`。
  - 如需要裸流，新增明确 unsafe 命名的 opener。

- `src/fyuneru/s3_source.py`
  - `bind_source_reader` 透传新的 `consume` 参数。
  - `MultiSourceReader.read` 保持 URI 解析、reader 缓存、错误分支处理。

- `src/fyuneru/worker/types.py`
  - 暂时可以继续把 `source_reader` 标为 `ObjectStorageReader | None`。
  - 文档中明确它是 blob URI reader，当前由 object storage reader 实现。

- `docs/reference/21_s3_toolkit.md`
  - 更新 reader/writer API。
  - 强调 reader 的 `consume` 同步消费约束。

- `docs/reference/22_s3_source.md`
  - 更新 `bind_source_reader` 用法。

- `docs/reference/32_worker_env.md`
  - 补充 `source_reader` 与 `ObjectStorageReader` 的关系。

### pipeline-ant-video-multitrack

- `src/pyproject/supplier_unpack.py`
  - 使用新的受控消费 reader 下载压缩包。
  - 继续使用 `BinaryIO` writer 上传解压产物。
  - 不恢复 `SupplierUnpackManifest` 已删除字段。

- `deploy/supplier-unpack-worker.example.yml`
  - 新增无密钥示例模板。
  - 不提交含密钥的 `deploy/supplier-unpack-worker.yml`。

## 测试计划

### fyuneru-pylib 单元测试

1. `bind_s3_reader` 成功路径：consumer 读取数据并返回值，断言返回 `Success` 且 body 被关闭。
2. `bind_s3_reader` 的 `get_object` 抛错：断言返回 `Failure`。
3. `bind_s3_reader` 的 `body.read()` 抛错：断言返回 `Failure` 且 body 被关闭。
4. `bind_s3_reader` 的 consumer 自身抛错：断言返回 `Failure` 且 body 被关闭。
5. `bind_source_reader` 未知 source：断言返回 `Failure`。
6. `bind_source_reader` 成功路径：断言 blob URI 被解析后调用底层 reader，并保持 `consume` 语义。
7. `bind_s3_writer` 成功路径：fake client `upload_fileobj` 读取输入流，断言上传内容正确。
8. `bind_s3_writer` 读取输入流抛错：断言返回 `Failure`。
9. `test/test_worker_env.py` 更新 source/s3 reader mock，覆盖新签名。

### 下游项目验证

在 `pipeline-ant-video-multitrack` 中，使用本地 `fyuneru-pylib/src` 跑：

```bash
uv run ruff check .
PYTHONPATH="/home/inklov3/fyuneru-pylib/src" uv run --no-sync pyrefly check .
```

如 fyuneru 已提交并推送，再用：

```bash
uv sync --upgrade-package fyuneru
uv run ruff check .
uv run pyrefly check .
```

## 验收标准

- 不再有默认 reader API 返回裸 `StreamingBody` 或可逃逸的懒 iterator。
- 读取期错误能通过 `ResultE` 返回。
- Writer 侧保持流式上传，不全量读取文件。
- `source_reader` 文档说明当前实现与未来扩展边界。
- 示例部署文件不含真实凭据。
- fyuneru-pylib 通过 `./pre_release.sh` 和 `uv run python test/test_worker_env.py`。
- 下游项目通过 `ruff` 和 `pyrefly`。
