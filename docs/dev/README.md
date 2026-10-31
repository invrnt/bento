# Developer documentation

Everything a maintainer needs to build, configure and ship the Telegram-first Bento: the desktop app, the pairing relay and the public site.

| Guide | What it covers |
|---|---|
| [Architecture overview](architecture.md) | Processes, packages, data flow and where the binding contracts live. |
| [Telegram API credentials](telegram-credentials.md) | Registering Bento’s `api_id`/`api_hash` and storing them as CI secrets. |
| [Pairing relay](relay.md) | Deploying `apps/relay` to Cloudflare and setting `BENTO_RELAY_URL`. |
| [Public site](site.md) | Building and deploying `apps/site` to Cloudflare Pages and setting `BENTO_PUBLIC_SITE_URL`. |
| [Multi-device development](multi-device.md) | Running two local Bento instances against the fake Telegram cloud. |

Related:

- [Desktop release and signing](../desktop/releasing.md) (Spanish).
- [User guides](../user/README.md) and [legal documents](../legal/README.md).
- [Repository README](../../README.md) for setup commands.

## Build-time configuration at a glance

| Variable | Kind | Used by | Where to set it |
|---|---|---|---|
| `BENTO_TELEGRAM_API_ID` | secret | API and worker (Telethon) | GitHub Actions secret; local env for dev |
| `BENTO_TELEGRAM_API_HASH` | secret | API and worker (Telethon) | GitHub Actions secret; local env for dev |
| `BENTO_RELAY_URL` | public | Pairing (host and guest) | GitHub Actions variable; local env for dev |
| `BENTO_PUBLIC_SITE_URL` | public | Pairing dialog web link (`/join#…`) | GitHub Actions variable; local env for dev |

Desktop builds write these into `resources/build-config.json` at package time and pass them to the sidecars as environment variables; absent values are omitted. Without Telegram credentials, sign-in reports `telegram_not_available`; without a relay URL, pairing uses the Telegram Sync-channel fallback; without a site URL, the pairing dialog shows no web link.
