# Web Core Flows Agent (Stage 16)

## Mission

Build the screens that make Bento understandable to anyone: first run with Telegram sign-in, joining from another device, recovery kit, devices and pairing, account, and a simplified Settings. Everything must feel calm, obvious, and beautiful in the Bento brand.

## First Read

- `AGENTS.md`, `orchestration/execution/telegram-first-program.md`
- `orchestration/design-system/brand.md` (binding: tokens only, primitives, one shu per screen, voice)
- `orchestration/product/telegram-first-experience.md` (binding flows and copy)
- `orchestration/api/telegram-first-endpoints.md`
- `orchestration/architecture/desktop-bridge-telegram-first.md` (deep links, PDF saving, preferences, platform metadata)
- Existing web code: `src/app/**`, `src/components/**`, `src/features/{onboarding,settings}/**`, `src/routes/**`, `src/i18n/**`, `src/api/**` (typed clients for every new endpoint already exist: `account`, `vault`, `sync`, `devices`, `pairing`, `backup`, `activity`, `trash`, `telegram`, `qr`), `src/lib/usePolledResource.ts`, `src/i18n/locale.ts`

## Own These Paths

- `src/features/{onboarding,account,devices,pairing,recovery,settings}/**`
- `src/components/QrCode.tsx` (renders the API's QR matrix as an accessible SVG of rects with a quiet zone; label prop)
- `src/i18n/es/onboarding.ts`, `src/i18n/en/onboarding.ts` (all your strings, both languages)
- `src/app/App.tsx` (first-run gating, deep-link routing, pairing approval dialog mount), `src/routes/{settings,join}.tsx` and their `routeConfig.ts` lines
- Tests for all of the above under `src/test/**` or co-located

## Deliver

1. **First run** replacing the old wizard: Bienvenida → Conecta tu Telegram (QR auto-refresh, phone/code/2FA alternative, human errors incl. flood wait countdown) → Creando tu nube (create vault; show account name/avatar) → Elige qué respaldar (suggestions as toggles + "Añadir carpeta…" via desktop picker or typed path in browser) → Kit de recuperación (code in 9 groups, copy, `Guardar PDF` via `savePageAsPdf` on desktop / `window.print()` in browser with a print stylesheet, confirm by typing the last group, "Más tarde") → Listo. "Usar solo en este equipo" sets local mode through the settings API. Gate: show first run when the vault state is `signed_out`/`no_vault` and the user has not chosen local mode; `locked` shows the join/recovery choice.
2. **Join (new device)**: code field accepting codes and links (auto-format as `XXXX-XXXX-XXXX`), state-driven progress from `GET /pairing/{id}` polling (1 s), SAS emojis, `needs_telegram_login` showing the Telegram QR, bootstrapping progress from `/sync/status`, errors with clear next steps, "No tengo el otro dispositivo" → Telegram sign-in + recovery code entry, and fallback "Pedir acceso a mis otros dispositivos". Desktop deep links (`bento.onDeepLink`) open this screen pre-filled; browser route `/join?c=…` does the same.
3. **Add device (host)** dialog from Settings › Dispositivos: big QR, code with copy, link, countdown, waiting state, then "¿Añadir «…»?" with emojis and `Añadir`/`No soy yo`; relay-unavailable state explains the fallback. Incoming fallback requests (`/pairing/requests`, polled every 5 s while the app is visible) show a non-modal banner → review → approve.
4. **Devices** list (this device badge, platform icon, last seen), rename inline, remove with consequences explained and the mandatory new recovery kit step.
5. **Recovery** section: status (saved/not saved), generate new code (explain old stops working), verify a code, kit view/print.
6. **Account** section: avatar (`/api/account/avatar`), name, username, premium badge, usage, sign out (explain local library stays, sync stops).
7. **Settings IA** per the product doc: General (language via `setLocale`, open at login / keep running / auto-download updates via desktop preferences, theme via the existing ThemeSwitcher), Cuenta y nube, Dispositivos, Respaldo (sources from `api/backup`, add/remove/enable, pause, pause on battery, speed limit with friendly presets), Búsqueda inteligente (OCR and semantic search as two plain toggles mapped to the existing settings registry), Avanzado (the existing editable settings form). Hide env var names outside Avanzado.
8. All strings in your i18n files (Spanish and English). Keyboard navigation, focus management in dialogs, screen-reader labels and live regions for state changes, reduced motion.

## Required Tests

Component and journey tests with mocked API clients (no real backend): first run happy path and phone/2FA path, local-only choice, recovery kit confirmation, join with code (host approves), wrong code, needs Telegram login, fallback request, host dialog states, device removal flow with new kit, settings sections rendering and saving, deep-link prefill, QR component accessibility, i18n completeness (every key you add exists in `es` and `en`). Keep the whole web suite green (`npm --prefix apps/web test`) and TypeScript clean.

## Constraints

- Brand rules are binding (no Tailwind palette classes, tokens only, primitives only, lucide icons only).
- Do not edit `src/api/**` (report gaps), `src/features/{activity,trash,share,import,quicklook}/**`, `src/components/{Sidebar,AppShell}.tsx` (owned by the everyday agent), or anything outside `apps/web`.

## Handoff

Commit on your branch. Report screens, routes, strings added, tests, and any API gaps found.
