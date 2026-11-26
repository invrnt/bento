from __future__ import annotations

import os
from types import MappingProxyType

from bento.domain.settings import (
    SettingApplyMode as Apply,
    SettingAvailability as Availability,
    SettingDefinition,
    SettingValueType as Type,
)
from bento.domain.smart_search import EMBEDDINGS_PROVIDER_CHOICES, Pooling, default_embedding_threads


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


PLATFORMS = ("auto", "android")

# Mirror of `infrastructure/models/manifest.json` (model id -> Matryoshka dims), recommended model first.
# The domain does no IO, so the manifest is not read here; `tests/unit/test_smart_search_settings.py`
# keeps this table equal to the canonical manifest. Validation prefers a `ModelCatalogPort` when one is wired.
MANAGED_MODEL_DIMS: MappingProxyType[str, tuple[int, ...]] = MappingProxyType(
    {
        "embeddinggemma-2-q8_0": (768, 512, 256, 128),
        "qwen3-embedding-0.6b-q8_0": (1024, 768, 512, 256),
    }
)
SMART_SEARCH_MODEL_IDS: tuple[str, ...] = tuple(MANAGED_MODEL_DIMS)
DEFAULT_SMART_SEARCH_MODEL_ID = SMART_SEARCH_MODEL_IDS[0]
DEFAULT_EMBEDDING_DIMENSIONS = 512  # D9: EmbeddingGemma 2 truncated to 512.
# Where Stage <= 23 builds looked for the Jina GGUF; read only to map a leftover `jina` provider value.
LEGACY_CUSTOM_MODEL_PATH = "./data/models/jina-v5-omni-nano.gguf"
# `auto` leaves pooling to the GGUF metadata (no `--pooling` flag).
CUSTOM_POOLING_CHOICES: tuple[str, ...] = ("auto", *(pooling.value for pooling in Pooling))
# Providers offered per platform (D6: Android keeps search by meaning on `disabled`; `managed` is never offered).
PLATFORM_EMBEDDINGS_PROVIDERS: dict[str, tuple[str, ...]] = {
    "auto": EMBEDDINGS_PROVIDER_CHOICES,
    "android": tuple(choice for choice in EMBEDDINGS_PROVIDER_CHOICES if choice != "managed"),
}

# Defaults that differ by host platform; everything else uses the registry default.
PLATFORM_DEFAULTS: dict[str, dict[str, object]] = {
    "android": {
        "backup_wifi_only": True,
        "ocr_requires_charging": True,
        "ocr_provider": "mlkit",
        "embeddings_provider": "disabled",
        "cache_max_gb": 2,
    },
}

