# Telegram-First Architecture

Status: binding contract for Stages 14-18. It supersedes the Bot API storage design in `product/storage-telegram.md` and the "multi-PC sync" non-goal.

## Decisions

- Bento connects to the user's own Telegram account through MTProto using **Telethon 1.x** (pure Python, PyInstaller friendly). The Bot API, BotFather setup, `telegram-bot-api` server, webhook, and aiogram are removed.
- Bento ships its own `api_id`/`api_hash` as build configuration (`BENTO_TELEGRAM_API_ID`, `BENTO_TELEGRAM_API_HASH`). Users never see them. Dev builds read the same environment variables.
- A **vault** is a set of private channels created and owned by the user's account. Every device is an independent Telegram authorization plus a local SQLite replica.
- Telegram is the blob store **and** the replication transport. Local SQLite remains the per-device source of truth for reads; the encrypted Sync channel is the replication log.
- Everything that leaves the device is encrypted. Telegram learns ciphertext sizes and timing only. Filenames, folder names, MIME types, metadata, OCR text, and embeddings never leave in plaintext.
- Device pairing uses an end-to-end encrypted handshake (SPAKE2 + AES-GCM) through a stateless **pairing relay** (Cloudflare Worker + Durable Object, `apps/relay`) or, as fallback, through the Sync channel itself.
- No backend database is hosted. The relay keeps only ephemeral in-memory/DO room state for at most 10 minutes.
- Storage backends after this program: `local` (device only, no sync) and `telegram` (MTProto vault). `fake` is a filesystem-backed Telegram simulator for development, demos, and multi-process tests; it is never selectable in packaged release builds.

## Telegram Terms Compliance

- Product name never contains "Telegram". UI copy says "conecta tu cuenta de Telegram" and the about/legal pages state that Bento uses the Telegram API.
- Each build uses Bento's own `api_id`. Never use data from Telegram to train or fine-tune models; local OCR/embeddings index the user's own files only.
- Enforcement: `assets.origin` (device-local, never synced; migration `0005`) is `device`, `telegram_inbox`, or `telegram_import`, and NULL for assets received from other devices. Only `device` assets get OCR/embedding jobs (upload, reindex) and the OCR/embedding services refuse any other origin when a job runs. Filename, type, and date search keep working for every asset.
- Respect `FLOOD_WAIT_X` and slow mode; never parallelize beyond the policy below; never automate actions on chats the user did not choose.

## Process Topology

```txt
Electron main ──► API sidecar (FastAPI)  ─┐
              └─► worker sidecar          ├─► Telethon client (one per process, same session)
                                           └─► local SQLite + data dir
API/worker ──► pairing relay (wss, optional, only during pairing)
```

- One Telethon session file per device. API and worker each open a client on the same session; Telethon's SQLite session must not be shared concurrently, so the session is persisted as a `StringSession` in the key store and each process creates an in-memory `StringSession` copy. Only the worker runs long-lived update handlers (sync pull, inbox). The API performs request/response calls (login, share, import listing, pairing).
- Login happens in the API process. After authorization, the API stores the new session string in the key store and asks the worker to reload (job `account_reload`).

## Key Store (`KeyStorePort`)

Secrets created at runtime (Telegram session, vault keyring, device private key) never travel through the renderer or HTTP.

- `WrappedFileKeyStore` persists each named secret as `data/secure/<name>.bin` = AES-256-GCM(device_wrapping_key, value, aad=name), mode `0600`, atomic replace.
- Desktop: Electron main generates a 32-byte `BENTO_DEVICE_WRAPPING_KEY` on first launch, stores it with `safeStorage`, and passes it to sidecars in the spawn environment only.
- Headless: `BENTO_DEVICE_WRAPPING_KEY` env var; if absent, generate `data/secure/wrapping.key` (`0600`) and report a `doctor` warning ("protege esta carpeta").
- Names: `telegram.session`, `vault.keyring`, `device.identity` (X25519 private key + device id), `pairing.pending` (transient).

## Vault Layout In Telegram

Created by `VaultTransportPort.create_vault` with `channels.CreateChannelRequest(broadcast=True)`:

| Role | Title | About marker | Visibility |
|---|---|---|---|
| files | `Bento · Archivos` | `bento:v1:files:<vault_id>` | muted, archived |
| sync | `Bento · Sync` | `bento:v1:sync:<vault_id>` | muted, archived |
| inbox | `Bento · Bandeja` | `bento:v1:inbox:<vault_id>` | muted, not archived |

