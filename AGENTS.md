# AGENTS.md — fyuneru-pylib

Python utility library wrapping common infrastructure components (Redis, S3, MongoDB,
Dramatiq, Google Gemini) with unified, composable functional interfaces.
Local `Success`/`Failure` result type for safe error handling and lazy initialization.

## Build & Test Commands

```bash
# Install (development, all optional deps)
uv sync --group dev --extra redis --extra s3 --extra pipeline --extra media --extra gemini --extra mongo

# Install (development, minimal)
uv sync --group dev

# Lint (import sorting only)
uv run ruff check src/

# Auto-format
uv run ruff format src/

# Type check
uv run pyrefly check src/

# Full pre-release pipeline (lint + typecheck + tests)
./pre_release.sh
```

### Running Tests

No test framework — tests are plain Python scripts with `assert` statements.

```bash
# Run a single test
uv run python test/test_logger.py
uv run python test/test_s3_source.py
uv run python test/test_config.py

# Run all tests
uv run python test/test_s3_source.py && uv run python test/test_logger.py && uv run python test/test_config.py
```

### After Making Changes — Always Run

```bash
uv run ruff check src/
uv run ruff format src/
uv run pyrefly check src/
```

## Tech Stack

- Python >= 3.11, `src/` layout (PEP 517/621)
- Build backend: Hatchling
- Package manager: **uv** (not pip, not poetry)
- Linter/formatter: ruff
- Type checker: pyrefly
- Core deps: loguru, pyyaml, tqdm
- **Local result type**: `src/fyuneru/result.py` 实现 `Success` / `Failure` / `@safe` (非外部 returns 库)
- Optional deps grouped in `pyproject.toml`: redis, s3, pipeline, media, gemini, mongo

## Architecture

### Module Layout (`src/fyuneru/`)

| Module               | Pattern              | External Deps          |
|----------------------|----------------------|------------------------|
| `logger.py`          | `configure_logger`   | loguru, tqdm           |
| `config.py`          | Pure `read_config`   | pyyaml                 |
| `converter.py`       | Pure functions       | stdlib                 |
| `markdown_utils.py`  | Pure function        | stdlib re              |
| `redis_toolkit.py`   | `init_*` + `bind_*`  | redis                  |
| `s3_toolkit.py`      | `init_*` + `bind_*`  | boto3, mypy-boto3-s3   |
| `s3_source.py`       | `parse_*` + `bind_*` | boto3 (via s3_toolkit) |
| `mongo_toolkit.py`   | `init_client`        | pymongo                |
| `dramatiq_toolkit.py`| `build_broker` + helpers | dramatiq, redis    |
| `gemini_toolkit.py`  | `init_client` + `build_*` | google-genai      |

### Core Design Patterns

- **`init_*` functions**: Capture config and return zero-arg `Callable`.
  Client is created lazily when the callable is invoked.
- **`bind_*` functions**: Take a client + resource name, return one `@safe`-decorated
  operation closure.
- **Two-layer config init**: Low-level `init_*_from_config` returns client factory;
  high-level `init_*_workspace_from_config` binds resource names and returns ready-to-use factories.
- **`TYPE_CHECKING` guards**: Heavy optional-dependency types imported only under
  `if TYPE_CHECKING:` to avoid runtime import failures.
- **`__init__.py` is empty**: No re-exports. Users import directly from submodules:
  `from fyuneru.redis_toolkit import bind_redis_set_writer`.

## Code Style

### Ruff Configuration

```toml
[tool.ruff]
line-length = 88

[tool.ruff.lint]
select = ["I"]               # import sorting only

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
skip-magic-trailing-comma = false
```

### Naming Conventions

| Context    | Convention            | Examples                                    |
|------------|-----------------------|---------------------------------------------|
| Functions  | `snake_case`          | `init_client`, `bind_s3_reader`, `parse_blob_uri` |
| Variables  | `snake_case`          | `set_name`, `bucket_id`, `override_path`    |
| Classes    | `PascalCase`          | `LogLevel`, `RedisSetReader`, `NonSerializable` |
| Constants  | `UPPER_SNAKE_CASE`    | `BLOB_SCHEME = "blob"`                      |
| Private    | `_leading_underscore` | `_read_yaml_mapping`, `_merge_config_value` |

### Import Style

Enforced by ruff (`select = ["I"]`), isort-compatible ordering:

1. Standard library (`from collections.abc import Callable`, `from functools import partial`)
2. Third-party (`from fyuneru.result import safe`, `from redis import Redis`)
3. Local/project (`from fyuneru.config import read_config_with_override`)

Each group separated by a blank line. Prefer `from X import Y` over bare `import X`.

### Language Convention

- **Code** (identifiers): English
- **Docstrings and comments**: Chinese
- **Commit messages**: Chinese, prefixed with type (`fix:`, `refactor:`, `feat:`, `doc:`, `style:`)

### Type Annotations

- Use modern Python 3.11+ syntax: `str | None`, `dict[str, Any]`, `tuple[str, str]`
- `ResultE[T]` from local `fyuneru.result` for typed error results
- `Protocol` classes for structural typing of returned callables
- `Callable[[], T]` for factory return types

## Error Handling

- **`@safe` decorator** from `fyuneru.result`: wraps functions returning `ResultE[T]`
  (alias for `Result[T, Exception]`) instead of raising.
- **Protocol classes** define type signatures for safe-wrapped callables.
- **Guard clauses** with `raise ValueError(...)` / `raise KeyError(...)` for input validation.
- **No silent failures**: errors surface through `Result` or direct exceptions.
- **Mutable default args**: always `kwargs: dict | None = None` with `if kwargs is None: kwargs = {}`.

## Testing Patterns

- Plain Python scripts with `assert` statements (no pytest).
- `if __name__ == "__main__":` block calls test functions, prints Chinese success messages.
- Error-path tests: `try/except` with `assert False, "message"` as failure.
- Temp files via `tempfile.TemporaryDirectory` and `Path.write_text`.
- Tests mock no external services — `test_s3_source.py` and `test_config.py` test pure logic only.

## Key Documentation

- `src/fyuneru/GUIDE.md` — comprehensive API reference (English), distributed with the package
- `README.md` — user-facing documentation (Chinese)
- `CHANGELOG.md` — release history (Chinese)
- `example.yml` — reference YAML config file
