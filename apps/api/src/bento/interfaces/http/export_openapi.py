"""Deterministic OpenAPI export for clients generated at build time (Android DTOs, `android-runtime.md` §8).

`uv run python -m bento.interfaces.http.export_openapi > apps/android/core/api/openapi.json`

The schema comes from `create_app().openapi()` with settings that do not depend on the machine (no data
directory is touched, no environment is read); keys are sorted and the output ends with a newline, so the same
code always yields byte-identical output and CI can fail on a stale snapshot.
"""

from __future__ import annotations

import json
import sys
import tempfile
from typing import Any, TextIO


def openapi_schema() -> dict[str, Any]:
    from bento.infrastructure.settings import Settings
    from bento.interfaces.http.main import create_app

    with tempfile.TemporaryDirectory(prefix="bento-openapi-") as data_dir:
        settings = Settings(_env_file=None, data_dir=data_dir, storage_backend="local", app_version="0.0.0")  # type: ignore[call-arg]
        app = create_app(settings, guard_environ={})
        return app.openapi()


def render(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(stream: TextIO | None = None) -> int:
    (stream or sys.stdout).write(render(openapi_schema()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