- All three channels are added to a chat folder titled `Bento` (`messages.UpdateDialogFilterRequest`).
- About text also contains a human line: "Creado por Bento. No borres ni edites estos mensajes."
- Discovery: iterate dialogs, keep channels where the user is creator and the title starts with `Bento`, then read the full channel `about` and match markers. One vault per account in v1; if several exist, report the others in status. `created_at` is unauthenticated until the MAC is checked, so it only orders candidates: headers with naive (timezone-less) timestamps are not candidates, a device holding a keyring picks the newest candidate whose MAC its keyring verifies, and a recovery unlock tries every candidate (newest first) and opens the one whose wrap the code unwraps and whose MAC the unwrapped keyring verifies at its own current epoch.

## Cryptography

All primitives come from `cryptography` (already a dependency) and `spake2`.

### Keyring

- Vault master key `VMK_e`: 32 random bytes per key epoch `e` (starting at 1).
- Keyring: `{"vault_id": str, "current_epoch": int, "keys": {"<epoch>": base64url(VMK)}}` serialized as canonical JSON (sorted keys, no spaces).
- Subkeys: `HKDF-SHA256(ikm=VMK_e, salt=vault_id_utf8, info="bento/v1/<purpose>", length=32)` with purposes `blob`, `sync`, `snapshot`, `header-mac`, `device-record`.

### Envelope (`seal`/`open`) for sync batches, snapshots, inbox state, device records

```txt
"BENV" | version u8 = 1 | purpose u8 | epoch u32 BE | nonce 12B | AES-256-GCM(ciphertext || tag 16B)
AAD = the 22-byte prefix (magic..nonce) || caller aad
```

Purpose codes: `1=sync`, `2=snapshot`, `3=device-record`, `4=pairing`. Payloads are zlib-compressed JSON before sealing.

### Blob format v2 (streaming AEAD)

Used for every original, thumbnail, and preview uploaded to Telegram.

```txt
header = "BNT2" | version u8 = 2 | epoch u32 BE | file_salt 16B | segment_size u32 BE | nonce_prefix 7B   (36 bytes)
file_key = HKDF-SHA256(ikm=blob_subkey(epoch), salt=file_salt, info="bento/v1/blob-file", length=32)
segment i (0-based) = AES-256-GCM(file_key, nonce = nonce_prefix || u32 BE(i) || u8(last ? 1 : 0), aad = header) → ciphertext || tag
```

- `segment_size` default 1 MiB (1,048,576). Every segment except the last carries exactly `segment_size` plaintext bytes. Empty plaintext produces one final empty segment.
- Ciphertext offset of segment `i` = `36 + i * (segment_size + 16)`. This enables range decryption for video streaming and resumable/partial downloads.
- Reordering, truncation, and extension are detected by the index and last-flag nonce construction.
- The plaintext sha256 is stored in the catalog and verified after full decryption.
- The header carries a random `file_salt`, so `cipher_header_sha256` = b64url SHA-256 of the 36-byte header names one encryption of one file. It is set on upload, synced in the `blob` op, and every remote download and range read compares it (constant time) before decrypting a segment: a ciphertext swapped for another file sealed with the same vault keys fails with `IntegrityError("blob_header")`, also on range reads where the plaintext sha256 is never checked. Refs synced before the field existed (NULL) are not compared.
- Legacy v1 (`BENTOENC\x01`, single GCM stream) stays decryptable; it is never written again.

### Recovery code

- 20 random bytes (160 bits) + 20-bit checksum (first 20 bits of SHA-256 of the secret) = 180 bits, Crockford Base32 (36 chars), shown as 9 groups of 4: `K7QM-3XRA-...`.
- Parsing upper-cases, ignores spaces/dashes, maps `O→0`, `I/L→1`, and rejects bad checksums with a "revisa el código" error.
- `recovery_wrap_key = HKDF-SHA256(ikm=secret, salt="bento/v1/recovery", info=vault_id, length=32)`; the header stores `AES-256-GCM(recovery_wrap_key, keyring_json)` with AAD `vault_id`.
- Devices never persist the recovery secret. Rotating keys requires generating a new recovery code (see Devices).

### Device identity and sealed boxes

- Each device has an X25519 key pair and a `device_id` (`dev_<uuid4 hex>`).
- `seal_for_device(recipient_pub, plaintext, aad)`: ephemeral X25519, `HKDF(shared, salt=eph_pub||recipient_pub, info="bento/v1/sealed-box")`, AES-256-GCM with random nonce. Output `"BBOX" | version u8 | eph_pub 32B | nonce 12B | ciphertext||tag`.

### Header

The Sync channel's pinned message is a JSON text message (≤ 4096 chars):

