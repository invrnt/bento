from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from bento.domain.errors import ValidationFailedError
from bento.domain.security import RecoveryWrap
from bento.domain.vault import (
    CHANNEL_ABOUT_NOTICE,
    SnapshotPointer,
    VaultChannelCandidate,
    VaultChannelRole,
    VaultHeader,
    VaultLayout,
    channel_about,
    channel_marker,
    discover_vault_layouts,
    parse_channel_marker,
)

LAYOUT = VaultLayout(vault_id="vlt_abc", files_channel_id=-1001, sync_channel_id=-1002, inbox_channel_id=-1003)


def make_header(**overrides: object) -> VaultHeader:
    values: dict[str, object] = {
        "vault_id": "vlt_abc",
        "created_at": datetime(2026, 10, 1, 12, 30, tzinfo=UTC),
        "layout": LAYOUT,
        "current_epoch": 2,
        "recovery": RecoveryWrap(alg="hkdf-aesgcm-v1", nonce="bm9uY2U", wrapped_keyring="d3JhcHBlZA"),
        "snapshot": SnapshotPointer(
            message_id=123, covers_through_message_id=456, created_at=datetime(2026, 10, 2, tzinfo=UTC)
        ),
        "mac": "bWFj",
    }
    values.update(overrides)
    return VaultHeader(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("snapshot", [True, False])
def test_vault_header_json_round_trip(snapshot: bool) -> None:
    header = make_header() if snapshot else make_header(snapshot=None)

    text = header.to_json()

    assert VaultHeader.from_json(text) == header
    payload = json.loads(text)
    assert payload["bento"] == "vault-header" and payload["v"] == 1
    assert payload["layout"] == {"files": -1001, "sync": -1002, "inbox": -1003}
    assert len(text) <= 4096


def test_vault_header_canonical_bytes_are_sorted_compact_and_exclude_mac() -> None:
    header = make_header()

    canonical = header.canonical_unsigned_bytes()

    assert b" " not in canonical.replace(b"Bento", b"")
    assert b'"mac"' not in canonical
    assert canonical == json.dumps(json.loads(canonical), sort_keys=True, separators=(",", ":")).encode()
    assert canonical == make_header(mac="other").canonical_unsigned_bytes()
    assert canonical != make_header(current_epoch=3).canonical_unsigned_bytes()
    assert header.to_json().encode() == json.dumps(
        {**json.loads(canonical), "mac": "bWFj"}, sort_keys=True, separators=(",", ":")
    ).encode()


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        json.dumps({"bento": "sync-batch", "v": 1}),
        json.dumps({"bento": "vault-header", "v": 2}),
        json.dumps({"bento": "vault-header", "v": 1, "vault_id": "vlt_abc"}),
    ],
)
def test_vault_header_rejects_invalid_text(text: str) -> None:
    with pytest.raises(ValidationFailedError):
        VaultHeader.from_json(text)


def test_channel_markers_round_trip() -> None:
    about = channel_about(VaultChannelRole.INBOX, "vlt_abc")

    assert about.splitlines() == ["bento:v1:inbox:vlt_abc", CHANNEL_ABOUT_NOTICE]
    assert parse_channel_marker(about) == (VaultChannelRole.INBOX, "vlt_abc")
    assert parse_channel_marker("Creado por Bento\n  bento:v1:files:vlt_x  ") == (VaultChannelRole.FILES, "vlt_x")
    assert parse_channel_marker("bento:v1:other:vlt_x") is None
    assert parse_channel_marker("bento:v2:files:vlt_x") is None
    assert len(about) <= 255


def test_discovery_keeps_complete_creator_owned_bento_vaults() -> None:
    def candidate(channel_id: int, role: VaultChannelRole, vault_id: str, **overrides: object) -> VaultChannelCandidate:
        values: dict[str, object] = {
            "channel_id": channel_id,
            "title": f"Bento · {role.value}",
            "about": channel_about(role, vault_id),
            "creator": True,
        }
        values.update(overrides)
        return VaultChannelCandidate(**values)  # type: ignore[arg-type]

    candidates = [
        candidate(-11, VaultChannelRole.FILES, "vlt_new"),
        candidate(-12, VaultChannelRole.SYNC, "vlt_new"),
        candidate(-13, VaultChannelRole.INBOX, "vlt_new"),
        candidate(-14, VaultChannelRole.SYNC, "vlt_new"),
        candidate(-21, VaultChannelRole.FILES, "vlt_old"),
        candidate(-22, VaultChannelRole.SYNC, "vlt_old"),
        candidate(-23, VaultChannelRole.INBOX, "vlt_old", creator=False),
        candidate(-31, VaultChannelRole.FILES, "vlt_renamed", title="Mis archivos"),
        candidate(-32, VaultChannelRole.SYNC, "vlt_renamed"),
        candidate(-33, VaultChannelRole.INBOX, "vlt_renamed"),
        VaultChannelCandidate(channel_id=-41, title="Bento fans", about="Un canal", creator=True),
    ]

    assert discover_vault_layouts(candidates) == (
        VaultLayout(vault_id="vlt_new", files_channel_id=-11, sync_channel_id=-12, inbox_channel_id=-13),
    )
    assert channel_marker(VaultChannelRole.SYNC, "vlt_new") == "bento:v1:sync:vlt_new"


DIGEST = "LXEWQrcmsEQBYnyp-6wy9chTD7GQPMTbAiWHF5IaSIE"  # b64url SHA-256 of b"x"


def test_snapshot_digest_is_mac_covered_and_omitted_only_for_old_pointers() -> None:
    pointer = SnapshotPointer(
        message_id=123, covers_through_message_id=456, created_at=datetime(2026, 10, 2, tzinfo=UTC), sha256=DIGEST
    )
    header = make_header(snapshot=pointer)

    assert json.loads(header.to_json())["snapshot"]["sha256"] == DIGEST
    assert VaultHeader.from_json(header.to_json()) == header
    other = make_header(snapshot=SnapshotPointer(123, 456, pointer.created_at, sha256="A" * 43))
    assert other.canonical_unsigned_bytes() != header.canonical_unsigned_bytes()

    legacy = make_header()  # pointers written before the digest existed keep their exact MAC-covered bytes
    assert "sha256" not in json.loads(legacy.to_json())["snapshot"]
    assert VaultHeader.from_json(legacy.to_json()).snapshot.sha256 is None  # type: ignore[union-attr]


@pytest.mark.parametrize("digest", ["", "abc", DIGEST + "A", DIGEST[:-1] + "B", DIGEST[:-1] + "=", 42])
def test_malformed_snapshot_digests_make_the_header_invalid(digest: object) -> None:
    payload = json.loads(make_header().to_json())
    payload["snapshot"]["sha256"] = digest
    with pytest.raises(ValidationFailedError):
        VaultHeader.from_json(json.dumps(payload))
