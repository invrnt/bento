# Telegram MTProto Agent (Stage 15)

## Mission

Connect Bento to the user's Telegram account with Telethon: sign-in (QR, phone, 2FA), vault creation/discovery, the vault session every feature depends on, encrypted remote blob storage with resumable parts, sharing, import, and the Inbox. Remove the Bot API implementation completely.

## First Read

- `AGENTS.md`, `orchestration/execution/telegram-first-program.md`
- `orchestration/architecture/telegram-first.md` (whole, especially § Integration Rules)
- `orchestration/api/telegram-first-endpoints.md` § Account, § Vault and recovery, § Telegram sharing and import, § Development only
- `orchestration/product/telegram-first-experience.md`
- Contracts: `domain/{account,telegram,vault,security,storage,devices}.py`, `ports/{telegram,vault,key_store,security,blob_store,content,pairing}.py`, `infrastructure/{runtime,services}.py`, `interfaces/http/qr.py`
- Stage 14 results: `adapters/fake_telegram/**`, `adapters/security/**`, `adapters/repositories/devices.py`, migration `0004`

## Retrieve First

Telethon 1.45 docs/source for: `TelegramClient` construction (`device_model`, `system_version`, `app_version`, `StringSession`), `qr_login()`/`QRLogin.wait/recreate`, `send_code_request`/`sign_in`/`SessionPasswordNeededError`, raw requests (`channels.CreateChannelRequest`, `channels.GetFullChannelRequest`, `messages.UpdateDialogFilterRequest` + `DialogFilter` fields in the bundled layer, `account.UpdateNotifySettingsRequest`, `folders.EditPeerFoldersRequest`, `auth.AcceptLoginTokenRequest`, `account.GetAuthorizationsRequest`, `account.ResetAuthorizationRequest`, `messages.SendReactionRequest`), `send_file` (documents, albums of up to 10, `force_document`, progress callbacks), `iter_download`/`download_media` with offsets, `iter_messages(min_id, reverse=True)`, `pin_message`, events (`NewMessage(chats=…)`), `FloodWaitError`, file reference expiry handling. Read the Telegram API terms. Record versions/assumptions in your handoff.

## Own These Paths

- `infrastructure/mtproto/**` (client factory, config from `BENTO_TELEGRAM_API_ID`/`BENTO_TELEGRAM_API_HASH`, session persistence via `KeyStorePort`, flood-wait policy, transfer token bucket honoring `backup_bandwidth_limit_kbps`, parallel transfer limit, `runtime.create_mtproto_runtime`)
- `adapters/telegram_mtproto/**` (account, vault transport, part store, chats)
- `adapters/storage/telegram_vault_blob_store.py` (`RemoteBlobStorePort` over any `RemotePartStorePort` + `BlobCipherPort` + `VaultSessionPort`, with `upload_sessions` resume) — works identically with the fake cloud
- `application/{account,vault,sharing,telegram_import,inbox}.py`
- `interfaces/http/routes_{account,vault,telegram}.py` (+ one include line each in `routes.py`)
- Worker: inbox loop, `account_reload` and `telegram_import` handlers (own module + registration lines)
- `infrastructure/services.py`: implement `get_key_store`, `get_vault_crypto`, `get_blob_cipher`, `get_pairing_crypto`, `get_vault_session`, `get_remote_blob_store`, and their part of `reset_services`
- `infrastructure/storage/factory.py` (`create_blob_store` always returns the local store; the remote store comes from `get_remote_blob_store`)
- Legacy removal: `infrastructure/telegram/**`, `interfaces/telegram/**`, `adapters/storage/{telegram_blob_store,encrypted_blob_store}.py`, Bot API/legacy-encryption fields in `domain/settings_registry.py` and `infrastructure/settings.py`, `aiogram` extras in `pyproject.toml`/`uv.lock`, the `telegram-bot-api` service/profile in `docker-compose.yml`, `.env.example`, `scripts/doctor/**` (report storage mode, build credentials present/missing, key store mode), packaging spec references under `apps/api/packaging/**`, and tests of removed code. `domain/jobs.py`: append `account_reload`, `inbox_import`, `telegram_import` (exists).

