# Desktop Bridge — Telegram-First Additions

Status: binding contract for Stage 16 web agents (`28-web-onboarding-devices`, `29-web-everyday`). Source of truth for types: `apps/desktop/src/shared/contracts.ts`. Security model: `architecture/desktop-runtime-settings.md` (unchanged guarantees: `contextIsolation`, sandbox, CSP, navigation blocking, allowlisted IPC, payload validation on both sides, log redaction; no generic filesystem, shell, or process access).

`window.bento` exists only in the desktop app. Feature-detect every member (`window.bento?.preferences`) so the same renderer still works in the browser/headless mode, where these capabilities simply do not exist.

## Breaking Changes To Existing Members

| Member | Before | Now | Renderer action |
|---|---|---|---|
| `platform().secureStorage` | `"available" \| "unavailable"` | `"os" \| "file"` | `"os"`: device keys are wrapped by the OS store. `"file"`: the backend keeps its key in a `0600` file; show the Advanced notice "protege esta carpeta". Replace `=== "available"` checks. |
| `platform().locale` | – | BCP 47 OS locale (e.g. `"es-CO"`) | Optional input for language/number formatting. |
| `settings.probe()` | kinds incl. `"telegram"`, optional `secrets` | kinds `"writable-directory" \| "model-file" \| "ffmpeg" \| "ocr"`; no `secrets` field | Remove the Bot API connection test. Extra fields are rejected with `TypeError`. |
| `settings.apply().secrets` | any key | only keys in the desktop secret allowlist, which is now **empty** | Send `secrets: {}`. Any secret key is rejected with `TypeError` (Telegram sessions/keyrings live in the backend key store, never in settings). |

## Types

```ts
export type SecureStorageMode = "os" | "file";

export interface PlatformMetadata {
  desktop: true;
  platform: NodeJS.Platform;          // "darwin" | "win32" | "linux"
  arch: string;
  version: string;                     // app semver
  secureStorage: SecureStorageMode;
  locale: string;                      // OS preferred locale, BCP 47
  recoveryMode: boolean;
}

export interface DesktopPreferences {
  keepRunningInBackground: boolean;    // default true
  launchAtLogin: boolean;              // default false until onboarding enables it
  autoDownloadUpdates: boolean;        // default true
}
export type DesktopPreferencesPatch = Partial<DesktopPreferences>;

export interface JoinDeepLink { kind: "join"; code: string }   // code: "K7Q2-MXR9-T4WA" (upper-case)
export type DeepLink = JoinDeepLink;

export type NavigationTarget = "activity" | "drive" | "settings" | "recovery-kit";
export interface NavigateRequest { target: NavigationTarget; attentionId?: string }

export interface SavePdfRequest { suggestedName?: string }
export interface SavePdfResult { saved: boolean; fileName?: string }
```

## Bridge Additions

```ts
interface BentoDesktopBridge {
  // existing: platform, pickDirectory, pickFile, settings, lifecycle, updates
  preferences: {
    get(): Promise<DesktopPreferences>;
    set(patch: DesktopPreferencesPatch): Promise<DesktopPreferences>;
  };
  onDeepLink(listener: (link: DeepLink) => void): () => void;
  onNavigate(listener: (request: NavigateRequest) => void): () => void;
  savePageAsPdf(request?: SavePdfRequest): Promise<SavePdfResult>;
}
```

| Member | IPC channel(s) | Payload validation (main) |
|---|---|---|
| `preferences.get` | `bento:preferences-get` | no payload |
| `preferences.set` | `bento:preferences-set` | plain object; only the three keys; booleans; at least one key |
| `onDeepLink` | event `bento:deep-link`; commands `bento:deep-link-subscribe` / `-unsubscribe` | no payload; sender must be the main window's top-level frame |
| `onNavigate` | event `bento:navigate`; commands `bento:navigate-subscribe` / `-unsubscribe` | same as above |
| `savePageAsPdf` | `bento:save-page-as-pdf` | optional `suggestedName` only: 1–120 chars, no path separators, control or reserved characters, no leading dot, not a Windows reserved name |

All channels also require the `bento://app` origin (existing rule).

### `preferences`

- `get()` returns the stored values (defaults above on first run or if the file is unreadable).
- `set(patch)` applies side effects first and persists only if they succeed; it resolves with the full updated preferences.
  - `launchAtLogin`: macOS/Windows login item, Linux `~/.config/autostart/bento.desktop` (atomic write). An inherited `APPIMAGE` is used only while this executable runs from that AppImage's mount (`APPDIR`) and it is an absolute regular file owned by the current user and not world-writable; otherwise the entry is not written and the call fails with `preferences_launch_at_login_failed`. Login starts use `--hidden` (macOS uses `wasOpenedAtLogin`) and stay in the tray. Development (unpackaged) builds store the value but never register the Electron binary.
  - `keepRunningInBackground`: when `true`, closing the window hides it; `Salir` in the tray (or OS shutdown/update) is the only way to quit. When `false`, closing the window quits.
  - `autoDownloadUpdates`: when turned on with an update already `available`, the download starts immediately.
