"""Backend seams the Android engine relies on, verified on desktop."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from alembic.config import Config

from bento.domain.devices import DevicePlatform
from bento.domain.settings_registry import PLATFORM_DEFAULTS, platform_default
from bento.infrastructure import process_secrets
from bento.infrastructure.db.migrate import (
    MigrationLayoutError,
    current_revision,
    default_migrations_dir,
    head_revision,
    run_migrations,
)
from bento.infrastructure.settings import Settings, get_settings, install_settings, load_effective_settings

API_ROOT = Path(__file__).parents[3]


def test_alembic_free_head_matches_alembic() -> None:
    config = Config()
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    assert head_revision(default_migrations_dir()) == ScriptDirectory.from_config(config).get_current_head()


def test_migrations_run_from_any_directory_and_skip_alembic_at_head(tmp_path: Path) -> None:
    import shutil

    extracted = tmp_path / "extracted" / "migrations"
    shutil.copytree(API_ROOT / "migrations", extracted, ignore=shutil.ignore_patterns("__pycache__"))
    settings = Settings(data_dir=str(tmp_path / "data"))
    first = run_migrations(settings, migrations_dir=extracted)
    assert first.ran and first.from_revision is None and first.to_revision == head_revision(extracted)
    assert current_revision(tmp_path / "data" / "db" / "bento.sqlite3") == first.to_revision
    assert all((tmp_path / "data" / child).is_dir() for child in ("db", "cache", "uploads", "journal"))
    second = run_migrations(settings, migrations_dir=extracted)
    assert not second.ran and second.as_dict()["from"] == first.to_revision
    with pytest.raises(MigrationLayoutError):
        run_migrations(settings, migrations_dir=tmp_path / "missing")


def test_at_head_check_imports_no_alembic(tmp_path: Path) -> None:
    run_migrations(Settings(data_dir=str(tmp_path / "data")))
    code = (
        "import sys; from bento.infrastructure.settings import Settings;"
        "from bento.infrastructure.db.migrate import run_migrations;"
        f"r = run_migrations(Settings(data_dir={str(tmp_path / 'data')!r}));"
        "assert not r.ran; print(sorted(m for m in ('alembic', 'mako', 'watchdog', 'telethon') if m in sys.modules))"
    )
    output = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert output.strip() == "[]"


def test_android_hot_path_imports_no_desktop_only_modules() -> None:
    code = (
        "import sys; import bento.interfaces.android.engine, bento.interfaces.http.main, bento.interfaces.worker.main;"
        "import bento.interfaces.worker.runtime, bento.adapters.android.host;"
        "print(sorted(m for m in ('alembic', 'mako', 'watchdog', 'telethon', 'PIL', 'pypdfium2', 'rapidocr', 'uvicorn')"
        " if m in sys.modules))"
    )
    output = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd="/").stdout
    assert output.strip() == "[]"


def test_installed_settings_bypass_the_environment_and_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("STORAGE_BACKEND=local\n")
    monkeypatch.setenv("DATA_DIR", "/should/not/be/used")
    explicit = Settings(data_dir=str(tmp_path / "phone"), storage_backend="fake")
    install_settings(explicit)
    try:
        assert get_settings() is explicit
    finally:
        install_settings(None)
    assert get_settings().data_dir == "/should/not/be/used"
    get_settings.cache_clear()


def test_platform_defaults_apply_only_on_android_and_saved_values_win(tmp_path: Path) -> None:
    android = load_effective_settings(Settings(data_dir=str(tmp_path)), environ={"BENTO_PLATFORM": "android"})
    desktop = load_effective_settings(Settings(data_dir=str(tmp_path)), environ={})
    for key, value in PLATFORM_DEFAULTS["android"].items():
        assert getattr(android, key) == value
        assert platform_default(key, "auto") == getattr(desktop, key)
    assert (desktop.backup_wifi_only, desktop.ocr_requires_charging, desktop.backup_only_charging) == (False, False, False)

    from bento.domain.settings import PersistedSettings

    saved = PersistedSettings(values={"backup_wifi_only": "false"})
    assert load_effective_settings(
        Settings(data_dir=str(tmp_path)), environ={"BENTO_PLATFORM": "android"}, persisted=saved
    ).backup_wifi_only is False


def test_process_secrets_put_holds_and_blank_forgets() -> None:
    process_secrets.clear()
    process_secrets.put("BENTO_API_TOKEN", "t" * 40)
    assert process_secrets.get("BENTO_API_TOKEN") == "t" * 40
    process_secrets.put("BENTO_API_TOKEN", "  ")
    assert process_secrets.get("BENTO_API_TOKEN") is None


def test_android_device_platform_and_name() -> None:
    from bento.infrastructure.mtproto.wiring import device_description
    from bento.interfaces.http.routes_pairing import local_device_info

    settings = Settings(data_dir="/tmp/x", platform="android", device_name="Pixel 7a")
    assert device_description(settings).platform == DevicePlatform.ANDROID
    assert device_description(settings).name == "Pixel 7a"
    info = local_device_info(settings)
    assert (info.platform, info.name) == (DevicePlatform.ANDROID, "Pixel 7a")
    assert local_device_info(Settings(data_dir="/tmp/x")).platform != DevicePlatform.ANDROID


def test_http_main_import_builds_no_app() -> None:
    code = (
        "import bento.interfaces.http.main as m, bento.infrastructure.settings as s;"
        "print(s.get_settings.cache_info().currsize)"
    )
    output = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd="/").stdout
    assert output.strip() == "0"
