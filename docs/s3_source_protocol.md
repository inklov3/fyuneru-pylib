# S3 多源协议设计

## 协议格式

```
blob://桶id/object/key/path
```

- **协议名**: `blob`（通用二进制大对象语义，简短清晰）
- **桶id**: 用户在 `.s3_source.yml` 中自定义的标识符（不一定等于实际桶名）
- **对象key**: S3 对象的完整 key，支持 `/` 分隔的路径

## 配置文件

在主配置 YAML 中增加 `s3_sources` 段（与 `redis`、`s3` 等同级）：

```yaml
s3_sources:
- source_id: my-images              # 桶id（自定义标识，对应 blob://my-images/...）
  endpoint: "https://s3.example.com"
  bucket: "actual-bucket-name"      # 实际的 S3 桶名
  access_key_id: "AK..."
  secret_access_key: "SK..."
  region_name: "us-east-1"          # 可选

- source_id: backup-store
  endpoint: "https://s3.backup.com"
  bucket: "backup-bucket"
  access_key_id: "AK..."
  secret_access_key: "SK..."
```

每个源条目包含：

| 字段 | 必填 | 说明 |
|------|------|------|
| `source_id` | 是 | 自定义标识符，用于 `blob://` URI 的桶id 部分 |
| `endpoint` | 是 | S3 兼容服务端点 |
| `bucket` | 是 | 实际桶名 |
| `access_key_id` | 是 | 访问密钥 ID |
| `secret_access_key` | 是 | 访问密钥 |
| `region_name` | 否 | 区域名称 |

## 解析流程

1. 解析 URI → 提取桶id + 对象key
2. 用桶id查找配置中 `s3_sources` 列表的对应条目
3. 用源配置初始化 S3 client（复用 `s3_toolkit.init_client`）
4. 调用 `gen_s3worker` 生成读取函数，执行读取

## 使用示例

```python
from pathlib import Path
from fyuneru.s3_source import load_source_registry, init_source_reader

registry = load_source_registry(Path("config.yml"))
read = init_source_reader(registry)

result = read("blob://my-images/photos/2024/img001.jpg")
# result: Result[bytes, Exception]
```