SETTINGS_REGISTRY: tuple[SettingDefinition, ...] = (
    _field("app_name", ("APP_NAME",), "advanced", Type.STRING, "Bento", editable=False),
    _field("app_version", ("APP_VERSION",), "advanced", Type.STRING, "0.1.0", editable=False),
    _field("environment", ("ENVIRONMENT",), "advanced", Type.STRING, "local", editable=False),
    _field("runtime_mode", ("BENTO_RUNTIME_MODE",), "advanced", Type.CHOICE, "headless", editable=False, choices=("headless", "desktop")),
    # Host platform; `android` is set by the embedded engine and selects the platform defaults below.
    _field("platform", ("BENTO_PLATFORM",), "advanced", Type.CHOICE, "auto", editable=False, choices=PLATFORMS),
    _field("device_name", ("BENTO_DEVICE_NAME",), "advanced", Type.STRING, "", editable=False),
    # Telegram-first: without an account or vault the library simply stays local; `local` is the explicit opt-out.
    _field("storage_backend", ("STORAGE_BACKEND",), "storage", Type.CHOICE, "telegram", apply=Apply.RESTART_SERVICES, choices=("local", "telegram", "fake"), probe="storage"),
    _field("host", ("HOST",), "advanced", Type.STRING, "127.0.0.1", availability=Availability.HEADLESS, editable=False),
    _field("api_port", ("API_PORT",), "advanced", Type.INTEGER, 8000, availability=Availability.HEADLESS, editable=False, minimum=1, maximum=65535),
    _field("web_port", ("WEB_PORT",), "advanced", Type.INTEGER, 5173, availability=Availability.HEADLESS, editable=False, minimum=1, maximum=65535),
    _field("worker_concurrency", ("WORKER_CONCURRENCY",), "performance", Type.INTEGER, 1, apply=Apply.RESTART_WORKER, minimum=1, maximum=8),
    _field("data_dir", ("DATA_DIR",), "storage", Type.PATH, "/app/data", apply=Apply.RESTART_APP, probe="writable_directory"),
    _field("ocr_provider", ("OCR_PROVIDER", "BENTO_OCR_PROVIDER"), "ai", Type.CHOICE, "disabled", apply=Apply.RESTART_WORKER, choices=("disabled", "mock", "rapidocr", "mlkit")),
    # `managed` is written by the smart search activation flow (`/api/smart-search/activate`), not by the form.
    _field("embeddings_provider", ("EMBEDDINGS_PROVIDER", "BENTO_EMBEDDING_PROVIDER"), "ai", Type.CHOICE, "disabled", apply=Apply.RESTART_SERVICES, choices=EMBEDDINGS_PROVIDER_CHOICES),
    _field("smart_search_model", ("BENTO_SMART_SEARCH_MODEL",), "ai", Type.CHOICE, DEFAULT_SMART_SEARCH_MODEL_ID, apply=Apply.RESTART_SERVICES, choices=SMART_SEARCH_MODEL_IDS),
    # Advanced (`ADVANCED_SETTINGS`): a person's own GGUF (`custom`) and the llama.cpp runtime.
    _field("custom_model_path", ("BENTO_CUSTOM_MODEL_PATH", "JINA_MODEL_PATH", "BENTO_EMBEDDING_MODEL_PATH"), "ai", Type.PATH, "", apply=Apply.RESTART_SERVICES, probe="model_file"),
    _field("custom_mmproj_path", ("BENTO_CUSTOM_MMPROJ_PATH",), "ai", Type.PATH, "", apply=Apply.RESTART_SERVICES, probe="model_file"),
    _field("custom_query_prefix", ("BENTO_CUSTOM_QUERY_PREFIX",), "ai", Type.STRING, "", apply=Apply.RESTART_SERVICES),
    _field("custom_document_prefix", ("BENTO_CUSTOM_DOCUMENT_PREFIX",), "ai", Type.STRING, "", apply=Apply.RESTART_SERVICES),
    _field("custom_pooling", ("BENTO_CUSTOM_POOLING",), "ai", Type.CHOICE, "auto", apply=Apply.RESTART_SERVICES, choices=CUSTOM_POOLING_CHOICES),
    _field("embedding_dimensions", ("BENTO_EMBEDDING_DIMENSIONS",), "ai", Type.INTEGER, DEFAULT_EMBEDDING_DIMENSIONS, apply=Apply.RESTART_SERVICES, minimum=1, maximum=65536),
    _field("llama_server_path", ("BENTO_LLAMA_SERVER_PATH",), "ai", Type.PATH, "", apply=Apply.RESTART_SERVICES),
    # An external OpenAI-compatible server; when set, Bento spawns no llama-server of its own.
    _field("embedding_server_url", ("BENTO_EMBEDDING_SERVER_URL",), "ai", Type.STRING, "", apply=Apply.RESTART_SERVICES),
    _field("embedding_threads", ("BENTO_EMBEDDING_THREADS",), "ai", Type.INTEGER, default_embedding_threads(os.cpu_count() or 1), apply=Apply.RESTART_SERVICES, minimum=1, maximum=64),
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
    # Device-condition policy (`api/android-endpoints.md` §2). Permissive everywhere but Android (platform defaults).
    _field("backup_wifi_only", ("BENTO_BACKUP_WIFI_ONLY",), "backup", Type.BOOLEAN, False),
    _field("backup_videos_on_metered", ("BENTO_BACKUP_VIDEOS_ON_METERED",), "backup", Type.BOOLEAN, False),
    _field("backup_only_charging", ("BENTO_BACKUP_ONLY_CHARGING",), "backup", Type.BOOLEAN, False),
    _field("ocr_requires_charging", ("BENTO_OCR_REQUIRES_CHARGING",), "ai", Type.BOOLEAN, False),
    _field("fake_telegram_dir", ("BENTO_FAKE_TELEGRAM_DIR",), "advanced", Type.PATH, "", apply=Apply.RESTART_SERVICES),
    # Debug only: a `fake-telegram-serve` URL shared by emulator and host processes (never in production).
    _field("fake_telegram_url", ("BENTO_FAKE_TELEGRAM_URL",), "advanced", Type.STRING, "", apply=Apply.RESTART_SERVICES, editable=False),
)

