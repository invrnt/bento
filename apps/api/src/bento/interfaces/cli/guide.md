# Bento CLI — guide for AI agents

You are acting for a person who keeps their photos and documents in **Bento**: a private cloud stored,
end-to-end encrypted, in their own Telegram account and synced to all their devices. Anything you change
with this CLI shows up on every device of that person within seconds. Work carefully, keep their existing
organization, and tell them what you did.

## 1. Ground rules

- Always pass `--json`. Each command prints exactly one JSON document on stdout; errors are one JSON
  document on stderr: `{"error": {"code", "message", "details", "exit_code"}}`. Branch on `error.code`
  and the exit code, never on human text.
- Long-running commands (`login`, `pair --wait`, `join`) also write progress events to stderr as one JSON
  object per line, e.g. `{"event": "pairing_code", "code": "K7Q2-MXR9-T4WA", ...}`,
  `{"event": "pairing_sas", "sas": [...]}`, `{"event": "login_qr", "qr_url": "tg://login?token=..."}`.
  Read them to relay the code, emojis or QR link to the person while the command keeps waiting.
- Discover the CLI with `bento commands --json` (every command, argument, flag and output shape).
- Bento paths are absolute, `/`-separated: `/Documentos/Facturas/2024`. A trailing `/` means "must be a
  folder". `id:<id>` addresses an item directly and is always unambiguous. Every JSON item has `id` and
  `path`.
- **Never purge.** `bento rm` moves to the trash (undoable). Do not run `bento trash purge`,
  `bento trash empty`, `bento devices remove` or `bento vault recovery rotate` unless the person explicitly
  asked for that exact action. They need `--yes` and you should not add it on your own.
- Never print, store or repeat secrets: recovery codes, Telegram codes or passwords. If the person must
  type one, ask them to run the command themselves in their terminal.
- `bento share` sends an **unencrypted** copy to a Telegram chat. Only on explicit request.

## 2. Exit codes

| Code | Meaning | What to do |
|---|---|---|
| 0 | Success | Continue. |
| 2 | Usage error / confirmation needed | Fix the arguments. `confirmation_required` means the action is irreversible: ask the person. |
| 3 | Not found (`path_not_found`) | Re-check with `bento tree` / `bento find`; do not guess. |
| 4 | Conflict (`path_ambiguous`, `path_exists`, `not_a_folder`) | See § 6. |
| 5 | Bento not reachable | Retry once; then `bento doctor --json` and report. |
| 6 | Setup required | See § 3. |
| 7 | Partial failure | Read per-item `items[].status` / `items[].error`; retry only the failed ones. |
| 8 | Waiting on Telegram (`telegram_flood_wait`) | Wait `error.details.retry_after_seconds`, then retry. |

## 3. Before anything: check the state

```sh
bento status --json
```

- Exit `0`: ready. `target.kind` says whether you are talking to the person's desktop app (`desktop`) or a
  background daemon (`daemon`).
- Exit `6` (setup required): `setup.reason` is `signed_out`, `no_vault`, `locked` or
  `telegram_not_available`, and `setup.next` names the command to run. Setup involves scanning a QR code
  with the person's phone, approving on another device, or typing a recovery code, so **ask the person to
  run `bento setup` in their own terminal** (or, to add this machine to an existing Bento,
  `bento join CODE` with the code shown by another device under Settings → Devices → Add, or by
  `bento pair` there). Do not try to complete it for them. Re-run `bento status --json` afterwards.
- Other commands can also exit `6` with `error.details.next`; handle them the same way.

## 4. Discover before you organize

```sh
bento tree / --depth 3 --no-files --json        # the folder skeleton
bento tree /Documentos --depth 2 --json          # one branch with files
bento ls /Fotos --all --json                     # one folder, every page
bento find "factura luz" --json                  # name, metadata and OCR text search
bento find --type photo --from 2024-06-01 --to 2024-06-30 --json
```

Look at how the person already names things and **mirror it**:

- Language (Spanish `Documentos/Facturas` vs English `Documents/Invoices`), capitalization, separators,
  date formats (`2024`, `2024-06`, `2024-06 Viaje a Cartagena`), singular/plural.
- Prefer an existing folder over a new one. If `/Documentos/Facturas` exists, do not create
  `/Documents/Bills` or `/Facturas`.
- Only create a new top-level folder when nothing fits, and keep it short and obvious (`/Fotos`,
  `/Documentos`, `/Trabajo`, `/Salud`, `/Hogar`).
- If `tree` reports `"truncated": true`, use a smaller `--depth` or walk the branches separately.

## 5. Put files in place

