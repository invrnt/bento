# Telegram-First HTTP Contract

All routes live under `/api`, use the existing error model (`api/error-model.md`), and never accept or return plaintext Telegram sessions, keyrings, private keys, or wrapping keys. The only secret ever returned is a freshly generated recovery code, exactly once, in the response that created it.

QR payloads are returned as a matrix so the renderer draws them without third-party libraries or HTML injection:

```json
"qr": {"size": 29, "rows": ["1111111010...", "..."]}
```

Generate with `segno` (error correction `M`, no border; the UI adds the quiet zone).

## Request guard (headless mode)

Outside desktop mode every request must use a loopback `Host` (`127.0.0.1`, `localhost`, or `[::1]`, any port) or a host listed in `BENTO_ALLOWED_HOSTS` (comma-separated, read from the API process environment); anything else gets `400 host_not_allowed` (DNS rebinding). Every method other than GET/HEAD/OPTIONS must also carry `X-Bento-Client: web`, or it gets `403 csrf_header_missing`: browsers only let a page send that header after a CORS preflight, which the API grants solely to its web origins. The web client (`apps/web/src/api/client.ts`) sends it on every request; scripts must add it too (`curl -H 'X-Bento-Client: web' …`). Desktop mode keeps its exact-origin + bearer-token middleware instead; the header is accepted there and ignored.

## Account (Telegram sign-in) — owner: mtproto agent

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/account` | – | `AccountStatus` |
| POST | `/account/login/qr` | – | `AccountStatus` with `qr_url`, `qr`, `qr_expires_at`; refreshes an expired token |
| POST | `/account/login/phone` | `{phone}` | `AccountStatus` (`step=code_required`) |
| POST | `/account/login/code` | `{code}` | `AccountStatus` (`authorized` or `password_required`) |
| POST | `/account/login/password` | `{password}` | `AccountStatus` |
| POST | `/account/logout` | – | `AccountStatus` (`signed_out`); keeps local library, stops sync |
| GET | `/account/avatar` | – | small JPEG or 404 |

`AccountStatus`:

```json
{"step": "signed_out|qr_pending|code_required|password_required|authorized|failed",
 "account": {"user_id": 1, "display_name": "Ana", "username": "ana", "phone_masked": "+57 ••• ••• 12", "premium": false} | null,
 "qr_url": "tg://login?token=…" | null, "qr": QR | null, "qr_expires_at": "ISO" | null,
 "password_hint": "str" | null, "error": {"code": "…", "message": "…"} | null}
```

Error codes: `telegram_not_available` (no build credentials), `telegram_login_expired`, `telegram_code_invalid`, `telegram_password_invalid`, `telegram_flood_wait` (`details.retry_after_seconds`), `telegram_network`.

## Vault and recovery — owner: mtproto agent (vault), pairing agent (recovery)

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/vault` | – | `VaultStatus` |
| POST | `/vault` | – | `{vault: VaultStatus, recovery_code: "XXXX-…"}` creates the vault on the first device |
| POST | `/vault/unlock` | `{recovery_code}` | `VaultStatus` unlocks an existing vault on this device |
| POST | `/vault/recovery-code` | – | `{recovery_code}` rotates the recovery code (old one stops working) |
| POST | `/vault/recovery-code/confirm` | `{last_group}` | `VaultStatus` marks the kit as saved when the last group matches |
| POST | `/vault/recovery-code/verify` | `{recovery_code}` | `{valid: bool}` |

`VaultStatus`:

```json
{"state": "local_only|signed_out|no_vault|locked|bootstrapping|ready",
 "vault_id": "vlt_…" | null, "created_at": "ISO" | null,
 "recovery_kit_saved": false, "devices_count": 2,
 "usage": {"files": 1200, "bytes": 52428800000},
 "other_vaults": 0, "recovery_kit_stale": false, "reason": null}
```

`locked` means the account has a vault but this device has no keyring yet (show "aprobar desde otro dispositivo" or "usar kit de recuperación"). `reason` with `signed_out` is `session_closed` (this device was attached to a vault and lost its Telegram session; show a reconnect screen, not the first-run welcome) or `device_removed` (removed and signed out). `reason: "device_removed"` with `locked` means another device removed this one: the keys were dropped, the local library stays, and re-joining (pairing or kit) gives this device a new identity. `recovery_kit_stale: true` (with `recovery_kit_saved: false`) means the pinned header wraps an older key epoch: generate a new kit with `POST /vault/recovery-code`. `bootstrapping` means the snapshot/ops are being applied (`/sync/status` has progress).

## Sync — owner: sync agent

