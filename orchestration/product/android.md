# Bento for Android — Product and UX Contract

Status: binding for Stages 19-22 (`execution/android-program.md`). Runtime: `architecture/android-runtime.md`. Visual language: `design-system/android.md`. Backend additions: `api/android-endpoints.md`. Journeys and gates: `testing/android-journeys.md`.

Bento for Android is a **full device of the vault**, not a remote control for the desktop: it has its own Telegram authorization, its own encrypted SQLite replica, its own device identity, and works with every other device off. It reuses the Telegram-first protocol unchanged (`architecture/telegram-first.md`).

## 1. Experience principles

Every screen, state, and string is reviewed against these. A feature that breaks one does not ship.

1. **Instant.** The app never opens to a spinner. Launch shows the last library state from the on-device cache in under a second; fresh data merges in silently. `BentoLoader` appears only on first run and on screens with nothing cached.
2. **Calm.** Background work is one line of status and a ring on the avatar. No per-file notifications, no toasts for routine success, no modal for something that can wait.
3. **Thumb-first.** Primary actions live in the bottom half (navigation bar, FAB, viewer actions, bottom sheets). Top bars hold search and status only.
4. **Honest.** The user can always tell what is only on this phone, what is in their cloud, and what is still uploading. Plaintext disclosures (Enviar por Telegram, Abrir con otra app, Guardar en el teléfono) are labelled every time.
5. **Reversible.** Every action except "Eliminar para siempre" and "Quitar dispositivo" offers `Deshacer` for 6 s. Irreversible actions explain the consequence in one sentence before the confirm button.
6. **Native.** Edge-to-edge, predictive back, system photo picker, share sheet, per-app language, themed icon, Material motion physics, haptics, TalkBack. It must feel built for Android, dressed in Bento.
7. **Private by construction.** No analytics SDKs, no ads, no third-party crash reporters, no network call that is not Telegram, the pairing relay (only while pairing), or the signed update manifest/APK download.

## 2. Platform scope

- `minSdk 29` (Android 10), `targetSdk 36`, `compileSdk` latest stable.
- ABIs: `arm64-v8a` (release), `x86_64` (emulators, Chromebooks). No 32-bit builds.
- Form factors: phones (portrait first, landscape supported), foldables, tablets, ChromeOS. Window size classes drive layout (§4.6).
- Locales: Spanish default (`values/`), English (`values-en/`). Per-app language through the system setting (Android 13+) and an in-app picker on older versions.
- Distribution (v1): **signed APK** (arm64-v8a; plus a universal APK) attached to GitHub releases and linked from the site. The app checks updates through the existing Ed25519-signed manifest, shows "Hay una versión nueva" in Ajustes › Acerca de and as a calm card, downloads the APK, verifies its SHA-256 against the signed manifest and the signing certificate against the installed one, then hands it to the system installer (`PackageInstaller` session, `REQUEST_INSTALL_PACKAGES`); never silent. Google Play is a later channel (same package name and signing key so users can move over).

## 3. Information architecture

```txt
┌ Top bar ───────────────────────────────────────┐
│ [ 🔍 Buscar en Bento               ]   (◐ Ana) │  search pill + account/status avatar
├────────────────────────────────────────────────┤
│                                                │
│                 destination content            │
│                                     [ + Nuevo ]│  FAB only in Archivos
├────────────────────────────────────────────────┤
│   ▣ Fotos        ▢ Archivos      ▢ Colecciones │  navigation bar (3 destinations)
└────────────────────────────────────────────────┘
```

