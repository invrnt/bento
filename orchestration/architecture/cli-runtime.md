# CLI Runtime

How the `bento` CLI finds or starts a Bento instance, authenticates, and is packaged. Product behavior: `product/cli.md`. HTTP additions: `api/cli-endpoints.md`.

## Layers

- `bento.interfaces.cli` is an **interface** like `interfaces/http`: argument parsing, output rendering, HTTP client, local file walking/hashing, daemon supervision. It must not import `application/`, `adapters/`, or repositories; it talks to the API over HTTP only (so it works the same against the desktop app and the daemon, and a second process never opens the SQLite DB or the Telegram session).
- Allowed imports from the backend package: `bento.interfaces.desktop.launcher` (to run sidecars inside the frozen binary), `bento.infrastructure.process_secrets`, and pure `bento.domain` helpers that have no IO (e.g. `domain/drive_paths.py` for client-side validation). Nothing else.
- Dependencies: stdlib `argparse` for parsing (no new CLI framework), `httpx` (promoted from dev to runtime dependency) for HTTP with streaming uploads/downloads, `segno` (already a dependency) for the terminal QR. No other new dependency.

## Modules (`apps/api/src/bento/interfaces/cli/`)

```txt
main.py            entry point `bento` (console script); `_sidecar` hidden subcommand delegates to launcher.main
app.py             global flags, command registry, dispatch, exit codes
catalog.py         command metadata used by argparse, `commands --json`, and completion
client.py          BentoClient: base URL, bearer token, X-Bento-Client header, error mapping, retries for idempotent GETs
errors.py          CliError(code, message, details, exit_code) + mapping from API error codes
output.py          JSON/human renderers, tables, sizes/dates, TTY detection, progress (stderr)
i18n.py            es/en message dictionary (CLI strings only)
paths.py           parse/format Bento paths and `id:` refs (wraps domain/drive_paths.py)
profiles.py        profile directories, endpoint files, desktop endpoint discovery
daemon.py          start/stop/status/run supervisor for api + worker, service files
qr.py              terminal QR rendering from the API's QR matrix
local_files.py     local tree walking, filters, junk list, symlink policy, hashing
transfer.py        upload/download engine (lookup, ensure folders, concurrent uploads, resume)
commands/          one module per group: account.py, vault.py, pairing.py, devices.py, drive.py,
                   transfer_cmds.py, search.py, photos.py, trash.py, backup.py, sync.py, telegram.py,
                   settings.py, runtime.py, agent.py
guide.md           packaged agent guide (`bento guide`)
```

## Profiles and data

`BENTO_HOME` overrides the CLI home; defaults:

| OS | CLI home |
|---|---|
| Linux/BSD | `${XDG_DATA_HOME:-~/.local/share}/bento-cli` |
| macOS | `~/Library/Application Support/Bento CLI` |
| Windows | `%LOCALAPPDATA%\Bento CLI` |

A profile `<home>/profiles/<name>/` (default `default`, `--profile`/`BENTO_PROFILE`) holds `data/` (the instance `DATA_DIR`, same layout as the launcher creates), `endpoint.json`, `daemon.pid`, `logs/api.log`, `logs/worker.log`, `logs/daemon.log`, `config.json` (non-secret CLI preferences such as `lang`). Directories `0700`, files `0600` on POSIX.

A profile daemon is a **separate Bento device** (its own identity, keys, and local replica) that joins the person's vault through `bento setup`/`bento join` like any other device. The device wrapping key is file-based (`data/secure/wrapping.key`, `0600`) because a headless machine has no OS keychain the backend can use; `bento doctor` reports it as a warning, as the backend doctor already does.

## Target resolution (`--target auto`)

1. `--api-url` / `BENTO_API_URL` (with `BENTO_API_TOKEN`): use as-is.
2. Desktop: if `--profile` was not given, read the desktop endpoint file; if its PID is alive and `GET /api/health` with its token succeeds → use the desktop app (same library and device the person sees).
3. Profile daemon: read `<profile>/endpoint.json`; if alive → use it.
4. Otherwise, unless `--no-start`, start the profile daemon (`daemon start`) and wait for readiness (default 60 s) → use it. Errors → exit `5`.

`--target desktop` fails (exit 5, `desktop_not_running`) instead of falling back; `--target daemon` skips step 2. `bento status` always says which target is in use.

### Desktop endpoint file

Desktop main writes `<userData>/bento-desktop/cli-endpoint.json` (`0600`, atomic temp+rename) every time the API sidecar becomes ready, and deletes it when the sidecars stop or the app quits:

```json
{"version": 1, "kind": "desktop", "url": "http://127.0.0.1:53211", "token": "<cli token>", "pid": 4242, "app_version": "0.3.0", "started_at": "ISO"}
```

