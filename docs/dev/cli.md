# Bento CLI (developer guide)

`bento` is an agent-first command-line client and headless daemon for Bento. Binding contracts: [`orchestration/product/cli.md`](../../orchestration/product/cli.md) (commands, JSON, exit codes), [`orchestration/architecture/cli-runtime.md`](../../orchestration/architecture/cli-runtime.md) (profiles, daemon, discovery, packaging) and [`orchestration/api/cli-endpoints.md`](../../orchestration/api/cli-endpoints.md) (HTTP additions and auth). User guide: [es](../user/es/cli.md) · [en](../user/en/cli.md).

## Architecture

- `bento.interfaces.cli` is an **interface** like `interfaces/http`: argument parsing (stdlib `argparse`), rendering, an `httpx` client, local file walking/hashing and daemon supervision. It never imports `application/`, `adapters/` or repositories; every rule is reached over the local HTTP API, so the CLI behaves the same against the desktop app and against its own daemon, and a second process never opens the SQLite database or the Telegram session.
- The only backend imports it may use: `bento.interfaces.desktop.launcher` (the hidden `_sidecar` subcommand runs api/worker/migrations inside the frozen binary), `bento.infrastructure.process_secrets` and IO-free `bento.domain` helpers (`domain/drive_paths.py`).
- Output contract: `--json` (or `BENTO_JSON=1`) prints exactly one JSON document on stdout; errors are one JSON document on stderr with a stable `error.code` and the exit codes listed in the product doc. `bento commands --json` prints the command catalog; `bento guide` prints the packaged agent guide (`interfaces/cli/guide.md`).

## Target resolution

`--target auto` (default) tries, in order: `--api-url`/`BENTO_API_URL` with `BENTO_API_TOKEN`; the running desktop app; the profile daemon; and finally starts the profile daemon (unless `--no-start`). `bento status` always says which target is in use.

### Desktop endpoint file

The Electron main process (`apps/desktop/src/main/cli-endpoint.ts`, wired in `index.ts`) publishes the running desktop API to local CLIs:

- `SidecarSupervisor` issues a fresh `BENTO_DESKTOP_CLI_TOKEN` (32 random bytes, base64url, same source as the renderer token) on **every** API sidecar start and passes it only through the API child's environment. It is stripped from the inherited environment of every sidecar, added to the per-launch redaction list, and never logged.
- When the API is authenticated-ready the supervisor emits `api-endpoint` `{port, cliToken}`; when the API stops, restarts or crashes it emits `api-endpoint` `null`.
- `CliEndpointFile` follows those events and writes `<userData>/bento-desktop/cli-endpoint.json` (`0600`, directory `0700`, temp file + rename, writes serialized), or deletes it. It is also deleted at startup (stale file from a crash) and on quit after the sidecars stop.

```json
{"version": 1, "kind": "desktop", "url": "http://127.0.0.1:53211", "token": "<cli token>", "pid": 4242, "app_version": "0.3.0", "started_at": "2026-11-23T10:00:00.000Z"}
```

`pid` is the Electron main process; the CLI checks it is alive and that `GET /api/health` succeeds with the token before using the desktop. The backend's `DesktopSecurityMiddleware` accepts the CLI token only on requests **without** an `Origin` header, so a web page cannot use it. `<userData>`: Linux `${XDG_CONFIG_HOME:-~/.config}/Bento`, macOS `~/Library/Application Support/Bento`, Windows `%APPDATA%\Bento`; `BENTO_DESKTOP_USER_DATA` overrides it for the CLI (tests, portable installs).

## Profiles and the daemon

`BENTO_HOME` overrides the CLI home (Linux `${XDG_DATA_HOME:-~/.local/share}/bento-cli`, macOS `~/Library/Application Support/Bento CLI`, Windows `%LOCALAPPDATA%\Bento CLI`). Each profile (`--profile NAME`, `BENTO_PROFILE`, default `default`) is a separate Bento **device** with its own `data/` (the instance `DATA_DIR`), `endpoint.json`, `daemon.pid`, logs and `config.json`.

`bento daemon run` migrates, spawns `_sidecar api --ephemeral` and `_sidecar worker` with a per-run `BENTO_API_TOKEN` (child environment only), writes `endpoint.json` once `/api/health` answers, restarts crashed children with backoff and cleans up on SIGTERM/SIGINT. `daemon start` runs it detached; `daemon install-service` writes a systemd user unit (Linux) or a launchd agent (macOS) and prints the enable commands without running `sudo`. A daemon refuses a data directory that belongs to the desktop app.

Headless devices keep the device wrapping key in `data/secure/wrapping.key` (`0600`) because there is no OS keychain the backend can use; `bento doctor` reports it as a warning.

## Running from source

```sh
uv sync --project apps/api --extra dev
uv run --project apps/api bento --version
uv run --project apps/api bento --json commands

# Isolated profile on the fake Telegram cloud (no real account needed):
export BENTO_HOME="$PWD/data/dev/cli-home" STORAGE_BACKEND=fake ENVIRONMENT=local
export BENTO_FAKE_TELEGRAM_DIR="$PWD/data/dev/fake-telegram"
uv run --project apps/api bento setup
uv run --project apps/api bento upload ./some-folder --to /Inbox
uv run --project apps/api bento --profile second join CODE   # a second device of the same account
```

Install the console script for your user: `uv tool install ./apps/api` or `pipx install ./apps/api` (Python ≥ 3.12).

## Packaging

### Standalone binary (PyInstaller onedir)

