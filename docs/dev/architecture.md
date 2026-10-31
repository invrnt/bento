# Architecture overview

Bento is a modular monolith with separate runtime processes. The user’s own Telegram account (MTProto) is both the encrypted blob store and the replication log between devices; each device keeps a local SQLite replica as its source of truth for reads. The only hosted component is a stateless pairing relay.

```txt
Electron main ──► API sidecar (FastAPI) ─┐
              └─► worker sidecar          ├─► Telethon client (one per process, same session)
                                          └─► local SQLite + data dir
API/worker ──► pairing relay (wss, optional, only during pairing)
Browser ──► public site (static, /join hands codes to bento://)
```

## Repository layout

| Path | What it is |
|---|---|
| `apps/api/src/bento` | One Python package for the API and the worker: `domain → application → ports ← adapters ← infrastructure`, with `interfaces/` for HTTP, worker and desktop entry points. |
| `apps/web` | React + Vite renderer used by the browser mode and packaged into the desktop app. |
| `apps/desktop` | Electron host: secure window, sidecar supervision, tray, deep links, updates, key provisioning. |
| `apps/relay` | Cloudflare Worker + SQLite-backed Durable Object that relays opaque pairing frames. |
| `apps/site` | Static public website on Cloudflare Pages, including the `/join` handoff page. |
| `docs/` | User guides, legal drafts, desktop docs and these developer docs. |
| `orchestration/` | Binding implementation contracts (architecture, API, product, testing, execution). |

## Storage backends

`STORAGE_BACKEND` selects where blobs and the sync log live:

- `local`: device only. No Telegram, no sync, no pairing. Change capture is disabled so local users pay nothing.
- `telegram`: MTProto vault in three private channels of the user’s account (`Bento · Archivos`, `Bento · Sync`, `Bento · Bandeja`). Requires `BENTO_TELEGRAM_API_ID`/`BENTO_TELEGRAM_API_HASH`.
- `fake`: a filesystem simulation of the Telegram cloud for development, demos and multi-process tests (`BENTO_FAKE_TELEGRAM_DIR`). Rejected when `ENVIRONMENT=production` and never selectable in packaged release builds.

## Key ideas

- **Everything that leaves a device is encrypted.** Blobs use a streaming AES-256-GCM format (1 MiB segments) keyed from a per-vault keyring; sync batches, snapshots and device records are sealed envelopes. Telegram learns sizes and timing only.
- **Secrets never cross the renderer or HTTP.** The Telegram session, keyring and device identity live in a key store wrapped by a device key (Electron `safeStorage` on desktop, `BENTO_DEVICE_WRAPPING_KEY` or a `0600` file headless).
- **Sync** is last-writer-wins per field with hybrid logical clocks, batched to the Sync channel, with periodic encrypted snapshots for bootstrapping new devices.
- **Pairing** uses SPAKE2 over the relay (or the Sync channel as fallback), a 4-emoji SAS, and seals the keyring to the new device’s X25519 key. Removing a device rotates keys and issues a new recovery code.

## Binding contracts

- [System overview](../../orchestration/architecture/system-overview.md) and [boundaries and layers](../../orchestration/architecture/boundaries-layers.md)
- [Telegram-first architecture](../../orchestration/architecture/telegram-first.md): vault layout, cryptography, sync, pairing, devices, inbox
- [Telegram-first HTTP endpoints](../../orchestration/api/telegram-first-endpoints.md)
- [Pairing relay contract](../../orchestration/api/pairing-relay-contract.md)
- [Telegram-first product experience](../../orchestration/product/telegram-first-experience.md)
- [Desktop runtime and settings](../../orchestration/architecture/desktop-runtime-settings.md)
- [Performance and security](../../orchestration/architecture/performance-security.md)
- [Brand and design language](../../orchestration/design-system/brand.md)
- [Testing layers](../../orchestration/testing/test-layers.md) and [critical journeys](../../orchestration/testing/critical-journeys.md)
- [Telegram-first program and ownership](../../orchestration/execution/telegram-first-program.md)
