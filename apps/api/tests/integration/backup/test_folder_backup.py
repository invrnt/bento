from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import select

from bento.adapters.backup.repositories import SQLiteBackupPolicyRepository
from bento.adapters.backup.watcher import WatchdogFolderWatcher
from bento.application.backup import ScanDebouncer
from bento.application.jobs import JobsUseCases
from bento.domain.assets import AssetMode
from bento.domain.backup import BackupFileState, BackupSourceState
from bento.domain.errors import SettingsSourceLockedError
from bento.domain.jobs import JobType
from bento.domain.storage import BlobKind, StorageBackend
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import AssetModel, BackupFileModel, FolderModel, JobModel, SettingModel
from bento.interfaces.worker.storage_pipeline import StoragePipelineLoop
from tests.integration.storage_pipeline.support import (
    JobRunner,
    RemoteSwitch,
    age,
    migrated_data_dir,
    pipeline_for,
    run,
    vault_remote_store,
)

JPEG = b"\xff\xd8\xff\xe0" + b"photo" * 50


def _components(tmp_path: Path, remote: RemoteSwitch | None = None):
    components = pipeline_for(migrated_data_dir(tmp_path), remote or RemoteSwitch(None), storage_backend="local")
    components.backup._settle_seconds = 0  # noqa: SLF001 - files in tests are written right before scanning
    return components


def _tree(root: Path) -> Path:
    (root / "viajes" / "2024").mkdir(parents=True)
    (root / ".cache").mkdir()
    (root / "playa.jpg").write_bytes(JPEG)
    (root / "viajes" / "2024" / "copia.jpg").write_bytes(JPEG)
    (root / "viajes" / "2024" / "itinerario.pdf").write_bytes(b"%PDF-1.4 plan")
    (root / "notas.txt").write_text("hola")
    (root / ".cache" / "x.txt").write_text("hidden")
    (root / "borrador.docx.tmp").write_text("temp")
    (root / "enlace.txt").symlink_to(root / "notas.txt")
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            age(path)
    return root


def _assets(components) -> list[AssetModel]:
    with session_scope(components.session_factory) as session:
        return list(session.scalars(select(AssetModel).order_by(AssetModel.filename)))


def _folder_path(components, folder_id: str | None) -> str:
    names = []
    with session_scope(components.session_factory) as session:
        while folder_id is not None:
            folder = session.get(FolderModel, folder_id)
            names.append(folder.name)
            folder_id = folder.parent_id
    return "/".join(reversed(names))


def _job_count(components, job_type: JobType, status: str = "queued") -> int:
    with session_scope(components.session_factory) as session:
        return len(
            list(session.scalars(select(JobModel).where(JobModel.type == job_type.value, JobModel.status == status)))
        )


def test_backup_scans_incrementally_and_files_photos_and_drive_folders(tmp_path: Path) -> None:
    async def scenario() -> None:
        components = _components(tmp_path)
        backup = components.backup
        root = _tree(tmp_path / "Fotos de Ana")

        source = await backup.add_source(str(root))
        assert source.label == "Fotos de Ana" and source.state == BackupSourceState.SCANNING
        await JobRunner(components).run_all()

        assets = _assets(components)
        assert [asset.filename for asset in assets] == ["itinerario.pdf", "notas.txt", "playa.jpg"]
        by_name = {asset.filename: asset for asset in assets}
        assert by_name["playa.jpg"].mode == AssetMode.PHOTOS.value and by_name["playa.jpg"].folder_id is None
        assert _folder_path(components, by_name["notas.txt"].folder_id) == "Respaldo/Fotos de Ana"
        assert _folder_path(components, by_name["itinerario.pdf"].folder_id) == "Respaldo/Fotos de Ana/viajes/2024"
        with session_scope(components.session_factory) as session:
            rows = {row.relative_path: row for row in session.scalars(select(BackupFileModel))}
        assert set(rows) == {"playa.jpg", "notas.txt", "viajes/2024/copia.jpg", "viajes/2024/itinerario.pdf"}
        assert rows["viajes/2024/copia.jpg"].asset_id == rows["playa.jpg"].asset_id  # sha256 dedupe
        assert {row.state for row in rows.values()} == {"done"}
        listed = (await backup.list_sources())[0]
        assert (listed.files_total, listed.files_done, listed.files_pending, listed.state) == (
            4,
            4,
            0,
            BackupSourceState.IDLE,
        )

        # Unchanged: nothing new is queued.
        summary = await backup.scan_source(source.id)
        assert summary.queued == 0 and _job_count(components, JobType.BACKUP_UPLOAD) == 0

        # Edited file → new asset; deleted file → row dropped, asset kept (one-way).
        (root / "notas.txt").write_text("hola de nuevo")
        age(root / "notas.txt", 60)
        (root / "playa.jpg").unlink()
        summary = await backup.scan_source(source.id)
        assert (summary.queued, summary.removed) == (1, 1)
        await JobRunner(components).run_all()
        names = [asset.filename for asset in _assets(components)]
        assert names.count("notas.txt") == 2 and "playa.jpg" in names

    run(scenario())