- Errors: invalid payload → `TypeError`; OS refused the login item → rejects with message containing `preferences_launch_at_login_failed` (value unchanged). Electron prefixes IPC errors (`Error invoking remote method '…': Error: <message>`), so match with `includes`.

**Renderer must:** call `preferences.set({ launchAtLogin: true })` when onboarding reaches **Listo** (unless the user opted out), and expose all three toggles in Ajustes › General ("Abrir al iniciar sesión", "Mantener en segundo plano", "Descargar actualizaciones automáticamente").

### `onDeepLink`

- Main accepts only `bento://join?v=1&c=<code>` (exactly the `v` and `c` parameters, `v=1`, code upper-cased and matched against `^[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$`, max 256 chars). Everything else is dropped and logged without its content.
- Sources: cold-start argv (Windows/Linux), `second-instance` (Windows/Linux), `open-url` (macOS). Main also shows and focuses the window.
- Delivery is buffered: links received before the renderer subscribes (cold start, reload, renderer crash) are held (max 16, duplicates collapsed) and flushed once when the first listener subscribes. The returned function unsubscribes; when the last listener leaves, main buffers again.

**Renderer must:** subscribe once at app bootstrap (not inside a lazily mounted screen), then route `{kind: "join", code}` to the join flow ("Ya uso Bento") and call `POST /api/pairing/join` with `{code}`. If the device is already paired, show a calm explanation instead of starting a pairing.

### `onNavigate`

Emitted when the user clicks a native notification (after main focuses the window). Same buffering as `onDeepLink`.

| `target` | Raised by | Suggested route |
|---|---|---|
| `"activity"` | attention items with `retry`/`none`, bursts of >2 items, Send-to failures | Actividad panel (highlight `attentionId` when present) |
| `"recovery-kit"` | `recovery_kit` items / `save_recovery_kit` action | Guardar kit de recuperación |
| `"settings"` | `open_settings` action | Ajustes (section for the item) |
| `"drive"` | "N archivos añadidos a Bento" after Send-to | Drive (recent uploads) |

Unknown targets from a newer desktop build should fall back to Actividad.

### `savePageAsPdf`

- Prints the **current page of the main window** with `printToPDF({ printBackground: true, pageSize: "A4" })`, then shows a native save dialog (default `Documents/Kit de recuperación de Bento.pdf`, or `Bento recovery kit.pdf` for English OS locales; `suggestedName` overrides the file name, `.pdf` is appended when missing; an existing file the dialog did not confirm is never replaced, so the appended name becomes `<name> (2).pdf`, `(3)`, … instead). The file is written atomically with owner-only permissions and the in-memory PDF is wiped afterwards.
- Result: `{ saved: false }` when the dialog is canceled; `{ saved: true, fileName }` (base name only, never a path) on success.
- Errors: invalid payload → `TypeError`; called from anything but the main window's top-level frame → `This command is only available to the main window`; a save already in progress → `pdf_save_in_progress`; filesystem failures reject with the OS error.
- The renderer never supplies HTML, URLs, or paths.

**Renderer must:** render the recovery kit as a dedicated print view before calling it (A4 `@page` rules, `@media print` hiding app chrome, kit title, account name, vault date, code in 9 groups, QR of `bento-recovery:<code>`, warning copy from `product/telegram-first-experience.md`), then restore the normal view. Offer `Imprimir` (`window.print()`) as the browser/headless alternative.

### `updates` (behavior change, same API)

- Packaged builds check metadata at startup and every 6 h. With `autoDownloadUpdates`, an available update is downloaded and verified in the background (all existing hash/size/manifest/feed checks and fail-closed rules still apply).
- `status: "downloaded"` is the **ready** state: show `Reiniciar para actualizar` (`installMode: "automatic"`) or `Instalar actualización…` (`"manual"`, Linux `.deb`) and call `updates.install()` only on explicit user action. The tray offers the same action.
- Verification failures surface as `status: "error"` with a bounded `error.code` (`updates_*`); nothing is staged and the next 6 h cycle retries.
- Development builds never check automatically.

## Main-Process Behavior The Renderer Should Know

