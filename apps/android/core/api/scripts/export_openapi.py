"""Print the backend OpenAPI schema deterministically (api/android-endpoints.md §10).

usage: uv run --project apps/api python apps/android/core/api/scripts/export_openapi.py [<output>]

Prefers agent 35's `bento.interfaces.http.export_openapi` once it exists; until then it serializes
`create_app().openapi()` with sorted keys. Both must produce the same bytes.
"""

from __future__ import annotations

import json
import sys


def render() -> str:
    try:
        from bento.interfaces.http import export_openapi  # type: ignore[attr-defined]

        for name in ("render", "export_json", "dumps"):
            if hasattr(export_openapi, name):
                return str(getattr(export_openapi, name)())
    except ImportError:
        pass
    from bento.interfaces.http.main import create_app

    return json.dumps(create_app().openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    text = render()
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
