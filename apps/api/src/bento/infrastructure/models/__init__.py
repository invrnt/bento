"""Packaged smart-search model manifest, license texts and the on-disk model layout.

`manifest.json` is version-controlled and reviewed like code (`execution/smart-search-program.md`
§Distribution). It is read with `importlib.resources`, so it works from a wheel and from the PyInstaller
bundles (which must list this package's data files).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from bento.adapters.models.filesystem_store import FilesystemModelStore
from bento.adapters.models.manifest_catalog import ManifestModelCatalog

PACKAGE = "bento.infrastructure.models"
MANIFEST_FILE = "manifest.json"
LICENSES_DIR = "licenses"
MODELS_DIR_NAME = "models"
LICENSE_URL_PATH = "/api/smart-search/license"
DOWNLOAD_USER_AGENT_PRODUCT = "Bento"

_SPDX_RE = re.compile(r"^[A-Za-z0-9.+-]{1,64}$")


def packaged_manifest_data() -> dict[str, Any]:
    text = resources.files(PACKAGE).joinpath(MANIFEST_FILE).read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("The packaged model manifest must be a JSON object")
    return data


@lru_cache(maxsize=1)
def packaged_model_catalog() -> ManifestModelCatalog:
    return ManifestModelCatalog.from_mapping(packaged_manifest_data())


def load_model_catalog(manifest_path: Path | None = None) -> ManifestModelCatalog:
    """The packaged catalog, or one read from `manifest_path` (tests, release tooling)."""
    if manifest_path is None:
        return packaged_model_catalog()
    return ManifestModelCatalog.from_path(manifest_path)


def models_root(data_dir: Path | str) -> Path:
    """`<data_dir>/models`: `<model_id>/<revision>/<file>` (+ `.part`, `.verified`, `LICENSE`)."""
    return Path(data_dir) / MODELS_DIR_NAME


def model_store(data_dir: Path | str) -> FilesystemModelStore:
    return FilesystemModelStore(models_root(data_dir))


def license_text(spdx: str) -> str:
    """The license text shipped for `spdx` (for example `Apache-2.0`)."""
    if not _SPDX_RE.match(spdx):
        raise FileNotFoundError(spdx)
    entry = resources.files(PACKAGE).joinpath(LICENSES_DIR).joinpath(f"{spdx}.txt")
    if not entry.is_file():
        raise FileNotFoundError(spdx)
    return entry.read_text(encoding="utf-8")


def model_notice_text(model_id: str) -> str | None:
    """Per-model notice (publisher, pinned source, use-policy link), or None.

    Notices are named after the model family: `embeddinggemma-2-q8_0` → `embeddinggemma-2-NOTICE.txt`.
    """
    licenses = resources.files(PACKAGE).joinpath(LICENSES_DIR)
    family = model_id.rsplit("-q", 1)[0] if re.search(r"-q\d", model_id) else model_id
    entry = licenses.joinpath(f"{family}-NOTICE.txt")
    return entry.read_text(encoding="utf-8") if entry.is_file() else None


def download_user_agent(version: str) -> str:
    """Generic `User-Agent: Bento/<version>`; the download sends no other identifier."""
    return f"{DOWNLOAD_USER_AGENT_PRODUCT}/{version or '0'}"
