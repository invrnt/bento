# Agent 31 — CLI Backend Support

Read first: `AGENTS.md`, `orchestration/README.md`, `architecture/system-overview.md`, `architecture/boundaries-layers.md`, then `api/cli-endpoints.md` (binding), `architecture/cli-runtime.md` (context), `product/cli.md` (context).

## Goal

Implement every item of `api/cli-endpoints.md`:

1. `domain/drive_paths.py`: pure path parsing/normalization (`parse_drive_path`, `parse_drive_ref`, canonical formatting with `\/` escaping), errors `PathNotFoundError`, `PathAmbiguousError` as `DomainError`s mapped to `404 path_not_found` / `409 path_ambiguous` through the existing error mapping (find where error codes map to HTTP statuses and add these two).
2. `application/drive_paths.py`: `DrivePathUseCases` with `resolve`, `ensure_folder`, `tree`, `paths_for_ids`, `lookup_sha256`. Reuse `DriveUseCases.create_folder` for creation so the manifest/sync change capture is identical to the UI path (folders created by `ensure` must sync to other devices — verify with the existing sync change-capture tests or add one). Add only the additive repository query methods you need (children by parent including assets, batch get by ids, get by sha256 batch), with efficient SQL (no N+1 over whole trees; `tree` bounded by `max_nodes`).
3. `interfaces/http/routes_drive_paths.py` + one `router.include_router(...)` line; responses reuse the existing `FolderResponse`/`AssetResponse` builders (do not duplicate them — import or move helpers carefully without behavior change).
4. Headless `BENTO_API_TOKEN` in `LocalRequestGuard` (HTTP + WebSocket), desktop `BENTO_DESKTOP_CLI_TOKEN` in `DesktopSecurityMiddleware`, both adopted with `process_secrets.adopt_environment_secrets` in the launcher; `bento-sidecar api --ephemeral` for headless.
5. Update `api/endpoint-map.md` with the new routes.

## Tests

Unit tests for path parsing (NFC, trailing slash, dot segments, escaping, limits) and use cases with in-memory fakes; API tests with TestClient covering resolve (root/folder/asset/ambiguous/not found/trashed ignored/`id:`), ensure (creates, reuses oldest duplicate, idempotent), tree (depth, truncation, ordering), paths, lookup; guard tests (token required, valid token exempts CSRF header, websocket rejection, unchanged when unset); desktop middleware tests for the CLI-token path including "Origin + CLI token is rejected"; launcher `--ephemeral` test. Run the full backend suite (`cd apps/api && uv run --extra dev pytest -q`) before finishing; it must stay green.

## Handoff

Commit on your branch with a clear message. Report: files changed, new error codes, any deviation from the contract (should be none), test counts.
