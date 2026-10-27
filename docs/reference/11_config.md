# fyuneru.config

YAML 配置读取（含单层增量覆盖）+ 强类型解析器。默认安装。

## API

```python
from fyuneru.config import (
    read_config,
    read_config_with_override,
    parse_redis_config,
    parse_s3_config,
)

read_config(config: Path) -> dict[str, Any]
# 读取 YAML 配置。空文件返回 {}。
# 根节点非 mapping 时抛 ValueError。

read_config_with_override(base: Path, override: Path | None = None) -> dict[str, Any]
# 读 base，可选覆盖一份 override YAML。
# 合并规则：
# - dict: 递归合并，key 冲突时 override 胜
# - 标量: override 替换 base
# - list: 追加 (base + override)
# 非目标：不做模板渲染、不支持字段删除语义。

parse_redis_config(config: dict[str, Any]) -> RedisConfig
parse_s3_config(config: dict[str, Any]) -> S3Config
# 强类型解析，显式字段校验，错误带 path 信息。
# parse_s3_config 支持可选 addressing_style: "path" | "virtual"；默认 "virtual"。
```

## 关键约束

- `read_config_with_override` 只支持**单层** override（base + 一个 pod 文件），不递归合并多层
- `s3_sources` 的 list 走追加合并，**去重在 `load_source_registry` 里做**（后者覆盖前者，见 `22_s3_source.md`）
- `read_config_from_env` 读 `FYUNERU_CONFIG_PATHS`（冒号分隔，按顺序合并多份 YAML）—— 高级场景

## 用法

```python
from pathlib import Path
from fyuneru.config import read_config_with_override, parse_redis_config

cfg = read_config_with_override(base=Path("config.yml"), override=Path("pod.yml"))
redis_cfg = parse_redis_config(cfg)   # 类型化后 .host / .port 等可放心用
```
