"""`keys` messages (architecture § Keys messages): rotated keyrings granted per device, authenticated by the sender.

```json
{"bento": "keys", "v": 2, "vault_id": "vlt_…", "epoch": 2, "sender_device_id": "dev_a",
 "removed_device_ids": ["dev_c"],
 "grants": {"dev_b": {"sealed": "<b64url seal_for_device(pub_b, keyring_bytes, aad=vault_id)>",
                      "auth": "<grant_auth(sender identity, pub_b, grant_auth_payload(...))>"}}}
```

Sealed boxes alone are anonymous: anyone holding a recipient's public key (every device of the account,
including a removed one whose Telegram session is still alive) can make one. A grant is accepted only from
an active device of the local registry, never from a device removed by an applied keys message, and only
when its `auth` tag (static X25519 between sender and recipient) covers the whole message context.

Epochs move exactly one step: a grant for `current + 1` is merged, a grant for `current` must agree with
the keys already held, and anything else is rejected. A newer epoch from another active device that has no
grant for this device (or lists it as removed) means this device was removed (`removes_this_device`).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from bento.application.pairing import decode_public_key
from bento.application.sync.codec import b64url_decode, b64url_encode
from bento.application.sync.state import REMOVED_DEVICES, SyncStateValues
from bento.domain.errors import IntegrityError, ValidationFailedError
from bento.domain.security import DeviceIdentity, VaultKeyring
from bento.domain.vault import canonical_json
from bento.ports.pairing import DeviceRepositoryPort
from bento.ports.repositories import ClockPort
from bento.ports.security import VaultCryptoPort
from bento.ports.vault import VaultContext

KEYS_MARKER = "keys"
KEYS_VERSION = 2
GRANT_AUTH_MARKER = "keys-grant"
_DEVICE_ID_PREFIX = "dev_"
_MESSAGE_FIELDS = frozenset({"bento", "v", "vault_id", "epoch", "sender_device_id", "removed_device_ids", "grants"})
_GRANT_FIELDS = frozenset({"sealed", "auth"})


@dataclass(frozen=True, slots=True)
class KeysGrant:
    sealed: str
    auth: str


@dataclass(frozen=True, slots=True)
class KeysMessage:
    vault_id: str
    epoch: int
    sender_device_id: str
    removed_device_ids: tuple[str, ...]
    grants: Mapping[str, KeysGrant]


def grant_auth_payload(message: KeysMessage, *, recipient_device_id: str, sealed: str) -> bytes:
    """Canonical JSON every grant's `auth` tag covers: the whole message context plus this recipient's box."""
    return canonical_json(
        {
            "bento": GRANT_AUTH_MARKER,
            "v": KEYS_VERSION,
            "vault_id": message.vault_id,
            "epoch": message.epoch,
            "sender_device_id": message.sender_device_id,
            "recipient_device_id": recipient_device_id,
            "removed_device_ids": list(message.removed_device_ids),
            "sealed": sealed,
        }
    )


def build_keys_message(
    crypto: VaultCryptoPort,
    sender: DeviceIdentity,
    keyring: VaultKeyring,
    recipients: Mapping[str, bytes],
    *,
    removed_device_ids: Iterable[str] = (),
) -> bytes:
    """Canonical JSON `.bkeys` document granting `keyring` to each `recipients` device id → X25519 public key."""
    removed = tuple(sorted(set(removed_device_ids)))
    context = KeysMessage(
        vault_id=keyring.vault_id,
        epoch=keyring.current_epoch,
        sender_device_id=sender.device_id,
        removed_device_ids=removed,
        grants={},
    )
    if not all(is_device_id(device_id) for device_id in (sender.device_id, *removed, *recipients)):
        raise ValidationFailedError("Invalid device id in a keys message")
    _check_ids(context, recipients)
    payload = crypto.keyring_to_bytes(keyring)
    aad = keyring.vault_id.encode("utf-8")
    grants: dict[str, dict[str, str]] = {}
    for device_id, public_key in sorted(recipients.items()):
        sealed = b64url_encode(crypto.seal_for_device(public_key, payload, aad=aad))
        auth = crypto.grant_auth(sender, public_key, grant_auth_payload(context, recipient_device_id=device_id, sealed=sealed))
        grants[device_id] = {"sealed": sealed, "auth": auth}
    return canonical_json(
        {
            "bento": KEYS_MARKER,
            "v": KEYS_VERSION,
            "vault_id": context.vault_id,
            "epoch": context.epoch,
            "sender_device_id": context.sender_device_id,
            "removed_device_ids": list(removed),
            "grants": grants,
        }
    )


def parse_keys_message(payload: bytes) -> KeysMessage:
    """Strict v2 parsing; anything else (including v1 anonymous grants) raises `ValidationFailedError`."""
    try:
        data = json.loads(bytes(payload).decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise ValidationFailedError("Invalid keys message") from None
    if not isinstance(data, dict) or data.get("bento") != KEYS_MARKER:
        raise ValidationFailedError("Invalid keys message")
    if type(data.get("v")) is not int or data["v"] != KEYS_VERSION:
        raise ValidationFailedError("Unsupported keys message version")
    if set(data) != _MESSAGE_FIELDS:
        raise ValidationFailedError("Invalid keys message")
    vault_id, epoch, sender = data["vault_id"], data["epoch"], data["sender_device_id"]
    if not isinstance(vault_id, str) or not vault_id or not _is_epoch(epoch) or not is_device_id(sender):
        raise ValidationFailedError("Invalid keys message")
    removed = data["removed_device_ids"]
    if not isinstance(removed, list) or not all(is_device_id(item) for item in removed) or len(set(removed)) != len(removed):
        raise ValidationFailedError("Invalid keys message")
    grants = data["grants"]
    if not isinstance(grants, dict):
        raise ValidationFailedError("Invalid keys message")
    parsed: dict[str, KeysGrant] = {}
    for device_id, grant in grants.items():
        if not is_device_id(device_id) or not _is_grant(grant):
            raise ValidationFailedError("Invalid keys message")
        parsed[device_id] = KeysGrant(sealed=grant["sealed"], auth=grant["auth"])
    message = KeysMessage(
        vault_id=vault_id, epoch=epoch, sender_device_id=sender, removed_device_ids=tuple(removed), grants=parsed
    )
    _check_ids(message, parsed)
    return message


def merge_granted_keyring(current: VaultKeyring, granted: VaultKeyring, *, epoch: int) -> VaultKeyring | None:
    """Keyring to persist after a grant, or None when it brings nothing new.

    The grant must be for this vault and epoch, and must agree with every key this device already holds;
    older epochs this device knows but the grant lacks are kept.
    """
    if granted.vault_id != current.vault_id or granted.current_epoch != epoch:
        raise IntegrityError("keys_grant")
    for known_epoch, key in current.keys.items():
        if known_epoch in granted.keys and granted.keys[known_epoch] != key:
            raise IntegrityError("keys_grant")
    if epoch <= current.current_epoch and set(granted.keys) <= set(current.keys):
        return None
    keys = {**granted.keys, **current.keys}
    return VaultKeyring(vault_id=current.vault_id, current_epoch=max(epoch, current.current_epoch), keys=keys)


class KeysGrantApplier:
    """Accepts the grant addressed to this device in a keys message, or rejects it with `IntegrityError`.

    Trust anchors: this device's own identity and the X25519 public keys in the local device registry.
    Device ids listed in `removed_device_ids` of an accepted message are remembered in `sync_state`
    (`removed_device_ids`) and marked removed in the registry, so their later grants are rejected even
    when the removal op arrives later or a stale op re-activates the registry row.
    """

    def __init__(
        self, *, crypto: VaultCryptoPort, devices: DeviceRepositoryPort, values: SyncStateValues, clock: ClockPort
    ) -> None:
        self._crypto = crypto
        self._devices = devices
        self._values = values
        self._clock = clock

    async def removed_device_ids(self) -> frozenset[str]:
        stored = await self._values.get_json(REMOVED_DEVICES)
        if not isinstance(stored, list):
            return frozenset()
        return frozenset(item for item in stored if isinstance(item, str))

    async def apply(self, message: KeysMessage, context: VaultContext) -> VaultKeyring | None:
        """Keyring to persist, or None when nothing is addressed to this device or the grant brings nothing new."""
        identity = context.device
        grant = message.grants.get(identity.device_id)
        if grant is None or message.vault_id != context.layout.vault_id:
            return None
        current = context.keyring.current_epoch
        if message.epoch > current + 1:
            raise IntegrityError("keys_epoch_gap")
        if message.epoch < current:
            raise IntegrityError("keys_epoch_stale")
        removed = await self.removed_device_ids()
        sender_key = await self._sender_public_key(message.sender_device_id, identity, removed)
        auth_payload = grant_auth_payload(message, recipient_device_id=identity.device_id, sealed=grant.sealed)
        if not self._crypto.verify_grant_auth(identity, sender_key, auth_payload, grant.auth):
            raise IntegrityError("keys_grant_auth")
        try:
            sealed = b64url_decode(grant.sealed)
            opened = self._crypto.open_sealed(identity, sealed, aad=message.vault_id.encode("utf-8"))
            granted = self._crypto.keyring_from_bytes(opened)
        except ValidationFailedError:
            raise IntegrityError("keys_grant") from None
        merged = merge_granted_keyring(context.keyring, granted, epoch=message.epoch)
        await self._record_removals(message.removed_device_ids, removed)
        return merged

    async def removes_this_device(self, message: KeysMessage, context: VaultContext) -> bool:
        """A rotation past this device's epoch, by another active registry device, that leaves this device out.

        No tag in such a message is addressed to this device, so only the sender rules can be checked; anyone
        able to post to the Sync channel can already deny service by deleting it, so a forged removal costs
        nothing more than a re-pairing.
        """
        identity = context.device
        if message.vault_id != context.layout.vault_id or message.sender_device_id == identity.device_id:
            return False
        if message.epoch <= context.keyring.current_epoch:
            return False
        if identity.device_id in message.grants and identity.device_id not in message.removed_device_ids:
            return False
        try:
            await self._sender_public_key(message.sender_device_id, identity, await self.removed_device_ids())
        except IntegrityError:
            return False
        return True

    async def _sender_public_key(self, sender_id: str, identity: DeviceIdentity, removed: frozenset[str]) -> bytes:
        if sender_id in removed:
            raise IntegrityError("keys_sender_removed")
        if sender_id == identity.device_id:
            return identity.public_key
        sender = await self._devices.get(sender_id)
        if sender is None:
            raise IntegrityError("keys_sender_unknown")
        if not sender.active:
            raise IntegrityError("keys_sender_removed")
        try:
            return decode_public_key(sender.public_key)
        except ValidationFailedError:
            raise IntegrityError("keys_sender_unknown") from None

    async def _record_removals(self, device_ids: tuple[str, ...], known: frozenset[str]) -> None:
        if not device_ids:
            return
        if not set(device_ids) <= known:
            await self._values.set_json(REMOVED_DEVICES, sorted(known | set(device_ids)))
        now = self._clock.now()
        for device_id in device_ids:
            device = await self._devices.get(device_id)
            if device is not None and device.removed_at is None and not device.current:
                await self._devices.save(replace(device, removed_at=now))


def _check_ids(message: KeysMessage, recipients: Mapping[str, Any]) -> None:
    removed = set(message.removed_device_ids)
    if message.sender_device_id in removed or removed & set(recipients):
        raise ValidationFailedError("A keys message cannot grant keys to or come from a removed device")


def _is_epoch(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def is_device_id(value: object) -> bool:
    """`dev_<suffix>`, the only device ids a keys message may name."""
    return isinstance(value, str) and value.startswith(_DEVICE_ID_PREFIX) and len(value) > len(_DEVICE_ID_PREFIX)


def _is_grant(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == _GRANT_FIELDS
        and all(isinstance(value[name], str) and value[name] for name in _GRANT_FIELDS)
    )