```sh
bento mkdir -p "/Documentos/Facturas/2024" --json
bento upload ./factura-luz-enero.pdf ./factura-agua.pdf --to "/Documentos/Facturas/2024" --json
bento upload ~/Escaneos/Viaje --to /Fotos/2024 --json      # creates /Fotos/2024/Viaje/…
bento upload ~/Escaneos/Viaje/ --to /Fotos/2024/Viaje --json   # trailing / = only its contents
bento upload ~/Descargas --include "*.pdf" --to /Documentos/Sin-ordenar --dry-run --json
```

- `mkdir -p` and `upload --to` create missing folders and **reuse** an existing folder with the same
  name, so they are safe to repeat.
- `upload` recreates the local directory structure under `--to` (`--flatten` puts every file directly in
  `--to`). Hidden files and OS junk (`.DS_Store`, `Thumbs.db`, …) are skipped unless `--hidden`;
  symlinks are not followed unless `--follow-symlinks`.
- Content is deduplicated by SHA-256: a file already in Bento is reported as
  `"status": "duplicate"` with the `path` where it already lives, and nothing is transferred. A Bento file
  lives in one folder; if a duplicate is in the wrong place, `bento mv` it instead of uploading again.
- Re-running an interrupted upload transfers only what is missing. Use `--dry-run` first for big batches
  and show the person the plan.
- The summary is `{uploaded, duplicates, skipped, failed, bytes, items: [{local_path, status, path, …}]}`.
  The upload is accepted locally at once; Bento then encrypts and sends it to Telegram in the background
  (`bento activity --json`, or `upload --wait`).

Reorganize what is already in Bento:

```sh
bento mv "/Entrada/IMG_0042.jpg" "/Entrada/IMG_0043.jpg" "/Fotos/2024/Cumpleaños de Ana" --json
bento mv "/Entrada/scan.pdf" "/Documentos/Salud/2024-03 Resultados laboratorio.pdf" --json   # move + rename
bento rename "/Documentos/cv.pdf" "CV Ana Pérez 2024.pdf" --json
bento albums add "Vacaciones 2024" "/Fotos/2024/Viaje/IMG_0101.jpg" --json   # photos can also go in albums
bento favorite "/Fotos/2024/Viaje/IMG_0101.jpg" --json
```

`mv SRC… DEST` moves into the folder `DEST`. With a single `SRC` and a `DEST` that does not exist but
whose parent does, it moves and renames. Moving or renaming folders moves everything inside them.

## 6. Ambiguity and conflicts

Two devices can create folders with the same name at the same time, so sibling names are not unique.
A path that matches several items fails with exit `4`:

```json
{"error": {"code": "path_ambiguous", "details": {"path": "/Fotos",
  "candidates": [{"id": "folder_…", "kind": "folder", "path": "/Fotos", "created_at": "…"}, …]}}}
```

Inspect each candidate (`bento ls id:folder_… --json`), pick the right one (usually the oldest or the one
with content) and continue with `id:`. You may suggest merging them to the person (`bento mv` the
contents of one into the other, then `bento rm -r` the empty one — it goes to the trash). A name that
contains `/` can only be addressed by `id:`.

`path_exists` (plain `mkdir` of an existing folder): use `mkdir -p`. `not_a_folder`: the destination is a
file.

## 7. Verify, then report

After changing things, check the result instead of assuming it:

```sh
bento ls "/Documentos/Facturas/2024" --json
bento stat "/Documentos/Facturas/2024/factura-luz-enero.pdf" --json
```

Then tell the person, briefly and concretely, what changed, e.g.:

> Subí 12 archivos a /Documentos/Facturas/2024 (3 ya estaban en Bento y no se duplicaron), creé la
> carpeta /Fotos/2024/Viaje a Cartagena con 40 fotos y moví scan.pdf a /Documentos/Salud. Nada se borró;
> si algo no te gusta, `bento trash restore` lo recupera.

Report every failed item from a partial result (exit `7`) and anything you were unsure about.

## 8. Undo

```sh
bento trash --json                          # what was removed, with ids
bento trash restore id:asset_… --json         # or the trashed name when it is unique
```

Restoring an already restored item is harmless. Items stay in the trash for the retention period
(30 days by default) unless someone purges them.

## 9. Other useful commands

- `bento download PATH… --to DIR [-r]` (never overwrites without `--overwrite`), `bento cat PATH` (bytes
  to stdout).
- `bento photos --json`, `bento albums --json`, `bento albums show "Name" --json`.
- `bento backup --json` (folders backed up automatically), `bento backup suggestions --json`.
- `bento activity --json`, `bento sync --json`, `bento jobs --state failed --json`.
- `bento doctor --json` when something does not work; include its result in your report.
- `bento api GET /drive/items --query folder_id=… --json` is a raw escape hatch to the local API; prefer
  the dedicated commands.
