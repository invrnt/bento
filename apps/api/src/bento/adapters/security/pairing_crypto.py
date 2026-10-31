"""Pairing cryptography (architecture/telegram-first.md § Pairing Protocol, pairing-relay-contract § Inner protocol).

Every session method produces or consumes a complete relay binary frame `type u8 || payload`:

```txt
0x01 || SPAKE2 message            SPAKE2_A (host) / SPAKE2_B (guest), idA=b"bento-host", idB=b"bento-guest"
0x02 || HMAC-SHA256(K, label)     label = b"host-confirm" (host) | b"guest-confirm" (guest), 33 bytes total
0x03 || AES-256-GCM(dir_key, nonce = 4 zero bytes || u64 BE counter, canonical JSON), no AAD
dir_key = HKDF-SHA256(K, salt=None, info="bento/v1/pairing/h2g" | "bento/v1/pairing/g2h")
SAS     = 4 x 6 bits of HKDF-SHA256(K, salt=None, info="bento/v1/pairing/sas", length=3) over SAS_EMOJIS
```

Counters are implicit: they start at 0 per direction, are never sent, and advance by one per frame,
so replayed, reordered, dropped or reflected frames fail authentication. Any failure poisons the
session; callers must abort and burn the code.
"""

from __future__ import annotations

import json
import os
from typing import Any, NoReturn

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.constant_time import bytes_eq
from spake2 import SPAKE2_A, SPAKE2_B

from bento.adapters.security.primitives import KEY_BYTES, TAG_BYTES, RandomBytes, hkdf_sha256, hmac_sha256
from bento.domain.errors import IntegrityError, ValidationFailedError
from bento.domain.pairing import PairingRole
from bento.domain.vault import canonical_json

HOST_ID = b"bento-host"
GUEST_ID = b"bento-guest"
FRAME_SPAKE2 = 0x01
FRAME_CONFIRMATION = 0x02
FRAME_MESSAGE = 0x03
MAX_FRAME_BYTES = 64 * 1024
"""Relay limit per binary frame (pairing-relay-contract § Frames)."""

SAS_EMOJIS: tuple[str, ...] = (
    "\U0001f436",  # 0  dog face
    "\U0001f431",  # 1  cat face
    "\U0001f981",  # 2  lion
    "\U0001f434",  # 3  horse face
    "\U0001f984",  # 4  unicorn
    "\U0001f437",  # 5  pig face
    "\U0001f418",  # 6  elephant
    "\U0001f430",  # 7  rabbit face
    "\U0001f43c",  # 8  panda
    "\U0001f413",  # 9  rooster
    "\U0001f427",  # 10 penguin
    "\U0001f422",  # 11 turtle
    "\U0001f41f",  # 12 fish
    "\U0001f419",  # 13 octopus
    "\U0001f98b",  # 14 butterfly
    "\U0001f337",  # 15 tulip
    "\U0001f333",  # 16 deciduous tree
    "\U0001f335",  # 17 cactus
    "\U0001f344",  # 18 mushroom
    "\U0001f30d",  # 19 globe
    "\U0001f319",  # 20 crescent moon
    "\U0001f308",  # 21 rainbow
    "\U0001f525",  # 22 fire
    "\U0001f34c",  # 23 banana
    "\U0001f34e",  # 24 red apple
    "\U0001f353",  # 25 strawberry
    "\U0001f33d",  # 26 ear of corn
    "\U0001f355",  # 27 pizza
    "\U0001f382",  # 28 birthday cake
    "\U0001f369",  # 29 doughnut
    "\U0001f41d",  # 30 honeybee
    "\U0001f916",  # 31 robot
    "\U0001f3a9",  # 32 top hat
    "\U0001f453",  # 33 glasses
    "\U0001f527",  # 34 wrench
    "\U0001f33b",  # 35 sunflower
    "\U0001f438",  # 36 frog
    "\U0001f302",  # 37 closed umbrella
    "⌛",  # 38 hourglass
    "⏰",  # 39 alarm clock
    "\U0001f381",  # 40 gift
    "\U0001f4a1",  # 41 light bulb
    "\U0001f4d5",  # 42 closed book
    "\U0001f347",  # 43 grapes
    "\U0001f4ce",  # 44 paperclip
    "⭐",  # 45 star
    "\U0001f512",  # 46 lock
    "\U0001f511",  # 47 key
    "\U0001f528",  # 48 hammer
    "\U0001f4de",  # 49 telephone receiver
    "⛵",  # 50 sailboat
    "\U0001f682",  # 51 locomotive
    "\U0001f6b2",  # 52 bicycle
    "\U0001f697",  # 53 automobile
    "\U0001f680",  # 54 rocket
    "\U0001f3c6",  # 55 trophy
    "⚽",  # 56 soccer ball
    "\U0001f3b8",  # 57 guitar
    "\U0001f3ba",  # 58 trumpet
    "\U0001f514",  # 59 bell
    "⚓",  # 60 anchor
    "\U0001f3a7",  # 61 headphone
    "\U0001f4c1",  # 62 file folder
    "\U0001f4cc",  # 63 pushpin
)
"""Fixed SAS alphabet: 64 distinct single-code-point emoji with default emoji presentation
(no variation selectors, people, skin tones or flags). Index order is part of the protocol."""

