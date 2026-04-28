from __future__ import annotations

from typing import Any

from fyuneru import mongo_toolkit, redis_toolkit, s3_source, s3_toolkit
from fyuneru.worker.types import WorkerEnv


def calculate_result_key(
    workspace: str,
    task: str,
    key: str,
    artifact: str,
) -> str:
    workspace_name = _require_non_empty_text("workspace", workspace)
    task_name = _require_non_empty_text("task", task)
    unit_key = _require_non_empty_text("key", key)
    artifact_name = _require_non_empty_text("artifact", artifact)
    return f"{workspace_name}/{task_name}/result/{unit_key}/{artifact_name}.pkl"


def setup_worker_env(label: str, config: dict[str, Any]) -> WorkerEnv:
    label_name, workspace, task = _validate_base(label, config)

    redis_client, advance_checkpoint, is_past_checkpoint = _build_redis(
        config=config,
        workspace=workspace,
        task=task,
        label=label_name,
    )
    s3_writer, s3_reader = _build_s3(config)
    source_reader = _build_source(config)
    mongo_db = _build_mongo(config)

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


def _validate_base(label: str, config: dict[str, Any]) -> tuple[str, str, str]:
    if not isinstance(config, dict):
        raise TypeError("config 必须是字典")
    label_name = _require_non_empty_text("label", label)
    workspace = _require_non_empty_text("workspace", config.get("workspace"))
    task = _require_non_empty_text("task", config.get("task"))
    return label_name, workspace, task


def _build_redis(
    config: dict[str, Any],
    workspace: str,
    task: str,
    label: str,
):
    if "redis" not in config:
        return None, None, None

    redis_client = redis_toolkit.init_client_from_config(config)()
    checkpoint_key = redis_toolkit.calculate_checkpoint_key(
        workspace=workspace,
        task=task,
        label=label,
    )
    advance_checkpoint = redis_toolkit.bind_redis_set_writer(
        redis_client, checkpoint_key
    )
    is_past_checkpoint = redis_toolkit.bind_redis_set_reader(
        redis_client, checkpoint_key
    )
    return redis_client, advance_checkpoint, is_past_checkpoint


def _build_s3(config: dict[str, Any]):
    if "s3" not in config:
        return None, None
    s3_writer, s3_reader, _ = s3_toolkit.init_workspace_from_config(config)()
    return s3_writer, s3_reader


def _build_source(config: dict[str, Any]):
    if "s3_sources" not in config:
        return None
    source_registry = s3_source.load_source_registry(config)
    return s3_source.bind_source_reader(source_registry)


def _build_mongo(config: dict[str, Any]):
    if "mongo" not in config:
        return None
    return mongo_toolkit.init_database_from_config(config)()


def _require_non_empty_text(field_name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} 必须是字符串")
    normalized = value.strip()
    if normalized == "":
        raise ValueError(f"{field_name} 不能为空")
    return normalized