```json
{"bento": "vault-header", "v": 1, "vault_id": "vlt_...", "created_at": "ISO-8601",
 "layout": {"files": <channel_id>, "sync": <channel_id>, "inbox": <channel_id>},
 "current_epoch": 1,
 "recovery": {"alg": "hkdf-aesgcm-v1", "nonce": "b64url", "wrapped_keyring": "b64url", "confirmed_at": "ISO-8601 (optional)"},
 "snapshot": {"message_id": 123, "covers_through_message_id": 456, "created_at": "ISO-8601"} | null,
 "mac": "b64url HMAC-SHA256(header-mac subkey, canonical JSON without mac)"}
```

- New headers are posted and pinned; older header messages are then deleted (best effort, resumable cursor per device) because they carry the keyring wrapped by superseded recovery codes. The current header and newer ones are never deleted.
- `recovery.confirmed_at` (optional ISO-8601, MAC-covered, omitted while unset) records that the current recovery code was saved (kit confirmation or an unlock with the code). It is vault-wide: every device reports `recovery_kit_saved` from it, and every new wrap (rotation, device removal) starts without it.
- Devices with a keyring verify the MAC and ignore headers with invalid MACs. A device that unlocks via recovery code verifies the MAC after unwrapping, at the epoch the wrap opened (`header.current_epoch == keyring.current_epoch`).
- **Current header**: bootstrap, recovery kit status, and `read_header` accept the pinned header only when it is MACed with this device's current epoch; removed devices keep older epochs and can MAC and pin older headers.
- `update_header` builds on the pinned header at the current epoch, or one epoch back only when the mutation brings a fresh recovery wrap (the device that rotated, or anyone generating a new kit after an unfinished rotation). It never carries `recovery` forward from an older-epoch header (that wrap holds a keyring without the current key): such an update fails with `IntegrityError("vault_header_stale")`, and status reports `recovery_kit_saved: false, recovery_kit_stale: true` (Activity `recovery_kit` item with `params.reason = "stale"`: "genera un nuevo kit"). An older-epoch base keeps its `snapshot` pointer only when this process verified that header while its epoch was current (the rotating device reads it right before rotating); otherwise the pointer is dropped and new devices replay the Sync channel until the next snapshot.

## Sync Protocol

### Entities and synced fields

| Entity | Key | Synced fields |
|---|---|---|
| `folder` | folder id | `name`, `parent_id`, `created_at`, `deleted_at` |
| `asset` | asset id | `kind`, `mode`, `folder_id`, `filename`, `original_filename`, `mime_type`, `size_bytes`, `sha256`, `taken_at`, `exif`, `favorite`, `created_at`, `deleted_at` |
| `album` | album id | `title`, `created_at`, `deleted_at` |
| `album_item` | `<album_id>:<asset_id>` | `album_id`, `asset_id`, `created_at`, `removed` |
| `blob` | blob id | `asset_id`, `kind`, `size_bytes`, `sha256`, `encryption_mode`, `key_epoch`, `format_version`, `cipher_header_sha256`, `parts` (list of `{index, channel_id, message_id, size_bytes}`) |
| `thumbnail` | thumbnail id | `asset_id`, `blob_id`, `width`, `height` |
| `asset_index` | asset id | `ocr_text`, `pdf_pages` (list), `language`, `embedding` (`{provider, dimensions, vector_b64_f32}` or null) |
| `device` | device id | `name`, `platform`, `public_key`, `telegram_auth_hash`, `added_at`, `removed_at` |

`processing_state`, `origin`, the device rows' `introduced_by`/`first_seen_at`/`reviewed_at`, jobs, local cache paths, settings, and search index tables are device-local and never synced. Peers create received assets as `indexed`; the uploading device settles each asset to `indexed` (or `failed_partial` after a step failed for good) once no thumbnail/OCR/embedding job is left for it.

### Operations

```json
{"op": "<uuid4>", "hlc": "0001730000000000-000042-dev_ab12", "device": "dev_ab12",
 "entity": "asset", "id": "asset_...", "kind": "upsert|purge",
 "fields": {"filename": "a.jpg", "favorite": true}}
```

