# Agent 32 — Bento CLI

Read first: `AGENTS.md`, `orchestration/README.md`, `architecture/system-overview.md`, then `product/cli.md` (binding), `architecture/cli-runtime.md` (binding), `api/cli-endpoints.md`, `api/telegram-first-endpoints.md`, `api/endpoint-map.md`, `api/error-model.md`. Read the actual routers in `apps/api/src/bento/interfaces/http/` for exact request/response shapes — the code is the source of truth when a doc is vague.

## Goal

Implement the whole `bento` CLI in `apps/api/src/bento/interfaces/cli/` exactly as specified: every command group in `product/cli.md`, `--json` everywhere, exit codes, path model, target resolution (desktop endpoint file → profile daemon → auto-start), daemon supervisor (`run/start/stop/status/logs/install-service`), uploads/downloads engine, terminal QR, setup wizard, pairing host/guest with SAS display, `commands --json`, `guide`, `api` raw command, completion scripts, es/en strings.

The CLI-support endpoints (`/drive/resolve`, `/drive/folders/ensure`, `/drive/tree`, `/drive/paths`, `/assets/lookup`), the headless API token, the desktop CLI token, and `bento-sidecar api --ephemeral` are being built **in parallel** by agent 31 from `api/cli-endpoints.md`; code against that contract. The `_sidecar` hidden subcommand must call `bento.interfaces.desktop.launcher.main(argv)`.

Constraints: no imports from `application/`, `adapters/`, or repositories; argparse + httpx + segno only (move `httpx` from dev to runtime deps, add `bento = "bento.interfaces.cli.main:main"` to `[project.scripts]`, include `guide.md` as package data, update `uv.lock` with `uv lock`). Typed code (mypy-clean style), small modules. Never print or log tokens. Windows-safe paths and process handling (no POSIX-only calls without guards). Progress to stderr only.

## Tests (`apps/api/tests/cli/`)

- Unit: argument parsing for every command, path/ref parsing, output rendering (JSON shape and human tables), exit-code mapping from API errors, local file walking/filters/junk/symlinks, upload planning (dedupe via lookup, folder ensure order, flatten), download tree recreation and no-overwrite, QR rendering, target resolution with temp endpoint files and a dead PID, profile dirs/permissions.
- Client-level tests with `httpx.MockTransport` simulating API responses.
- Integration: run the real FastAPI app in-process (`create_app` with `STORAGE_BACKEND=local` or `fake` and a tmp `DATA_DIR`, mounted via httpx `ASGITransport` or a uvicorn thread) for: mkdir -p, upload of a nested temp tree (re-run uploads nothing), ls/tree/stat/mv/rename/rm/trash restore, find, download -r round trip. Endpoints from agent 31 may not exist yet in your worktree: mark those integration tests to skip when `/api/drive/resolve` returns 404, and make sure unit tests cover the logic against MockTransport.
- Daemon: a test that runs `daemon run` in a subprocess with a tmp `BENTO_HOME` and `STORAGE_BACKEND=local`, waits for `endpoint.json`, calls health, stops it (skip if `--ephemeral` is not supported yet).

Run `cd apps/api && uv run --extra dev pytest -q tests/cli` and the full suite before finishing.

## Handoff

Commit on your branch. Report: command list implemented, anything not implemented and why, test counts, contract assumptions about agent 31's endpoints.