`apps/api/packaging/bento-cli.spec` builds a onedir named `bento` (entry `bento.interfaces.cli.main:main` through a generated launcher script, the sidecar's hidden imports and data plus `interfaces/cli/guide.md`). `apps/api/scripts/build_cli.py` mirrors `build_desktop_sidecar.py`:

```sh
# Optional: public build configuration, validated by the desktop validator (writes apps/desktop/resources/build-config.json).
# Release builds also export BENTO_TELEGRAM_API_ID/BENTO_TELEGRAM_API_HASH and pass --require-telegram.
BENTO_RELAY_URL=wss://relay.example BENTO_PUBLIC_SITE_URL=https://bento.example \
  node apps/desktop/scripts/write-build-config.mjs        # Node 24

uv sync --project apps/api --extra desktop
uv run --project apps/api --extra desktop python apps/api/scripts/build_cli.py \
  --output dist/cli \
  --build-config apps/desktop/resources/build-config.json \
  --archive dist/cli-release

dist/cli/bento/bento --version
```

- `--build-config` copies only the four public build keys (`BENTO_TELEGRAM_API_ID`, `BENTO_TELEGRAM_API_HASH`, `BENTO_RELAY_URL`, `BENTO_PUBLIC_SITE_URL`) to `dist/cli/bento/build-config.json` (mode `0644`); values are never printed. The CLI exports them to the daemon environment.
- `--archive DIR` writes `bento-cli-<version>-<os>-<arch>.tar.gz` (`.zip` on Windows) with a single top-level `bento/` directory, plus `<archive>.sha256`. `<version>` defaults to `apps/api/pyproject.toml`; `<os>` is `linux|macos|windows`, `<arch>` `x64|arm64`.
- There is no Makefile target (the Makefile is not owned by the CLI stage); use the commands above.

### Debian package

```sh
scripts/install/build_deb.sh dist/cli/bento 0.1.0 dist/cli-release amd64   # or arm64; needs dpkg-deb
sudo apt install ./dist/cli-release/bento-cli_0.1.0_amd64.deb
```

Installs to `/opt/bento-cli` with a `/usr/bin/bento` symlink. The bundle is frozen, so the package declares no dependencies.

### Installers

- `scripts/install/install.sh` (POSIX `sh`, Linux/macOS): detects OS/arch, downloads `bento-cli-<version>-<os>-<arch>.tar.gz` and `SHA256SUMS`, verifies the SHA-256, installs to `~/.local/share/bento-cli/app` (or `$XDG_DATA_HOME/bento-cli/app`) by swapping the directory, symlinks `~/.local/bin/bento` and prints `bento setup` as the next step. Never uses `sudo`.
- `scripts/install/install.ps1` (Windows): same flow into `%LOCALAPPDATA%\Bento CLI\app` and adds it to the user `PATH`. Windows on Arm uses the x64 build.
- Variables: `BENTO_CLI_VERSION` (default: the latest Bento release, `releases/latest`), `BENTO_CLI_BASE_URL` (default `https://github.com/invrnt/bento/releases/download/v<version>`; a custom base must serve the archives, `SHA256SUMS` and, without `BENTO_CLI_VERSION`, a `VERSION` file), `BENTO_INSTALL_DIR`, `BENTO_BIN_DIR` (sh only).

Local test of the installer against a build:

```sh
cat dist/cli-release/*.sha256 > dist/cli-release/SHA256SUMS
HOME="$(mktemp -d)" BENTO_CLI_VERSION=0.1.0 BENTO_CLI_BASE_URL="file://$PWD/dist/cli-release" sh scripts/install/install.sh
```

### Releases

CLI archives, the `.deb` packages and both installers are assets of the product release `vX.Y.Z`, built locally by
`scripts/release/bento-release` (`--only cli` on each platform; smoke test `--version` and daemon
start/status/stop) and listed in its signed `SHA256SUMS`. The installers read `releases/latest`, which is
always the product release. `cli-v*` tags are retired (none was ever published). See [releasing](releasing.md).

The dormant `.github/workflows/cli-release.yml` (manual-only since Actions has no billing) documents the former
matrix:

| Matrix id | Runner | Notes |
|---|---|---|
| `linux-x64` | `ubuntu-22.04` | Also builds and installs the `.deb` (`amd64`). |
| `linux-arm64` | `ubuntu-22.04-arm` | Also builds the `.deb` (`arm64`). |
| `macos-x64` | `macos-15-intel` | |
| `macos-arm64` | `macos-15` | |
| `windows-x64` | `windows-2025` | `.zip` |

Each job runs `pytest tests/cli`, writes the build configuration (Telegram credentials from secrets only on tags, with `--require-telegram`), builds the archive, and smoke-tests the frozen binary: `bento --version`, `bento commands --json`, `bento daemon start/status/stop` with `STORAGE_BACKEND=local` in a throwaway `BENTO_HOME`. Dispatch runs only upload workflow artifacts (version `<x.y.z>+<sha>`).

Linux builds use Ubuntu 22.04 runners (glibc 2.35) so the bundle runs on Debian 12, Ubuntu 22.04+ and Raspberry Pi OS bookworm. macOS binaries are not yet signed or notarized: when downloaded through a browser, Gatekeeper may block them (`xattr -d com.apple.quarantine`); the `curl | sh` installer is not affected.

## Testing

```sh
(cd apps/api && uv run pytest tests/cli)                   # CLI unit/integration tests
(cd apps/api && uv run pytest)                             # whole backend
export PATH="$HOME/.local/share/mise/installs/node/24.19.0/bin:$PATH"   # or any Node 24
npm --prefix apps/desktop ci && npm --prefix apps/desktop test          # includes cli-endpoint tests
sh -n scripts/install/install.sh && sh -n scripts/install/build_deb.sh
```

The desktop tests cover the CLI token (fresh per API start, API-only environment, redaction) and the endpoint file (schema, `0600`, atomic replace, removal on stop/crash/restart).
