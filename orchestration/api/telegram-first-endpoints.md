# Telegram-First HTTP Contract

All routes live under `/api`, use the existing error model (`api/error-model.md`), and never accept or return plaintext Telegram sessions, keyrings, private keys, or wrapping keys. The only secret ever returned is a freshly generated recovery code, exactly once, in the response that created it.

QR payloads are returned as a matrix so the renderer draws them without third-party libraries or HTML injection:

```json
"qr": {"size": 29, "rows": ["1111111010...", "..."]}
```

Generate with `segno` (error correction `M`, no border; the UI adds the quiet zone).

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
 "other_vaults": 0}
```

`locked` means the account has a vault but this device has no keyring yet (show "aprobar desde otro dispositivo" or "usar kit de recuperación"). `bootstrapping` means the snapshot/ops are being applied (`/sync/status` has progress).

## Sync — owner: sync agent

| Method | Path | Response |
|---|---|---|
| GET | `/sync/status` | `{state: "disabled|idle|syncing|bootstrapping|offline|paused|waiting|error", pending_ops, last_push_at, last_pull_at, bootstrap: {done, total} | null, waiting_until: ISO | null, error: Error | null}` |
| POST | `/sync/now` | `{accepted: true}` |

## Devices — owner: pairing agent

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/devices` | – | `{items: [{id, name, platform, added_at, last_seen_at, current, removed_at}]}` |
| PATCH | `/devices/{id}` | `{name}` | device |
| DELETE | `/devices/{id}` | – | `{device, telegram_session_closed: bool, recovery_code}` (mandatory new kit) |

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
| POST | `/pairing/request` | – | `Pairing` (Sync-channel fallback; requires Telegram sign-in) |

Fallback requests seen by hosts:

| Method | Path | Response |
|---|---|---|
| GET | `/pairing/requests` | `{items: [{id, device_name, platform, created_at}]}` |
| POST | `/pairing/requests/{id}/review` | `Pairing` with `sas` |
| POST | `/pairing/requests/{id}/approve` · `/reject` | `Pairing` |

`Pairing`:

```json
{"id": "pair_…", "role": "host|guest", "transport": "relay|telegram",
 "state": "waiting|connected|awaiting_approval|approving|needs_telegram_login|bootstrapping|completed|rejected|failed|expired|cancelled",
 "code": "K7Q2-MXR9-T4WA" | null, "link": "bento://join?v=1&c=…" | null, "web_link": "…" | null, "qr": QR | null,
 "expires_at": "ISO", "peer": {"device_name": "…", "platform": "linux|macos|windows"} | null,
 "sas": ["🐙", "🌵", "🎈", "🚀"] | null, "telegram_qr": QR | null, "error": Error | null}
```

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
 "attention": [{"id": "…", "kind": "upload_failed|sync_error|flood_wait|recovery_kit|inbox_failed", "title_key": "i18n key", "params": {}, "action": "retry|open_settings|save_recovery_kit|none"}]}
```

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
