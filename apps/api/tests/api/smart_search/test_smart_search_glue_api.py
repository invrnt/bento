"""Smart search glue over HTTP: settings schema flags, `GET /api/settings` folding, "Usar ya", the onboarding
suggestion and update progress (`orchestration/api/smart-search-contract.md`)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bento.adapters.settings import SQLiteSettingsRepository
from bento.application.settings import EditableSettingsService
from bento.application.smart_search.activation import DownloadJobResult, InstallState, ModelInstallRecord
from bento.application.smart_search.reembed import EmbeddingSpaceState, ReembedService
from bento.application.storage_maintenance import StorageMaintenanceStatus, StorageReclaimResult
from bento.domain.assets import Asset
from bento.domain.jobs import JobType
from bento.domain.settings_registry import EMBEDDINGS_PROVIDER_CHOICES, SMART_SEARCH_MODEL_IDS
from bento.domain.smart_search import EmbeddingSpace, SmartSearchState, SmartSearchStatus, space_id_for
from bento.infrastructure.db.clock import SystemClock
from bento.infrastructure.settings import Settings
from bento.interfaces.http import host_resources as host_resources_module
from bento.interfaces.http.host_resources import HostResources, physical_ram_bytes
from bento.interfaces.http.main import create_app
from bento.interfaces.http.routes import StorageMaintenanceDependencies
from tests.fakes.model_host import BLOB_SIZE, FakeModelHost, running_model_host
from tests.integration.db.support import migrated_session_factory
from tests.unit.models.model_fakes import DEFAULT_MODEL_ID, ServiceKit, files_under, make_kit, tiny_catalog, tiny_spec

GIB = 1024**3
OLD_REVISION = "aaaaaaa1"
NEW_REVISION = "bbbbbbb2"


@pytest.fixture
def host() -> Iterator[FakeModelHost]:
    with running_model_host() as server:
        yield server


# ------------------------------------------------------------------------------------------
# Fakes


@dataclass
class FakeSpaces:
    """`embedding_spaces` with the adapter's flip rule: one active space, the previous one retired."""

    states: dict[str, EmbeddingSpaceState] = field(default_factory=dict)
    registered: list[str] = field(default_factory=list)

    async def space_state(self, space_id: str) -> EmbeddingSpaceState | None:
        return self.states.get(space_id)

    async def register_space(self, space: EmbeddingSpace) -> None:
        self.registered.append(space.id)
        if self.states.get(space.id) in {None, EmbeddingSpaceState.RETIRED}:
            self.states[space.id] = EmbeddingSpaceState.BUILDING

    async def active_space_id(self) -> str | None:
        return next((key for key, state in self.states.items() if state is EmbeddingSpaceState.ACTIVE), None)

    async def activate_space(self, space_id: str) -> tuple[str, ...]:
        if self.states.get(space_id) is EmbeddingSpaceState.ACTIVE:
            return ()
        previous = tuple(key for key, state in self.states.items() if state is EmbeddingSpaceState.ACTIVE)
        for key in previous:
            self.states[key] = EmbeddingSpaceState.RETIRED
        self.states[space_id] = EmbeddingSpaceState.ACTIVE
        return previous


class NoAssets:
    async def list_live(self, *, after_id: str | None = None, limit: int = 200) -> tuple[Asset, ...]:
        return ()


class NoVectors:
    async def assets_with_vectors(self, space_id: str, asset_ids: Any) -> frozenset[str]:
        return frozenset()


class NoActiveJobs:
    async def has_active(
        self, asset_id: str, *, types: frozenset[JobType], exclude_job_id: str | None = None
    ) -> bool:
        return False


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


@dataclass
class FakeStorageMaintenance:
    async def status(self) -> StorageMaintenanceStatus:
        return StorageMaintenanceStatus(
            connection_state="connected",
            can_reclaim=False,
            fully_remote=False,
            reclaimable_bytes=0,
            reclaimable_files=0,
            local_blob_count=0,
            telegram_blob_count=0,
        )

    async def reclaim(self) -> StorageReclaimResult:  # pragma: no cover - not used here
        raise AssertionError("not used")


def wire_blue_green(kit: ServiceKit) -> tuple[FakeSpaces, ReembedService]:
    spaces = FakeSpaces()
    reembed = ReembedService(
        assets=NoAssets(),
        spaces=spaces,
        vectors=NoVectors(),
        jobs=kit.jobs,  # type: ignore[arg-type]
        active=NoActiveJobs(),
        clock=FixedClock(),
    )
    kit.service.spaces = spaces
    kit.service.reembed = reembed
    return spaces, reembed


def smart_search_client(tmp_path: Path, kit: ServiceKit, **settings: Any) -> TestClient:
    app = create_app(Settings(data_dir=str(tmp_path / "data"), storage_backend="local", **settings))
    app.state.smart_search_activation = kit.service
    app.state.storage_maintenance_dependencies = StorageMaintenanceDependencies(service=FakeStorageMaintenance())
    return TestClient(app)


