# Changelog

All notable changes to Bento are documented here. The format follows
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) and Bento uses
[Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html): one product version (the `VERSION`
file) shared by the desktop app, the `bento` CLI, the backend and the Android app. See
[docs/dev/releasing.md](docs/dev/releasing.md) for how versions and releases are made.

How to add an entry: in the same pull request as the change, add one line under `## [Unreleased]` in
the matching category (Added, Changed, Deprecated, Removed, Fixed, Security). Write it for the people
who use Bento, start it with the component in bold (**Desktop**, **Android**, **CLI**, **Backend**,
**Sync**, **Relay**, **Site**) and leave out internal refactors, tests and tooling unless they change
how Bento is built or verified. At release time `bento-release version bump` (or `changelog cut`)
turns `[Unreleased]` into the dated release section.

No version has been published yet; the entries under `[Unreleased]` are the first release, `0.1.0`.

## [Unreleased]

### Added

- **Desktop:** Bento for Windows, macOS and Linux (Electron) with the backend bundled as a local sidecar
  bound to localhost: Drive file manager with bulk actions, Photos timeline with albums and favorites,
  Documents view, inline text/PDF previews, global search, Jobs and Settings screens, tray icon and
  `bento://` deep links.
- **Backend:** local-first FastAPI service and background worker on SQLite: uploads and ingestion,
  metadata, thumbnails and previews, optional on-device OCR (RapidOCR) and local embeddings, hybrid search
  (full text, names, metadata and embeddings) with match explanations, storage health checks and reclaim.
- **Sync:** Telegram-first vault. Your own Telegram account (MTProto) stores every file end-to-end
  encrypted before it leaves the device and carries the replication log between your devices.
  Includes sign-in with phone/code/2FA, a recovery kit, automatic backup, QR or code pairing through the
  stateless relay, device list and removal, and a Telegram inbox for importing files sent to Bento.
- **CLI:** the agent-first `bento` command with JSON/NDJSON output, profiles, a headless daemon,
  desktop discovery, Drive path commands and scoped API tokens; standalone builds for Linux, macOS and
  Windows, a `.deb` package and `install.sh` / `install.ps1` installers that check SHA-256 sums.
- **Android:** Bento for Android 10+ (64-bit) as a full vault device embedding the same backend:
  camera-roll backup with progress notifications, Fotos timeline with viewer, Archivos, Buscar,
  Colecciones, share to Bento, scan-to-join pairing, free up space, app lock, Quick Settings tile and an
  in-app updater that checks an Ed25519-signed manifest and the APK signer before installing.
- **Relay:** pairing relay on Cloudflare Workers and Durable Objects that only sees ciphertext.
- **Site:** public site with downloads, the `/join` pairing page, Android App Links and the legal pages.
- **Releases:** local release tool (`scripts/release/bento-release`) with a single `VERSION`, signed
  `SHA256SUMS`, CycloneDX SBOMs for the Python, npm and Gradle dependencies, and this changelog.

### Security

- Per-start API credentials with server proof between the apps and their local backend; wider log
  redaction; loopback-only limits.
- Android hardening from the Stage 22 security review: `FLAG_SECURE` on join and login codes,
  tapjacking guards, expiring decrypted share copies, strict join-link parsing, App Links bound to the
  release host.
- Pillow 13.0.0 (also built for Android) and Starlette 1.10 to close known image-parsing and
  request-handling advisories; image decoding limited to the formats Bento uses.

[unreleased]: https://github.com/invrnt/bento/commits/main
