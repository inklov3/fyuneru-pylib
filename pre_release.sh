#!/usr/bin/env bash
set -euo pipefail

uv sync --group dev --extra redis --extra s3 --extra gemini --extra pipeline --extra media
uv run pyclean src/
uv run ruff check src/
uv run pyrefly check src/
uv run python test/test_s3_source.py
uv run python test/test_s3_toolkit.py
uv run python test/test_logger.py
uv run python test/test_config.py
uv run python test/test_retry.py
uv run python test/test_gemini_toolkit.py
uv run python test/test_video_toolkit.py
uv run python test/test_task_queue.py