_CONFIRM_LABELS = {PairingRole.HOST: b"host-confirm", PairingRole.GUEST: b"guest-confirm"}
_DIRECTION_INFO = {PairingRole.HOST: b"bento/v1/pairing/h2g", PairingRole.GUEST: b"bento/v1/pairing/g2h"}
_SAS_INFO = b"bento/v1/pairing/sas"
_FALLBACK_SAS_INFO = b"bento/v1/pairing/fallback-sas"
_COUNTER_LIMIT = 1 << 64
_NONCE_PAD = bytes(4)

assert len(SAS_EMOJIS) == 64 and len(set(SAS_EMOJIS)) == 64


def sas_from_bits(bits: bytes) -> tuple[str, str, str, str]:
    """Map 24 bits (big-endian) to four emoji, most significant 6 bits first."""
    if len(bits) != 3:
        raise ValidationFailedError("SAS input must be 3 bytes")
    value = int.from_bytes(bits, "big")
    return (
        SAS_EMOJIS[(value >> 18) & 63],
        SAS_EMOJIS[(value >> 12) & 63],
        SAS_EMOJIS[(value >> 6) & 63],
        SAS_EMOJIS[value & 63],
    )


class PairingCryptoSession:
    """One side of a relay pairing (`PairingCryptoSessionPort`). Single use; not thread-safe."""

    def __init__(self, role: PairingRole, password: bytes, *, random_bytes: RandomBytes = os.urandom) -> None:
        if not isinstance(password, bytes) or not password:
            raise ValidationFailedError("Pairing password is required")
        self._role = PairingRole(role)
        spake_class = SPAKE2_A if self._role is PairingRole.HOST else SPAKE2_B
        self._spake: SPAKE2_A | SPAKE2_B | None = spake_class(
            password, idA=HOST_ID, idB=GUEST_ID, entropy_f=random_bytes
        )
        self._started = False
        self._failed = False
        self._peer_confirmed = False
        self._own_confirmation = b""
        self._peer_confirmation = b""
        self._sas_bits = b""
        self._send: AESGCM | None = None
        self._receive: AESGCM | None = None
        self._send_counter = 0
        self._receive_counter = 0

    def __repr__(self) -> str:
        return f"PairingCryptoSession(role={self._role.value}, state={self._state()})"

    def start(self) -> bytes:
        self._ensure_alive()
        if self._started or self._spake is None:
            raise ValidationFailedError("Pairing handshake was already started")
        self._started = True
        message: bytes = self._spake.start()
        return bytes((FRAME_SPAKE2,)) + message

    def finish(self, peer_message: bytes) -> None:
        self._ensure_alive()
        if not self._started or self._spake is None:
            raise ValidationFailedError("Pairing handshake is not in progress")
        spake, self._spake = self._spake, None
        frame = bytes(peer_message)
        if len(frame) < 2 or frame[0] != FRAME_SPAKE2:
            self._fail("pairing")
        try:
            shared = spake.finish(frame[1:])
        except Exception:
            self._fail("pairing")
        peer = PairingRole.GUEST if self._role is PairingRole.HOST else PairingRole.HOST
        self._own_confirmation = hmac_sha256(shared, _CONFIRM_LABELS[self._role])
        self._peer_confirmation = hmac_sha256(shared, _CONFIRM_LABELS[peer])
        self._send = AESGCM(hkdf_sha256(shared, salt=None, info=_DIRECTION_INFO[self._role]))
        self._receive = AESGCM(hkdf_sha256(shared, salt=None, info=_DIRECTION_INFO[peer]))
        self._sas_bits = hkdf_sha256(shared, salt=None, info=_SAS_INFO, length=3)

    def confirmation(self) -> bytes:
        self._ensure_keys()
        return bytes((FRAME_CONFIRMATION,)) + self._own_confirmation

    def verify_peer_confirmation(self, confirmation: bytes) -> None:
        self._ensure_keys()
        frame = bytes(confirmation)
        if len(frame) != 1 + len(self._peer_confirmation) or frame[0] != FRAME_CONFIRMATION:
            self._fail("pairing_confirmation")
        if not bytes_eq(frame[1:], self._peer_confirmation):
            self._fail("pairing_confirmation")
        self._peer_confirmed = True

    def sas(self) -> tuple[str, str, str, str]:
        self._ensure_keys()
        return sas_from_bits(self._sas_bits)

    def encrypt_message(self, payload: dict[str, Any]) -> bytes:
        aead = self._ensure_confirmed(self._send)
        if not isinstance(payload, dict):
            raise ValidationFailedError("Pairing message must be a JSON object")
        try:
            encoded = canonical_json(payload)
        except (TypeError, ValueError):
            raise ValidationFailedError("Pairing message must be JSON serializable") from None
        if 1 + len(encoded) + TAG_BYTES > MAX_FRAME_BYTES:
            raise ValidationFailedError("Pairing message is too large")
        if self._send_counter >= _COUNTER_LIMIT:
            self._fail("pairing_frame")
        nonce = _NONCE_PAD + self._send_counter.to_bytes(8, "big")
        self._send_counter += 1
        return bytes((FRAME_MESSAGE,)) + aead.encrypt(nonce, encoded, None)

    def decrypt_message(self, frame: bytes) -> dict[str, Any]:
        aead = self._ensure_confirmed(self._receive)
        data = bytes(frame)
        if len(data) < 1 + TAG_BYTES or len(data) > MAX_FRAME_BYTES or data[0] != FRAME_MESSAGE:
            self._fail("pairing_frame")
        if self._receive_counter >= _COUNTER_LIMIT:
            self._fail("pairing_frame")
        nonce = _NONCE_PAD + self._receive_counter.to_bytes(8, "big")
        try:
            plaintext = aead.decrypt(nonce, data[1:], None)
        except InvalidTag:
            self._fail("pairing_frame")
        self._receive_counter += 1
        try:
            message = json.loads(plaintext.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            self._fail("pairing_frame")
        if not isinstance(message, dict):
            self._fail("pairing_frame")
        return message

    def _state(self) -> str:
        if self._failed:
            return "failed"
        if self._peer_confirmed:
            return "confirmed"
        if self._send is not None:
            return "keyed"
        return "started" if self._started else "new"

    def _fail(self, what: str) -> NoReturn:
        self._failed = True
        self._spake = None
        self._send = self._receive = None
        self._own_confirmation = self._peer_confirmation = self._sas_bits = b""
        raise IntegrityError(what) from None

    def _ensure_alive(self) -> None:
        if self._failed:
            raise IntegrityError("pairing")

    def _ensure_keys(self) -> None:
        self._ensure_alive()
        if self._send is None:
            raise ValidationFailedError("Pairing handshake is not finished")

    def _ensure_confirmed(self, aead: AESGCM | None) -> AESGCM:
        self._ensure_keys()
        if not self._peer_confirmed or aead is None:
            raise ValidationFailedError("Pairing peer is not confirmed")
        return aead


class FallbackPairingKeys:
    """Ephemeral X25519 key for Sync-channel pairing (`FallbackPairingKeysPort`).

    SAS = 4 x 6 bits of HKDF-SHA256(X25519(own, peer), salt=min(pubA, pubB) || max(pubA, pubB),
    info="bento/v1/pairing/fallback-sas", length=3).
    """

    def __init__(self, *, random_bytes: RandomBytes = os.urandom) -> None:
        self._private = X25519PrivateKey.from_private_bytes(random_bytes(KEY_BYTES))
        self._public = self._private.public_key().public_bytes_raw()

    def __repr__(self) -> str:
        return "FallbackPairingKeys()"

    def public_key(self) -> bytes:
        return self._public

    def sas_with(self, peer_public_key: bytes) -> tuple[str, str, str, str]:
        peer = bytes(peer_public_key)
        if len(peer) != KEY_BYTES or bytes_eq(peer, self._public):
            raise IntegrityError("pairing")
        try:
            shared = self._private.exchange(X25519PublicKey.from_public_bytes(peer))
        except ValueError:
            raise IntegrityError("pairing") from None
        salt = b"".join(sorted((self._public, peer)))
        return sas_from_bits(hkdf_sha256(shared, salt=salt, info=_FALLBACK_SAS_INFO, length=3))


class PairingCryptoFactory:
    """`PairingCryptoFactoryPort`. `random_bytes` is injectable only for known-answer tests."""

    def __init__(self, *, random_bytes: RandomBytes = os.urandom) -> None:
        self._random = random_bytes

    def __repr__(self) -> str:
        return "PairingCryptoFactory()"

    def host_session(self, password: bytes) -> PairingCryptoSession:
        return PairingCryptoSession(PairingRole.HOST, password, random_bytes=self._random)

    def guest_session(self, password: bytes) -> PairingCryptoSession:
        return PairingCryptoSession(PairingRole.GUEST, password, random_bytes=self._random)

    def fallback_keys(self) -> FallbackPairingKeys:
        return FallbackPairingKeys(random_bytes=self._random)