`pid` is the Electron main process. The token is a fresh per-launch `BENTO_DESKTOP_CLI_TOKEN` (never the renderer token). `<userData>` per OS: Linux `${XDG_CONFIG_HOME:-~/.config}/Bento`, macOS `~/Library/Application Support/Bento`, Windows `%APPDATA%\Bento`; `BENTO_DESKTOP_USER_DATA` overrides it (tests, portable installs).

### Daemon

`bento daemon run` (foreground, used by services and by `start`):

1. Ensure profile dirs; set `DATA_DIR=<profile>/data`, `BENTO_RUNTIME_MODE=headless`, `HOST=127.0.0.1`, `STORAGE_BACKEND=telegram` unless already set (env `STORAGE_BACKEND=fake` is honored for tests/demos), Telegram build credentials from the bundled build config or env.
2. Run migrations (`_sidecar migrate`).
3. Generate a per-run `BENTO_API_TOKEN` (32 bytes, urlsafe base64), spawn `_sidecar api --ephemeral` and `_sidecar worker` as children with stdout/stderr to the log files (token only via child env, never logged), wait for the READY line, verify `/api/health` with the token.
4. Write `endpoint.json` `{"version":1,"kind":"daemon","url","token","pid":<supervisor pid>,"app_version","started_at","profile"}` and `daemon.pid`.
5. Supervise: restart a crashed child with backoff (1 s → 30 s); on SIGTERM/SIGINT (Windows: CTRL_BREAK) stop children gracefully (10 s, then kill), delete `endpoint.json` and `daemon.pid`.

`daemon start` spawns `daemon run` detached (POSIX: new session, stdio to `logs/daemon.log`; Windows: `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`) and waits for `endpoint.json` + health. A second `run` for the same profile exits with `daemon_already_running` (PID lock). `daemon stop` signals the supervisor PID from `daemon.pid` and waits.

Desktop and a daemon must never share a data directory; the daemon refuses a `DATA_DIR` that contains a desktop `bootstrap.json` marker.

`daemon install-service` writes `~/.config/systemd/user/bento.service` (or `bento@<profile>`) with `ExecStart=<abs path to bento> daemon run --profile <p>` and prints the `systemctl --user enable --now` / `loginctl enable-linger` commands (it does not run `sudo`); macOS writes `~/Library/LaunchAgents/app.bento.cli.<profile>.plist`.

## Auth headers

Every request carries `Authorization: Bearer <token>` (when the target has one), `X-Bento-Client: web` (accepted by both guards; required by the headless guard when no token), and `User-Agent: bento-cli/<version>`. The token is never printed, logged, or included in error output; `bento api` redacts it from `--verbose` traces.

## Uploads

- Walk local inputs (files and directories), apply filters, build the plan `[(local_path, relative_dir)]` (with `--flatten`, all into `--to`).
- Hash files (SHA-256, streaming, 1 MiB chunks) with a small thread pool; `POST /assets/lookup` in batches of 500; existing contents are reported as `duplicate` with their path, without transfer.
- Ensure each destination directory once (`POST /drive/folders/ensure`), parents first, cached by relative dir.
- Upload remaining files with `--jobs` concurrent streaming multipart requests (`POST /assets/upload`, `folder_id`); retry transient failures (connection errors, 5xx, 429) 3 times with backoff; `telegram_flood_wait` is not an error for local upload (remote upload happens in the worker).
- The API accepts the file locally and the worker encrypts/uploads to Telegram in the background; `bento activity` / `bento sync status` show remote progress. `upload --wait` waits until `activity.uploads` is idle.

## Packaging and distribution

- **From source / Python:** `uv tool install ./apps/api` or `pipx install ./apps/api` installs the `bento` console script (`[project.scripts] bento = "bento.interfaces.cli.main:main"`). Requires Python ≥ 3.12.
- **Standalone binary:** `apps/api/packaging/bento-cli.spec` (PyInstaller onedir, same hidden imports as the sidecar spec plus the CLI) built by `apps/api/scripts/build_cli.py`; the `_sidecar` subcommand lets the frozen binary run api/worker/migrations without Python installed. `build-config.json` (Telegram build credentials, relay URL, public site URL) is placed next to the executable at build time from CI secrets, exactly like the desktop build config; the CLI exports it to the daemon environment.
- **Archives:** `bento-cli-<version>-<os>-<arch>.tar.gz` (Linux, macOS) / `.zip` (Windows), plus `bento-cli_<version>_<arch>.deb` for Debian/Ubuntu (built with `dpkg-deb`, installs to `/opt/bento-cli` with `/usr/bin/bento` symlink). `scripts/install/install.sh` installs the right archive into `~/.local/share/bento-cli/app` with a `~/.local/bin/bento` symlink after verifying the SHA-256 checksum; `scripts/install/install.ps1` for Windows.
- **CI:** `.github/workflows/cli-release.yml` builds and smoke-tests (`bento --version`, `bento commands --json`, daemon start/stop with `STORAGE_BACKEND=local`) on linux-x64, linux-arm64, macos-x64, macos-arm64, windows-x64; release artifacts with checksums.
