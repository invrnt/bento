# Jobs Settings UI Agent

## Mission

Implement Jobs, Settings, global status indicator, and final shared frontend API additions for Stage 9.

## First Read

- `/orchestration/README.md`
- `/orchestration/AGENTS.md`
- `/orchestration/product/jobs.md`
- `/orchestration/product/settings-recovery-security.md`
- `/orchestration/api/jobs-events-contract.md`
- `/orchestration/api/endpoint-map.md`
- `/orchestration/design-system/brand.md`
- `/orchestration/design-system/primitives.md`

## Retrieve First

- TanStack Query docs.
- React accessibility docs for tables/status regions.

## Own These Paths

- `/apps/web/src/features/jobs/**`
- `/apps/web/src/features/settings/**`
- `/apps/web/src/routes/jobs*`
- `/apps/web/src/routes/settings*`
- `/apps/web/src/api/jobs*`
- `/apps/web/src/api/settings*`
- `/apps/web/src/api/client*` Stage 9 temporary owner
- `/apps/web/src/app/status*`
- `/apps/web/src/i18n/**` Jobs/Settings/shared status keys only
- `/apps/web/src/test/jobs/**`
- `/apps/web/src/test/settings/**`

## Starting Reality Check

- App shell has status indicator placeholder.
- Job/settings APIs exist.
- Other UI agents may request shared client additions through this stage owner.

## Deliver

- Jobs list with status, type, attempts, error, timestamps.
- Retry failed job action.
- Admin reindex action if exposed.
- Settings page showing storage, Telegram, OCR, embeddings, model, worker status.
- Global status indicator showing active/pending/failed jobs.
- Shared API client adjustments needed by Stage 9 UI agents.

## Constraints

- Do not implement Drive or Photos feature UI.
- Do not hard-code user strings outside i18n.
- Do not expose secrets or raw local paths in UI.

## Required Tests

- Jobs list render and retry action.
- Failed job state.
- Settings mode/status render.
- Global status indicator state.
- Shared API client regression tests.

## Definition Of Done

- Users can see background work, retry failures, and understand local/Telegram/OCR/embedding configuration state.