- **HLC**: `<16-digit zero-padded unix ms>-<6-digit counter>-<device_id>`; string comparison equals causal order with device id tiebreak. Each device persists its last HLC and advances on every local op and on every received op. The physical part is at most `9999999999999999`; ticks saturate there instead of overflowing the format.
- **Bounded remote clocks**: a remote op is skipped (integrity warning, `sync_state.skipped_ops` += 1, the batch and cursor still advance) when its HLC is malformed or its physical time exceeds `min(Sync message date, local wall clock) + 5 min`. Snapshot fields whose clock exceeds `min(snapshot created_at, local clock) + 5 min` (and such purge records) are dropped. One poisoned op can therefore never freeze an entity on every device.
- **Repair**: a stored field clock or device HLC that is malformed or beyond `local clock + 5 min` (written before the bound existed) counts as absent: the next genuine remote or local op overwrites it, and local ticks clamp the device HLC to the wall clock, so local writes never fail on a bad stored clock. A device whose wall clock jumps back by more than 5 minutes resets its HLC to wall time (peers would reject its old clocks anyway).
- **Merge**: last-writer-wins per field. A field is applied only if `op.hlc > field_clock(entity, id, field)`. Deletion is the `deleted_at` field (trash), so a concurrent rename and delete both apply; restore sets `deleted_at = null` with a newer HLC.
- **Purge** is terminal: removes the entity locally, records `(entity, id, hlc)` in `sync_purged`, and ignores any later op for it.
- **Folder cycles**: applying a `parent_id` that would create a cycle (or points to a purged/missing folder) moves the folder to the root and records a local notice; the op still advances clocks so every device converges identically.
- **Duplicate content**: two devices uploading the same sha256 concurrently produce two assets; nothing is merged automatically. The UI offers "duplicados" cleanup later.
- **Missing references** (asset in unknown folder, blob for unknown asset) are applied as-is; readers treat unknown parents as root until the parent arrives.
- **Device registry** (the trust anchor of key grants, so stricter than LWW): a registered non-empty `public_key` never changes through sync; this device's own row only takes `removed_at` from peers; `device` purges (ops and snapshot tombstones) are ignored; `removed_at = null` is ignored for ids in `sync_state.removed_device_ids`. A row first created on this device by sync data records `introduced_by` (the sending device, or the snapshot's creator), `first_seen_at`, and `reviewed_at` (set immediately for snapshot rows and rows seen while bootstrapping, which predate this device). Active rows with `introduced_by` set and no `reviewed_at` raise an Activity `new_device` item until `POST /devices/{id}/acknowledge`.

### Change capture

- A SQLAlchemy `before_flush` listener installed on the session factory captures inserts/updates/deletes of `FolderModel`, `AssetModel`, `AlbumModel`, `AlbumAssetModel`, `BlobRefModel`, `BlobPartModel`, and `ThumbnailModel`, diffs changed synced columns, assigns an HLC, and inserts rows into `sync_outbox` in the same transaction.
- Sessions that apply remote ops set `session.info["sync_apply"] = True`; the listener skips them, so remote ops never echo.
- `asset_index` ops are emitted explicitly by the OCR and embedding application services after a successful index write.
- Capture is disabled when the vault is not configured (storage `local`) so local-only users pay nothing.

### Batches

- The worker's sync loop flushes `sync_outbox` when it holds ≥1 op and the oldest op is ≥3 s old, or ≥256 ops, or ≥512 KiB of JSON.
- Batch payload: `{"bento": "sync-batch", "v": 1, "batch": "<uuid4>", "device": "<device_id>", "ops": [...]}` → zlib → `seal(purpose=sync, epoch=current)` → uploaded as a document named `<uuid4>.bsync` to the Sync channel. Outbox rows are deleted only after Telegram confirms the message.
- Pull: list Sync messages with `id > last_applied_message_id` in ascending order, download `.bsync` documents, open, skip batches whose `device` is self (but advance the cursor), apply ops in HLC order inside one `sync_apply` transaction per batch, record `batch` ids in `sync_applied_batches` for idempotency, then advance the cursor.
- Untrusted input limits: the listed `size_bytes` is checked before downloading (batch 8 MiB, keys 1 MiB, snapshot 512 MiB) and the transport re-checks the fetched message's document size before downloading (a message can be edited). A batch is inflated to at most 16 MiB of JSON. The epoch floor is checked on the envelope's public prefix before decrypting. A message that can never be processed (too large, malformed, unauthenticated, below the floor, rejected grant) is passed over: the cursor advances and `sync_state.skipped_messages` / `last_skipped {message_id, kind, reason, at}` record it; transient transport errors still retry.
- Own batches: after Telegram confirms a batch, its message id is kept in `sync_state.own_batch_message_ids` until pulled. Own batches are skipped without decrypting; an own batch that lands below the floor is the only below-floor batch that is decrypted, and its ops are queued again under the current epoch.
- Real time: the worker subscribes to new-message updates for the Sync and Inbox channels; it also polls every 30 s and on network regain.

### Snapshots