def test_watcher_paths_trigger_partial_scans(tmp_path: Path) -> None:
    async def scenario() -> None:
        components = _components(tmp_path)
        root = tmp_path / "Docs"
        root.mkdir()
        source = await components.backup.add_source(str(root))
        await JobRunner(components).run_all()

        (root / "nuevo").mkdir()
        (root / "nuevo" / "a.txt").write_text("a")
        (root / "b.txt").write_text("b")
        (root / ".oculto.txt").write_text("c")
        summary = await components.backup.scan_source(
            source.id, paths=(str(root / "nuevo"), str(root / "b.txt"), str(root / ".oculto.txt"), "/etc/passwd")
        )
        assert summary.queued == 2
        with session_scope(components.session_factory) as session:
            assert set(session.scalars(select(BackupFileModel.relative_path))) == {"nuevo/a.txt", "b.txt"}

        (root / "b.txt").unlink()
        summary = await components.backup.scan_source(source.id, paths=(str(root / "b.txt"),))
        assert summary.removed == 1

    run(scenario())


def test_policy_pause_battery_and_bandwidth_apply_live(tmp_path: Path) -> None:
    async def scenario() -> None:
        components = _components(tmp_path)
        backup = components.backup
        root = _tree(tmp_path / "Fotos")
        source = await backup.add_source(str(root))

        policy = await backup.update_policy(paused=True)
        assert policy.paused and policy.effective_paused
        assert (await backup.scan_source(source.id)).skipped
        assert (await backup.get_source(source.id)).state == BackupSourceState.PAUSED

        await backup.update_policy(paused=False, bandwidth_limit_kbps=512)
        assert _job_count(components, JobType.BACKUP_SCAN) >= 1
        with session_scope(components.session_factory) as session:
            assert session.get(SettingModel, "backup_bandwidth_limit_kbps").value == "512"

        on_battery = await backup.set_power(on_battery=True)
        assert on_battery.on_battery and on_battery.pause_on_battery and on_battery.effective_paused
        assert await backup.upload_pending() == 0
        await backup.update_policy(pause_on_battery=False)
        assert not (await backup.get_policy()).effective_paused
        with session_scope(components.session_factory) as session:
            assert session.get(SettingModel, "backup_pause_on_battery").value == "false"

        # Live: another process changing the setting is seen on the next read.
        with session_scope(components.session_factory) as session:
            session.get(SettingModel, "backup_bandwidth_limit_kbps").value = "64"
        assert (await backup.get_policy()).bandwidth_limit_kbps == 64

        locked = SQLiteBackupPolicyRepository(
            components.session_factory, components.clock, locked={"backup_bandwidth_limit_kbps": 100}
        )
        assert (await locked.get()).bandwidth_limit_kbps == 100
        with pytest.raises(SettingsSourceLockedError):
            await locked.save((await locked.get()).__class__(bandwidth_limit_kbps=5))

    run(scenario())


