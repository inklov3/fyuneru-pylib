# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository shape

- This is a `src/`-layout Python library, not an application repo. Package code lives in `src/fyuneru/`.
- Use `uv` for dependency management and commands. Do not switch to `pip`, `poetry`, or ad-hoc virtualenv workflows.
- The top-level `fyuneru` package does not act as a public re-export surface; import from concrete submodules.
- Tests are executable Python scripts under `test/`, not a pytest-discovery workflow.

## Setup and verification commands

### Install development dependencies

```bash
uv sync --group dev
```

### Install development dependencies with all optional toolkits

```bash
uv sync --group dev --extra redis --extra s3 --extra mongo --extra gemini --extra pipeline --extra media
```

### Full release-style verification

This repository treats `pre_release.sh` as the authoritative full check:

```bash
./pre_release.sh
```

At the time of writing it runs, in order:

```bash
uv sync --group dev --extra redis --extra s3 --extra mongo --extra gemini --extra pipeline --extra media
uv run pyclean src/
uv run ruff check src/
uv run pyrefly check src/
uv run python test/test_s3_source.py
uv run python test/test_logger.py
uv run python test/test_config.py
uv run python test/test_task_queue.py
```

### Run a single test script

```bash
uv run python test/test_worker_env.py
```

Other commonly used targeted checks:

```bash
uv run python test/test_logger.py
uv run python test/test_s3_source.py
uv run python test/test_config.py
uv run python test/test_task_queue.py
uv run python test/test_worker_env.py
```

### Run a specific test function inside a script

These test files are plain Python scripts, so there is no stable pytest node-selection command documented in the repo. The practical workflow is to run the whole target script:

```bash
uv run python test/test_task_queue.py
```

If you need function-level isolation, edit or temporarily instrument the script locally rather than assuming pytest selectors exist.

## Dependency extras map

Many modules are intentionally optional. Before editing code that imports one of these modules, verify the matching extra is installed:

- `fyuneru[redis]` → `fyuneru.redis_toolkit`
- `fyuneru[s3]` → `fyuneru.s3_toolkit`, `fyuneru.s3_source`
- `fyuneru[mongo]` → `fyuneru.mongo_toolkit`
- `fyuneru[gemini]` → `fyuneru.gemini_toolkit`
- `fyuneru[pipeline]` → `fyuneru.task_queue`, `fyuneru.dramatiq_toolkit`
- `fyuneru[media]` installs media dependencies used by downstream code

Do not assume optional dependencies are present in the minimal environment.

## Core design conventions

The whole library uses a consistent functional wrapper pattern:

- `init_*`: returns a lazy initializer (`Callable`) that creates a client only when invoked
- `bind_*`: binds a client and resource name, returning a single focused operation closure
- `build_*`: assembles a higher-level composed object

This convention is the main architectural through-line across Redis, S3, Mongo, Gemini, and task-queue helpers. Preserve it when extending existing modules.

### Error model

`src/fyuneru/result.py` defines the single error-handling contract for the repo:

- operations return `Success(value)` or `Failure(error)`
- `@safe` converts exceptions into `ResultE[T]`
- `unwrap(result)` is the standard boundary for turning a `Failure` back into an exception

When using toolkit operations, prefer `unwrap(...)` or explicit `is_failure(...)` branching instead of bypassing the `Result` model.

## Configuration architecture

`src/fyuneru/config.py` is the central config entrypoint.

Key behaviors that matter across multiple modules:

- `read_config_from_paths(paths)` merges multiple YAML files in order
- `read_config_from_env()` reads `FYUNERU_CONFIG_PATHS` as a colon-separated list
- `read_config_with_override(base, override)` is just a thin two-file specialization of the same merge path
- merge semantics are intentional: `dict` recursively merges, scalars overwrite, lists append

This matters because downstream systems rely on those exact semantics:

- Redis / S3 / Mongo / Gemini config initializers all parse from the merged mapping
- `s3_sources` deduplication does **not** happen during merge; later duplicate handling happens in `s3_source.load_source_registry`
- worker environment assembly assumes the config has already been normalized by these readers