## Deliver

1. Account sign-in exactly per the HTTP contract, with the QR token refreshed automatically, 2FA, phone code, errors mapped to the listed codes, avatar, logout (keeps the local library, stops sync), and the raw `qr_token` exposed only in-process for pairing. Telegram sees the client as `device_model="Bento"`, `system_version=<OS>`, `app_version=<Bento version>`.
2. `VaultService` implementing `VaultSessionPort` and the vault endpoints: create (channels, folder `Bento`, mute/archive, header with recovery wrap, register current device, return recovery code once), find (markers; report `other_vaults`), unlock with recovery code, install grant, recovery code rotate/confirm/verify, keyring persistence (`vault.keyring`), layout persistence (`sync_state`), header read with MAC verification and `update_header`, status with usage (files and bytes from the catalog).
3. Remote blob store: v2 encryption, parts of `telegram_part_size_mb` (premium-aware cap), album batching for small blobs, resumable uploads via `upload_sessions` (deterministic params), full download with segment verification, `read_range` decrypting only needed segments (part/offset mapping), `delete_ref` deleting every part, file-reference refresh on expiry.
4. Sharing (`POST /assets/{id}/share/telegram`, uses `AssetContentPort.materialize_original` and sends with the original filename), chat listing, import listing and the `telegram_import` job (downloads media to temp, ingests through the existing ingestion service, deduped by sha256).
5. Inbox loop in the worker: on activity/poll, import new Inbox items through ingestion, react ✅ (fall back to 👍 or no reaction if the channel disallows it), record `inbox_items`, delete after `inbox_keep_hours`, react ⚠️ and record an attention-worthy failure on errors.
6. Bot API removal with no dead code or settings left; `make doctor` still works.

## Required Tests

- Adapters with a fake Telethon client (request construction, flood wait, file reference refresh, album batching, range mapping, part splitting at boundaries).
- Application services against the fake cloud from Stage 14: full sign-in flows, vault create → second device unlock with recovery code, header MAC rejection, recovery rotation invalidates the old code, remote blob store round trip with resume after a simulated crash mid-part, range reads, delete, sharing, import, inbox lifecycle.
- HTTP tests with `storage_backend=fake` for every owned endpoint, including that no response ever contains session strings, keyrings, or tokens.
- Full backend suite green; import-boundary test green.

## Constraints

- No real network or real Telegram in tests. Never log phone numbers, codes, passwords, session strings, tokens, or keys.
- Respect Telegram terms (see architecture § Telegram Terms Compliance).
- Do not implement sync, pairing, devices removal, backup, trash, or content caching—use the ports/factories.

## Handoff

Commit on your branch. Report public services/factories, env vars, removed files, test counts, and anything other agents must adapt to.

## Stage 14 Handoff Notes

- Crypto adapters (all exported from `bento.adapters.security`): `StreamingBlobCipher(legacy_keys=None)`, `VaultCrypto()`, `PairingCryptoFactory()`, `WrappedFileKeyStore(directory, wrapping_key)`, `InMemoryKeyStore()`, `load_wrapping_key(os.environ, data_dir) -> WrappingKey(key, file_based, path)`. Production code never passes `random_bytes`.
- Key store directory: `<data_dir>/secure`. Surface `file_based=True` as a `make doctor` warning.
- Legacy Bot API blobs are not migrated; do not wire `legacy_keys` (the legacy encryption settings are removed).
- Headers: MAC with the keyring's current epoch and keep `current_epoch` equal to it.
- Resumed uploads: before reusing an `upload_sessions` row's `file_salt`/`nonce_prefix`, verify the source file's size and sha256 still match the blob ref; otherwise discard the session and start fresh (GCM nonce reuse).
- Relay: `relay_url` is a ws(s) origin without path or trailing slash (e.g. `wss://bento-relay.<subdomain>.workers.dev`; local `ws://localhost:8787`).
