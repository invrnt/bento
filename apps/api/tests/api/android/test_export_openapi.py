from __future__ import annotations

import json
import os
import subprocess
import sys

from bento.interfaces.http.export_openapi import openapi_schema, render


def test_export_is_deterministic_and_covers_the_android_contract() -> None:
    first = render(openapi_schema())
    assert first == render(openapi_schema())
    schema = json.loads(first)
    paths = schema["paths"]
    for path in (
        "/api/android/imports",
        "/api/android/imports/{import_id}",
        "/api/backup/run-now",
        "/api/backup/status",
        "/api/backup/free-up-space/preview",
        "/api/backup/free-up-space/confirm",
        "/api/photos/timeline/index",
        "/api/assets/{asset_id}/offline",
        "/api/storage/local",
    ):
        assert path in paths, path
    assert any(parameter["name"] == "size" for parameter in paths["/api/assets/{asset_id}/thumbnail"]["get"]["parameters"])
    assert schema["info"]["version"] == "0.0.0"


def test_export_ignores_the_environment() -> None:
    environment = {**os.environ, "APP_VERSION": "9.9.9", "DATA_DIR": "/nonexistent", "STORAGE_BACKEND": "fake"}
    command = [sys.executable, "-m", "bento.interfaces.http.export_openapi"]
    first = subprocess.run(command, capture_output=True, text=True, check=True, env=environment).stdout
    assert first == render(openapi_schema())
