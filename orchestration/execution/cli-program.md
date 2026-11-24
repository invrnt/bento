# CLI Program (Stage 18)

Goal: a complete, agent-first `bento` CLI for every OS that can run the backend (Debian/Ubuntu and other Linux, macOS, Windows), with zero-config setup and Stremio-like device pairing, plus headless daemon mode. Binding docs: `product/cli.md`, `architecture/cli-runtime.md`, `api/cli-endpoints.md`.

## Workflow

- Integration branch: `feature/cli`. Each agent works in its own git worktree, commits there, and touches only its owned paths.
- Setup: `uv sync --project apps/api --extra dev`; desktop needs Node 24 (see `execution/telegram-first-program.md`).
- The orchestrator merges in order backend → cli → desktop/packaging/docs and resolves one-line registration conflicts.

## Stage 18 (parallel)

| Agent | Prompt | Owns |
|---|---|---|
| cli-backend | `agent-prompts/31-cli-backend-agent.md` | `domain/drive_paths.py`, `application/drive_paths.py`, `interfaces/http/routes_drive_paths.py` (+ one `include_router` line in `routes.py`), `interfaces/http/request_guard.py`, `interfaces/http/main.py` (guard wiring only), `interfaces/desktop/security.py`, `interfaces/desktop/launcher.py` (`--ephemeral`, token adoption), `infrastructure/services.py` (drive paths factory only), repository query methods needed by drive paths (`ports/` + `adapters/repositories/`, additive), tests under `tests/unit/drive_paths`, `tests/api/drive_paths`, `tests/api/test_request_guard.py`, `tests/api/test_desktop_security.py`, launcher tests |
| cli | `agent-prompts/32-cli-agent.md` | `interfaces/cli/**`, `apps/api/pyproject.toml` (scripts, httpx runtime dependency, package data), `apps/api/uv.lock`, `apps/api/tests/cli/**` |
| cli-desktop-packaging-docs | `agent-prompts/33-cli-distribution-agent.md` | `apps/desktop/**`, `apps/api/packaging/bento-cli.spec`, `apps/api/scripts/build_cli.py`, `scripts/install/**`, `.github/workflows/cli-release.yml`, `docs/user/{es,en}/cli.md`, `docs/dev/cli.md`, `README.md` (CLI section), `apps/site/**` (optional CLI page) |

Exit: backend suite green (including new tests), CLI tests green, desktop tests green, an end-to-end CLI journey against a real API process on the fake Telegram cloud (setup → upload tree → organize → search → second CLI profile joins by code → sees the files), PyInstaller CLI build runs `bento --version` and `bento daemon start/stop` locally.

## Status

See the bottom of this file (updated by the orchestrator at the end of the stage).