def settings_client(tmp_path: Path, environ: dict[str, str] | None = None) -> TestClient:
    data_dir = tmp_path / "data"
    database_dir = data_dir / "db"
    database_dir.mkdir(parents=True)
    repository = SQLiteSettingsRepository(migrated_session_factory(database_dir), SystemClock())
    app = create_app(Settings(data_dir=str(data_dir)))
    app.state.editable_settings_service = EditableSettingsService(
        repository=repository, environ=environ or {}, runtime_mode="headless"
    )
    return TestClient(app)


def schema_fields(client: TestClient) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    response = client.get("/api/settings/schema")
    assert response.status_code == 200
    body = response.json()
    return body, {item["key"]: item for item in body["fields"]}


def install_old_revision(kit: ServiceKit, host: FakeModelHost) -> Path:
    """The installed (older) revision: its weights on disk, its install row, the status `ready` in its space."""
    old = tiny_spec(host.blob, revision=OLD_REVISION)
    weights = kit.store.path_for(old, old.weights)
    weights.parent.mkdir(parents=True, exist_ok=True)
    weights.write_bytes(host.blob)
    record = ModelInstallRecord(
        model_id=old.model_id,
        revision=old.revision,
        file=old.weights.name,
        bytes_total=BLOB_SIZE,
        bytes_done=BLOB_SIZE,
        sha256=old.weights.sha256,
        state=InstallState.INSTALLED,
    )
    asyncio.run(kit.repository.save_install(record))
    kit.repository.status = SmartSearchStatus(
        state=SmartSearchState.READY,
        space_id=space_id_for(DEFAULT_MODEL_ID, OLD_REVISION, 512),
        bytes_done=BLOB_SIZE,
        bytes_total=BLOB_SIZE,
    )
    return weights


# ------------------------------------------------------------------------------------------
# 1. Settings schema


def test_schema_flags_advanced_fields_and_offers_every_provider_on_desktop(tmp_path: Path) -> None:
    body, fields = schema_fields(settings_client(tmp_path))

    assert body["platform"] == "auto"
    assert all(isinstance(item["advanced"], bool) and isinstance(item["hidden"], bool) for item in body["fields"])
    for key in ("custom_model_path", "custom_pooling", "embedding_dimensions", "llama_server_path", "embedding_server_url"):
        assert fields[key]["advanced"] is True, key
        assert fields[key]["group"] == "ai"
    for key in ("embeddings_provider", "smart_search_model", "ocr_provider", "worker_concurrency"):
        assert fields[key]["advanced"] is False, key
    assert fields["embeddings_provider"]["constraints"]["choices"] == list(EMBEDDINGS_PROVIDER_CHOICES)
    assert fields["smart_search_model"]["constraints"]["choices"] == list(SMART_SEARCH_MODEL_IDS)
    assert fields["smart_search_model"]["hidden"] is (len(SMART_SEARCH_MODEL_IDS) <= 1)
    assert fields["ocr_provider"]["constraints"]["choices"] == ["disabled", "mock", "rapidocr", "mlkit"]
    assert not any(item["hidden"] for key, item in fields.items() if key != "smart_search_model")


def test_schema_on_android_offers_no_managed_search(tmp_path: Path) -> None:
    body, fields = schema_fields(settings_client(tmp_path, {"BENTO_PLATFORM": "android"}))

    assert body["platform"] == "android"
    assert fields["embeddings_provider"]["constraints"]["choices"] == ["disabled", "custom", "mock"]
    assert fields["smart_search_model"]["constraints"]["choices"] == []
    assert fields["smart_search_model"]["hidden"] is True
    assert fields["embeddings_provider"]["default"] == "disabled"


def test_default_settings_service_validates_against_the_packaged_manifest(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "db").mkdir(parents=True)
    migrated_session_factory(data_dir / "db")
    app = create_app(Settings(data_dir=str(data_dir)))
    client = TestClient(app)

    result = client.post(
        "/api/settings/validate",
        json={"values": {"embeddings_provider": "managed", "embedding_dimensions": 300}},
    ).json()

    assert app.state.editable_settings_service._model_catalog is not None
    assert result["valid"] is False
    assert {"key": "embedding_dimensions", "code": "invalid_model_spec"} in [
        {"key": issue["key"], "code": issue["code"]} for issue in result["errors"]
    ]
    ok = client.post("/api/settings/validate", json={"values": {"embeddings_provider": "managed", "embedding_dimensions": 256}})
    assert ok.json()["valid"] is True


# ------------------------------------------------------------------------------------------
# 2. GET /api/settings


