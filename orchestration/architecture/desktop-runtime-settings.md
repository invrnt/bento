> Telegram-first update: the Bot API sidecar and Telegram secret fields were removed; runtime secrets (Telegram session, vault keyring, device key) live in the backend key store wrapped by `BENTO_DEVICE_WRAPPING_KEY`. See `desktop-bridge-telegram-first.md` and `telegram-first.md`.

# Desktop Runtime And Editable Settings

## Decision

Use Electron as the desktop host because the existing React/Vite renderer can be reused and the main process can supervise the Python API and worker without moving business rules into JavaScript. Package Windows, macOS, and Linux artifacts with Electron Forge or an equivalent single approved packager selected during the implementation spike. Bundle the Python backend as platform-specific sidecars from the existing `bento` package.

Docker Compose remains supported for development and headless installs. A desktop user must not need Docker, Python, Node, or a manually edited `.env` file.

## Process Topology

```txt
Electron main
  -> BrowserWindow (compiled React renderer)
  -> FastAPI sidecar on 127.0.0.1:<ephemeral>
  -> worker sidecar using the same data directory and settings snapshot
```

Electron main is an interface/infrastructure host, not a domain layer. It may manage windows, native dialogs, secure storage, child processes, logs, restarts, and desktop updates. Product rules remain in Python application/domain modules and React renders state returned by typed contracts.

## Startup And Shutdown

1. Acquire a single-instance lock and route subsequent launches to the existing window.
2. Resolve the platform user-data directory and read only minimal bootstrap metadata: schema version, active data directory, and last-known-good settings revision.
3. Create an unguessable per-launch API token (a fresh one for every API process) and spawn API first, passing the token only in that process's environment. The API binds `127.0.0.1:0` itself and reports the OS-assigned port with one stdout line, `BENTO_API_READY {"port":N}`, once it accepts connections. Main never reserves a port, never passes `--port` or the token in argv, and never sends the token anywhere before that line arrives (or after that API exits).
4. Wait for a bounded authenticated readiness check against the announced port; then spawn the worker.
5. Load the bundled renderer only after API readiness. Show a native recovery window with safe diagnostics if startup fails.
6. On quit, stop accepting work, terminate sidecars gracefully with a timeout, and only then force-kill owned child processes if required.

Crashes use bounded backoff. Three failures in a short window enter recovery mode instead of a restart loop. Logs live under the platform user-data directory, are rotated, and redact settings marked secret.

## Settings Registry

Create one canonical registry in the backend. Every configurable field declares:

- stable key and legacy environment aliases;
- group, label/help i18n keys, type, default, constraints, and choices;
- whether it is secret;
- whether it is available in desktop, headless, or both;
- apply mode: `live`, `restart_worker`, `restart_services`, or `restart_app`;
- validation and optional connection-test behavior.

API, worker, doctor, `.env.example`, desktop forms, and documentation must consume or be checked against this registry. Direct feature-level `os.getenv` calls are migrated to the settings service.

## Sources And Precedence

Desktop mode:

1. security/packaging policy and bootstrap arguments;
2. persisted user setting or secure-secret reference;
3. one-time imported legacy `.env` value;
4. safe default.

Headless/Docker mode:

1. explicit environment value;
2. persisted non-secret setting;
3. safe default.

The API reports each effective value's source. An environment- or policy-controlled value is read-only in the UI with an explanation. On first desktop launch, a detected `.env` can be imported deliberately; Bento never keeps silently rereading it after migration. Import reports unknown keys and never echoes secret values.

## Storage And Secrets

- Non-secret settings and their revision persist in SQLite through `SettingsRepositoryPort`.
- Secrets never appear in API responses, SQLite values, exported diagnostics, renderer storage, URLs, or logs.
- Electron main stores secret material through `safeStorage` backed by the operating system and persists only encrypted payloads plus opaque references under its user-data directory.
- The backend receives required secret material only in the spawned process environment for the lifetime of that revision. A renderer cannot request the plaintext value; it sees only `configured`, `missing`, or `changed`.
- Headless mode keeps secrets environment-only unless a separately reviewed `SecretStorePort` adapter is added.
- Configuration export excludes secrets. Resetting a secret deletes its secure-store entry only after the new configuration commits successfully.

## Apply Transaction

