# Product: Bento CLI

Audience: AI agents (Claude Code, Codex, etc.) acting for a person, power users, and headless machines (Debian/Ubuntu servers, Raspberry Pi, macOS, Windows). Typical request: "here are 40 photos and 3 PDFs, put them where they belong in my Bento". Whatever the CLI changes reaches every device of the person within seconds, because the vault and the sync log live in their Telegram account.

The CLI is a thin client of the local Bento API (`bento` executable, `bento.interfaces.cli`). It contains no business rules: every rule stays in `application/` and is reached over HTTP. Runtime (profiles, daemon, discovery, auth, packaging) is in `architecture/cli-runtime.md`; new endpoints are in `api/cli-endpoints.md`.

## Principles

- **Agent-first output.** Every command supports `--json` (or `BENTO_JSON=1`): exactly one JSON document on stdout, nothing else; errors as one JSON document on stderr. Human output is concise tables in the user's locale (Spanish default, English via `BENTO_LANG=en` or `LANG`).
- **Stable contracts.** JSON field names mirror the HTTP contracts; additions only. `bento commands --json` prints the full command catalog (name, args, flags, description, JSON output shape name) so agents can discover the CLI without reading docs; `bento guide` prints the agent guide (Markdown, packaged with the CLI).
- **Non-interactive by default when not a TTY.** Prompts only on a TTY; otherwise a missing value is a usage error. Destructive commands that cannot be undone (`trash purge`, `trash empty`, `devices remove`, `vault recovery rotate`) require `--yes` when not on a TTY. Moving to trash is undoable and needs no confirmation.
- **Idempotent and resumable.** `mkdir -p`, `upload` (content-hash dedupe), `backup add` of an existing source, `trash restore` of a restored item all succeed without duplicating anything. Re-running an interrupted `upload` transfers only what is missing.
- **Zero-config start.** The first command starts what it needs (see runtime doc). `bento setup` is the only thing a person ever has to run.
- **Never print secrets** except the recovery code in the response that created it (same rule as the HTTP contract). Telegram passwords are read from a TTY prompt or `--password-stdin`, never from argv in examples.

## Paths

Bento paths address Drive folders and files:

- Absolute, `/`-separated, leading `/` optional: `/`, `/Documentos/Facturas/2024`, `Fotos/Viaje/IMG_001.jpg`. No relative paths, `.` or `..`.
- A trailing `/` means "must be a folder".
- `id:<folder_or_asset_id>` addresses an item directly (`id:fld_…`, `id:ast_…`); always unambiguous. Every JSON item carries `id` and `path`.
- Names are compared exactly (case-sensitive, Unicode NFC-normalized on both sides). Sibling names are not unique in Bento (two devices may create the same folder concurrently): a path that matches several items fails with exit code `4` and `error.code = "path_ambiguous"`, `details.candidates = [{id, kind, path, created_at}]`; use `id:`.
- A name containing `/` can only be addressed by `id:`.
- `mkdir -p` and `upload --to` reuse the oldest existing sibling folder with the same name instead of creating another.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Unexpected error |
| 2 | Usage error (bad flags, missing argument, confirmation needed) |
| 3 | Not found (`path_not_found`, `*_not_found`) |
| 4 | Conflict (`path_ambiguous`, `*_conflict`, state conflicts) |
| 5 | Bento not reachable (daemon failed to start, desktop stopped, network to API) |
| 6 | Setup required (`signed_out`, `no_vault`, `locked`, `telegram_not_available`) — `error.details.next` names the command to run |
| 7 | Partial failure (a batch where some items failed; per-item results in the JSON) |
| 8 | Waiting on Telegram (`telegram_flood_wait`; `details.retry_after_seconds`) |
| 130 | Interrupted |

Error JSON (stderr): `{"error": {"code": "...", "message": "...", "details": {...}, "exit_code": N}}`.

## Commands