| Method | Path | Response |
|---|---|---|
| GET | `/sync/status` | `{state: "disabled|idle|syncing|bootstrapping|offline|paused|waiting|error", pending_ops, last_push_at, last_pull_at, bootstrap: {done, total} | null, waiting_until: ISO | null, error: Error | null}` |
| | | A removed device reports `state: "paused"` with `error.code = "device_removed"` until it joins again. |
| | | A device clock more than 5 min off Telegram's reports `error: {code: "clock_skew", message, details: {direction: "ahead" \| "behind", skew_seconds}}` while `state` stays what the loop reports (`idle`, `syncing`, …); a loop error (offline, flood wait, failure) is reported instead while it lasts. |
| POST | `/sync/now` | `{accepted: true}` |

## Devices — owner: pairing agent

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/devices` | `?include_removed` | `{items: [Device]}` |
| PATCH | `/devices/{id}` | `{name}` | `Device` |
| GET | `/devices/{id}/removal-preview` | – | `{recipients: [Device]}`: the active devices that would receive the new keys if `{id}` were removed now (this device first). `409 device_is_current`, `404 device_not_found` |
| DELETE | `/devices/{id}` | optional `{exclude_device_ids: [string]}` (≤ 256) | `{device: Device, telegram_session_closed: bool, recovery_code, recovery_qr: QR, removed_device_ids: [string]}` (mandatory new kit; `removed_device_ids` = `{id}` then every excluded id). Excluded devices are removed too, get no key grant, and keep their Telegram sessions. `400 device_exclusion_invalid` for unknown ids or this device |
| POST | `/devices/{id}/acknowledge` | – | `Device` with `needs_review: false` (the person reviewed a device first seen through sync) |

`Device`: `{id, name, platform: "linux|macos|windows|other", added_at, last_seen_at, current, removed_at, introduced_by: string|null, first_seen_at: string|null, needs_review: bool}`. `introduced_by` is the device whose sync data introduced this one on this device (null when it was added here, e.g. as pairing host); `needs_review` is true for active devices first seen through sync and not acknowledged yet (they also appear as Activity `new_device` items).

Web flow for removal: fetch the preview, show the recipients, let the person tick unknown ones (`needs_review` ones first), then `DELETE` with `exclude_device_ids`.

## Pairing — owner: pairing agent

Host (existing device):

| Method | Path | Response |
|---|---|---|
| POST | `/pairing/host` | `Pairing` with `code`, `link`, `web_link` (null without `public_site_url`), `qr`, `expires_at` |
| GET | `/pairing/{id}` | `Pairing` |
| POST | `/pairing/{id}/approve` | `Pairing` |
| POST | `/pairing/{id}/reject` | `Pairing` |
| DELETE | `/pairing/{id}` | `Pairing` (`cancelled`) |

Guest (new device):

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/pairing/join` | `{code}` (code or full `bento://`/`https` link) | `Pairing` |
| POST | `/pairing/request` | – | `Pairing` (Sync-channel fallback; requires Telegram sign-in; `409 pairing_vault_ambiguous` when the account has several vaults) |
| POST | `/pairing/{id}/confirm` | – | `Pairing` (`approving`). Fallback guests only, in `awaiting_approval` with `sas`: the user saw the same emojis on the reviewing device. Until then the guest opens no grant; afterwards it accepts only the grant bound to the offer behind those emojis. Relay guests and hosts get `409 pairing_state_conflict`. "No coinciden" is `DELETE /pairing/{id}`. |

Fallback requests seen by hosts:

| Method | Path | Response |
|---|---|---|
| GET | `/pairing/requests` | `{items: [{id, device_name, platform, created_at}]}` |
| POST | `/pairing/requests/{id}/review` | `Pairing` with `sas`, or `failed` with `pairing_request_taken` when the guest already answered another device's offer; `409 pairing_device_removed` for a removed device id |
| POST | `/pairing/requests/{id}/approve` · `/reject` | `Pairing` |

A host session that sees another device's answer (a reveal for another offer, or a grant/reject it did not post) ends `failed` with `pairing_request_taken`; the UI says "Otro dispositivo respondió a esta solicitud. Si no fuiste tú, cancela en el equipo nuevo."

`Pairing`:

```json
{"id": "pair_…", "role": "host|guest", "transport": "relay|telegram",
 "state": "waiting|connected|awaiting_approval|approving|needs_telegram_login|bootstrapping|completed|rejected|failed|expired|cancelled",
 "code": "K7Q2-MXR9-T4WA" | null, "link": "bento://join?v=1&c=…" | null, "web_link": "…" | null, "qr": QR | null,
 "expires_at": "ISO", "peer": {"device_name": "…", "platform": "linux|macos|windows"} | null,
 "sas": ["🐙", "🌵", "🎈", "🚀"] | null, "telegram_qr": QR | null, "error": Error | null,
 "vault": {"created_at": "ISO" | null, "devices_count": 3 | null} | null}
```

`vault` is set only for fallback guests: `created_at` comes from the pinned header the guest discovered (checked again against the granted keyring before installing) and `devices_count` from the host's offer (an unverified hint). Pairing error codes: `pairing_request_taken`, `pairing_vault_ambiguous` (409), `pairing_device_removed` (409; the guest must join with a new identity), plus the relay codes in `pairing-relay-contract.md`.

