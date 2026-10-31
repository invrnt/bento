"""Sync-channel fallback pairing (commit-then-reveal) between two devices on the fake cloud, no relay."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest

from bento.adapters.fake_telegram import FakeTelegramCloud
from bento.adapters.security import FallbackPairingKeys
from bento.application.pairing import b64url_decode, b64url_encode
from bento.domain.errors import TelegramAccountError
from bento.domain.pairing import PairingError, PairingRole, PairingState, PairingTransport
from bento.domain.sync import SyncMessageKind
from bento.domain.vault import VaultHeader
from bento.domain.vault import VaultState
from tests.integration.pairing.pairing_support import PairingDevice, make_pairing_device, wait_for_state


async def _devices(tmp_path: Path) -> tuple[PairingDevice, PairingDevice]:
    host = make_pairing_device(tmp_path, tmp_path / "cloud", "host")
    guest = make_pairing_device(tmp_path, tmp_path / "cloud", "guest")
    await host.sign_in()
    await host.vault.create_vault()
    await guest.sign_in()
    return host, guest


def _pairing_texts(cloud: FakeTelegramCloud, sync_channel_id: int) -> list[dict[str, object]]:
    _, messages = cloud.read_chat(sync_channel_id)
    texts = []
    for message in messages:
        if message.text and message.media is None:
            payload = json.loads(message.text)
            if payload.get("bento", "").startswith("pair_"):
                texts.append(payload)
    return texts


def test_fallback_pairing_end_to_end(tmp_path: Path) -> None:
    async def scenario() -> None:
        host, guest = await _devices(tmp_path)
        try:
            assert (await guest.vault.status()).state == VaultState.LOCKED
            requested = await guest.pairing.request_access()
            assert requested.session.role == PairingRole.GUEST
            assert requested.session.transport == PairingTransport.TELEGRAM
            assert requested.session.state == PairingState.WAITING

            requests = await host.pairing.list_requests()
            assert [(item.device_name, item.platform.value) for item in requests] == [("guest · Linux", "linux")]
            reviewed = await host.pairing.review_request(requests[0].id)
            assert reviewed.session.state == PairingState.AWAITING_APPROVAL
            assert reviewed.session.peer is not None and reviewed.session.peer.device_name == "guest · Linux"

            guest_view = await wait_for_state(lambda: guest.pairing.get(requested.session.id), PairingState.AWAITING_APPROVAL)
            assert guest_view.session.sas == reviewed.session.sas and len(reviewed.session.sas or ()) == 4

            approving = await host.pairing.approve_request(requests[0].id)
            assert approving.session.state in {PairingState.APPROVING, PairingState.COMPLETED}
            await wait_for_state(lambda: host.pairing.get(reviewed.session.id), PairingState.COMPLETED)
            await wait_for_state(lambda: guest.pairing.get(requested.session.id), PairingState.COMPLETED)

            assert await guest.vault.keyring() == await host.vault.keyring()
            assert (await guest.vault.status()).state == VaultState.READY
            recorded = await host.devices.get(guest.device_id)
            assert recorded is not None and recorded.public_key == b64url_encode(guest.identity.public_key)
            assert await host.pairing.list_requests() == ()

            assert host.vault.layout is not None
            texts = _pairing_texts(FakeTelegramCloud(tmp_path / "cloud"), host.vault.layout.sync_channel_id)
            assert texts == [], "the guest deletes every pairing message of its request"
        finally:
            await host.pairing.close()
            await guest.pairing.close()

    asyncio.run(scenario())


def test_fallback_requires_telegram_sign_in(tmp_path: Path) -> None:
    async def scenario() -> None:
        host = make_pairing_device(tmp_path, tmp_path / "cloud", "host")
        await host.sign_in()
        await host.vault.create_vault()
        guest = make_pairing_device(tmp_path, tmp_path / "cloud", "guest")
        with pytest.raises(TelegramAccountError) as error:
            await guest.pairing.request_access()
        assert error.value.code == "telegram_not_authorized"
        with pytest.raises(PairingError) as paired:
            await host.pairing.request_access()
        assert paired.value.code == "pairing_already_paired"

    asyncio.run(scenario())


def test_host_rejects_a_reveal_that_does_not_match_the_commitment(tmp_path: Path) -> None:
    async def scenario() -> None:
        host, guest = await _devices(tmp_path)
        assert host.vault.layout is not None
        layout = host.vault.layout
        try:
            # A forged request whose reveal uses a different ephemeral key than the one committed to.
            committed = FallbackPairingKeys()
            forged = FallbackPairingKeys()
            request_id = "f" * 32
            public_key = guest.identity.public_key
            await host.runtime.transport.post_sync_text(
                layout,
                SyncMessageKind.PAIRING,
                json.dumps(
                    {
                        "bento": "pair_request",
                        "v": 1,
                        "request_id": request_id,
                        "device_id": guest.device_id,
                        "device_name": "Intruso",
                        "platform": "linux",
                        "public_key": b64url_encode(public_key),
                        "commitment": committed.commitment(device_public_key=public_key, request_id=request_id),
                    }
                ),
            )
            [request] = await host.pairing.list_requests()
            review = asyncio.create_task(host.pairing.review_request(request.id))
            cloud = FakeTelegramCloud(tmp_path / "cloud")
            offer = None
            for _ in range(200):
                offer = next((item for item in _pairing_texts(cloud, layout.sync_channel_id) if item["bento"] == "pair_offer"), None)
                if offer is not None:
                    break
                await asyncio.sleep(0.01)
            assert offer is not None
            await host.runtime.transport.post_sync_text(
                layout,
                SyncMessageKind.PAIRING,
                json.dumps(
                    {"bento": "pair_reveal", "v": 1, "request_id": request_id, "eph_pub": b64url_encode(forged.public_key())}
                ),
            )
            view = await review
            if not view.session.state.terminal:
                view = await wait_for_state(lambda: host.pairing.get(view.session.id), PairingState.FAILED)
            assert view.session.state == PairingState.FAILED
            assert view.session.error_code == "pairing_commitment_mismatch"
            assert view.session.sas is None
        finally:
            await host.pairing.close()
            await guest.pairing.close()

    asyncio.run(scenario())


def test_rejected_request_ends_the_guest_session(tmp_path: Path) -> None:
    async def scenario() -> None:
        host, guest = await _devices(tmp_path)
        try:
            requested = await guest.pairing.request_access()
            [request] = await host.pairing.list_requests()
            await host.pairing.review_request(request.id)
            rejected = await host.pairing.reject_request(request.id)
            assert rejected.session.state == PairingState.REJECTED
            await wait_for_state(lambda: guest.pairing.get(requested.session.id), PairingState.REJECTED)
            assert await host.pairing.list_requests() == ()
            assert (await guest.vault.status()).state == VaultState.LOCKED
        finally:
            await host.pairing.close()
            await guest.pairing.close()

    asyncio.run(scenario())


def test_rejecting_an_unreviewed_request(tmp_path: Path) -> None:
    async def scenario() -> None:
        host, guest = await _devices(tmp_path)
        try:
            requested = await guest.pairing.request_access()
            [request] = await host.pairing.list_requests()
            rejected = await host.pairing.reject_request(request.id)
            assert rejected.session.state == PairingState.REJECTED and rejected.session.role == PairingRole.HOST
            assert rejected.session.peer is not None and rejected.session.peer.device_name == "guest · Linux"
            await wait_for_state(lambda: guest.pairing.get(requested.session.id), PairingState.REJECTED)
            with pytest.raises(PairingError) as gone:
                await host.pairing.review_request(request.id)
            assert gone.value.code == "pairing_request_not_found"
            assert host.vault.layout is not None
            texts = _pairing_texts(FakeTelegramCloud(tmp_path / "cloud"), host.vault.layout.sync_channel_id)
            assert [text["bento"] for text in texts] == ["pair_reject"], "the guest removed its own request"
        finally:
            await host.pairing.close()
            await guest.pairing.close()

    asyncio.run(scenario())


def test_guest_ignores_a_grant_forged_by_a_channel_writer(tmp_path: Path) -> None:
    async def scenario() -> None:
        host, guest = await _devices(tmp_path)
        assert host.vault.layout is not None
        layout = host.vault.layout
        cloud = FakeTelegramCloud(tmp_path / "cloud")
        try:
            requested = await guest.pairing.request_access()
            [request] = await host.pairing.list_requests()
            reviewed = await host.pairing.review_request(request.id)
            assert reviewed.session.state == PairingState.AWAITING_APPROVAL

            # Everything a channel writer can read: the request, the host offer, and the guest reveal.
            texts = {item["bento"]: item for item in _pairing_texts(cloud, layout.sync_channel_id)}
            guest_eph = b64url_decode(texts["pair_reveal"]["eph_pub"], max_bytes=32)
            host_eph = b64url_decode(texts["pair_offer"]["eph_pub"], max_bytes=32)
            device_key = b64url_decode(texts["pair_request"]["public_key"], max_bytes=32)
            attacker_keyring = guest.crypto.generate_keyring(layout.vault_id)
            # The attacker also pins a header MACed with its own keyring, so the header check alone would pass.
            genuine_header = await host.runtime.transport.read_header_text(layout)
            assert genuine_header is not None
            header = VaultHeader.from_json(genuine_header)
            forged_header = replace(
                header, mac=guest.crypto.header_mac(attacker_keyring, header.canonical_unsigned_bytes())
            )
            await host.runtime.transport.publish_header_text(layout, forged_header.to_json())
            sealed = guest.crypto.seal_for_device(
                device_key, guest.crypto.keyring_to_bytes(attacker_keyring), aad=request.id.encode()
            )
            intruder = FallbackPairingKeys()
            forged = intruder.seal_grant(
                guest_eph,
                sealed,
                request_id=request.id,
                guest_device_public_key=device_key,
                guest_ephemeral_public_key=guest_eph,
                host_ephemeral_public_key=intruder.public_key(),
            )
            for payload in (
                {"bento": "pair_grant", "v": 1, "request_id": request.id, "grant": b64url_encode(forged)},
                {"bento": "pair_grant", "v": 1, "request_id": request.id, "grant": b64url_encode(b"\x00" * 64)},
                {"bento": "pair_grant", "v": 1, "request_id": request.id, "sealed_keyring": b64url_encode(sealed)},
            ):
                await host.runtime.transport.post_sync_text(layout, SyncMessageKind.PAIRING, json.dumps(payload))
            assert host_eph != intruder.public_key()

            await asyncio.sleep(0.5)  # several guest polls
            waiting = await guest.pairing.get(requested.session.id)
            assert waiting.session.state == PairingState.AWAITING_APPROVAL
            assert guest.vault.installs == [] and await guest.vault.keyring() is None

            # The genuine host can still complete the pairing once the real header is pinned again.
            await host.runtime.transport.publish_header_text(layout, genuine_header)
            await host.pairing.approve(reviewed.session.id)
            await wait_for_state(lambda: guest.pairing.get(requested.session.id), PairingState.COMPLETED)
            assert await guest.vault.keyring() == await host.vault.keyring() != attacker_keyring
        finally:
            await host.pairing.close()
            await guest.pairing.close()

    asyncio.run(scenario())