Global flags: `--json`, `--profile NAME`, `--target auto|desktop|daemon` (default `auto`), `--api-url URL`, `--no-start`, `--yes/-y`, `--quiet/-q`, `--timeout SECONDS`, `--lang es|en`, `--version`.

### Setup and account

| Command | Behavior |
|---|---|
| `bento setup [--phone NUMBER] [--join CODE] [--recovery-code CODE]` | Guided, resumable from any step: start/locate Bento → Telegram sign-in (QR rendered in the terminal with Unicode half blocks; `--phone` for code login) → if the account has no vault create it and print the recovery code once (asks to confirm the last group on a TTY) → if the account has a vault and this device is locked, offer pairing (`--join CODE`), fallback request, or `--recovery-code` → offer backup suggestions on a TTY. JSON mode runs non-interactively and returns the current `step` plus `next` actions instead of prompting. |
| `bento status` | One-screen summary: target (desktop/daemon, version), account, vault state, sync state, activity summary, attention items. Exit `6` when setup is required. |
| `bento login [--phone NUMBER] [--code CODE] [--password-stdin]` | Telegram sign-in. Without `--phone`: QR flow, refreshed automatically until authorized or `--timeout`. Prompts for code / 2FA password on a TTY. |
| `bento logout [--yes]` | Telegram sign-out (keeps the local library). |
| `bento whoami` | `AccountStatus.account`. |
| `bento vault status` · `create` · `unlock --recovery-code CODE` | Vault lifecycle. `create` prints the recovery code once. |
| `bento vault recovery rotate [--yes]` · `verify CODE` · `confirm LAST_GROUP` | Recovery kit management. |

### Devices and pairing (Stremio-like)

| Command | Behavior |
|---|---|
| `bento pair [--wait] [--approve]` | Host: create a pairing code; prints code, `bento://` link, web link and a terminal QR; with `--wait` follows the session, shows the guest's device name and the 4 SAS emojis and asks to approve on a TTY. `--approve` approves non-interactively once the peer connects (for an agent acting on explicit user instruction; the emojis are still printed). |
| `bento join CODE_OR_LINK [--no-wait]` | Guest: join with the code from another device; prints the emojis ("confirma en tu otro dispositivo"), waits for approval, then for bootstrap progress. If the relay says Telegram sign-in is needed, runs the QR login inline. |
| `bento pair status ID` · `approve ID` · `reject ID` · `cancel ID` · `confirm ID` | Drive a pairing session explicitly. |
| `bento pair request` · `pair requests` · `pair review REQ` · `pair accept REQ` · `pair deny REQ` | Sync-channel fallback (no relay). |
| `bento devices [ls] [--include-removed]` · `devices rename ID NAME` · `devices remove ID [--exclude ID…] [--yes]` · `devices ack ID` | Device management; `remove` prints the new recovery code. |

### Files (Drive)

