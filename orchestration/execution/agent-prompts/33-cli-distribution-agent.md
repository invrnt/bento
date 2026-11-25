# Agent 33 — CLI Desktop Integration, Packaging, Docs

Read first: `AGENTS.md`, `orchestration/README.md`, then `architecture/cli-runtime.md` (binding), `product/cli.md`, `api/cli-endpoints.md`, `architecture/desktop-runtime-settings.md`, `architecture/desktop-bridge-telegram-first.md`.

## Goals

1. **Desktop endpoint file** (`apps/desktop/src/main/**`): generate a fresh `BENTO_DESKTOP_CLI_TOKEN` (≥ 32 chars, same randomness source as the desktop token) per API sidecar start, pass it only through the API child environment, and write `<userData>/bento-desktop/cli-endpoint.json` (`0600`, temp + rename, schema in `architecture/cli-runtime.md`) whenever the API becomes ready; delete it when sidecars stop/restart and on quit. Never log the token (extend redaction if needed). Tests in `apps/desktop/tests` (vitest).
2. **Standalone CLI build**: `apps/api/packaging/bento-cli.spec` (PyInstaller onedir named `bento`, entry `bento.interfaces.cli.main`, hidden imports/data like `bento-sidecar.spec` plus `bento/interfaces/cli/guide.md`), `apps/api/scripts/build_cli.py` (mirrors `build_desktop_sidecar.py`, optional `--build-config` copying a JSON next to the executable), a Makefile target `cli-build` only if the Makefile has no owner conflict (otherwise document the command).
3. **Distribution**: `scripts/install/install.sh` (POSIX sh: detect OS/arch, download from GitHub release URL pattern configurable by `BENTO_CLI_BASE_URL`, verify SHA-256, install to `~/.local/share/bento-cli/app`, symlink `~/.local/bin/bento`, print next step `bento setup`), `scripts/install/install.ps1`, `scripts/install/build_deb.sh` (dpkg-deb, `/opt/bento-cli` + `/usr/bin/bento` symlink, control file with deps none since frozen). `.github/workflows/cli-release.yml` building on linux-x64, linux-arm64 (`ubuntu-24.04-arm`), macos-13, macos-14, windows-latest with smoke steps (`bento --version`, `bento commands --json`, `bento daemon start/stop` with `STORAGE_BACKEND=local`), uploading archives + checksums; triggered by `workflow_dispatch` and tags `cli-v*`. Do not change the existing required desktop workflows.
4. **Docs**: `docs/user/es/cli.md` and `docs/user/en/cli.md` (install per OS, `bento setup`, pairing a second device, everyday commands, using it with an AI agent), `docs/dev/cli.md` (architecture, profiles, daemon, packaging, testing), README CLI section, and the agent guide content `apps/api/src/bento/interfaces/cli/guide.md` is owned by agent 32 — do not create it. Optionally add a CLI page to `apps/site` if it fits its existing structure and tests.

The CLI itself is built in parallel by agent 32 from the same docs: write docs from `product/cli.md` command names; do not edit `interfaces/cli/**`.

## Verification

`npm --prefix apps/desktop test` (Node 24, see `execution/telegram-first-program.md`), `npm --prefix apps/desktop run typecheck` if present, site tests if touched, `sh -n` / shellcheck if available on scripts, YAML validity of the workflow.

## Handoff

Commit on your branch. Report files changed, test results, and the exact build commands.
