"""Process-wide service factories shared by Telegram-first features.

Each factory is implemented by the stage agent that owns the service (see
`orchestration/execution/telegram-first-program.md`). Callers depend on the returned
ports only, so features can be wired before every implementation lands.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from bento.adapters.android.host import AndroidHost
    from bento.application.indexing.ocr import PDFPageRendererPort
    from bento.application.media.service import MediaGeneratorPort
    from bento.domain.device import DeviceConditions, JobDeferral
    from bento.ports.backup import BackupSuggestionsPort, FolderWatcherPort, MediaLibraryPort
    from bento.ports.device import ContentImportsPort, DeviceConditionsPort, NotifierPort
    from bento.ports.providers import OCRProviderPort, TextExtractorPort
    from bento.infrastructure.settings import Settings
    from bento.ports.blob_store import RemoteBlobStorePort
    from bento.ports.content import AssetContentPort
    from bento.ports.key_store import KeyStorePort
    from bento.ports.security import BlobCipherPort, PairingCryptoFactoryPort, VaultCryptoPort
    from bento.ports.sync import SyncStatusProviderPort
    from bento.ports.vault import VaultSessionPort


class JobEligibilitySource(Protocol):
    def current(self) -> JobDeferral: ...

    def conditions(self) -> DeviceConditions: ...


def get_key_store(settings: Settings) -> KeyStorePort:
    """Owner: vault-crypto (Stage 14) / mtproto wiring (Stage 15). `<data_dir>/secure`, cached per data dir."""
    from bento.infrastructure.mtproto import wiring

    return wiring.key_store(settings)


def get_vault_crypto() -> VaultCryptoPort:
    from bento.infrastructure.mtproto import wiring

    return wiring.vault_crypto()


def get_blob_cipher() -> BlobCipherPort:
    from bento.infrastructure.mtproto import wiring

    return wiring.blob_cipher()


def get_pairing_crypto() -> PairingCryptoFactoryPort:
    from bento.infrastructure.mtproto import wiring

    return wiring.pairing_crypto()


def get_vault_session(settings: Settings) -> VaultSessionPort:
    """Owner: mtproto agent. Cached per process; never raises (local mode reports `local_only`)."""
    from bento.infrastructure.mtproto import wiring

    return wiring.vault_session(settings)


def get_remote_blob_store(settings: Settings) -> RemoteBlobStorePort | None:
    """Owner: mtproto agent. None when the vault is not ready on this device."""
    from bento.infrastructure.mtproto import wiring

    return wiring.remote_blob_store(settings)


def get_asset_content(settings: Settings) -> AssetContentPort:
    """Owner: storage-pipeline (backup) agent."""
    from bento.infrastructure.storage_pipeline import get_storage_pipeline

    return get_storage_pipeline(settings).content


_sync_status_lock = threading.Lock()
_sync_status_providers: dict[tuple[str, str], SyncStatusProviderPort] = {}


def get_sync_status_provider(settings: Settings) -> SyncStatusProviderPort:
    """Owner: sync agent. Reads only the local sync state the worker loop persists (no Telegram calls);
    reports `disabled` for local storage. `request_sync()` writes the cross-process "sync now" marker."""
    from bento.adapters.sync import SQLiteSyncOutbox, SQLiteSyncStateStore
    from bento.application.sync import SyncStatusService
    from bento.infrastructure.db.clock import SystemClock
    from bento.infrastructure.db.engine import create_app_session_factory
    from bento.infrastructure.settings import settings_database_path

    key = (settings.storage_backend, str(settings_database_path(settings).resolve()))
    with _sync_status_lock:
        provider = _sync_status_providers.get(key)
        if provider is None:
            factory = create_app_session_factory(settings)
            provider = SyncStatusService(
                enabled=settings.storage_backend != "local",
                state=SQLiteSyncStateStore(factory),
                outbox=SQLiteSyncOutbox(factory),
                clock=SystemClock(),
            )
            _sync_status_providers[key] = provider
        return provider


def reset_services() -> None:
    """Drop cached instances (tests, account reloads). Each owner clears its own caches here."""
    from bento.infrastructure.mtproto import wiring
    from bento.infrastructure.storage_pipeline import reset_storage_pipeline

    wiring.reset()
    reset_storage_pipeline()
    with _sync_status_lock:
        _sync_status_providers.clear()
    with _host_lock:
        _eligibility.clear()


# Host devices (Android wiring) ---------------------------------------------------------------------------
# Desktop/headless get permissive conditions, a no-op notifier, and the Pillow/ffmpeg/pypdfium2/RapidOCR/watchdog
# adapters. `install_android_host` (called by `interfaces.android.engine.configure`) swaps in the bridge adapters
# for settings with `platform == "android"`. Nothing else in the backend branches on the platform.

_host_lock = threading.Lock()
_android_host: AndroidHost | None = None
_eligibility: dict[str, JobEligibilitySource] = {}


def install_android_host(host: AndroidHost | None) -> None:
    global _android_host
    with _host_lock:
        _android_host = host
        _eligibility.clear()


def android_host(settings: Settings) -> AndroidHost | None:
    with _host_lock:
        return _android_host if settings.platform == "android" else None


def get_device_conditions(settings: Settings) -> DeviceConditionsPort:
    host = android_host(settings)
    if host is not None and host.conditions is not None:
        return host.conditions
    from bento.adapters.device import PermissiveDeviceConditions

    return PermissiveDeviceConditions()


def get_notifier(settings: Settings) -> NotifierPort:
    host = android_host(settings)
    if host is not None and host.notifier is not None:
        return host.notifier
    from bento.adapters.device import NullNotifier

    return NullNotifier()


def get_content_imports(settings: Settings) -> ContentImportsPort:
    host = android_host(settings)
    if host is not None and host.content_imports is not None:
        return host.content_imports
    from bento.adapters.device import UnavailableContentImports

    return UnavailableContentImports()


def get_media_library(settings: Settings) -> MediaLibraryPort | None:
    """The phone's MediaStore (Android only); None elsewhere, where backup sources are folders."""
    host = android_host(settings)
    return host.media_library if host is not None else None


