# Product: Telegram-First Experience

Audience: non-technical people who want "una nube sin límite" using the Telegram account they already have. Every screen must be understandable without knowing what a bot, channel ID, API, key, or environment variable is.

## Principles

- One idea per screen, one primary button, plain Spanish (English via dictionary). Never show env var names, channel IDs, hashes, ports, or stack traces outside **Avanzado**.
- Automatic by default: sensible folders preselected, background work, retries, resume after sleep, no confirmations for reversible actions (use **Deshacer** toasts instead).
- Honest: say what Telegram can see (archivos cifrados, tamaños, horas), that Telegram does not contractually guarantee unlimited space, and that losing every device **and** the recovery kit means losing access.
- Status is always visible but quiet: sidebar footer + tray icon. Notifications only for things the user must act on.

## First run (new user)

1. **Bienvenida** — "Tu nube privada, sin límite de espacio, guardada en tu Telegram." Buttons: `Empezar` (primary), `Ya uso Bento en otro dispositivo`, small link `Usar solo en este equipo` (local mode, Advanced choice).
2. **Conecta tu Telegram** — QR (refreshes automatically every ~25 s) + steps: "Abre Telegram en tu móvil › Ajustes › Dispositivos › Vincular dispositivo de escritorio y escanea." Secondary: `Usar mi número de teléfono` (phone → code → 2FA password if needed). Errors in human words with retry.
3. **Creando tu nube** — progress while channels/folder/keys are created (≤ 10 s). Shows avatar + name: "Conectado como Ana".
4. **Elige qué respaldar** — suggested existing folders (Imágenes, Documentos, Escritorio) as toggles with sizes when cheap to compute; `Añadir carpeta…` (native picker). `Continuar` starts backup in background; `Ahora no` allowed.
5. **Guarda tu kit de recuperación** — explains in one sentence why; shows the code in 9 groups; buttons `Guardar PDF` (desktop) / `Imprimir`, `Copiar`; checkbox-free confirmation by typing the last group. `Más tarde` allowed but the app keeps a gentle attention item until saved.
6. **Listo** — "Todo lo que guardes aquí estará también en tu Telegram, cifrado." Tips: Bandeja de Telegram, arrastrar archivos, atajo de búsqueda.

AI/OCR choices and data location are not part of first run. OCR turns on automatically when the device has ≥ 4 CPU cores and ≥ 8 GB RAM; "Búsqueda inteligente" (embeddings) is an opt-in single toggle in Ajustes that downloads the model in the background.

## Add another device

On the **existing** device: Ajustes › Dispositivos › `Añadir dispositivo` opens a dialog with a large QR, the code `K7Q2-MXR9-T4WA` (copy button), the link, expiry countdown, and "En el otro equipo, abre Bento y elige «Ya uso Bento»". When the guest connects the dialog shows: "¿Añadir «Portátil de Ana · Linux»?" + 4 emojis + `Añadir` / `No soy yo`.

On the **new** device: Bienvenida › `Ya uso Bento en otro dispositivo` → code field (accepts pasted link) with `Escanear QR` hint for phones, and `No tengo el otro dispositivo` (→ sign in to Telegram, then use recovery kit). After joining: the same 4 emojis + "Confirma en tu otro dispositivo", then "Descargando tu biblioteca… 1.240 de 3.000" (snapshot bootstrap) and the library appears progressively.

Fallback without relay: after Telegram sign-in the new device offers `Pedir acceso a mis otros dispositivos`; existing devices show a non-modal banner "Un dispositivo nuevo quiere unirse" → review emojis → approve.

`bento://join?...` links open the app directly on the join screen (desktop deep link).

## Everyday use

- **Sidebar footer**: avatar, `1,2 TB en tu nube`, status line ("Todo al día ✓", "Subiendo 12 archivos · 3 min", "Sin conexión — se reanudará solo", "Telegram pidió esperar 4 min"). Click opens **Actividad**.
- **Actividad** panel: current transfers with progress, queue, paused state, attention items with one action button each (`Reintentar`, `Abrir ajustes`, `Guardar kit`).
- **Tray/menu bar**: same status, `Abrir Bento`, `Pausar/Reanudar`, `Salir`. Closing the window keeps Bento running (first time shows a one-time notification explaining it). Launch at login on by default after onboarding.
- **Drag & drop** anywhere, paste from clipboard, OS "Abrir con Bento", single-instance file hand-off.
- **Bandeja de Telegram**: anything forwarded to "Bento · Bandeja" from any Telegram app appears in Bento within seconds (✅ reaction on the message).
- **Compartir por Telegram**: on any file `Enviar por Telegram…` → searchable recent chats → send. Copy: "Se enviará una copia sin cifrar a ese chat."
- **Importar de Telegram**: Ajustes › Telegram › `Importar de Mensajes guardados u otro chat` → pick chat → grid of media with select all → import in background.
- **Papelera**: deleted items stay 30 days; restore, delete forever, empty. Delete actions elsewhere show `Movido a la papelera · Deshacer`.
- **Vista rápida**: Space opens preview for the focused item; videos stream with seeking; PDFs and text render inline.
- **Espacio en este equipo**: thumbnails always local; originals cached up to `cache_max_gb` (default 10 GB) with LRU eviction; files open on demand.

## Settings information architecture (simplified)

- **General**: idioma, abrir al iniciar sesión, mantener en segundo plano, tema (claro/oscuro/sistema), actualizaciones.
- **Cuenta y nube**: cuenta de Telegram (avatar, cerrar sesión), uso, kit de recuperación (ver/generar nuevo/verificar).
- **Dispositivos**: lista con "este dispositivo", renombrar, quitar, añadir.
- **Respaldo**: carpetas, pausar, pausar con batería, límite de velocidad.
- **Búsqueda inteligente**: OCR y búsqueda semántica (one toggle each, plain explanations).
- **Avanzado**: almacenamiento local/telegram, ubicación de datos, rendimiento, tamaño de partes, relay, exportar diagnóstico, restaurar valores.

## Recovery and trust copy

- Kit PDF: title "Kit de recuperación de Bento", account name, vault creation date, the code, a QR of `bento-recovery:<code>`, instructions "Guárdalo fuera de este equipo. Con tu Telegram y este código puedes recuperar todo.", and a warning that anyone with both can open the vault.
- Privacy page (in-app Ajustes › Acerca de and website): what is encrypted, what Telegram sees, that the relay only passes encrypted pairing messages for a few minutes, that Bento has no servers storing your files, that Bento uses the Telegram API and is not affiliated with Telegram.

## Deferred (specified, not in this program)

- **Mobile app** with camera-roll backup (React Native or Capacitor + TDLib/Telethon bridge), reusing the sync and pairing protocols; scan-to-join from the phone.
- **Files on demand in the OS file manager** (Windows Cloud Files API, macOS File Provider, Linux FUSE).
- **Public links** for non-Telegram recipients (needs a proxy that never sees keys: key in URL fragment, ciphertext served via a short-lived download proxy).
- **Shared family vaults** (multiple Telegram accounts as channel admins, per-member device grants).
