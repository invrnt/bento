from __future__ import annotations

from bento.domain.settings import (
    SettingApplyMode as Apply,
    SettingAvailability as Availability,
    SettingDefinition,
    SettingValueType as Type,
)


def _field(
    key: str,
    aliases: tuple[str, ...],
    group: str,
    value_type: Type,
    default: object,
    *,
    apply: Apply = Apply.LIVE,
    availability: Availability = Availability.BOTH,
    secret: bool = False,
    editable: bool = True,
    choices: tuple[str, ...] = (),
    minimum: float | None = None,
    maximum: float | None = None,
    probe: str | None = None,
) -> SettingDefinition:
    return SettingDefinition(
        key=key,
        env_aliases=aliases,
        group=group,
        label_key=f"settings.{key}.label",
        help_key=f"settings.{key}.help",
        value_type=value_type,
        default=default,
        apply_mode=apply,
        availability=availability,
        secret=secret,
        editable=editable,
        choices=choices,
        minimum=minimum,
        maximum=maximum,
        probe=probe,
    )


SETTINGS_REGISTRY: tuple[SettingDefinition, ...] = (
    _field("app_name", ("APP_NAME",), "advanced", Type.STRING, "Bento", editable=False),
    _field("app_version", ("APP_VERSION",), "advanced", Type.STRING, "0.1.0", editable=False),
    _field("environment", ("ENVIRONMENT",), "advanced", Type.STRING, "local", editable=False),
    _field("runtime_mode", ("BENTO_RUNTIME_MODE",), "advanced", Type.CHOICE, "headless", editable=False, choices=("headless", "desktop")),
    # Telegram-first: without an account or vault the library simply stays local; `local` is the explicit opt-out.
    _field("storage_backend", ("STORAGE_BACKEND",), "storage", Type.CHOICE, "telegram", apply=Apply.RESTART_SERVICES, choices=("local", "telegram", "fake"), probe="storage"),
    _field("host", ("HOST",), "advanced", Type.STRING, "127.0.0.1", availability=Availability.HEADLESS, editable=False),
    _field("api_port", ("API_PORT",), "advanced", Type.INTEGER, 8000, availability=Availability.HEADLESS, editable=False, minimum=1, maximum=65535),
    _field("web_port", ("WEB_PORT",), "advanced", Type.INTEGER, 5173, availability=Availability.HEADLESS, editable=False, minimum=1, maximum=65535),
    _field("worker_concurrency", ("WORKER_CONCURRENCY",), "performance", Type.INTEGER, 1, apply=Apply.RESTART_WORKER, minimum=1, maximum=8),
    _field("data_dir", ("DATA_DIR",), "storage", Type.PATH, "/app/data", apply=Apply.RESTART_APP, probe="writable_directory"),
    _field("ocr_provider", ("OCR_PROVIDER", "BENTO_OCR_PROVIDER"), "ai", Type.CHOICE, "disabled", apply=Apply.RESTART_WORKER, choices=("disabled", "mock", "rapidocr")),
    _field("embeddings_provider", ("EMBEDDINGS_PROVIDER", "BENTO_EMBEDDING_PROVIDER"), "ai", Type.CHOICE, "disabled", apply=Apply.RESTART_SERVICES, choices=("disabled", "mock", "jina")),
    _field("jina_model_path", ("JINA_MODEL_PATH", "BENTO_EMBEDDING_MODEL_PATH"), "ai", Type.PATH, "./data/models/jina-v5-omni-nano.gguf", apply=Apply.RESTART_SERVICES, probe="model_file"),
    _field("embedding_server_url", ("BENTO_EMBEDDING_SERVER_URL",), "ai", Type.STRING, "http://127.0.0.1:8080/v1/embeddings", apply=Apply.RESTART_SERVICES),
    _field("embedding_dimensions", ("BENTO_EMBEDDING_DIMENSIONS",), "ai", Type.INTEGER, 768, apply=Apply.RESTART_SERVICES, minimum=1, maximum=65536),
    # Build configuration (Bento's own Telegram application), read from the environment only.
    _field("telegram_api_id", ("BENTO_TELEGRAM_API_ID",), "telegram", Type.SECRET, None, apply=Apply.RESTART_SERVICES, secret=True, editable=False),
    _field("telegram_api_hash", ("BENTO_TELEGRAM_API_HASH",), "telegram", Type.SECRET, None, apply=Apply.RESTART_SERVICES, secret=True, editable=False),
    _field("telegram_parallel_transfers", ("BENTO_TELEGRAM_PARALLEL_TRANSFERS",), "performance", Type.INTEGER, 1, apply=Apply.RESTART_SERVICES, minimum=1, maximum=4),
    _field("telegram_part_size_mb", ("BENTO_TELEGRAM_PART_SIZE_MB",), "advanced", Type.INTEGER, 512, apply=Apply.RESTART_SERVICES, minimum=64, maximum=1950),
    _field("relay_url", ("BENTO_RELAY_URL",), "advanced", Type.STRING, "", apply=Apply.RESTART_SERVICES),
    _field("public_site_url", ("BENTO_PUBLIC_SITE_URL",), "advanced", Type.STRING, "", apply=Apply.RESTART_SERVICES),
    _field("inbox_keep_hours", ("BENTO_INBOX_KEEP_HOURS",), "telegram", Type.INTEGER, 24, apply=Apply.RESTART_WORKER, minimum=0, maximum=720),
    _field("trash_retention_days", ("BENTO_TRASH_RETENTION_DAYS",), "storage", Type.INTEGER, 30, apply=Apply.RESTART_WORKER, minimum=1, maximum=365),
    _field("cache_max_gb", ("BENTO_CACHE_MAX_GB",), "storage", Type.NUMBER, 10, apply=Apply.RESTART_SERVICES, minimum=1, maximum=2048),
    _field("backup_pause_on_battery", ("BENTO_BACKUP_PAUSE_ON_BATTERY",), "backup", Type.BOOLEAN, True),
    _field("backup_bandwidth_limit_kbps", ("BENTO_BACKUP_BANDWIDTH_LIMIT_KBPS",), "backup", Type.INTEGER, 0, minimum=0, maximum=1_000_000),
    _field("fake_telegram_dir", ("BENTO_FAKE_TELEGRAM_DIR",), "advanced", Type.PATH, "", apply=Apply.RESTART_SERVICES),
)

SETTINGS_BY_KEY = {item.key: item for item in SETTINGS_REGISTRY}
SETTINGS_BY_ALIAS = {alias: item for item in SETTINGS_REGISTRY for alias in item.env_aliases}


def validate_registry() -> None:
    keys = [item.key for item in SETTINGS_REGISTRY]
    aliases = [alias for item in SETTINGS_REGISTRY for alias in item.env_aliases]
    if len(keys) != len(set(keys)):
        raise RuntimeError("Duplicate settings registry keys")
    if len(aliases) != len(set(aliases)):
        raise RuntimeError("Duplicate settings environment aliases")
    if any(item.secret != (item.value_type == Type.SECRET) for item in SETTINGS_REGISTRY):
        raise RuntimeError("Secret registry fields must use the secret value type")


validate_registry()