- Created by the worker after 2,000 applied ops or 24 h since the last snapshot, whichever comes first, only if this device has applied everything up to the current tip.
- Payload: JSON lines of every synced entity's full current fields **plus field clocks** and the purge list, zlib, `seal(purpose=snapshot)`, uploaded as `<uuid4>.bsnap`; then a new header points to it with `covers_through_message_id`.
- Bootstrap of a new device: read header (current epoch only) → unlock keyring → download snapshot → apply with clocks → set the epoch floor to `(snapshot envelope epoch, covers_through_message_id)` → pull ops after `covers_through_message_id` → enqueue thumbnail downloads lazily. Search indexes rebuild locally from `asset_index` data without re-running OCR/embeddings.
- Floor at bootstrap: a snapshot's creator held its sealing epoch `s` when it had processed everything through `covers` (keys are stored only after their keys message is posted), so batches sealed below `s` and posted after `covers` are not genuine. The sealing epoch, not the keyring's current epoch, is used: when the rotation came after `covers`, older-epoch batches between `covers` and the keys message are genuine, and the pull raises the floor when it reaches that keys message.
- A snapshot that fails to download within limits, open, or parse is counted as skipped and the device replays the Sync channel from the start instead (never retried in a loop).

### Rate and size policy

- One upload stream and one download stream per device by default (`telegram_parallel_transfers`, max 4). Batches and headers share a 1 message / 2 s budget per channel.
- The v2 ciphertext stream is split into parts of `telegram_part_size_mb` (default 512 MiB, max 1,950 MiB; 3,900 MiB allowed when `premium`). Each part is one document named `<random>.bpart`. Parts are byte slices of one continuous ciphertext stream, so a range read maps a ciphertext offset to `(part, offset_in_part)`.
- Uploads are resumable at part granularity: an `upload_sessions` row persists `file_salt`, `nonce_prefix`, epoch, and completed part message ids, so a restarted upload re-encrypts deterministically and skips completed parts.
- `FLOOD_WAIT_X` sleeps exactly `X` seconds plus jitter and surfaces "Telegram pidió esperar N min" in status when `X > 60`.

## Pairing Protocol

### Code format

`<nameplate>-<secret1>-<secret2>`: three groups of 4 Crockford Base32 chars, e.g. `K7Q2-MXR9-T4WA`. The nameplate (20 bits) addresses the relay room; the remaining 40 bits are the SPAKE2 password. Links: `bento://join?v=1&c=K7Q2-MXR9-T4WA`; web form `https://<site>/join#v=1&c=K7Q2-MXR9-T4WA` (fragment never reaches a server) whose page offers "Abrir Bento". QR codes encode the `bento://` link.

### Relay flow (preferred)

1. **Host** (existing device, Ajustes › Dispositivos › Añadir) creates a random nameplate and secret, connects `wss://<relay>/v1/rooms/<nameplate>?role=host`. On `nameplate_taken` it regenerates.
2. **Guest** (new device, "Ya uso Bento") enters/scans the code and connects with `role=guest`.
3. Both run SPAKE2 (`SPAKE2_A` host / `SPAKE2_B` guest, password = secret groups normalized, `idA=b"bento-host"`, `idB=b"bento-guest"`), then exchange key confirmations `HMAC-SHA256(K, "host-confirm"|"guest-confirm")`. Any mismatch aborts and burns the code.
4. Session keys: `HKDF(K, info="bento/v1/pairing/h2g" | "g2h")`; frames are AES-256-GCM with counter nonces. SAS: 4 emojis from `HKDF(K, info="bento/v1/pairing/sas")` over a fixed 64-emoji list (24 bits) shown on both screens.
5. Guest → host: `join_request {device_id, device_name, platform, public_key, app_version, telegram: {authorized: bool, login_token_b64?: str}}`. If the guest is not signed in to Telegram it starts a QR login and forwards the token, refreshing it with `login_token` frames before expiry (~30 s).
6. Host UI shows "¿Añadir «Portátil · Linux»?" with the same emojis. On approval:
   - If a login token is present, the host calls `auth.acceptLoginToken`. On `AUTH_TOKEN_EXPIRED` it sends `need_login_token`; on any other failure it sends `telegram_login_failed {reason}` and the guest shows its own Telegram QR (scan with phone), then sends `telegram_ready`.
   - Host sends `vault_grant {vault_id, layout, sealed_keyring}` where `sealed_keyring = seal_for_device(guest.public_key, keyring_json, aad=vault_id)`.
   - Host records the `device` entity (op) for the guest.
7. Guest stores keyring and layout, sends `done`, both close. Guest bootstraps from the snapshot.

### Sync-channel fallback