def test_public_settings_fold_the_managed_status_and_verified_install(tmp_path: Path, host: FakeModelHost) -> None:
    kit = make_kit(tmp_path, host)
    client = smart_search_client(tmp_path, kit, embeddings_provider="managed")
    space_id = kit.spec.space().id

    def public() -> tuple[str, bool]:
        body = client.get("/api/settings").json()
        return body["embeddings_state"], body["model_available"]

    assert public() == ("disabled", False)
    client.post("/api/smart-search/activate")
    assert public() == ("pending", False)
    assert asyncio.run(kit.run_last_job()) is DownloadJobResult.STARTING
    assert public() == ("pending", True)
    asyncio.run(kit.service.runtime_ready(space_id))
    assert public() == ("pending", True)
    asyncio.run(kit.service.indexed(space_id))
    assert public() == ("ready", True)
    asyncio.run(kit.service.runtime_failed(space_id))
    assert public() == ("failed", True)
    client.delete("/api/smart-search/model")
    assert public() == ("disabled", False)


def test_public_settings_check_the_custom_model_path(tmp_path: Path, host: FakeModelHost) -> None:
    model = tmp_path / "own-model.gguf"
    model.write_bytes(b"GGUF")
    kit = make_kit(tmp_path, host)

    present = smart_search_client(tmp_path, kit, embeddings_provider="custom", custom_model_path=str(model))
    body = present.get("/api/settings").json()
    assert (body["embeddings_state"], body["model_available"]) == ("ready", True)

    missing = smart_search_client(
        tmp_path, kit, embeddings_provider="custom", custom_model_path=str(tmp_path / "missing.gguf")
    )
    body = missing.get("/api/settings").json()
    assert (body["embeddings_state"], body["model_available"]) == ("pending", False)

    disabled = smart_search_client(tmp_path, kit).get("/api/settings").json()
    assert (disabled["embeddings_state"], disabled["model_available"], disabled["embeddings_enabled"]) == (
        "disabled",
        False,
        False,
    )


# ------------------------------------------------------------------------------------------
# 3 + 7. Update progress, blue/green and "Usar ya"


def test_update_progress_then_use_now_switches_search_to_the_new_space(tmp_path: Path, host: FakeModelHost) -> None:
    kit = make_kit(tmp_path, host, catalog=tiny_catalog(host.blob, revision=NEW_REVISION))
    spaces, _ = wire_blue_green(kit)
    old_weights = install_old_revision(kit, host)
    old_space = space_id_for(DEFAULT_MODEL_ID, OLD_REVISION, 512)
    new_space = space_id_for(DEFAULT_MODEL_ID, NEW_REVISION, 512)
    spaces.states[old_space] = EmbeddingSpaceState.ACTIVE
    client = smart_search_client(tmp_path, kit)

    before = client.get("/api/smart-search").json()
    assert before["state"] == "ready"
    assert before["update_available"] == {"revision": NEW_REVISION, "size_bytes": BLOB_SIZE, "progress": None}
    assert before["can_use_now"] is False
    refused = client.post("/api/smart-search/use-now")
    assert refused.status_code == 409
    assert refused.json()["error"]["details"] == {"state": "ready", "event": "use_now"}

    started = client.post("/api/smart-search/update").json()
    assert started["state"] == "ready"
    assert started["update_available"]["progress"] == {"bytes_done": 0, "bytes_total": BLOB_SIZE, "state": "downloading"}

    assert asyncio.run(kit.run_last_job()) is DownloadJobResult.UPDATE_READY
    ready = client.get("/api/smart-search").json()
    assert (ready["state"], ready["space_id"], ready["search_available"]) == ("ready", old_space, True)
    assert ready["update_available"]["progress"] == {
        "bytes_done": BLOB_SIZE,
        "bytes_total": BLOB_SIZE,
        "state": "installed",
    }
    assert spaces.registered == [new_space]
    assert spaces.states[new_space] is EmbeddingSpaceState.BUILDING
    assert kit.jobs.jobs[-1].type is JobType.REEMBED
    assert kit.jobs.jobs[-1].payload == {"space_id": new_space, "phase": "queue"}
    assert ready["can_use_now"] is True

    flipped = client.post("/api/smart-search/use-now")
    assert flipped.status_code == 200
    body = flipped.json()
    assert (body["state"], body["space_id"], body["search_available"]) == ("ready", new_space, True)
    assert body["update_available"] is None
    assert body["can_use_now"] is False
    assert body["download"] == {"bytes_done": BLOB_SIZE, "bytes_total": BLOB_SIZE}
    assert spaces.states == {old_space: EmbeddingSpaceState.RETIRED, new_space: EmbeddingSpaceState.ACTIVE}
    assert not old_weights.exists()
    assert files_under(old_weights.parent) == []
    assert [record.revision for record in asyncio.run(kit.repository.installs())] == [NEW_REVISION]
    new_spec = tiny_spec(host.blob, revision=NEW_REVISION)
    assert kit.store.path_for(new_spec, new_spec.weights).is_file()

    again = client.post("/api/smart-search/use-now")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "smart_search_state_conflict"


