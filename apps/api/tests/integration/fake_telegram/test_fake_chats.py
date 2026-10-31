from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from bento.adapters.fake_telegram import FAKE_USER, FakeTelegramCloud
from bento.adapters.fake_telegram.media import jpeg_bytes, mp4_bytes, pdf_bytes, png_bytes
from bento.domain.errors import ValidationFailedError
from bento.domain.telegram import TelegramChat, TelegramChatKind, TelegramMediaKind
from tests.integration.fake_telegram.support import make_device, run, sign_in


def test_list_chats_offers_saved_messages_and_seeded_chats_but_not_vault_channels(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = make_device(tmp_path)
        await sign_in(device)
        await device.runtime.transport.create_vault("vlt_demo")
        news = FakeTelegramCloud(tmp_path).create_channel("Noticias", "Canal público", creator=False)

        chats = await device.runtime.chats.list_chats()

        assert chats[0] == TelegramChat(id=FAKE_USER.user_id, title="Saved Messages", kind=TelegramChatKind.SAVED)
        assert {chat.title for chat in chats} == {"Saved Messages", "Carlos Ruiz", "Familia", "Noticias"}
        assert next(chat for chat in chats if chat.title == "Noticias").id == news.id
        assert await device.runtime.chats.list_chats(query="fam") == (
            TelegramChat(id=-400000001, title="Familia", kind=TelegramChatKind.GROUP),
        )
        assert len(await device.runtime.chats.list_chats(limit=2)) == 2

    run(scenario())


def test_list_media_pages_newest_first_and_filters_by_kind(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = make_device(tmp_path)
        await sign_in(device)
        chats = device.runtime.chats

        saved = await chats.list_media(FAKE_USER.user_id)
        carlos = await chats.list_media(777000002)

        assert [(item.filename, item.kind, item.mime_type) for item in saved] == [
            ("atardecer.jpg", TelegramMediaKind.PHOTO, "image/jpeg"),
            ("recibo-cafe.pdf", TelegramMediaKind.DOCUMENT, "application/pdf"),
        ]
        assert [item.kind for item in carlos] == [TelegramMediaKind.VIDEO, TelegramMediaKind.PHOTO]
        assert await chats.list_media(777000002, kind="photo") == (carlos[1],)
        assert await chats.list_media(777000002, before_message_id=carlos[0].message_id) == (carlos[1],)
        assert await chats.list_media(777000002, limit=1) == (carlos[0],)
        assert all(item.size_bytes and item.size_bytes > 0 for item in saved + carlos)
        with pytest.raises(ValidationFailedError):
            await chats.list_media(777000002, kind="sticker")

    run(scenario())


def test_downloaded_seed_media_are_valid_files(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = make_device(tmp_path)
        await sign_in(device)
        chats = device.runtime.chats
        downloaded: dict[str, bytes] = {}
        for chat in await chats.list_chats():
            for item in await chats.list_media(chat.id):
                target = await chats.download_media(chat.id, item.message_id, tmp_path / "out" / item.filename)
                downloaded[item.filename] = target.read_bytes()
                assert len(downloaded[item.filename]) == item.size_bytes

        assert set(downloaded) == {"atardecer.jpg", "recibo-cafe.pdf", "playa.png", "paseo.mp4", "cumpleanos.jpg", "notas.txt"}
        assert_png(downloaded["playa.png"])
        assert_jpeg(downloaded["atardecer.jpg"])
        assert downloaded["recibo-cafe.pdf"].startswith(b"%PDF-1.4") and downloaded["recibo-cafe.pdf"].endswith(b"%%EOF\n")
        assert downloaded["paseo.mp4"][4:8] == b"ftyp"

    run(scenario())


def test_send_file_posts_a_document_with_caption(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = make_device(tmp_path)
        await sign_in(device)
        source = tmp_path / "plain.bin"
        source.write_bytes(b"decrypted original")

        await device.runtime.chats.send_file(777000002, source, filename="Factura marzo.pdf", caption="Aquí está")

        _, messages = FakeTelegramCloud(tmp_path).read_chat(777000002)
        sent = messages[-1]
        assert sent.text == "Aquí está"
        assert sent.media is not None
        assert (sent.media.kind, sent.media.filename, sent.media.mime_type) == (
            TelegramMediaKind.DOCUMENT,
            "Factura marzo.pdf",
            "application/pdf",
        )
        assert (await device.runtime.chats.list_media(777000002))[0].filename == "Factura marzo.pdf"
        with pytest.raises(ValidationFailedError):
            await device.runtime.chats.send_file(777000002, source, filename="x.bin", caption="x" * 1025)

    run(scenario())


def test_media_generators_produce_well_formed_files() -> None:
    assert_png(png_bytes(8, 4, [(255, 0, 0), (0, 0, 255)]))
    assert_jpeg(jpeg_bytes(16, 8, [(255, 255, 255), (0, 0, 0)]))
    with pytest.raises(ValueError):
        jpeg_bytes(10, 8, [(0, 0, 0)])
    pdf = pdf_bytes("Total (COP) \\ 12")
    assert b"(Total \\(COP\\) \\\\ 12)" in pdf
    offset = int(pdf.rsplit(b"startxref\n", 1)[1].split(b"\n", 1)[0])
    assert pdf[offset:].startswith(b"xref")
    assert mp4_bytes()[4:8] == b"ftyp"


def assert_png(data: bytes) -> None:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    position = 8
    kinds = []
    while position < len(data):
        (length,) = struct.unpack(">I", data[position : position + 4])
        kind = data[position + 4 : position + 8]
        body = data[position + 8 : position + 8 + length]
        (crc,) = struct.unpack(">I", data[position + 8 + length : position + 12 + length])
        assert zlib.crc32(kind + body) == crc
        kinds.append(kind)
        position += 12 + length
    assert kinds == [b"IHDR", b"IDAT", b"IEND"]


def assert_jpeg(data: bytes) -> None:
    assert data.startswith(b"\xff\xd8\xff\xe0") and data.endswith(b"\xff\xd9")
    markers = []
    position = 2
    while data[position] == 0xFF and data[position + 1] != 0xDA:
        markers.append(data[position + 1])
        (length,) = struct.unpack(">H", data[position + 2 : position + 4])
        position += 2 + length
    assert markers == [0xE0, 0xDB, 0xC0, 0xC4, 0xC4]
    scan = data[position:-2]
    assert all(scan[index + 1] in (0x00, 0xDA) for index in range(len(scan) - 1) if scan[index] == 0xFF)