- **Tray/menu bar**: status line from `GET /api/activity` (polled every 5 s through the authenticated loopback client, paused while the system sleeps), `Abrir Bento`, `Pausar respaldo`/`Reanudar respaldo` (`PATCH /api/backup/policy {paused}`), the update action when ready, `Salir`. Icons: idle, syncing, paused (also offline), attention. If the activity endpoint is missing or failing, the tray shows a neutral "Bento está abierto".
- **Notifications**: only for attention items not seen before (ids remembered across launches, max 500; silent while the main window is focused and visible), Send-to results, and the one-time "Bento sigue funcionando en segundo plano" on the first hide.
- **Send to Bento**: files from Explorer "Enviar a", macOS "Abrir con", Linux "Abrir con" (`%U`, `file://` URLs accepted) and files dropped on the macOS dock icon are validated (absolute regular files only; selected symlinks, directories, devices, duplicates rejected; max 2,000 per batch) and uploaded sequentially by main to `POST /api/assets/upload` (multipart field `file`, streamed). The renderer sees them through normal asset queries and `/api/activity`; no bridge call is involved.
- **Power**: main posts `POST /api/backup/power {on_battery}` at start, on every battery/AC change (polled every 60 s on Linux), and after each API restart.
- **Deep-link registration**: packaged builds declare `bento://` (macOS `CFBundleURLTypes`, deb `MimeType=x-scheme-handler/bento`) and call `setAsDefaultProtocolClient` at startup (Windows uses the Squirrel stub so updates keep working). Development runs do not register the scheme; test with `electron . "bento://join?v=1&c=…"` as a second instance.
- **Window**: `--hidden`/login starts load the renderer without showing it. Closing hides the window (see preference). On macOS the dock icon is hidden only while the window is closed.

## Sidecar Environment (for backend agents)

| Variable | When | Value |
|---|---|---|
| `BENTO_DEVICE_WRAPPING_KEY` | OS secure store available, or a key was stored before | base64url (no padding) of 32 random bytes generated on first launch and kept in the OS store under the reserved internal name `device-wrapping-key`. Omitted in file mode; an inherited value is always stripped. If a key was stored but the OS store is unavailable, startup fails closed with a recovery screen instead of switching keys. A data dir that already has `secure/wrapping.key` stays in file mode. |
| `BENTO_TELEGRAM_API_ID`, `BENTO_TELEGRAM_API_HASH`, `BENTO_RELAY_URL`, `BENTO_PUBLIC_SITE_URL` | present in build configuration | Packaged: from `resources/build-config.json` only (inherited values stripped). Development: from the parent environment. Values are validated (id digits, 32-hex hash, `wss:`/`https:` relay, `https:` site; loopback `ws:`/`http:` allowed only in development); invalid ones are dropped and logged by key name. |
| `ENVIRONMENT` | packaged builds | `production` (the backend refuses `STORAGE_BACKEND=fake`). Unpackaged runs keep the inherited value. |
| `STORAGE_BACKEND` | unpackaged and `BENTO_DEV_STORAGE_BACKEND=fake` | `fake`. Packaged builds strip an inherited `STORAGE_BACKEND=fake`. |
| existing | always | `BENTO_RUNTIME_MODE=desktop`, `HOST=127.0.0.1`, `DATA_DIR`, `BENTO_DESKTOP_ORIGIN` |
| `BENTO_DESKTOP_API_TOKEN` | API process only | a fresh per-launch token for each API process; inherited values are stripped from every sidecar. The backend moves it (and `BENTO_DEVICE_WRAPPING_KEY`) out of `os.environ` at start, so children never inherit either. |

`API_PORT` and `--port` are no longer passed: the API binds `127.0.0.1:0` and prints `BENTO_API_READY {"port":N}` on stdout once it accepts connections; main reads the port only from that line. `BENTO_SIDECAR_PATH` (development override of the sidecar executable) is ignored by packaged builds and never forwarded.

No Bot API variables (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_*_CHAT_ID`, webhook secret, `BENTO_ENCRYPTION_KEY`) are forwarded any more; stored legacy desktop secrets are deleted on startup (without decrypting or logging them).

## Backend Endpoints Main Calls

All through the authenticated loopback client (`Authorization: Bearer <per-launch token>`, `Origin: bento://app`). 404/5xx/network errors are treated as "unavailable" and retried on the next tick.

| Call | Shape expected |
|---|---|
| `GET /api/activity` | `Activity` from `api/telegram-first-endpoints.md` (`summary`, `uploads`, `downloads`, `attention[{id, kind, action, params}]`; `params.retry_after_seconds` is used for flood waits) |
| `GET /api/backup/policy`, `PATCH /api/backup/policy {paused}` | `{paused, pause_on_battery, bandwidth_limit_kbps, on_battery, effective_paused}` |
| `POST /api/backup/power {on_battery}` | policy |
| `POST /api/assets/upload` | existing multipart contract |
