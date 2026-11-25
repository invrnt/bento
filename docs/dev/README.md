# Developer documentation

Everything a maintainer needs to build, configure and ship the Telegram-first Bento: the desktop app, the Android app, the pairing relay and the public site.

| Guide | What it covers |
|---|---|
| [Architecture overview](architecture.md) | Processes, packages, data flow and where the binding contracts live. |
| [Telegram API credentials](telegram-credentials.md) | Registering Bento’s `api_id`/`api_hash` and storing them as CI secrets. |
| [Pairing relay](relay.md) | Deploying `apps/relay` to Cloudflare and setting `BENTO_RELAY_URL`. |
| [Public site](site.md) | Building and deploying `apps/site` to Cloudflare Pages and setting `BENTO_PUBLIC_SITE_URL`. |
| [Android](android.md) | Building and testing `apps/android` (JDK 17, Python 3.13, emulator e2e with the remote fake cloud), signing fingerprint, local release. |
| [Multi-device development](multi-device.md) | Running two local Bento instances against the fake Telegram cloud. |
| [Launch checklist](launch-checklist.md) | Owner actions before the first public release: credentials, relay, signing key, legal review. |
| [Android release](android-release.md) | Local signed APK builds, the Android update-manifest entry, the dry run and the in-app updater. |
| [CLI](cli.md) | The `bento` command: profiles, daemon, desktop discovery, packaging and tests. |
| [Releasing](releasing.md) | Versions and tags, the changelog, the local release tool, signing, SBOMs, Windows/macOS builds, publishing. |

Related:

- [Desktop release and signing](../desktop/releasing.md) (Spanish).
- [User guides](../user/README.md) and [legal documents](../legal/README.md).
- [Repository README](../../README.md) for setup commands.

## Build-time configuration at a glance

| Variable | Kind | Used by | Where to set it |
|---|---|---|---|
| `BENTO_TELEGRAM_API_ID` | secret | API and worker (Telethon) | [release environment](releasing.md#release-environment); local env for dev |
| `BENTO_TELEGRAM_API_HASH` | secret | API and worker (Telethon) | release environment; local env for dev |
| `BENTO_RELAY_URL` | public | Pairing (host and guest) | release environment; local env for dev |
| `BENTO_PUBLIC_SITE_URL` | public | Pairing dialog web link (`/join#…`) | release environment; local env for dev |
| `BENTO_UPDATE_PUBLIC_KEY` | public | Desktop and Android updaters (Ed25519 manifest signatures) | release environment |
| `BENTO_UPDATE_SIGNING_KEY_FILE` | secret (path) | `bento-release` and `release.sh` (sign update manifests) | release environment |
| `BENTO_RELEASE_SIGNING_KEY` | secret (path) | `bento-release` (signs `SHA256SUMS`) | release environment |

Desktop builds write these into `resources/build-config.json` at package time and pass them to the sidecars as environment variables; absent values are omitted. Without Telegram credentials, sign-in reports `telegram_not_available`; without a relay URL, pairing uses the Telegram Sync-channel fallback; without a site URL, the pairing dialog shows no web link.