## High-level package architecture

### Infrastructure toolkits

The repository is a set of small infrastructure wrappers rather than one integrated framework:

- `logger`, `config`, `converter`, `markdown_utils`, `result` are the minimal core
- `redis_toolkit`, `s3_toolkit`, `mongo_toolkit`, `gemini_toolkit` provide lazy client setup plus a few bound operations
- each toolkit is intentionally narrow and composable rather than stateful

### Multi-source S3 access

`fyuneru.s3_source` sits above `s3_toolkit`.

Important cross-file behavior:

- config merge appends `s3_sources`
- `load_source_registry` validates that list and resolves duplicate `source_id` entries with “later wins” semantics
- `bind_source_reader` then lazily creates and caches per-source S3 clients for `blob://source_id/key` reads

If you change config or S3 behavior, keep those phases conceptually separate: merge first, registry validation/dedup second, lazy client access third.

### Worker environment assembly

`src/fyuneru/worker/env.py` is the composition layer for data-processing workers.

It is not a new backend; it wires existing toolkits into one `WorkerEnv` bundle:

- validates `label` plus explicitly passed `workspace`
- optionally creates Redis checkpoint helpers when `redis` config exists
- optionally creates S3 writer/reader when `s3` config exists
- optionally creates `blob://` source reader when `s3_sources` exists
- optionally creates Mongo database handle when `mongo` config exists

Two naming conventions are shared with other modules and should stay stable:

- checkpoint key: `{workspace}:checkpoint:{label}`
- result artifact key: `{workspace}/result/{key}/{artifact}.pkl`

`test/test_worker_env.py` is the best executable spec for how this composition layer is expected to behave when resources are present or absent.

## Task queue architecture

The Redis Streams queue implementation spans several files under `src/fyuneru/task_queue/` and is one of the few parts that requires reading multiple files together.

The high-level model is:

- `build_broker(...)` constructs a `TaskQueueBroker`
- `@actor(...)` registers one handler per queue
- `new_message(...)` and `enqueue/enqueue_many(...)` produce messages
- `run_worker(...)` consumes messages from Redis Streams consumer groups

### Semantics that future edits must preserve

- Delivery semantics are **at least once**, not exactly once
- Payloads are serialized as a dataclass-based envelope, not arbitrary free-form JSON
- Actor registration is strict: one payload parameter, annotated as a dataclass type
- Producer/consumer schema mismatches are treated fail-fast at decode/registration time
- Handler failures, payload decode failures, or missing actor bindings go to XQ (dead-letter stream) and the source message is ACKed
- There is no built-in retry loop in the queue layer; retries belong in handlers or an upper orchestration layer

### Reliability and observability details

Important behavior spread across broker/worker/design docs:

- critical “write to XQ and ACK original” transition is protected with Lua for atomicity
- `claim_idle_ms` enables `XAUTOCLAIM`-based takeover of stale pending messages
- worker loops are designed to survive Redis connection/timeouts via retry/backoff rather than crash the process
- `BrokerHooks` are the observability seam; hook failures must never take down the worker
- `enqueue_many(...)` uses Redis pipeline support when available, but still returns per-message results

### Deployment implication

Because bad or mismatched payloads are pushed to XQ instead of crashing the worker, rolling upgrades must be ordered carefully: upgrade consumers before producers when introducing payload/schema changes. Otherwise valid new messages can be classified as dead letters by old workers.

## Imports and public API expectations

- Prefer submodule imports such as `from fyuneru.redis_toolkit import ...`.
- Do not add broad top-level re-exports unless there is a strong repository-wide reason.
- Keep new APIs aligned with the existing `init_* / bind_* / build_* / Result` vocabulary rather than introducing parallel conventions.

## Repository documents worth checking

- `README.md`: package positioning, install extras, config examples, and command examples
- `AGENTS.md`: concise repo-specific working rules for automation agents
- `docs/task_queue_design.md`: authoritative explanation of queue semantics and tradeoffs
- `src/fyuneru/GUIDE.md`: compact API overview for the package surface