Used when the relay is unreachable or disabled. Requires the guest to sign in to Telegram first.

Commit-then-reveal prevents anyone with channel access (including Telegram) from grinding ephemeral keys to match the 24-bit SAS.

1. Guest posts plaintext JSON `pair_request {request_id, device_id, device_name, platform, public_key, commitment}` where `commitment = b64url(SHA-256("bento/v1/pair-commit" || eph_guest_pub || public_key || request_id))`.
2. Online devices show a non-blocking prompt. On "Revisar", the host posts `pair_offer {request_id, eph_pub: eph_host_pub}`.
3. The guest posts `pair_reveal {request_id, eph_pub: eph_guest_pub}`; the host verifies the commitment and rejects mismatches.
4. Both compute the SAS with `HKDF(X25519(eph_host, eph_guest), salt = SHA-256(request_id || public_key || eph_guest_pub || eph_host_pub), info = "bento/v1/pairing/fallback-sas")` and display the emojis.
5. After the user confirms the emojis match, the host posts `pair_grant {request_id, grant}` with `grant = b64url(nonce 12B || AES-256-GCM(grant_key, nonce, sealed_keyring, aad = request_id))`, where `grant_key = HKDF(X25519(eph_host, eph_guest), salt = the SAS transcript hash of step 4, info = "bento/v1/pairing/fallback-grant", length = 32)` and `sealed_keyring = seal_for_device(public_key, keyring_json, aad = request_id)` (defence in depth). The grant is therefore bound to the exchange whose SAS the user verified, not only to the public device key: the guest ignores grants that fail to decrypt (anyone with channel access can post one), then still checks that the granted keyring verifies the pinned header MAC before installing it. Requests expire after 15 minutes; the guest deletes its own pairing messages after completion.

### Recovery

A signed-in device with the recovery code unwraps the keyring from the header. This also works when no other device exists.

## Devices, Removal, Key Rotation

