"""`fake-telegram-serve` + `BENTO_FAKE_TELEGRAM_URL`: devices that share no directory act on one fake account."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from bento.adapters.fake_telegram.cloud import DocumentUpload, FakeTelegramCloud
from bento.adapters.fake_telegram.options import FakeTelegramOptions
from bento.adapters.fake_telegram.remote import RemoteFakeTelegramCloud, decode, encode, make_http_server
from bento.domain.errors import DomainError, StorageUnavailableError
from bento.domain.telegram import TelegramChatKind, TelegramMediaKind
from tests.e2e.harness import Device, device_environ, wait_until
from tests.e2e.journey_support import wait_for_convergence, wait_for_vault_ready


@pytest.fixture
def server(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    import threading

    directory = tmp_path / "served-cloud"
    http = make_http_server(directory)
    thread = threading.Thread(target=http.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{http.server_address[1]}", directory
    finally:
        http.shutdown()
        http.server_close()


def test_codec_round_trips_cloud_values() -> None:
    options = FakeTelegramOptions(device_model="Pixel", platform="android")
    upload = DocumentUpload(source=b"\x00bytes", filename="a.bin", mime_type="application/octet-stream")
    typed = DocumentUpload(source=b"x", filename="b.bin", kind=TelegramMediaKind.DOCUMENT)
    for value in (options, upload, typed, (1, "x", None), b"\xff", TelegramChatKind.CHANNEL):
        decoded = decode(json.loads(json.dumps(encode(value))))
        assert decoded == value and type(decoded) is type(value)
    assert decode(json.loads(json.dumps(encode({"a": [1, 2]})))) == {"a": (1, 2)}
    assert type(decode(encode(typed)).kind) is TelegramMediaKind
    with pytest.raises(TypeError):
        encode(object())


def test_remote_cloud_matches_the_directory_cloud(server: tuple[str, Path], tmp_path: Path) -> None:
    url, directory = server
    remote = RemoteFakeTelegramCloud(url, tmp_path / "client-cache")
    local = FakeTelegramCloud(directory)
    with remote.locked():  # multi-call sections hold a server lease
        chat = remote.create_channel("Bento · Archivos", "bento:files")
        remote.update_chat(chat.id, muted=True)
    message = remote.post_message(chat.id, document=DocumentUpload(source=b"part bytes", filename="p.bin"))
    assert local.message(chat.id, message.id) == message  # same state as the served directory
    path = remote.document_path(chat.id, message.id)
    assert path.read_bytes() == b"part bytes" and path.is_relative_to(tmp_path / "client-cache")
    before = remote.chat_signature(chat.id)
    remote.post_message(chat.id, text="hola")
    assert remote.chat_signature(chat.id) != before
    assert [item.id for item in remote.dialogs()] == [item.id for item in local.dialogs()]
    with pytest.raises(DomainError) as missing:
        remote.document_path(chat.id, 999_999)
    assert missing.value.code == local_missing_code(local, chat.id)
    with pytest.raises(AttributeError):
        remote._seed  # noqa: B018 - private methods are not exposed
    with pytest.raises(StorageUnavailableError):
        RemoteFakeTelegramCloud("http://127.0.0.1:9", tmp_path / "x", timeout=2).dialogs()


def local_missing_code(cloud: FakeTelegramCloud, chat_id: int) -> str:
    try:
        cloud.document_path(chat_id, 999_999)
    except DomainError as exc:
        return exc.code
    raise AssertionError("expected an error")


def test_fake_telegram_serve_subcommand_refuses_production(tmp_path: Path) -> None:
    environ = device_environ(ENVIRONMENT="production")
    result = subprocess.run(
        [sys.executable, "-m", "bento.interfaces.desktop.launcher", "fake-telegram-serve", "--dir", str(tmp_path)],
        capture_output=True, text=True, env=environ, timeout=60,
    )
    assert result.returncode != 0 and "production" in result.stderr


def test_two_backend_processes_on_one_remote_cloud_converge(tmp_path: Path) -> None:
    served = subprocess.Popen(
        [sys.executable, "-m", "bento.interfaces.desktop.launcher", "fake-telegram-serve", "--dir", str(tmp_path / "cloud")],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=device_environ(),
    )
    devices: list[Device] = []
    try:
        assert served.stdout is not None
        line = served.stdout.readline()
        assert line.startswith("BENTO_FAKE_TELEGRAM_READY ")
        url = f"http://127.0.0.1:{json.loads(line.split(' ', 1)[1])['port']}"
        for name in ("host", "phone"):
            # Each device points at its own (unused) directory: only the URL connects them.
            device = Device(name=name, root=tmp_path / name, cloud_dir=tmp_path / f"{name}-unused", extra_env={"BENTO_FAKE_TELEGRAM_URL": url})
            devices.append(device.start())
        host, phone = devices
        host.sign_in_with_qr()
        created = host.post("/vault")
        recovery = created["recovery_code"]
        host.post("/vault/recovery-code/confirm", json={"last_group": recovery.split("-")[-1]})
        wait_for_vault_ready(host)
        asset = host.upload("hola.txt", b"desde el escritorio", "text/plain")

        phone.sign_in_with_qr()
        assert phone.get("/vault")["state"] == "locked"  # the same account and vault, seen over HTTP
        phone.post("/vault/unlock", {"recovery_code": recovery})
        wait_for_vault_ready(phone)
        snapshot = wait_for_convergence(host, phone, lambda shot: asset["id"] in shot["assets"], timeout=60)
        assert asset["id"] in snapshot["assets"]
        content = wait_until(
            lambda: (r := phone.request("GET", f"/assets/{asset['id']}/download", expect=(200, 503))).status_code == 200 and r.content,
            timeout=60, message="phone download",
        )
        assert content == b"desde el escritorio"
        assert not (tmp_path / "host-unused").exists() and not (tmp_path / "phone-unused").exists()
    finally:
        for device in devices:
            device.stop()
        served.terminate()
        served.wait(10)