1. Renderer submits a draft and current revision to the desktop settings bridge.
2. Electron main separates secret mutations from ordinary fields and asks the backend to validate ordinary fields plus secret presence markers, never plaintext secret echoes.
3. Optional probes test writable paths, model files, ffmpeg, and Telegram connectivity before enabling dependent features. A probe that needs a newly entered secret runs as a one-shot packaged backend subprocess with a short-lived inherited environment; the secret is not sent through the HTTP API or written to disk.
4. Backend commits non-secret settings with optimistic concurrency and returns a restart plan.
5. Electron commits secure-secret mutations, creates a new effective snapshot, and restarts the smallest affected process group.
6. Health checks confirm the revision. Failure restores the last-known-good revision and secret references, restarts once, and shows a recovery summary.

Browser/headless UI may edit non-secret settings through the API. Secret editing and automatic process restart are desktop capabilities; headless users receive exact environment-variable guidance.

## Desktop Bridge And Security

- `contextIsolation: true`, renderer sandbox enabled, `nodeIntegration: false`.
- Preload exposes a narrow, typed `window.bento` allowlist for settings apply, folder/file pickers, lifecycle status, and platform metadata.
- Validate every IPC payload on both sides; never expose generic filesystem, shell, process, or arbitrary IPC methods.
- Block new-window creation, external navigation, remote code, and unapproved protocols. Use a strict CSP and only bundled renderer assets.
- Sidecars bind to loopback on ephemeral ports and require the per-launch bearer token plus an expected desktop origin. Do not expose it in logs or persistent browser storage.
- At sidecar start the backend moves `BENTO_DESKTOP_API_TOKEN` and `BENTO_DEVICE_WRAPPING_KEY` out of `os.environ` into a process-private holder (`bento/infrastructure/process_secrets.py`); every external tool (ffmpeg, ffprobe) runs with an allowlisted environment (`PATH`, `HOME`, `LANG`, `LC_*`, `TMPDIR`/`TEMP`/`TMP`, plus `SYSTEMROOT`/`WINDIR` on Windows), from an absolute path resolved outside the current directory, in a Bento-owned working directory.
- Main redacts the per-launch tokens from its log and redacts sidecar output per complete line (overlong lines are dropped, never truncated).
- Packaged builds ignore `BENTO_SIDECAR_PATH`, reject `--remote-debugging-port`/`--remote-debugging-pipe`/`--inspect*` switches, disable DevTools, and install an application menu without reload or developer tools.
- `/api` proxy responses carry `X-Content-Type-Options: nosniff` and a `default-src 'none'; sandbox` CSP; redirects are never followed or handed to the renderer.
- Validate selected paths, prevent traversal, and never allow the data directory to be a filesystem root. A data-directory migration target must be owned by the current user and not world-writable.

## Packaging

- Build renderer once and consume the same typed API client in web and desktop modes.
- Build platform-specific Python sidecars in CI; never cross-compile them from another OS.
- Initial artifacts: Windows installer, signed/notarized macOS DMG, Linux AppImage and/or `.deb` as supported by the selected packager.
- Bundle or verify ffmpeg and required native libraries per platform. Large embedding models remain optional downloads with checksum, progress, cancellation, and resumability.
- Code-sign/notarize release artifacts and publish checksums, SBOM, provenance, and one immutable updater manifest per supported platform/architecture. A remote update check reads metadata only; main downloads and verifies exact HTTPS assets by hash/size before serving any Squirrel feed from loopback. Installation is explicit and fails closed on signature, schema, target, hash, size, or feed mismatch.
- Each per-target manifest is Ed25519-signed as `<manifest>.sig` (detached, up to four signatures for rotation). Builds embed the public key as `updatePublicKey` in `resources/build-config.json` (from `BENTO_UPDATE_PUBLIC_KEY`); with a key, a missing or invalid signature fails closed before the manifest is parsed, and without one the updater keeps hash-only checks and logs a warning once. Signing runs only in the dependency-free release publish job (`scripts/sign-update-manifest.mjs`, key from the `BENTO_UPDATE_SIGNING_KEY` secret). Key generation and rotation: `docs/desktop/releasing.md`.

## Definition Of Done

- A fresh desktop install opens without Docker or terminal use in local-storage mode.
- Settings can replace normal `.env` editing, with clear source and restart behavior.
- Secrets stay outside SQLite, renderer storage, diagnostics, and logs.
- Bad settings cannot strand the user; last-known-good rollback and recovery mode work.
- The same core API/worker package and web UI continue to run through Docker Compose.