| Command | Behavior |
|---|---|
| `bento ls [PATH] [-l] [--limit N] [--all]` | List a folder (folders first). `-l` adds size, type, dates, indexing state. `--all` follows cursors. |
| `bento tree [PATH] [--depth N] [--files/--no-files]` | Nested view (server-side, bounded; `truncated` flag). |
| `bento stat PATH…` | Full metadata of folders/files. |
| `bento mkdir [-p] PATH…` | Create folders. |
| `bento mv SRC… DEST` | Move files/folders into folder `DEST`; with a single `SRC` and a `DEST` whose parent exists but whose last segment does not, move and rename. |
| `bento rename PATH NEW_NAME` | Rename a file or folder. |
| `bento rm [-r] PATH…` | Move to trash (folders need `-r`). Prints how to undo (`bento trash restore`). |
| `bento upload LOCAL… [--to PATH] [--exclude GLOB…] [--include GLOB…] [--hidden] [--follow-symlinks] [--flatten] [--jobs N] [--dry-run] [--no-dedupe]` | Upload files and whole directory trees, recreating the directory structure under `--to` (default `/`; created with `mkdir -p` semantics). Hashes locally and asks the API which contents already exist (`POST /assets/lookup`), so re-runs and duplicates are skipped without transfer. Default `--jobs 2`. Hidden files and OS junk (`.DS_Store`, `Thumbs.db`, `desktop.ini`, `._*`) are skipped unless `--hidden`. Symlinks are not followed by default. Progress on stderr (TTY bar; with `--json`, nothing until the final summary). Summary: `{uploaded, duplicates, skipped, failed, bytes, items: [{local_path, status: "uploaded|duplicate|skipped|failed", asset?, path?, error?}]}`; exit `7` if any failed. A duplicate keeps its existing location and is reported with that path (`--no-dedupe` only skips the pre-check; the API still deduplicates). |
| `bento download PATH… [--to DIR] [-r] [--overwrite]` | Download files, or folders with `-r` recreating the tree. Never overwrites without `--overwrite`. |
| `bento cat PATH` | Stream one file's decrypted content to stdout. |
| `bento find [QUERY] [--in PATH] [--type TYPE] [--from DATE] [--to DATE] [--limit N] [--all]` | Search (name, metadata, OCR text, semantic when enabled). Results include `path`. |
| `bento open PATH` | Print the `bento://` / local content URL for the item (no GUI launch in JSON mode). |

### Photos

`bento photos [timeline] [--limit N]` · `bento albums [ls]` · `albums create NAME` · `albums show ALBUM` · `albums add ALBUM PATH…` · `albums remove ALBUM PATH…` · `bento favorite PATH… [--off]`. `ALBUM` is a name or `id:`.

### Trash

`bento trash [ls] [--all]` · `trash restore ID_OR_PATH…` · `trash purge ID… [--yes]` · `trash empty [--yes]`.

### Backup (watched folders)

`bento backup [ls]` · `backup add DIR [--label L]` · `backup remove ID` · `backup enable|disable ID` · `backup scan ID` · `backup suggestions` · `backup policy [--pause|--resume] [--pause-on-battery on|off] [--bandwidth-kbps N]`.

### Sync, activity, jobs

`bento sync [status]` · `sync now` · `bento activity [--watch]` (`--watch` streams NDJSON snapshots in JSON mode) · `bento jobs [ls] [--state S]` · `jobs retry ID` · `bento reindex`.

### Telegram

`bento telegram chats [--query Q]` · `bento share PATH --chat CHAT_ID [--caption TEXT] [--yes]` (sends an **unencrypted** copy; on a TTY asks for confirmation) · `bento import list --chat CHAT_ID [--kind photo|video|document|all]` · `bento import --chat CHAT_ID [--all | --message-ids ID…]`.

### Settings and maintenance

`bento settings [ls]` · `settings get KEY` · `settings set KEY=VALUE…` (validated with the server's `validate` endpoint first) · `settings schema` · `bento doctor` (connectivity, versions, data dir, Telegram, relay, disk) · `bento version`.

### Runtime

`bento daemon start|stop|restart|status|logs [-f]|run` · `bento daemon install-service` / `uninstall-service` (systemd user unit on Linux, launchd agent on macOS; Windows: not supported, `start` on demand works) · `bento completion bash|zsh|fish|powershell`.

### Agent helpers

- `bento commands --json`: catalog.
- `bento guide`: agent guide (how to organize a person's files: inspect with `tree`, prefer existing folders, `mkdir -p` sensible Spanish/English names matching the existing style, upload with `--to`, verify with `ls`, never purge, report what moved).
- `bento api METHOD PATH [--data JSON|@file] [--query K=V…]`: authenticated raw call to the local API (escape hatch; prints the response JSON).

## Out of scope (this program)

- A hosted web app that works without a local Bento process (would need MTProto + crypto in the browser; see `product/telegram-first-experience.md` § Deferred). The CLI and the local web UI cover every platform that can run the backend.
- Copy (`cp`) between Drive folders: Bento deduplicates content, so a file lives in one folder; albums cover multi-membership for photos.
- FUSE mount.
