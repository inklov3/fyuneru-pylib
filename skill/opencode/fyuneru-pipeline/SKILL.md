---
name: fyuneru-pipeline
description: fyuneru pipeline 项目搭建指南。当用户要用 fyuneru.task_queue / fyuneru.worker.WorkerEnv 搭建或重构 Redis Streams pipeline、worker、actor、节点编排、enqueue 脚本，或提到多节点/单节点 pipeline 时触发。触发后先读 references/40_pipeline_project.md，再按需读 fyuneru 的 00_overview、01_result、30_task_queue、32_worker_env 等 reference。
---

# fyuneru pipeline — opencode 搭建指南

这是下游项目搭建 `fyuneru.task_queue` + `fyuneru.worker.WorkerEnv` pipeline 的专用 skill。

## 触发条件

当会话满足以下任一情况时加载：

- 用户要搭建 / 重构 fyuneru pipeline、worker、actor、broker、enqueue 脚本
- 用户提到 `WorkerEnv`、`setup_worker_env`、`task_queue`、Redis Streams worker
- 用户讨论单节点或多节点 pipeline 的项目结构
- 代码中出现 `from fyuneru.worker import WorkerEnv, setup_worker_env`

## 先读什么

1. 必读：`references/40_pipeline_project.md`
2. 按需补充：
   - `references/00_overview.md`：fyuneru 总体约定和 extra
   - `references/01_result.md`：`ResultE` / `unwrap`
   - `references/30_task_queue.md`：broker / actor / worker 当前 API
   - `references/32_worker_env.md`：`WorkerEnv` 字段和约束
   - `references/20_redis_toolkit.md` / `21_s3_toolkit.md` / `22_s3_source.md` / `23_mongo_toolkit.md`：节点实际使用对应资源时再读

## 强制原则

- 默认按多节点 pipeline 骨架搭建；单节点也使用同一骨架，只是当前只注册一个 actor。
- `WorkerEnv` 是 pipeline 项目的标准入口，不要因为当前只有一个节点就绕开它。
- `src/pipeline` 负责装配；`src/pyproject` 负责纯业务；`worker/main.py --node <node>` 是唯一 worker 入口。
- 当前 API 不支持 actor `name=` / `max_retries=`；不要从旧项目照搬。
- 不要新增 `_fyuneru_patch.py`；当前 fyuneru 已修复旧 redis-py 兼容问题。
- `run_worker` 返回 `int`，不要 `unwrap(run_worker(...))`。

## 实施前自查

- payload 是否是集中定义的 dataclass
- 每个 actor handler 是否只有一个 payload 参数
- `setup_worker_env` 之前是否注入了 `workspace` 和 `task`
- 使用 `env.*` 前是否显式检查 None
- handler 是否满足 at-least-once 下的幂等要求
- 写完是否运行下游项目声明的 lint / typecheck