- **Fotos** — the photo and video timeline of the whole library.
- **Archivos** — Drive: folders and files, with `+ Nuevo`.
- **Colecciones** — Álbumes, Favoritos, Documentos, Videos, Del teléfono (this phone's backup folders), Importado de Telegram, Papelera.
- **Buscar** — the search pill on every destination opens the full-screen search (shared-axis transition); it is not a tab.
- **Avatar** (top right) — opens the **Cuenta y actividad** sheet (§7). Its ring is the global status indicator.
- **Ajustes** — from the sheet, never a tab.
- Reselecting the current tab scrolls to top; reselecting again at top opens search.
- Back: predictive back everywhere; from a non-start tab, back goes to Fotos, then exits. Never "press back again to exit".

## 4. Surfaces

### 4.1 First run

Branded system splash (`SplashScreen` API) with the animated `BrandMark` (compartments fill, ume last), held only while the engine opens the database (target ≤ 400 ms; never longer than 1 s — after that the welcome screen renders and engine readiness is awaited where needed).

1. **Bienvenida.** Logo, "Tu nube privada, en orden.", three lines with icons: "Sin límite de espacio, en tu propio Telegram", "Cifrado en tu teléfono antes de salir", "Tus fotos y archivos en todos tus dispositivos". Primary `Empezar`. Secondary `Ya uso Bento en otro dispositivo`. Text button `Usar solo en este teléfono` (local mode; explains "no se sincroniza ni se respalda" in a confirmation sheet).
2. **Conecta tu Telegram** (new vault, or join without another device).
   - If the Telegram app is installed: primary `Continuar con Telegram` opens the login confirmation in the Telegram app through the login-token deep link (`tg://login?token=…`, verified in the spike, `architecture/android-runtime.md` §12); Bento returns to the foreground on success. Body: "Telegram te pedirá confirmar el inicio de sesión de Bento."
   - Always available: `Usar mi número de teléfono` → country picker preselected from SIM/locale, number formatted as typed (E.164) → code screen ("Te enviamos un código a tu app de Telegram", `Abrir Telegram` button, a paste chip appears when the clipboard holds a 5-6 digit code, auto-submit on the last digit, resend countdown) → 2FA password if required (hint shown, show/hide toggle, `Olvidé mi contraseña` opens Telegram's help).
   - `Mostrar código QR` (secondary) shows the QR for signing in from another phone.
   - Errors are mapped to plain copy: wrong code, expired code, flood wait ("Telegram pidió esperar 3 min. Lo intentaremos solo."), no network.
3. **Creando tu nube.** Avatar + "Conectado como Ana". `BentoLoader` with three labelled compartments that fill as channels, folder, and keys are created. ≤ 10 s; if longer, "Telegram va lento, sigue en marcha…".
4. **Respalda este teléfono.** Illustration of the camera roll filling a compartment. "Tus fotos y videos se cifran y se guardan en tu nube. Puedes elegir qué carpetas." Options, preselected: `Solo con Wi-Fi` on, `Incluir videos` on, `Solo mientras carga` off. Primary `Respaldar fotos`:
   - shows a one-line rationale, then the system media permission (§6). Partial access ("Seleccionar fotos") is respected and explained, never nagged.
   - then the notification permission (Android 13+) with "Solo te avisaremos del progreso del respaldo y si algo necesita tu atención."
   - `Ahora no` keeps a dismissible card at the top of Fotos for 7 days.
5. **Guarda tu kit de recuperación.** One sentence of why. The code in 9 groups of 4 (Geist Mono, large, `FLAG_SECURE`). `Guardar PDF` (Storage Access Framework create-document, same layout as the desktop kit), `Imprimir` (system print), `Copiar` (clipboard marked sensitive, cleared after 60 s, warning chip). Confirmation by typing the last group. `Más tarde` allowed; an attention item stays until saved (vault-wide `recovery.confirmed_at`).
6. **Listo.** "Todo lo que guardes aquí estará también en tu Telegram, cifrado." Three tips as swipeable cards: "Comparte a Bento desde cualquier app", "Reenvía cosas a «Bento · Bandeja» en Telegram", "Busca por texto dentro de tus fotos". Primary `Ir a mis fotos`.

### 4.2 Join an existing vault (phone as guest)

The best path is three taps and zero typing.

- **From the desktop QR:** the desktop shows `Añadir dispositivo` with a QR. The person scans it with the phone's camera app or Google Lens. The QR encodes the App Link `https://<site>/join#v=1&c=…` (`architecture/android-runtime.md` §9): with Bento installed it opens Bento straight on the join screen with the code filled in; without Bento the site shows "Instala Bento" with the APK download and short sideload steps, and after install the person scans again.
- **Inside Bento:** `Ya uso Bento en otro dispositivo` opens a full-bleed scanner (CameraX, in-app, branded frame, haptic tick on detection) with `Escribir el código` below. The code field accepts the 12 characters with automatic dashes, a pasted link, or a clipboard suggestion chip. Camera permission is requested only when this screen opens, with a rationale; if denied, the screen falls back to the code field with no dead end.
- **Then:** "Confirma en tu computador" with the four SAS emojis at 48 sp and their names for TalkBack. If the phone is not signed in to Telegram, the login token is forwarded through the relay and the host accepts it: the phone ends signed in without a phone number (`architecture/telegram-first.md` § Relay flow). If the host's acceptance fails, the phone falls back to §4.1 step 2 inline and continues.
- **Bootstrap:** "Descargando tu biblioteca… 1.240 de 3.000" for at most 2 s, then the person lands in Fotos while the library fills progressively (thumbnails fade in as they arrive; the avatar ring shows progress). The backup step (§4.1 step 4) is offered as a sheet once the grid is visible, not as a blocking screen.
- **Without the other device:** `No tengo el otro dispositivo` → Telegram sign-in → recovery code entry (9 groups with auto-advance, paste, or scan the kit's QR `bento-recovery:`) → bootstrap.
- **Fallback without relay:** `Pedir acceso a mis otros dispositivos` (Sync-channel flow); the phone shows its emojis, the vault creation date, and device count, and requires `Coinciden` before anything is installed.

### 4.3 Fotos

- **Grid:** uniform square tiles, 3 columns on compact width (4-7 on wider windows), 2 dp gutters. Pinch to change density (2 ↔ 3 ↔ 5 columns ↔ month view with 8-column micro tiles), anchored on the pinch focal item, with a haptic tick per step.
- **Headers:** sticky month header (`Marzo de 2024`, `text-xl` equivalent) and day sub-headers (`Mar, 12 de mar.` in `ink-muted`); day headers carry a select-all circle in selection mode.
- **Fast scroller:** appears on scroll, a thumb on the right edge with a date bubble ("mar. 2024") and year ticks; dragging is O(1) (jump by index, never by layout), with haptic ticks at year boundaries.
- **Tiles:** thumbnail sized to the cell (`size` hint, §api), `sunken` placeholder and 120 ms fade-in. Overlays (bottom-left, small, with shadow for legibility): video duration `0:42`; favorite heart (shu, brand rule as on web); `CloudUpload` glyph for items on this phone that are not uploaded yet; `CloudOff` for items whose upload failed for good (tap opens Activity). No glyph means "safe in your cloud".
- **Selection:** long-press selects and enters selection mode; dragging after the long-press range-selects across rows with auto-scroll near edges (the core Google-Photos-class gesture, must be flawless at 120 Hz). The top bar becomes the selection bar ("12 seleccionados", close, select all); a floating action bar slides up: `Compartir`, `Añadir a álbum`, `Favorito`, `Eliminar`, overflow (`Mover a carpeta`, `Guardar en el teléfono`, `Enviar por Telegram…`).
- **Cards (top of grid, max one at a time):** backup off (§4.1 step 4), partial media access, kit pending, phone storage low, sign-in needed. Each has one action and a dismiss.
- **Empty:** new vault with backup off → illustration + `Respaldar fotos del teléfono` + `Subir fotos` (photo picker).

### 4.4 Visor (photo/video viewer)

- Always the dark `media` scheme, edge-to-edge, system bars hidden on tap.
- Opens with a shared-element transform from the tile (the tile's thumbnail is the first frame, so the open is instant even for remote originals). Progressive quality: tile thumbnail → large preview → original (for images ≤ 40 MP), crossfaded without flicker.
- Gestures: horizontal paging across the current collection; pinch and double-tap zoom with subsampled tiles for large images; one-finger zoom (double-tap-hold-drag); swipe down (or predictive back) shrinks the photo back into its tile; swipe up opens the info sheet.
- **Info sheet:** date and time, filename (editable), size and dimensions, camera/lens/exposure from EXIF, location as place text or coordinates with `Abrir en Mapas` (system intent, no embedded map service), folder path (tap navigates), albums, and the storage line: "En tu nube · cifrado", "En este teléfono · se subirá con Wi-Fi", or "Subiendo… 64 %". Device that added it ("Añadido desde Portátil de Ana").
- **Bottom actions:** `Compartir` (system share of a decrypted temporary copy; the first time a sheet explains "Se compartirá una copia sin cifrar"), `Favorito`, `Añadir a álbum`, `Eliminar` (to trash with undo). Overflow: `Enviar por Telegram…`, `Guardar en el teléfono` (MediaStore `Pictures/Bento`), `Mover a carpeta`, `Renombrar`, `Abrir con…`, `Usar como…` (wallpaper/contact via system intent), `Detalles`.
- **Video:** Media3 ExoPlayer streaming through Range requests (remote encrypted parts decrypted by range), scrubbing thumbnails when available, play/pause on tap, mute toggle, picture-in-picture when leaving the app during playback, playback speed in overflow. Starts within 1 s on Wi-Fi for cached or remote video.
- **Offline, not cached:** the preview shows with "Necesitas conexión para ver el original" and `Disponible sin conexión` as a hint for next time.

### 4.5 Archivos

- **List** by default on phones (icon in `kind-*` colors, name, `ink-muted` line with size · date or item count), **grid** toggle in the top bar overflow. Folders first. Sort sheet: Nombre, Fecha de modificación, Tamaño, Tipo; ascending/descending; remembered per folder.
- **Breadcrumbs:** collapsible chip row under the top bar (`Archivos › Trabajo › 2024`); tapping a chip navigates; long-press the back affordance shows the path as a menu.
- **`+ Nuevo`** (extended FAB that shrinks to an icon on scroll) opens a sheet: `Subir archivos` (SAF multi-select), `Subir fotos o videos` (system photo picker, no permission), `Subir una carpeta` (SAF tree; recreates structure), `Escanear documento` (on-device document scanner when available → multipage PDF into the current folder, named `Escaneo 2026-11-24 10.41.pdf`), `Nueva carpeta` (inline name field, keyboard opens, `Crear`).
- **Open:** images and videos → Visor; PDFs → in-app reader (page thumbnails rail, pinch zoom, page counter, text search when OCR/PDF text exists); text/markdown/code ≤ 2 MiB → in-app text view with monospace option; audio → mini player; everything else → `Abrir con…` after a decrypting download with progress and a one-line plaintext notice.
- **Item menu** (overflow button and long-press): `Compartir`, `Descargar al teléfono` (SAF create document or `Downloads/Bento`), `Disponible sin conexión` (pin, §api cache pins), `Mover`, `Renombrar`, `Favorito`, `Enviar por Telegram…`, `Detalles`, `Eliminar`.
- **Selection:** long-press then tap to add; floating action bar with `Compartir`, `Mover`, `Descargar`, `Eliminar`, overflow.
- **Move sheet:** folder browser in a bottom sheet with search, `Nueva carpeta` inline, and recent destinations at top; `Mover aquí` as primary.
- **Uploads:** a floating progress card above the navigation bar ("Subiendo 3 archivos · 12 MB de 40 MB", expands to per-file rows, `Pausar`), then it collapses into the avatar ring. Uploads continue when the app is closed (`architecture/android-runtime.md` §6).

### 4.6 Large screens

- ≥ 600 dp: navigation rail replaces the bar; Fotos grid 5-7 columns; viewer info sheet becomes a side pane.
- ≥ 840 dp: Archivos is list-detail (folder tree pane + content); Search shows filters as a side pane; Ajustes is list-detail.
- Keyboard and mouse (tablets with keyboards, ChromeOS): arrow-key focus in grids, `Enter` opens, `Space` quick look, `Ctrl+F` search, `Delete` to trash, `Ctrl+A`, right-click context menus, hover states, drag and drop files in and out (with `DragAndDropPermissions`).
- Foldables: tabletop posture plays video in the upper half with controls in the lower half.

### 4.7 Buscar

- Full screen, field focused, keyboard open. Before typing: recent searches (local only, swipe to remove, `Borrar historial`), and suggestion chips — types (Fotos, Videos, PDF, Documentos, Hojas de cálculo), time ("Este mes", "El año pasado", detected years), recent folders, albums.
- As you type: results update with 150 ms debounce, grouped (Fotos as a horizontal strip, Archivos and Documentos as rows). Each row shows the match reason with `Sparkles` ("Texto en la imagen: «factura de luz»", "Nombre", "Carpeta Trabajo") and highlights the matched fragment.
- Filters row (chips with sheets): Tipo, Fecha (range picker), Carpeta, Origen (Este teléfono, Otros dispositivos, Telegram).
- Search by meaning is shown only when the phone has the capability (v1: not on Android, `architecture/android-runtime.md` §7); the empty-result state never mentions it.
- No results: "No encontramos «factura»" + suggestion to remove filters + `Buscar en todas las carpetas` when scoped.

### 4.8 Colecciones

- **Álbumes:** 2-column grid of 4:3 covers with title and count; `Nuevo álbum` opens the photo picker over the library (multi-select grid of Bento photos) then a title field. Album detail = photo grid + `Añadir fotos`, `Renombrar`, `Cambiar portada`, `Eliminar álbum` (photos stay).
- **Favoritos, Videos, Documentos:** filtered grids/lists with the same behaviors as Fotos/Archivos.
- **Del teléfono:** one row per backed-up phone folder (Cámara, Capturas, WhatsApp Images…) with count and status.
- **Importado de Telegram:** imported items; `Importar de Telegram` opens the chat picker (Mensajes guardados first, then recent chats with avatars) → media grid with select all → import in background.
- **Papelera:** items with "Se eliminará en 12 días", `Restaurar`, `Eliminar para siempre`, `Vaciar papelera` (confirmation with count and size).

### 4.9 Share to Bento (share target)

- Bento appears in the share sheet for any MIME type, single or multiple (`ACTION_SEND`, `ACTION_SEND_MULTIPLE`), plus Direct Share targets for the 4 most recent destination folders.
- A translucent bottom sheet over the sending app (not a full app launch): thumbnails strip, "3 archivos · 18 MB", destination row (last used folder, tap to pick), optional `Añadir a álbum` for media, primary `Guardar en Bento`.
- On tap the sheet closes within 200 ms; content is copied from the content URIs into Bento's local store under a user-initiated job, then encrypted and uploaded in background. A single silent progress notification appears only if the copy takes over 3 s. Revoked or unreadable URIs are reported in Activity with the filename, never silently dropped.
- Text and URLs shared alone are saved as a `.txt` note named from the first line.

### 4.10 Bandeja de Telegram

Unchanged protocol. The phone imports Inbox items while it is the active device (foreground) and in periodic background runs; desktop devices usually import first. Copy in Ajustes › Telegram explains: "Reenvía cualquier cosa a «Bento · Bandeja» desde Telegram y aparecerá en Bento."

## 5. Phone backup (camera roll)

- **Sources:** MediaStore buckets with counts and thumbnails, `Cámara` and `Capturas de pantalla` on by default, others suggested (WhatsApp Images, Telegram, Descargas). Each enabled bucket maps to Drive folder `Del teléfono/<device name>/<bucket name>` and to the Fotos timeline.
- **Detection:** content-URI triggers for new media plus a periodic reconcile (12 h) and on app open. New photos appear in Fotos within 2 s when the app is open (local-first ingestion) and upload by policy.
- **Dedup:** a photo already in the vault (same sha256, from any device) is linked, not uploaded twice. Edited photos (new generation) upload as a new version only if the bytes changed.
- **Policy:** `Solo con Wi-Fi` (default on; unmetered networks), `Videos solo con Wi-Fi` (always on unless explicitly enabled), `Solo mientras carga` (default off), `Pausar con batería baja` (always, by the system and by Bento below 15 %), `Ahorro de datos` respected. Users can `Respaldar ahora` to lift the Wi-Fi rule once.
- **Initial backup** of an existing roll (e.g. 18,000 items) runs as a user-initiated data transfer with a persistent progress notification ("Respaldando 1.240 de 18.000 · Pausar"), resumes after reboots, and estimates time once it has 2 min of throughput.
- **Location:** with `ACCESS_MEDIA_LOCATION` granted, original EXIF GPS is preserved; if denied, the person is told once: "Tus fotos se guardarán sin ubicación." (Android redacts it otherwise.)
- **Liberar espacio:** Ajustes › Respaldo › `Liberar 3,2 GB en este teléfono` lists phone originals that are fully uploaded and verified (blob confirmed, sha256 matched), shows a summary, and deletes them through the system delete request (the system shows its own confirmation; items go to the system trash where available). Never automatic. Bento keeps thumbnails so the timeline is unchanged.
- **Status:** Ajustes › Respaldo header: "Todo respaldado ✓ · hace 3 min" / "Quedan 340 · esperando Wi-Fi" / "Pausado · batería baja".

## 6. Permissions

Ask in context, explain first in one sentence, never at launch, never twice in a session, and every denial has a working path.

| Permission | When | If denied |
|---|---|---|
| `READ_MEDIA_IMAGES` / `READ_MEDIA_VIDEO` (13+), `READ_EXTERNAL_STORAGE` (≤ 12) | Turning on phone backup | Backup stays off; uploading via the photo picker still works. |
| `READ_MEDIA_VISUAL_USER_SELECTED` (14+) | System offers partial access | Backs up only selected items; a calm card explains "Bento solo ve 12 fotos" with `Permitir todas` and `Elegir más`. |
| `ACCESS_MEDIA_LOCATION` | After media permission | Photos saved without location (told once). |
| `POST_NOTIFICATIONS` (13+) | After turning backup on, or before the first long transfer | Progress visible in-app only; transfers still run. |
| `CAMERA` | Opening the in-app QR scanner | Code field remains. |
| Biometric (no permission) | Turning on app lock | — |

Not requested: `MANAGE_EXTERNAL_STORAGE`, contacts, location, microphone, `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`, `SYSTEM_ALERT_WINDOW`, `QUERY_ALL_PACKAGES`.

## 7. Cuenta y actividad (status)

- **Avatar ring:** none = all synced; animated accent arc = syncing/uploading (determinate when known); warning dot = attention item; dimmed avatar + `CloudOff` = offline; pause glyph = backup paused. TalkBack reads the status line.
- **Sheet (modal bottom sheet, half → full):** avatar, account name, "1,2 TB en tu nube · 3 dispositivos", status line ("Todo al día ✓", "Subiendo 12 archivos · 3 min", "Sin conexión — se reanudará solo", "Telegram pidió esperar 4 min"), current transfers with progress (expandable), attention items each with one action (`Reintentar`, `Guardar kit`, `Revisar`, `Volver a conectar`), then `Pausar respaldo` / `Reanudar`, `Dispositivos`, `Papelera`, `Ajustes`.
- **Quick Settings tile** "Respaldo de Bento": tap to pause/resume, long-press opens Ajustes › Respaldo. Subtitle shows the status line.
- **App shortcuts** (long-press icon): `Buscar`, `Subir fotos`, `Escanear documento`, `Añadir dispositivo`.

## 8. Notifications

Channels (user-controllable, named and described in Spanish):

| Channel | Importance | Content |
|---|---|---|
| `Respaldo y transferencias` | Low, silent | One ongoing progress notification for long transfers (required by the system), with `Pausar`. Never one per file. Removed on completion; a completion summary only after an initial backup ("Listo: 18.000 fotos respaldadas"). |
| `Necesita tu atención` | Default | Sign in to Telegram again, kit pending after 3 days, device removed, storage full on the phone, a file that failed for good. Coalesced; at most one per day per kind. |
| `Dispositivos` | High | "Un dispositivo nuevo quiere unirse" (fallback pairing), "Se añadió «Portátil de Ana»" (new device review). Tap opens the review screen. |

No marketing notifications, ever.

## 9. Ajustes

Top: account card (avatar, name, usage). Then sections:

- **General:** Tema (Automático, Claro, Oscuro), Idioma (system per-app setting), Bloqueo de la app (huella/rostro o PIN del teléfono; after Inmediatamente / 1 min / 5 min / 15 min), Ocultar contenido en apps recientes (on with lock).
- **Respaldo del teléfono:** on/off, carpetas del teléfono, Solo con Wi-Fi, Videos solo con Wi-Fi, Solo mientras carga, Liberar espacio, status header.
- **Espacio en este teléfono:** usage bar (miniaturas, originales en caché, disponibles sin conexión), Límite de caché (1 / 2 / 5 / 10 GB, default 2 GB, auto-shrinks when the phone has < 10 % free), `Vaciar caché`, list of offline items.
- **Cuenta y nube:** Telegram account (`Cerrar sesión en este teléfono` with consequence copy), kit de recuperación (ver/generar nuevo/verificar).
- **Dispositivos:** list with "Este teléfono", platform icon, last seen; rename; `Añadir dispositivo` (phone as host: large QR + code + countdown + `Compartir enlace`); `Quitar` with removal preview and the mandatory new kit; pending new-device reviews at top.
- **Búsqueda:** `Texto en fotos y documentos` (on-device OCR; default: on, runs only while charging and idle) with plain explanation.
- **Telegram:** Bandeja, `Importar de Telegram`, `Enviar por Telegram` explanation.
- **Avanzado:** Exportar diagnóstico (redacted, SAF), servidor de emparejamiento (relay URL, default), modo de almacenamiento (read-only label), `Restablecer Bento en este teléfono` (wipes local data and keys after typing "RESTABLECER"; vault untouched).
- **Acerca de:** version, privacy summary (what is encrypted, what Telegram sees, the relay), "Bento usa la API de Telegram y no está afiliado a Telegram", open-source licenses, terms.

## 10. Security UX

- `FLAG_SECURE` on recovery kit, recovery code entry, pairing code/QR, and the 2FA password screen.
- App lock gates the UI only (background sync keeps working; keys are not bound to biometrics, `architecture/android-runtime.md` §5). Locked state hides recents preview (`setRecentsScreenshotEnabled(false)`).
- Clipboard writes of codes use the sensitive flag (13+) and are cleared after 60 s.
- Plaintext disclosure notices (§1.4) are shown the first time per action type and summarized in a "No volver a mostrar" sheet; Enviar por Telegram always shows its line.
- Signing out of Telegram or `Restablecer` explains what stays (the vault, other devices) and what goes (this phone's copy and keys).

## 11. States and edge cases (must all be designed, not defaulted)

Offline (browse cache, queue actions, banner only when an action needs network); Telegram flood wait; Telegram session revoked from another app ("Bento se desconectó de Telegram" → reconnect screen that keeps the library visible); device removed (read-only library, `Volver a unirme`); clock skew; vault header unreadable; partial media access; media permission revoked later; phone storage full (stop caching, pause ingestion, card with `Liberar espacio`); app updated mid-transfer (resumes); process killed mid-upload (resumes at part granularity); 20,000-item roll first sync; 100,000-asset library on a 4 GB RAM phone; huge files (4 GB video); unsupported formats (generic file tile, `Abrir con…`); HEIC/AVIF/RAW (DNG) thumbnails; Motion Photos (still shown, video part preserved); battery saver; Doze; OEM background killers (if backup stalls > 24 h with pending items and the app is not opened, the next open shows a card linking to a vendor-specific help page).

## 12. Accessibility

- Every interactive element has a TalkBack label; grid tiles read "Foto, 12 de marzo de 2024, favorita, pendiente de respaldo"; custom accessibility actions on tiles and rows (Abrir, Seleccionar, Favorito, Compartir, Eliminar) so no gesture is required.
- Touch targets ≥ 48 dp; visible focus for keyboard/switch access; logical traversal order; headings marked.
- Text scales to 200 % (nonlinear scaling on 14+) without truncating primary actions; layouts reflow, never clip.
- Contrast per `design-system/brand.md` §13 in both themes; color never the only signal.
- Reduced motion (`Settings.Global.ANIMATOR_DURATION_SCALE == 0` or the system "remove animations") replaces transforms with fades.
- Captions/subtitles honored by the video player when tracks exist.

## 13. Performance budgets (reference device: Pixel 7a and Galaxy A35; floor device: 4 GB RAM, Android 10)

| Metric | Budget |
|---|---|
| Cold start → first frame | ≤ 500 ms p50 (Baseline Profile) |
| Cold start → cached Fotos grid with thumbnails | ≤ 900 ms p50, ≤ 1.5 s p90 |
| Engine ready (API answering) | ≤ 2.5 s p50, ≤ 4 s p90 on the floor device (spike: 2.9 s p50 on emulator before import-time cuts) |
| Fotos scroll (10,000 items, fling + fast scroller) | ≤ 1 % janky frames (JankStats), no blank tiles after fling settles > 150 ms |
| Tile thumbnail (local) | ≤ 50 ms from bind to pixels |
| Viewer open | first frame ≤ 100 ms (shared thumbnail), original ≤ 1 s on Wi-Fi |
| Share sheet → dismissed | ≤ 200 ms |
| Memory (Fotos, 100k library) | ≤ 350 MB PSS; no OOM on the floor device |
| Background idle battery | ≤ 1 % per day with backup on and no new media |
| APK download size (arm64) | ≤ 60 MB |

Budgets are enforced by Macrobenchmark in CI on an emulator and verified on the physical matrix before release (`testing/android-journeys.md`).

## 13a. Copy rules

Same voice as `design-system/brand.md` §2. Mobile-specific: "teléfono" (not "dispositivo" when it is this phone), "computador" for desktops in pairing copy, "tu nube" for the vault, verbs on buttons, no "OK". All strings live in the Android string resources (`core/strings`), Spanish first, with plurals (`<plurals>`) and number/date formatting through ICU (`android.icu`).

## 14. Out of scope for v1 (specified so nobody builds them by accident)

Search by meaning on the phone (embeddings), widgets beyond the Quick Settings tile, Wear OS, Android Auto, editing photos, face grouping, shared family vaults, public links, files-on-demand provider (`DocumentsProvider` exposing Bento in the system Files app — v2 candidate), iOS.
