# S3 多源协议

`fyuneru.s3_source` 通过 `blob://source_id/key` URI 协议透明访问多个 S3 源。

## 配置

```yaml
s3_sources:
- source_id: my-images
  endpoint: https://s3.example.com
  bucket: actual-bucket-name
  access_key_id: xxx
  secret_access_key: xxx
  region_name: us-east-1

- source_id: backup-store
  endpoint: https://s3.backup.com
  bucket: backup-bucket
  access_key_id: xxx
  secret_access_key: xxx
```

## URI 格式

```text
blob://source_id/path/to/object
```

- `source_id` 对应配置里的 `source_id`
- `path/to/object` 是源 bucket 内的 object key

## 解析流程

1. 解析 URI → 提取 source_id + object key
2. 用 source_id 查找配置中 `s3_sources` 的对应条目
3. 用源配置初始化 S3 client（复用 `s3_toolkit.init_client`）
4. 调用 `bind_s3_reader` 生成受控消费式 reader，执行读取

## 使用示例

```python
from pathlib import Path

from fyuneru.config import read_config_with_override
from fyuneru.result import unwrap
from fyuneru.s3_source import bind_source_reader, load_source_registry

config = read_config_with_override(Path("config.yml"))
registry = load_source_registry(config)
read = bind_source_reader(registry)

def consume(body):
    return body.read()

result = read("blob://my-images/photos/2024/img001.jpg", consume)
data = unwrap(result)
```

`consume` 必须同步消费流，不要保存或返回 body 给外部继续读取。