def get_backup_suggestions(settings: Settings) -> BackupSuggestionsPort:
    host = android_host(settings)
    if host is not None and host.suggestions is not None:
        return host.suggestions
    from bento.adapters.backup.suggestions import OsBackupSuggestions

    return OsBackupSuggestions()


def get_folder_watcher(settings: Settings) -> FolderWatcherPort:
    host = android_host(settings)
    if host is not None:
        return host.watcher
    from bento.adapters.backup.watcher import WatchdogFolderWatcher

    return WatchdogFolderWatcher()


def get_media_generator(settings: Settings, cache_dir: Path) -> MediaGeneratorPort:
    from bento.adapters.media import LocalMediaGenerator

    host = android_host(settings)
    if host is not None and host.bridge("media_tools") is not None:
        from bento.adapters.android.media_tools import BridgeMediaGenerator

        return BridgeMediaGenerator(host.bridge("media_tools"), cache_dir, fallback=LocalMediaGenerator(cache_dir))
    return LocalMediaGenerator(cache_dir)


def get_pdf_page_renderer(settings: Settings, output_dir: Path) -> PDFPageRendererPort:
    host = android_host(settings)
    if host is not None and host.bridge("media_tools") is not None:
        from bento.adapters.android.media_tools import BridgePDFPageRenderer

        return BridgePDFPageRenderer(host.bridge("media_tools"), output_dir)
    from bento.adapters.ocr import Pypdfium2PDFPageRenderer

    return Pypdfium2PDFPageRenderer(output_dir)


def get_text_extractor(settings: Settings) -> TextExtractorPort:
    """Plain text everywhere; PDF text layers where pypdfium2 is installed (desktop, Docker). The Android engine
    does not bundle pypdfium2, so PDFs there are only indexed by OCR (ML Kit), as before."""
    from bento.adapters.text import CompositeTextExtractor, PlainTextExtractor

    extractors: list[TextExtractorPort] = [PlainTextExtractor()]
    if android_host(settings) is None and _pypdfium2_available():
        from bento.adapters.text import Pypdfium2TextLayerExtractor

        extractors.append(Pypdfium2TextLayerExtractor())
    return CompositeTextExtractor(extractors)


def _pypdfium2_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("pypdfium2") is not None


def get_ocr_provider(settings: Settings) -> OCRProviderPort:
    from bento.adapters.ocr import DisabledOCRAdapter, MockOCRAdapter

    if settings.ocr_provider == "rapidocr":
        from bento.adapters.ocr import RapidOCRAdapter

        return RapidOCRAdapter()
    if settings.ocr_provider == "mock":
        return MockOCRAdapter()
    if settings.ocr_provider == "mlkit":
        host = android_host(settings)
        if host is not None and host.bridge("ocr") is not None:
            from bento.adapters.android.ocr_mlkit import MLKitOCRAdapter

            return MLKitOCRAdapter(host.bridge("ocr"))
    return DisabledOCRAdapter()


def get_job_eligibility(settings: Settings) -> JobEligibilitySource:
    """Which job classes device conditions hold back right now (always nothing on desktop/headless)."""
    host = android_host(settings)
    if host is None or host.conditions is None:
        from bento.application.jobs import AlwaysEligible

        return AlwaysEligible()
    from bento.adapters.device_state import SQLiteDevicePolicySource, SQLiteRunNowState
    from bento.application.jobs import JobEligibility
    from bento.infrastructure.db.clock import SystemClock
    from bento.infrastructure.db.engine import create_app_session_factory
    from bento.infrastructure.settings import settings_database_path

    key = str(settings_database_path(settings).resolve())
    with _host_lock:
        cached = _eligibility.get(key)
        if cached is None:
            factory = create_app_session_factory(settings)
            cached = JobEligibility(
                conditions=host.conditions,
                policy=SQLiteDevicePolicySource(factory, platform=settings.platform),
                run_now=SQLiteRunNowState(factory, SystemClock()),
            )
            _eligibility[key] = cached
        return cached