def test_backup_sourced_originals_drop_the_local_copy_and_serve_the_source(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = await vault_remote_store(tmp_path)
        components = _components(tmp_path, RemoteSwitch(store))
        root = tmp_path / "Docs"
        root.mkdir()
        original = root / "contrato.pdf"
        original.write_bytes(b"%PDF-1.4 contrato firmado")
        age(original)
        await components.backup.add_source(str(root))
        await JobRunner(components).run_all()

        [asset] = _assets(components)
        ref = await components.blob_refs.latest_for_asset(asset.id, BlobKind.ORIGINAL)
        assert ref.backend == StorageBackend.TELEGRAM
        assert list((components.data_dir / "uploads" / "blobs" / "original").rglob("*.*")) == []
        assert not any(path.is_file() for path in (components.data_dir / "uploads" / "blobs" / "original").rglob("*"))
        assert await components.cache.lookup(ref.id) is None

        assert await components.content.materialize_original(asset.id) == original
        assert components.resolver.resolve(ref) == original
        assert store.downloads == []

        original.write_bytes(b"%PDF-1.4 contrato editado!")
        assert await components.content.local_path(ref) is None
        fetched = await components.content.materialize_original(asset.id)
        assert fetched.read_bytes() == b"%PDF-1.4 contrato firmado"
        assert store.downloads == [ref.id]

    run(scenario())


def test_failed_files_are_retryable_through_a_parked_scan_job(tmp_path: Path) -> None:
    async def scenario() -> None:
        components = _components(tmp_path)
        root = tmp_path / "Docs"
        root.mkdir()
        (root / "a.txt").write_text("a")
        age(root / "a.txt")
        source = await components.backup.add_source(str(root))
        ingestion = components.backup._ingestion  # noqa: SLF001

        class Broken:
            async def upload_file(self, file):  # type: ignore[no-untyped-def]
                raise OSError("disk full")

        components.backup._ingestion = Broken()  # noqa: SLF001
        await JobRunner(components).run_all()
        with session_scope(components.session_factory) as session:
            assert session.get(BackupFileModel, (source.id, "a.txt")).state == BackupFileState.FAILED.value

        activity = await components.activity.current()
        [item] = activity.attention
        assert item.kind.value == "upload_failed" and item.action.value == "retry"
        assert item.params["source_id"] == source.id and item.params["count"] == 1

        components.backup._ingestion = ingestion  # noqa: SLF001
        await JobsUseCases(jobs=components.jobs, clock=components.clock).retry_failed_job(item.params["job_id"])
        await JobRunner(components).run_all()
        with session_scope(components.session_factory) as session:
            assert session.get(BackupFileModel, (source.id, "a.txt")).state == BackupFileState.DONE.value
        assert (await components.activity.current()).attention == ()

    run(scenario())


def test_sources_crud_never_deletes_backed_up_assets(tmp_path: Path) -> None:
    async def scenario() -> None:
        components = _components(tmp_path)
        root = _tree(tmp_path / "Fotos")
        source = await components.backup.add_source(str(root), label="Mis fotos")
        await JobRunner(components).run_all()

        renamed = await components.backup.update_source(source.id, label=" Viajes / 2024 ", enabled=False)
        assert renamed.label == "Viajes 2024" and not renamed.enabled and renamed.state == BackupSourceState.PAUSED
        await components.backup.remove_source(source.id)
        assert await components.backup.list_sources() == ()
        assert len(_assets(components)) == 3

    run(scenario())


class FakeWatcher:
    def __init__(self) -> None:
        self.watches: dict[str, tuple[str, object]] = {}
        self.stopped = False

    def watch(self, source_id, path, on_change):  # type: ignore[no-untyped-def]
        self.watches[source_id] = (path, on_change)

    def unwatch(self, source_id):  # type: ignore[no-untyped-def]
        self.watches.pop(source_id, None)

    def stop(self) -> None:
        self.stopped = True


def test_housekeeping_loop_watches_sources_and_debounces_events_into_scans(tmp_path: Path) -> None:
    async def scenario() -> None:
        components = _components(tmp_path)
        root = tmp_path / "Docs"
        root.mkdir()
        source = await components.backup.add_source(str(root))
        await JobRunner(components).run_all()
        now = [100.0]
        watcher = FakeWatcher()
        loop = StoragePipelineLoop(
            components,
            watcher=watcher,
            debouncer=ScanDebouncer(clock=lambda: now[0]),
            clock=lambda: now[0],
        )

        await loop.tick()
        assert watcher.watches[source.id][0] == source.path
        scans_before = _job_count(components, JobType.BACKUP_SCAN)
        on_change = watcher.watches[source.id][1]
        on_change(source.id, str(root / "a.txt"))
        now[0] += 1
        on_change(source.id, str(root / "b.txt"))
        now[0] += 1.5
        await loop.tick()
        assert _job_count(components, JobType.BACKUP_SCAN) == scans_before
        now[0] += 1
        await loop.tick()
        with session_scope(components.session_factory) as session:
            scan = session.scalars(
                select(JobModel).where(JobModel.type == "backup_scan").order_by(JobModel.created_at.desc())
            ).first()
        assert scan.payload_json["paths"] == [str(root / "a.txt"), str(root / "b.txt")]
        assert _job_count(components, JobType.TRASH_PURGE) == 1

        await components.backup.update_source(source.id, enabled=False)
        now[0] += 31
        await loop.tick()
        assert watcher.watches == {}

    run(scenario())


def test_watchdog_handler_filters_ignored_paths(tmp_path: Path) -> None:
    class Observer:
        def __init__(self) -> None:
            self.handlers = []
            self.daemon = False

        def start(self) -> None: ...

        def schedule(self, handler, path, recursive=False):  # type: ignore[no-untyped-def]
            self.handlers.append((handler, path, recursive))
            return object()

        def unschedule(self, watch) -> None: ...  # type: ignore[no-untyped-def]

        def stop(self) -> None: ...

        def join(self, timeout=None) -> None: ...  # type: ignore[no-untyped-def]

    class Event:
        def __init__(self, event_type: str, src: str, dest: str = "") -> None:
            self.event_type, self.src_path, self.dest_path = event_type, src, dest

    observer = Observer()
    seen: list[tuple[str, str]] = []
    watcher = WatchdogFolderWatcher(observer_factory=lambda: observer)
    watcher.watch("s1", str(tmp_path), lambda source, path: seen.append((source, path)))
    handler, path, recursive = observer.handlers[0]
    assert path == str(tmp_path) and recursive
    handler.dispatch(Event("modified", os.fsencode(str(tmp_path / "a.jpg"))))
    handler.dispatch(Event("opened", str(tmp_path / "b.jpg")))
    handler.dispatch(Event("created", str(tmp_path / ".DS_Store")))
    handler.dispatch(Event("moved", str(tmp_path / "x.part"), str(tmp_path / "x.mp4")))
    assert seen == [("s1", str(tmp_path / "a.jpg")), ("s1", str(tmp_path / "x.mp4"))]
    watcher.stop()


def test_unwatchable_folders_are_retried_and_errored_sources_rescanned(tmp_path: Path) -> None:
    async def scenario() -> None:
        components = _components(tmp_path)
        root = tmp_path / "USB"
        root.mkdir()
        source = await components.backup.add_source(str(root))
        await JobRunner(components).run_all()

        class FlakyWatcher(FakeWatcher):
            calls = 0

            def watch(self, source_id, path, on_change):  # type: ignore[no-untyped-def]
                FlakyWatcher.calls += 1
                if FlakyWatcher.calls == 1:
                    raise OSError("inotify watch limit reached")
                super().watch(source_id, path, on_change)

        now = [0.0]
        watcher = FlakyWatcher()
        loop = StoragePipelineLoop(components, watcher=watcher, clock=lambda: now[0])
        await loop.tick()
        assert watcher.watches == {}
        now[0] += 31
        await loop.tick()
        assert source.id in watcher.watches
        await JobRunner(components).run_all()  # the startup full scan

        root.rename(tmp_path / "USB-unplugged")
        await components.backup.scan_source(source.id)
        assert (await components.backup.get_source(source.id)).state == BackupSourceState.ERROR
        (tmp_path / "USB-unplugged").rename(root)
        scans = _job_count(components, JobType.BACKUP_SCAN)
        now[0] += 301
        await loop.tick()
        assert _job_count(components, JobType.BACKUP_SCAN) == scans + 1
        await JobRunner(components).run_all()
        assert (await components.backup.get_source(source.id)).state == BackupSourceState.IDLE

    run(scenario())