SETTINGS_BY_KEY = {item.key: item for item in SETTINGS_REGISTRY}
SETTINGS_BY_ALIAS = {alias: item for item in SETTINGS_REGISTRY for alias in item.env_aliases}

# Shown only under the "Advanced" disclosure of their group (`ai`).
ADVANCED_SETTINGS: frozenset[str] = frozenset(
    {
        "custom_model_path",
        "custom_mmproj_path",
        "custom_query_prefix",
        "custom_document_prefix",
        "custom_pooling",
        "embedding_dimensions",
        "llama_server_path",
        "embedding_server_url",
        "embedding_threads",
    }
)


def is_advanced(key: str) -> bool:
    return key in ADVANCED_SETTINGS


def embeddings_provider_choices(platform: str) -> tuple[str, ...]:
    return PLATFORM_EMBEDDINGS_PROVIDERS.get(platform, EMBEDDINGS_PROVIDER_CHOICES)


def smart_search_model_choices(platform: str) -> tuple[str, ...]:
    """Managed models offered on `platform` (none where `managed` is not offered)."""
    return SMART_SEARCH_MODEL_IDS if "managed" in embeddings_provider_choices(platform) else ()


def is_hidden(key: str, platform: str = "auto") -> bool:
    """`smart_search_model` stays hidden unless the platform is offered more than one managed model."""
    if key == "smart_search_model":
        return len(smart_search_model_choices(platform)) <= 1
    return False


def platform_default(key: str, platform: str) -> object:
    """The default of `key` on `platform` (the registry default unless `PLATFORM_DEFAULTS` overrides it)."""
    overrides = PLATFORM_DEFAULTS.get(platform, {})
    return overrides[key] if key in overrides else SETTINGS_BY_KEY[key].default


def validate_registry() -> None:
    keys = [item.key for item in SETTINGS_REGISTRY]
    aliases = [alias for item in SETTINGS_REGISTRY for alias in item.env_aliases]
    if len(keys) != len(set(keys)):
        raise RuntimeError("Duplicate settings registry keys")
    if len(aliases) != len(set(aliases)):
        raise RuntimeError("Duplicate settings environment aliases")
    if any(item.secret != (item.value_type == Type.SECRET) for item in SETTINGS_REGISTRY):
        raise RuntimeError("Secret registry fields must use the secret value type")
    unknown_advanced = ADVANCED_SETTINGS - set(keys)
    if unknown_advanced or any(SETTINGS_BY_KEY[key].group != "ai" for key in ADVANCED_SETTINGS):
        raise RuntimeError(f"Invalid advanced settings: {sorted(unknown_advanced)}")
    if set(PLATFORM_EMBEDDINGS_PROVIDERS) != set(PLATFORMS):
        raise RuntimeError("Every platform needs its embeddings provider choices")
    for platform, overrides in PLATFORM_DEFAULTS.items():
        unknown = set(overrides) - set(keys)
        if platform not in PLATFORMS or unknown:
            raise RuntimeError(f"Invalid platform defaults for {platform}: {sorted(unknown)}")


validate_registry()
