# Web Everyday Experience Agent (Stage 16)

## Mission

Make daily use delightful: always-visible quiet status, an Activity panel, trash, sharing to Telegram, importing from Telegram, quick look with streaming video, and an English translation of the whole app.

## First Read

- `AGENTS.md`, `orchestration/execution/telegram-first-program.md`
- `orchestration/design-system/brand.md` (binding)
- `orchestration/product/telegram-first-experience.md` § Everyday use (binding)
- `orchestration/api/telegram-first-endpoints.md` § Backup, activity, power; § Trash and cache; § Content streaming; § Telegram sharing and import
- `orchestration/architecture/desktop-bridge-telegram-first.md` (`onNavigate`)
- Existing web code: `src/app/{App,status}.tsx`, `src/components/{AppShell,Sidebar,StatusIndicator}.tsx`, `src/features/{drive,photos,documents,search,jobs}/**`, `src/api/**` (typed clients already exist), `src/lib/usePolledResource.ts`, `src/i18n/**`

## Own These Paths

- `src/features/{activity,trash,share,import,quicklook}/**`
- `src/app/status.tsx`, `src/components/{AppShell,Sidebar,StatusIndicator}.tsx` (sidebar footer: avatar, usage, status line; top-bar status pill driven by `/activity`)
- Integration points in `src/features/{drive,photos,documents}/**`: item menu entries ("Enviar por Telegram…", "Vista rápida"), Space key handling, "Importar de Telegram…" in add/upload menus, delete toasts with **Deshacer** (restore from trash) replacing confirmation dialogs for reversible deletes
- `src/routes/{trash,activity}.tsx` and their `routeConfig.ts` lines (Trash in the Sistema group with a lucide icon)
- `src/i18n/es/everyday.ts`, `src/i18n/en/everyday.ts`, and **`src/i18n/en/base.ts` (translate every existing base key to natural English)**
- Tests for the above

## Deliver

1. **Status**: sidebar footer with avatar, `X en tu nube`, and a one-line status from `/activity` (poll 3 s while transfers are active, 15 s idle, paused when hidden): "Todo al día", "Subiendo N archivos · M min", "Sin conexión — se reanudará solo", "Telegram pidió esperar N min", "Pausado"; click opens Activity. Top-bar pill follows the same summary (replace the jobs-only indicator; keep a link to Jobs inside Activity for advanced users).
2. **Activity** page/panel: upload/download progress bars with ETA, queue counts, pause/resume backup, attention items each with exactly one action (retry → jobs retry API, open settings, save recovery kit → settings recovery section), and a link to the advanced Jobs page.
3. **Trash** page: virtualized list with thumbnails, deleted/purge dates ("se borrará el …"), multi-select restore, delete forever (consequence explained), empty trash; empty state.
4. **Share via Telegram** dialog: searchable recent chats (`/telegram/chats`), kind icons, send with optional caption, explicit copy "Se enviará una copia sin cifrar a ese chat.", success toast.
5. **Import from Telegram** dialog: choose chat (Saved Messages first), media grid with kind filter and select all, pagination, import → toast + Activity progress.
6. **Quick look**: Space or menu opens an overlay for the focused item; images (preview URL), videos streamed from `/api/assets/{id}/content` with native controls and seeking, PDFs/text via existing inline previews, arrows to move between items, Esc to close, focus trap, reduced motion.
7. **Undo deletes**: deletes move to trash immediately with a toast "Movido a la papelera · Deshacer".
8. **English**: complete `en/base.ts` for all existing keys and your own keys; the app renders fully in English when `bento.locale=en`.

## Required Tests

Status footer/pill mapping for every summary state; Activity actions; trash flows; share dialog (search, send, error); import dialog (selection, pagination, submit); quick look keyboard behavior and video source; undo toast restores; English completeness test asserting every `es` key has an `en` translation. Whole web suite green and TypeScript clean.

## Constraints

- Brand rules are binding. Thumbnails/previews only in grids; originals only via `/content` in quick look.
- Do not edit `src/api/**` (report gaps), `src/features/{onboarding,account,devices,pairing,recovery,settings}/**`, `src/app/App.tsx` (owned by the core-flows agent; ask for mount points in your handoff), or anything outside `apps/web`.

## Handoff

Commit on your branch. Report components, integration points, strings, tests, and any mount points the orchestrator must wire in `App.tsx`.
