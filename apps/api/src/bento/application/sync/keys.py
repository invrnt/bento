"""`keys` messages (architecture § Keys messages): rotated keyrings granted per device.

```json
{"bento": "keys", "v": 1, "vault_id": "vlt_…", "epoch": 2,
 "grants": {"dev_ab12": "<b64url seal_for_device(public_key, keyring_bytes, aad=vault_id)>"}}
```
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from bento.domain.errors import IntegrityError, ValidationFailedError
from bento.domain.security import VaultKeyring

KEYS_MARKER = "keys"
KEYS_VERSION = 1


@dataclass(frozen=True, slots=True)
class KeysMessage:
    vault_id: str
    epoch: int
    grants: Mapping[str, str]


def parse_keys_message(payload: bytes) -> KeysMessage:
    try:
        data = json.loads(bytes(payload).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ValidationFailedError("Invalid keys message") from None
    if not isinstance(data, dict) or data.get("bento") != KEYS_MARKER or data.get("v") != KEYS_VERSION:
        raise ValidationFailedError("Invalid keys message")
    vault_id, epoch, grants = data.get("vault_id"), data.get("epoch"), data.get("grants")
    if not isinstance(vault_id, str) or not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 1:
        raise ValidationFailedError("Invalid keys message")
    if not isinstance(grants, dict) or not all(
        isinstance(device, str) and isinstance(grant, str) for device, grant in grants.items()
    ):
        raise ValidationFailedError("Invalid keys message")
    return KeysMessage(vault_id=vault_id, epoch=epoch, grants=dict(grants))


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