def test_use_now_needs_a_building_space_and_a_reembed_owner(tmp_path: Path, host: FakeModelHost) -> None:
    kit = make_kit(tmp_path, host)
    kit.repository.status = SmartSearchStatus(state=SmartSearchState.READY, space_id=kit.spec.space().id)
    client = smart_search_client(tmp_path, kit)

    # No re-embed owner wired: never offered.
    assert client.get("/api/smart-search").json()["can_use_now"] is False
    assert client.post("/api/smart-search/use-now").status_code == 409

    spaces, _ = wire_blue_green(kit)
    spaces.states[kit.spec.space().id] = EmbeddingSpaceState.ACTIVE
    assert client.get("/api/smart-search").json()["can_use_now"] is False
    assert client.post("/api/smart-search/use-now").status_code == 409

    # The status's own space is still building while an older (legacy) space serves search.
    spaces.states = {"legacy:mock/512": EmbeddingSpaceState.ACTIVE, kit.spec.space().id: EmbeddingSpaceState.BUILDING}
    assert client.get("/api/smart-search").json()["can_use_now"] is True
    flipped = client.post("/api/smart-search/use-now").json()
    assert flipped["space_id"] == kit.spec.space().id
    assert flipped["can_use_now"] is False
    assert spaces.states[kit.spec.space().id] is EmbeddingSpaceState.ACTIVE


def test_use_now_is_not_offered_while_search_is_unavailable(tmp_path: Path, host: FakeModelHost) -> None:
    kit = make_kit(tmp_path, host)
    spaces, _ = wire_blue_green(kit)
    spaces.states = {kit.spec.space().id: EmbeddingSpaceState.BUILDING}
    kit.repository.status = SmartSearchStatus(state=SmartSearchState.STARTING, space_id=kit.spec.space().id)
    client = smart_search_client(tmp_path, kit)

    assert client.get("/api/smart-search").json()["can_use_now"] is False
    response = client.post("/api/smart-search/use-now")
    assert response.status_code == 409
    assert response.json()["error"]["details"] == {"state": "starting", "event": "use_now"}


# ------------------------------------------------------------------------------------------
# 4. Onboarding suggestion (D8)


@pytest.mark.parametrize(
    ("resources", "expected"),
    [
        ((4, 8 * GIB), True),
        ((16, 32 * GIB), True),
        ((3, 32 * GIB), False),
        ((8, 8 * GIB - 1), False),
        ((0, 0), False),
    ],
)
def test_onboarding_suggestion_follows_the_host_thresholds(
    tmp_path: Path, host: FakeModelHost, resources: tuple[int, int], expected: bool
) -> None:
    kit = make_kit(tmp_path, host)
    kit.service.host_resources = lambda: resources
    client = smart_search_client(tmp_path, kit)

    assert client.get("/api/smart-search").json()["suggest_in_onboarding"] is expected


def test_onboarding_suggestion_only_while_off_unlocked_and_not_android(tmp_path: Path, host: FakeModelHost) -> None:
    kit = make_kit(tmp_path, host)
    client = smart_search_client(tmp_path, kit)

    assert client.get("/api/smart-search").json()["suggest_in_onboarding"] is False  # no host probe wired
    kit.service.host_resources = lambda: (8, 16 * GIB)
    assert client.get("/api/smart-search").json()["suggest_in_onboarding"] is True

    kit.service.platform = "android"
    assert client.get("/api/smart-search").json()["suggest_in_onboarding"] is False
    kit.service.platform = "auto"

    kit.switch.is_locked = True
    assert client.get("/api/smart-search").json()["suggest_in_onboarding"] is False
    kit.switch.is_locked = False

    activated = client.post("/api/smart-search/activate").json()
    assert activated["state"] == "downloading"
    assert activated["suggest_in_onboarding"] is False


def test_default_wiring_reads_this_machine_and_the_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(host_resources_module, "host_resources", lambda: HostResources(cpu_cores=8, ram_bytes=16 * GIB))
    data_dir = tmp_path / "data"
    (data_dir / "db").mkdir(parents=True)
    migrated_session_factory(data_dir / "db")

    desktop = TestClient(create_app(Settings(data_dir=str(data_dir)))).get("/api/smart-search").json()
    assert (desktop["suggest_in_onboarding"], desktop["can_use_now"]) == (True, False)

    android = TestClient(create_app(Settings(data_dir=str(data_dir), platform="android"))).get("/api/smart-search")
    assert android.json()["suggest_in_onboarding"] is False


def test_physical_ram_is_read_from_the_standard_library() -> None:
    assert physical_ram_bytes() > 0