- Each device publishes its `device` entity after joining, including `telegram_auth_hash` from `account.GetAuthorizationsRequest` (current session).
- Removing a device (from any other device):
  0. `GET /devices/{id}/removal-preview` lists the active devices that would receive the new keys. Any device holding the vault keys can add registry rows through sync, so the person can leave unknown devices out (`exclude_device_ids`): they are marked removed too, listed in `removed_device_ids`, and get no grant; their Telegram sessions are not closed (a forged row may carry another device's session hash or model name).
  1. Mark `removed_at` (op).
  2. `account.ResetAuthorizationRequest(hash)`; if Telegram refuses because this session is too new, show "Podrás cerrarla desde Telegram › Dispositivos" and continue.
  3. Rotate: create `VMK_{e+1}`, post a `keys` message to Sync with `{epoch, grants: {device_id: seal_for_device(pub, keyring_json)}}` for every remaining active device, publish a new header wrapped with a **new recovery code**, and show the new recovery kit immediately (mandatory step).
  4. New data uses the new epoch. Copy explains that files the removed device already downloaded cannot be erased remotely.
  5. The rotating device records the new code's kit check (`VaultService.remember_recovery_kit`), so the person can confirm that kit with its last group.
- Devices apply `keys` messages addressed to them and keep all epochs.
- **Removed device**: a keys message for a newer epoch, from another active registry device (not removed, not this one), with no grant for this device or listing it in `removed_device_ids`, means this device was removed. Sync stops right before that message (it is read again after re-joining), the vault keyring is dropped from the key store (the local library stays), and `sync_state.device_removed = {device_id, epoch, message_id, by, at}` is set: `/vault` reports `locked` with `reason: "device_removed"`, `/sync/status` reports `paused` with `error.code = "device_removed"`, and Activity shows `device_removed` (action `open_settings`). Such a message cannot be authenticated by a device it leaves out; anyone who can post to the Sync channel can already deny service by deleting it, so a forged removal costs a re-pairing and nothing else.
- **Re-joining**: a device whose identity is removed (the `device_removed` flag names it, its own row has `removed_at`, or its id is in `removed_device_ids`) and that has no usable vault keys generates a fresh device identity before joining (pairing, recovery code); `install` does the same and clears the flag, so peers see a new device instead of re-activating a removed id.

## Inbox, Sharing, Import

- **Inbox**: anything posted or forwarded to `Bento · Bandeja` is imported by the worker: download → ingest as a normal upload (encrypt + store in Archivos) → react with ✅ on the inbox message → delete the inbox message after 24 h (setting `inbox_keep_hours`, default 24). Failures react with ⚠️ and appear in Actividad.
- **Share via Telegram**: user picks a recent chat/contact; the API decrypts the original locally and sends it as a document with the original filename. This is an explicit, user-initiated plaintext disclosure and is labelled as such.
- **Import**: Saved Messages and user-chosen chats list photos/videos/documents; selected items import as assets through the ingestion service (`telegram_import` job). Original messages are untouched.

## Fake Telegram Cloud

`adapters/fake_telegram/` implements every Telegram port on a directory (`BENTO_FAKE_TELEGRAM_DIR`, default `data/fake-telegram`): JSON message logs per channel, document files, pinned ids, chats, and an account. QR login auto-approves after 2 s (or immediately via `POST /api/dev/fake-telegram/approve-login` when `environment != production`). Two Bento instances pointing to the same directory behave like two devices of one account. It powers UI development, demos, and multi-device integration tests.

## Module Ownership Map (backend)

- `domain/`: `account.py`, `vault.py`, `sync.py`, `pairing.py`, `devices.py`, `backup.py`, `trash.py` (contracts); `security.py` (crypto).
- `ports/`: `telegram.py` (account, vault transport, chats), `sync.py`, `pairing.py`, `backup.py`, `trash.py` (contracts); `security.py`, `key_store.py` (crypto); `blob_store.py` (contracts extends).
- `adapters/security/` (crypto), `adapters/fake_telegram/` (platform), `adapters/telegram_mtproto/` + `infrastructure/mtproto/` (mtproto), `adapters/sync/` + `application/sync/` (sync), `adapters/pairing/` + `application/pairing.py` + `application/devices.py` + `application/recovery.py` (pairing), `adapters/backup/` + `application/backup.py` + `application/trash.py` (backup), `application/account.py` + `application/vault.py` + `application/sharing.py` + `application/telegram_import.py` + `application/inbox.py` (mtproto).
- See `execution/telegram-first-program.md` for stage ownership of shared files.

## Integration Rules (Stage 15)

These rules bind the parallel Stage 15 agents. Shared seams are `ports/vault.py` (`VaultSessionPort`), `ports/content.py` (`AssetContentPort`), `ports/sync.py` (`SyncStatusProviderPort`), and the factories in `infrastructure/services.py`; each factory is implemented by its owner and every other agent depends only on the port.

### Storage pipeline (local-first)

- Ingestion (web upload, Send-to, inbox, import, folder backup) always writes the plaintext original to the local blob store first and responds immediately. When the vault is ready, the storage-pipeline (backup) agent enqueues `remote_upload` for the original and later for thumbnails/previews.
- `remote_upload` uses `RemoteBlobStorePort.store` (mtproto agent): v2-encrypt with the current epoch, split into parts, upload, persist `upload_sessions` progress for resume, then update the blob ref to `backend=telegram` with `parts`, `key_epoch`, `format_version=2`. The local plaintext file becomes a cache entry (`cache_entries`) eligible for LRU eviction.
- Small blobs (thumbnails/previews) are uploaded in albums of up to 10 documents per request (`RemotePartStorePort` batch helper) to reduce message count.
- Downloads (`/download`, `/content`, thumbnails on other devices, sharing) go through `AssetContentPort`, which serves the local cache or fetches from Telegram (full or by range) and records cache access.
- Bandwidth limiting (`backup_bandwidth_limit_kbps`) is a token bucket inside the MTProto transfer layer. `Pausar respaldo` pauses folder-backup scanning and `backup_upload` jobs only; manual uploads continue.
- When a vault becomes ready on a device that already has local data, the pipeline enqueues `remote_upload` for every local-only blob and the sync engine publishes full-state upserts for every entity (initial publish).

### Sync capture details

- Tracked models: `FolderModel`, `AssetModel`, `AlbumModel`, `AlbumAssetModel`, `BlobRefModel` (only rows with `backend == "telegram"`), `BlobPartModel` (folded into the parent `blob` op's `parts` field), `ThumbnailModel`, `DeviceModel` (synced columns only; `is_current` and `last_seen_at` stay local).
- Hold rule: the flush withholds `asset`, `thumbnail`, `album_item`, and `asset_index` ops whose asset has no remote original yet, and releases them right after that asset's `blob` op, so peers never see assets they cannot download.
- Deleting an `AssetModel`/`FolderModel` row (trash purge) produces a `purge` op.
- Applying `asset_index` updates `asset_text`/FTS and the vector index through the existing search adapters. Receiving devices never run OCR/embeddings for remote assets.

### Keys messages

`.bkeys` documents in the Sync channel contain canonical JSON (not sealed as a whole). Sealed boxes are anonymous and every device of the account (including a removed one whose Telegram session is still alive) can post to Sync, so each grant is also authenticated by its sender's static device key:

```json
{"bento": "keys", "v": 2, "vault_id": "vlt_…", "epoch": 2, "sender_device_id": "dev_a1",
 "removed_device_ids": ["dev_c3"],
 "grants": {"dev_b2": {"sealed": "<b64url seal_for_device(pub_b2, keyring_bytes, aad=vault_id)>",
                       "auth": "<grant_auth(sender identity, pub_b2, auth_payload)>"}}}
```

- `grant_auth(identity, peer_pub, payload)` = b64url `HMAC-SHA256(HKDF-SHA256(X25519(identity.private, peer_pub), salt = min(pub_sender, pub_recipient) || max(...), info = "bento/v1/keys-grant-auth"), payload)`; verification is constant time.
- `auth_payload` = canonical JSON `{"bento": "keys-grant", "v": 2, "vault_id", "epoch", "sender_device_id", "recipient_device_id", "removed_device_ids", "sealed"}` (the whole message context plus that recipient's b64url box), so no field of the message can be edited or a box swapped.
- Writer (`DeviceService`): one grant per remaining active device (itself included) except the ones the person excluded; `removed_device_ids` lists the removed device, every excluded device, and every device the registry already knows as removed. Device ids are `dev_…`; removed ids never appear as sender or recipient.
- Apply (sync loop, `application/sync/keys.py`): only `v == 2` (v1 and unknown versions are skipped). Epochs move exactly one step: a grant for `current + 1` is merged, one for `current` must agree with the keys already held (nothing new), and anything older (`keys_epoch_stale`) or further ahead (`keys_epoch_gap`) is rejected. The grant addressed to this device is accepted only when the sender is this device or an active device of the local registry, is not in the `sync_state` key `removed_device_ids` (every id listed by an accepted keys message), and `auth` verifies with the sender's registered public key; only then is the box opened and merged (it must agree with every key already held; nothing older is dropped) and persisted via `VaultSessionPort.update_keyring`.
- An accepted message adds its `removed_device_ids` to `sync_state.removed_device_ids` and sets `removed_at` locally on registry rows not removed yet (a `device` op; already removed rows are left untouched), so grants from those devices stay rejected even when the removal op arrives later or a stale op re-activates the row. Rejected or unaddressed messages change nothing but the epoch floor, which only rises to epochs this device already holds, except that a newer-epoch message from another active device that leaves this device out marks it removed (§ Devices, Removal, Key Rotation).

Pairing (`.bpair`) messages are skipped by the sync loop; the pairing service reads them with its own cursor.

### Device registration

`VaultSessionPort` (mtproto agent) registers the current device (`devices` row with `is_current=True`, name defaulting to `<hostname> · <OS>`, X25519 public key, current Telegram authorization hash) whenever a vault is created, unlocked with a recovery code, or installed from a pairing grant. Listing, renaming, removal, and key rotation belong to the pairing agent.

### Crypto format decisions (Stage 14)

- Envelope AAD is the full 22-byte prefix plus caller AAD; sealed boxes (`BBOX` v1) use the 49-byte prefix plus caller AAD.
- Keys grants (`.bkeys` v2) are sender-authenticated with `grant_auth` (static X25519 → HKDF `bento/v1/keys-grant-auth` → HMAC-SHA256 over the canonical grant context); v1 anonymous grants are rejected.
- Pairing envelopes use subkey `info="bento/v1/pairing"`. Base64url is unpadded everywhere; decoding is strict.
- Blob v2 has `max(1, ceil(P/S))` segments (an exact multiple ends on a full last segment); segment size is capped at 64 MiB; unknown epochs raise `IntegrityError`.
- Relay pairing frames always carry their type byte; message counters are implicit; any failure poisons the session.
- Headers are MACed with the keyring's current epoch and `current_epoch` must equal it. Readers treat a header as current only at their own current epoch (see § Header).
- After a rotation to epoch `e` observed at Sync message `M`, devices reject batches, snapshots, and headers sealed with an epoch `< e` posted after `M` (a removed device keeps old keys). Bootstrap starts the floor at `(snapshot sealing epoch, covers_through_message_id)`. Batches are rejected from the envelope prefix, before decryption.
- `open_json` takes a per-call inflation limit (`max_json_bytes`); batches use 16 MiB, snapshots the adapter default (1 GiB).
- Header timestamps (`created_at`, `snapshot.created_at`, `recovery.confirmed_at`) must carry a timezone; naive values make the header invalid.
- Resumed uploads must verify the source's sha256 and size before reusing saved `file_salt`/`nonce_prefix` (nonce reuse otherwise).
