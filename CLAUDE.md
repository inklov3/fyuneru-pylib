# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

fyuneru is a Python utility library wrapping common infrastructure components (Redis, S3, MongoDB, Dramatiq, Gemini) with unified, composable functional interfaces. It uses the `returns` library for safe error handling and `functools.partial` for lazy initialization.

## Build & Development

```bash
# Install with uv (development)
uv sync --group dev

# Install with optional dependencies
uv sync --group dev --extra redis --extra s3 --extra pipeline --extra media --extra gemini --extra mongo

# Lint & format
uv run ruff check src/
uv run ruff format src/

# Type check
uv run pyrefly check src/

# Clean build artifacts
uv run pyclean .

# Run test (no test framework — just script execution)
uv run python test/test_logger.py
```

Build system: Hatchling. Package source is in `src/fyuneru/`.

## Architecture

All modules follow two naming conventions:
- **`init_*`** — Returns a `Callable` (via `functools.partial`) that lazily creates a client/handle when called
- **`gen_*`** — Returns a tuple of composable operation functions (writer, reader, deleter)

Error handling uses `@safe` from the `returns` library, wrapping return values in `Result` types. Protocol classes define the type signatures for returned callables.

### Module Layout (`src/fyuneru/`)

| Module | Pattern | External Deps |
|--------|---------|---------------|
| `logger.py` | `init_logger` + `tqdm_loguru` helper | loguru, tqdm |
| `config.py` | Pure function `read_config` | stdlib tomllib |
| `converter.py` | Pure functions for pickle/JSON conversion | stdlib |
| `markdown_utils.py` | Pure function `unwrap_codeblock` | stdlib re |
| `redis_toolkit.py` | `init_client_*` + `gen_redis_set` | redis |
| `s3_toolkit.py` | `init_client` + `gen_s3worker` | boto3, mypy-boto3-s3 |
| `mongo_toolkit.py` | `init_client` | pymongo |
| `dramatiq_toolkit.py` | `init_broker` + message helpers | dramatiq, redis |
| `gemini_toolkit.py` | `init_client` + `gen_content_config` | google-genai |

### Key Pattern: Checkpoint via Composition

Checkpoints are implemented by composing `calculate_checkpoint_key()` + `gen_redis_set()` — no dedicated checkpoint abstraction exists.

## Conventions

- Language: Code in English, docstrings/comments in Chinese
- Commit messages: Chinese, prefixed with type (`fix:`, `refactor:`, `feat:`, `doc:`)
- Ruff config: import sorting (`select = ["I"]`), double quotes, 88 char line length
- No `__init__.py` exports — users import directly from submodules
- Optional dependencies are grouped in `pyproject.toml` under `[project.optional-dependencies]`
