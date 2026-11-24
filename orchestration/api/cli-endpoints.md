# CLI-Support HTTP Contract

Additions needed by the CLI (`product/cli.md`). All under `/api`, existing error model (`api/error-model.md`). Business rules live in `application/drive_paths.py` (use cases) and `domain/drive_paths.py` (pure path parsing/normalization); the router is `interfaces/http/routes_drive_paths.py`.

## Path model (domain)

- `parse_drive_path(text) -> DrivePath`: strips one leading `/`, splits on `/`, rejects empty inner segments, `.` and `..`; NFC-normalizes each segment; `DrivePath.must_be_folder` is true when the text ends with `/` (except `/` itself). `/` or empty = root.
- `DriveRef`: either a `DrivePath` or an `id:<id>` reference (`parse_drive_ref`).
- Comparison is exact after NFC. Deleted (trashed) folders/assets never match.
- Ambiguity: when more than one non-deleted sibling matches a segment → `PathAmbiguousError` (`409 path_ambiguous`, `details.path`, `details.candidates: [{id, kind: "folder|asset", path, created_at}]`, max 20).
- Not found → `PathNotFoundError` (`404 path_not_found`, `details.path`, `details.missing_from` = the first missing segment index).
- Folders take precedence over assets only when `must_be_folder`; otherwise a folder and an asset with the same name under one parent are ambiguous.
- `ensure` picks the **oldest** (`created_at`, then id) existing folder when several siblings share the name — it never fails with `path_ambiguous` and never creates a duplicate.

## Endpoints

| Method | Path | Body / Query | Response |
|---|---|---|---|
| GET | `/drive/resolve` | `?path=` (path or `id:` ref) | `ResolvedItem` |
| POST | `/drive/folders/ensure` | `{path}` | `{folder: Folder \| null (root), path, created: [folder_id]}` (mkdir -p) |
| GET | `/drive/tree` | `?path=` (default `/`) `&depth=1..20` (default 3) `&include_assets=true` `&max_nodes=1..10000` (default 2000) | `{root: TreeNode, truncated: bool, nodes: int}` |
| POST | `/drive/paths` | `{ids: [string]}` (≤ 500, folder or asset ids) | `{paths: {id: "/A/B/file.pdf"}, missing: [id]}` |
| POST | `/assets/lookup` | `{sha256: [hex64]}` (≤ 500, lowercase hex) | `{items: {sha256: {asset: Asset, path}}}` only for existing non-deleted assets |

`ResolvedItem`: `{kind: "root|folder|asset", path: "/A/B", folder: Folder | null, asset: Asset | null, breadcrumbs: [{id, name}]}`. `Folder` and `Asset` are the existing response models (`FolderResponse`, `AssetResponse`).

`TreeNode`: `{kind: "root|folder|asset", id: string | null, name: string, path, size_bytes?: int, mime_type?: string, created_at?: ISO, children?: [TreeNode]}`. Folders before assets, each sorted by name (casefold) then id. `children` omitted at the depth limit for folders that have children, with `"has_more": true`.

Path strings in responses are canonical: leading `/`, NFC, no trailing `/`; root is `/`. A name containing `/` is rendered with the `/` escaped as `\/` (display only; such items are addressed by `id:`).

Validation errors: bad path syntax → `400 validation_failed` with `details.reason` (`empty_segment|dot_segment|too_long`); limits exceeded → `400 validation_failed`. Max path length 4096 characters, max 64 segments.

## Authentication additions

### Headless API token

`BENTO_API_TOKEN` (≥ 32 chars). The launcher adopts it with `process_secrets.adopt_environment_secrets` (removed from `os.environ` so children don't inherit it). When set, `LocalRequestGuard` additionally requires `Authorization: Bearer <token>` on every HTTP and WebSocket request (constant-time compare) → otherwise `401 api_token_required` with `WWW-Authenticate: Bearer`. A request with a valid bearer token is exempt from the `X-Bento-Client: web` CSRF header (browsers cannot attach a bearer token cross-site without a preflight). The Host check still applies. When unset, behavior is unchanged (Docker / `make dev`).

### Desktop CLI token

`BENTO_DESKTOP_CLI_TOKEN` (≥ 32 chars, optional; adopted the same way). `DesktopSecurityMiddleware` accepts a request when either:

1. existing rule: exact `Origin` + `Authorization: Bearer <desktop token>`, or
2. **no** `Origin` header and `Authorization: Bearer <cli token>` (non-browser client; a browser always sends `Origin` on cross-origin and on non-GET requests, so a page cannot use this path).

A request with an `Origin` header and the CLI token is rejected (`403 desktop_origin_rejected`).

### Launcher: ephemeral headless port

`bento-sidecar api --ephemeral` (headless mode only): binds a loopback socket chosen by the OS (same code path as desktop: `bind_loopback_listener` + `announce_ready`) and prints `BENTO_API_READY {"port":N}` once accepting. Refused together with `--port` or a non-loopback host.

## Ownership

Backend agent (`agent-prompts/31-cli-backend-agent.md`).
