# fyuneru.s3_source

通过 `blob://桶id/key` URI 协议透明访问多个 S3 源。

需要：`fyuneru[s3]`

## API

```python
from fyuneru.s3_source import parse_blob_uri, load_source_registry, bind_source_reader

parse_blob_uri(uri: str) -> tuple[str, str]
# "blob://bucket_id/key" -> (bucket_id, key)
# 格式非法抛 ValueError。

load_source_registry(config: dict) -> dict[str, dict]
# 读 config["s3_sources"] 列表，校验必填字段，转成以 source_id 为 key 的 dict。
# 缺 "s3_sources" 抛 KeyError。
# s3_sources 非 list / 条目非 dict / 必填字段缺失 / source_id 非非空字符串 → ValueError。
# 重复 source_id 时 warning 并用后者覆盖前者。

bind_source_reader(registry: dict[str, dict]) -> ObjectStorageReader
# reader(uri: str, consume: Callable[[ReadableBinaryStream], T]) -> ResultE[T]
# 返回受控消费式 blob:// URI reader。
# 按 bucket_id 惰性初始化并缓存 S3 client。
# consume 必须同步消费流，不要保存或返回 body 给外部继续读取。
```

## 用法

```python
from pathlib import Path
from fyuneru.config import read_config_with_override
from fyuneru.result import unwrap
from fyuneru.s3_source import bind_source_reader, load_source_registry

cfg = read_config_with_override(Path("config.yml"))
registry = load_source_registry(cfg)
read = bind_source_reader(registry)

def save_to_file(body):
    with Path("image.jpg").open("wb") as output:
        while chunk := body.read(1024 * 1024):
            output.write(chunk)

unwrap(read("blob://my-images/photos/img001.jpg", save_to_file))
```

## 配置 YAML

```yaml
s3_sources:
- source_id: my-images
  endpoint: https://s3.example.com
  bucket: actual-bucket-name
  access_key_id: xxx
  secret_access_key: xxx
  region_name: us-east-1   # optional

- source_id: backup-store
  endpoint: https://s3.backup.com
  bucket: backup-bucket
  access_key_id: xxx
  secret_access_key: xxx
```

## 关键约束

- `read_config_with_override` 对 list 走追加合并，**去重在 `load_source_registry` 完成**（后写的 source_id 覆盖前面的）
- `bind_source_reader` 返回的闭包内部 cache client，第一次访问某个 bucket 才初始化
- 当前 `source_reader` 由 `ObjectStorageReader` 实现，key 语义是 `blob://source-id/path` URI；后续增加 file/http 等来源时再引入更通用的 `SourceReader` Protocol
- 当前只暴露读，不支持写 / 删
