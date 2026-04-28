from __future__ import annotations

from typing import Any

from fyuneru import mongo_toolkit, redis_toolkit, s3_source, s3_toolkit
from fyuneru.logger import configure_logger
from fyuneru.result import unwrap
from fyuneru.worker.types import WorkerEnv


def calculate_result_key(
    workspace: str,
    media_key: str,
    label: str,
    artifact: str,
) -> str:
    workspace_name = _require_non_empty_text("workspace", workspace)
    media_name = _require_non_empty_text("media_key", media_key)
    label_name = _require_non_empty_text("label", label)
    artifact_name = _require_non_empty_text("artifact", artifact)
    return f"{workspace_name}/{media_name}/results/{label_name}/{artifact_name}.pkl"


def setup_worker_env(label: str, config: dict[str, Any]) -> WorkerEnv:
    if not isinstance(config, dict):
        raise TypeError("config 必须是字典")

    label_name = _require_non_empty_text("label", label)
    workspace = _require_non_empty_text("workspace", config.get("workspace"))
    task = _require_non_empty_text("task", config.get("task"))

    unwrap(configure_logger())

    redis_client = None
    advance_checkpoint = None
    is_past_checkpoint = None

    if "redis" in config:
        redis_client = redis_toolkit.init_client_from_config(config)()
        checkpoint_key = redis_toolkit.calculate_checkpoint_key(
            workspace=workspace,
            task=task,
            label=label_name,
        )
        advance_checkpoint = redis_toolkit.bind_redis_set_writer(
            redis_client, checkpoint_key
        )
        is_past_checkpoint = redis_toolkit.bind_redis_set_reader(
            redis_client, checkpoint_key
        )

    s3_writer = None
    s3_reader = None
    if "s3" in config:
        s3_config = config["s3"]
        if not isinstance(s3_config, dict):
            raise TypeError("s3 配置必须是字典")
        bucket = _require_non_empty_text("s3.bucket", s3_config.get("bucket"))
        s3_client = s3_toolkit.init_client_from_config(config)()
        s3_writer = s3_toolkit.bind_s3_writer(s3_client, bucket)
        s3_reader = s3_toolkit.bind_s3_reader(s3_client, bucket)

    source_reader = None
    if "s3_sources" in config:
        source_registry = s3_source.load_source_registry(config)
        source_reader = s3_source.bind_source_reader(source_registry)

    mongo_db = None
    if "mongo" in config:
        mongo_db = mongo_toolkit.init_database_from_config(config)()

    return WorkerEnv(
        config=config,
        label=label_name,
        redis_client=redis_client,
        s3_writer=s3_writer,
        s3_reader=s3_reader,
        source_reader=source_reader,
        mongo_db=mongo_db,
        advance_checkpoint=advance_checkpoint,
        is_past_checkpoint=is_past_checkpoint,
    )


def _require_non_empty_text(field_name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} 必须是字符串")
    normalized = value.strip()
    if normalized == "":
        raise ValueError(f"{field_name} 不能为空")
    return normalized
