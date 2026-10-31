# Desktop Settings UI Agent

## Mission

Turn Settings into a polished, accessible configuration experience and add the first-run wizard for desktop users.

## First Read

- `/orchestration/README.md`
- `/orchestration/AGENTS.md`
- `/orchestration/product/settings-recovery-security.md`
- `/orchestration/architecture/desktop-runtime-settings.md`
- `/orchestration/architecture/i18n-a11y.md`
- `/orchestration/design-system/brand.md`
- `/orchestration/design-system/primitives.md`
- `/orchestration/design-system/motion-interaction.md`

## Own These Paths

- `/apps/web/src/features/settings/**`
- `/apps/web/src/features/onboarding/**`
- `/apps/web/src/routes/settings*`
- Settings/onboarding API and desktop-bridge client wrappers
- Settings/onboarding i18n keys and frontend tests

## Deliver

- Searchable two-pane categories, health overview, source/locked/restart indicators, typed controls, inline validation, and accessible help.
- Secret presence controls that never fetch stored plaintext.
- Sticky save/discard flow, change/restart summary, apply progress, rollback result, and recovery actions.
- Guided Telegram/model probes, native path selection when available, `.env` import preview, safe export, and restore defaults.
- First-run wizard with local-safe defaults and later editability.
- Clear browser/headless fallback for desktop-only operations.

## Constraints

- Do not duplicate validation or restart rules from the backend schema.
- Do not place secrets in React state longer than the active edit, local/session storage, URLs, analytics, error reports, or test snapshots.
- Do not edit Electron main/preload code.
- Route all user-facing strings through i18n.

## Required Tests

- Keyboard/focus and screen-reader status behavior.
- Dirty state, discard, field/server validation, conflict recovery, save/restart, and rollback rendering.
- Secret configured/change/clear flows without plaintext redisplay.
- Desktop bridge present/absent behavior, native picker, import/export, and first-run completion.