Pairing sessions live in API memory; restarting the API cancels them.

## Backup, activity, power — owner: backup agent

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/backup/sources` | – | `{items: [BackupSource]}` |
| POST | `/backup/sources` | `{path, label?}` | `BackupSource` (validates existing readable directory, not filesystem root, not inside data dir, no duplicates/overlaps) |
| PATCH | `/backup/sources/{id}` | `{enabled?, label?}` | `BackupSource` |
| DELETE | `/backup/sources/{id}` | – | `{removed: true}` (never deletes uploaded files) |
| POST | `/backup/sources/{id}/scan` | – | `BackupSource` |
| GET | `/backup/suggestions` | – | `{items: [{path, label, kind: "pictures|documents|desktop|downloads"}]}` existing folders only |
| GET | `/backup/policy` | – | `{paused, pause_on_battery, bandwidth_limit_kbps, on_battery, effective_paused}` |
| PATCH | `/backup/policy` | partial | policy |
| POST | `/backup/power` | `{on_battery}` | policy (desktop main reports power state) |
| GET | `/activity` | – | `Activity` |

`BackupSource`: `{id, path, label, enabled, state: "idle|scanning|uploading|paused|error", files_total, files_done, files_pending, bytes_pending, last_scan_at, error}`.

`Activity`:

```json
{"summary": "up_to_date|uploading|downloading|syncing|paused|offline|attention",
 "uploads": {"active": 1, "queued": 11, "bytes_total": 1000, "bytes_done": 400, "eta_seconds": 180},
 "downloads": {"active": 0, "queued": 0, "bytes_total": 0, "bytes_done": 0, "eta_seconds": null},
 "attention": [{"id": "…", "kind": "upload_failed|sync_error|flood_wait|recovery_kit|inbox_failed|new_device|device_removed|clock_skew", "title_key": "i18n key", "params": {}, "action": "retry|open_settings|save_recovery_kit|open_devices|none"}]}
```

Security attention items (Stage 17):

- `new_device` (id `new_device:<device_id>`, `title_key` `activity.attention.new_device`, action `open_devices`, params `{device_id, name, first_seen_at}`): "Se añadió «{name}» a tu nube". Cleared by `POST /devices/{id}/acknowledge` or by removing the device.
- `device_removed` (id `device_removed`, `title_key` `activity.attention.device_removed`, action `open_settings`): another device removed this one; the vault is `locked` with `reason: "device_removed"` and re-joining goes through pairing (with a fresh device identity) or the recovery code.
- `recovery_kit` with `params.reason = "stale"`: the pinned header still wraps an older key epoch ("genera un nuevo kit"): `POST /vault/recovery-code` (rotate) fixes it.
- `clock_skew` (id `clock_skew`, `title_key` `activity.attention.clock_skew`, action `none`, params `{direction: "ahead" | "behind", skew_seconds, skew_minutes}`): this device's clock is more than 5 minutes off Telegram's, so other devices ignore its changes (`ahead`) or it ignores theirs (`behind`): "Ajusta la fecha y hora de este equipo (automática)". It clears by itself once the clock is fixed and the device posts or sees a recent message.

## Trash and cache — owner: backup agent

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/trash` | `?cursor&limit` | `{items: [{id, type: "asset|folder", name, size_bytes, deleted_at, purge_at, thumbnail_url}], next_cursor}` |
| POST | `/trash/restore` | `{ids}` | `{restored}` |
| POST | `/trash/purge` | `{ids}` | `{purged}` deletes remote blobs (all parts) and local copies |
| POST | `/trash/empty` | – | `{purged}` |

Existing `DELETE /assets/{id}` and folder delete move items to trash. A worker job purges items older than `trash_retention_days`.

## Content streaming — owner: backup agent

`GET /assets/{id}/content` streams decrypted bytes with `Accept-Ranges: bytes`, `Range` support (206), correct `Content-Type`, and `Content-Disposition: inline`. It downloads only the v2 segments needed (cached under `data/cache/blobs`) and never loads originals into grids. `/assets/{id}/download` stays as the attachment download.

## Telegram sharing and import — owner: mtproto agent

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/telegram/chats` | `?query&limit` | `{items: [{id, title, kind: "saved|user|group|channel"}]}` |
| POST | `/assets/{id}/share/telegram` | `{chat_id, caption?}` | `{sent: true}` |
| GET | `/telegram/import/media` | `?chat_id&cursor&kind=photo|video|document|all` | `{items: [{message_id, kind, filename, size_bytes, date}], next_cursor}` |
| POST | `/telegram/import` | `{chat_id, message_ids? , all?: bool}` | `{job_id, queued}` |

## Development only

`POST /dev/fake-telegram/approve-login` approves the pending fake QR login. Registered only when `storage_backend=fake` and `environment != "production"`.

## Removed

`POST /telegram/webhook` and every Bot API setting are removed in Stage 15.
