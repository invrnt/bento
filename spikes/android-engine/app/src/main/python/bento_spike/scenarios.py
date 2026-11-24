"""Spike scenarios driven from Kotlin (`Actions.python`). Each returns a JSON string. HTTP goes through the real API."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable

MIB = 1024 * 1024


def run(action: str, payload_json: str) -> str:
    payload = json.loads(payload_json)
    handler: Callable[[dict[str, Any]], dict[str, Any]] = globals()[f"scenario_{action}"]
    return json.dumps(handler(payload))


# HTTP ------------------------------------------------------------------------------------------


class Api:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.port = int(payload["port"])
        self.token = payload["token"]

    def request(self, method: str, path: str, body: Any = None, *, expect: tuple[int, ...] = (200,)) -> Any:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=600)
        headers = {"Authorization": f"Bearer {self.token}"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        connection.request(method, f"/api{path}", body=data, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        if response.status not in expect:
            raise RuntimeError(f"{method} {path} -> {response.status}: {raw[:500]!r}")
        return json.loads(raw) if raw else None

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, body: Any = None) -> Any:
        return self.request("POST", path, body)

    def upload_file(self, path: Path, filename: str, mime: str, mode: str = "drive") -> dict[str, Any]:
        boundary = uuid.uuid4().hex
        head = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"mode\"\r\n\r\n{mode}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n"
        ).encode()
        tail = f"\r\n--{boundary}--\r\n".encode()
        size = path.stat().st_size

        def body():  # type: ignore[no-untyped-def]
            yield head
            with path.open("rb") as handle:
                while chunk := handle.read(MIB):
                    yield chunk
            yield tail

        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3600)
        connection.request(
            "POST",
            "/api/assets/upload",
            body=body(),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(head) + size + len(tail)),
            },
        )
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        if response.status != 200:
            raise RuntimeError(f"upload -> {response.status}: {raw[:500]!r}")
        return json.loads(raw)

    def jobs_for(self, asset_id: str, job_type: str) -> list[dict[str, Any]]:
        items = self.get("/jobs?limit=200")["items"]
        return [job for job in items if job.get("asset_id") == asset_id and job.get("type") == job_type]


def wait_until(predicate: Callable[[], Any], timeout: float, interval: float = 0.25) -> Any:
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() > deadline:
            raise TimeoutError(f"timed out after {timeout}s")
        time.sleep(interval)


def results_dir() -> Path:
    path = Path(os.environ["HOME"]) / "spike"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save(name: str, value: dict[str, Any]) -> None:
    (results_dir() / f"{name}.json").write_text(json.dumps(value))


def load(name: str) -> dict[str, Any]:
    return json.loads((results_dir() / f"{name}.json").read_text())


def database() -> sqlite3.Connection:
    return sqlite3.connect(Path(os.environ["DATA_DIR"]) / "db" / "bento.sqlite3")


# Item 1 ------------------------------------------------------------------------------------------


def scenario_fts5(payload: dict[str, Any]) -> dict[str, Any]:
    connection = sqlite3.connect(":memory:")
    result: dict[str, Any] = {"sqlite_version": sqlite3.sqlite_version}
    try:
        connection.execute("CREATE VIRTUAL TABLE t USING fts5(body)")
        connection.execute("INSERT INTO t(body) VALUES ('hola mundo bento'), ('otra cosa')")
        result["fts5"] = connection.execute("SELECT count(*) FROM t WHERE t MATCH 'bento'").fetchone()[0] == 1
    except sqlite3.OperationalError as exc:
        result["fts5"] = False
        result["fts5_error"] = str(exc)
    options = [row[0] for row in connection.execute("PRAGMA compile_options")]
    result["compile_options"] = [o for o in options if "FTS" in o or "JSON" in o or "THREADSAFE" in o]
    if "DATA_DIR" in os.environ:
        with database() as db:
            result["alembic_version"] = db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            result["app_fts_tables"] = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE sql LIKE '%fts5%'")]
    import platform
    import sys

    result.update({"python": sys.version, "machine": platform.machine(), "platform": sys.platform})
    return result


def scenario_import_profile(payload: dict[str, Any]) -> dict[str, Any]:
    from bento_spike import importprof
    from bento_spike.engine import warm_up

    warm = json.loads(warm_up())
    return {"warm_up": warm, "profile": importprof.top(int(payload.get("count", 20)))}


def scenario_memory(payload: dict[str, Any]) -> dict[str, Any]:
    rollup = {}
    for line in Path("/proc/self/smaps_rollup").read_text().splitlines()[1:]:
        key, _, value = line.partition(":")
        rollup[key.strip()] = value.strip()
    python_pss_kb = 0
    current = None
    for line in Path("/proc/self/smaps").read_text().splitlines():
        parts = line.split()
        if parts and "-" in parts[0] and len(parts) >= 5:
            path = parts[5] if len(parts) > 5 else ""
            current = path if ("python" in path or "chaquopy" in path or ".cpython-313" in path or "_python.so" in path) else None
        elif current and line.startswith("Pss:"):
            python_pss_kb += int(parts[1])
    return {"smaps_rollup": rollup, "python_file_mappings_pss_kb": python_pss_kb}


# Item 3 (fake cloud) -------------------------------------------------------------------------------


def scenario_fake_login_vault(payload: dict[str, Any]) -> dict[str, Any]:
    api = Api(payload)
    result: dict[str, Any] = {"before": api.get("/vault")["state"]}
    method = payload.get("method", "qr")
    started = time.perf_counter()
    if method == "qr":
        first = api.post("/account/login/qr")
        result["qr_step"] = first["step"]
        result["qr_url_scheme"] = (first.get("qr_url") or "").split(":")[0]

        def authorized() -> Any:
            if payload.get("approve"):
                api.post("/dev/fake-telegram/approve-login")
            status = api.get("/account")
            return status if status["step"] == "authorized" else None

        account = wait_until(authorized, 30)
    else:
        first = api.post("/account/login/phone", {"phone": payload.get("phone", "+15550000001")})
        result["phone_step"] = first["step"]
        account = api.post("/account/login/code", {"code": payload.get("code", "12345")})
    result["login_ms"] = round((time.perf_counter() - started) * 1000)
    result["account_step"] = account["step"]
    vault = api.get("/vault")
    result["after_login"] = vault["state"]
    if vault["state"] == "no_vault":
        created = api.post("/vault")
        last = created["recovery_code"].split("-")[-1]
        api.post("/vault/recovery-code/confirm", {"last_group": last})
        result["vault_created"] = created["vault"]["state"]
    result["vault"] = api.get("/vault")["state"]
    return result


def _big_file(size_mb: int) -> Path:
    path = Path(os.environ["HOME"]).parent / "cache" / f"spike-{size_mb}mb.bin"
    if not path.exists() or path.stat().st_size != size_mb * MIB:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            for _ in range(size_mb):
                handle.write(os.urandom(MIB))
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * MIB):
            digest.update(chunk)
    return digest.hexdigest()


def _session_parts(asset_id: str) -> list[dict[str, Any]]:
    with database() as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(upload_sessions)")]
        rows = db.execute("SELECT * FROM upload_sessions WHERE asset_id = ?", (asset_id,)).fetchall()
    return [dict(zip(columns, row)) for row in rows]


def scenario_upload_big(payload: dict[str, Any]) -> dict[str, Any]:
    api = Api(payload)
    size_mb = int(payload.get("size_mb", 200))
    source = _big_file(size_mb)
    sha = _sha256(source)
    started = time.perf_counter()
    asset = api.upload_file(source, f"big-{uuid.uuid4().hex[:6]}.bin", "application/octet-stream")
    http_s = time.perf_counter() - started
    result: dict[str, Any] = {
        "asset_id": asset["id"],
        "size_mb": size_mb,
        "sha256": sha,
        "http_upload_s": round(http_s, 2),
        "http_upload_mb_s": round(size_mb / http_s, 1),
    }
    save("big", result)
    if not payload.get("wait", True):
        return result
    t0 = time.perf_counter()

    def finished() -> Any:
        jobs = api.jobs_for(asset["id"], "remote_upload")
        if any(job["status"] == "failed" for job in jobs):
            raise RuntimeError(f"remote_upload failed: {jobs}")
        return jobs if jobs and all(job["status"] == "succeeded" for job in jobs) else None

    jobs = wait_until(finished, 1800, 0.5)
    wall = time.perf_counter() - t0
    result.update(
        {
            "remote_upload_wait_s": round(wall, 2),
            "remote_upload_jobs": jobs,
            "upload_sessions": _session_parts(asset["id"]),
            "encrypted_upload_mb_s_wall": round(size_mb / wall, 1),
        }
    )
    save("big", result)
    return result


def scenario_upload_status(payload: dict[str, Any]) -> dict[str, Any]:
    api = Api(payload)
    big = load("big")
    return {"jobs": api.jobs_for(big["asset_id"], "remote_upload"), "sessions": _session_parts(big["asset_id"])}


def scenario_resume_check(payload: dict[str, Any]) -> dict[str, Any]:
    """After the process was killed mid-upload: the job is requeued and completed parts are not uploaded again."""
    api = Api(payload)
    big = load("big")
    asset_id = big["asset_id"]
    at_restart = _session_parts(asset_id)
    t0 = time.perf_counter()

    def finished() -> Any:
        jobs = api.jobs_for(asset_id, "remote_upload")
        if any(job["status"] == "failed" for job in jobs):
            raise RuntimeError(f"remote_upload failed: {jobs}")
        return jobs if jobs and all(job["status"] == "succeeded" for job in jobs) else None

    jobs = wait_until(finished, 1800, 0.5)
    return {
        "asset_id": asset_id,
        "sessions_at_restart": at_restart,
        "sessions_after": _session_parts(asset_id),
        "jobs": jobs,
        "resume_wait_s": round(time.perf_counter() - t0, 2),
    }


def scenario_download_big(payload: dict[str, Any]) -> dict[str, Any]:
    """Download + decrypt the v2 blob from the fake cloud through the real remote store, verify the digest."""
    import asyncio

    from bento.infrastructure.services import get_remote_blob_store
    from bento.infrastructure.settings import get_settings

    big = load("big")
    with database() as db:
        row = db.execute(
            "SELECT id FROM blob_refs WHERE asset_id = ? AND kind = 'original' AND backend != 'local'", (big["asset_id"],)
        ).fetchone()
    if row is None:
        raise RuntimeError("no remote original blob ref")
    store = get_remote_blob_store(get_settings())
    destination = Path(os.environ["HOME"]).parent / "cache" / "spike-download.bin"
    destination.unlink(missing_ok=True)

    async def download() -> float:
        blob_ref = await store.get(row[0])
        started = time.perf_counter()
        await store.download(blob_ref, destination)
        return time.perf_counter() - started

    elapsed = asyncio.run(download())
    sha = _sha256(destination)
    size = destination.stat().st_size
    destination.unlink(missing_ok=True)
    return {
        "blob_id": row[0],
        "seconds": round(elapsed, 2),
        "mb_s": round(size / MIB / elapsed, 1),
        "sha256_matches": sha == big["sha256"],
        "size_mb": round(size / MIB, 1),
    }


def scenario_aes_bench(payload: dict[str, Any]) -> dict[str, Any]:
    """Crypto ceilings on this device: AES-GCM + SHA-256 (v2 blob path) and Telethon AES-IGE (MTProto) ± cryptg."""
    import importlib
    import sys

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    size = int(payload.get("mb", 32)) * MIB
    data = os.urandom(size)
    result: dict[str, Any] = {"mb": size // MIB}
    aes = AESGCM(AESGCM.generate_key(bit_length=256))
    started = time.perf_counter()
    chunk = MIB
    for offset in range(0, size, chunk):
        aes.encrypt(os.urandom(12), data[offset : offset + chunk], None)
    result["aes_gcm_mb_s"] = round(size / MIB / (time.perf_counter() - started), 1)
    started = time.perf_counter()
    hashlib.sha256(data).hexdigest()
    result["sha256_mb_s"] = round(size / MIB / (time.perf_counter() - started), 1)

    ige_size = min(size, 16 * MIB)
    key, iv = os.urandom(32), os.urandom(32)
    sample = data[:ige_size]

    def ige(label: str) -> None:
        import telethon.crypto.aes as aes_module

        aes_module = importlib.reload(aes_module)
        started = time.perf_counter()
        aes_module.AES.encrypt_ige(sample, key, iv)
        elapsed = time.perf_counter() - started
        result[f"ige_{label}_mb_s"] = round(ige_size / MIB / elapsed, 2)
        result[f"ige_{label}_backend"] = "cryptg" if getattr(aes_module, "cryptg", None) else (
            "libssl" if getattr(getattr(aes_module, "libssl", None), "encrypt_ige", None) else "pyaes"
        )

    try:
        import cryptg  # noqa: F401

        result["cryptg_installed"] = True
        ige("with_cryptg")
    except ImportError:
        result["cryptg_installed"] = False
    saved = sys.modules.get("cryptg")
    sys.modules["cryptg"] = None  # type: ignore[assignment]  # block the import
    try:
        ige_small = sample
        sample = data[: 2 * MIB]  # pure-Python fallbacks are slow; measure a smaller sample
        ige_size = len(sample)
        ige("without_cryptg")
        sample = ige_small
    finally:
        if saved is not None:
            sys.modules["cryptg"] = saved
        else:
            sys.modules.pop("cryptg", None)
    return result
