# Web Design System Agent

## Mission

Create the frontend shell, design tokens, primitives, i18n, accessibility foundations, and route placeholders.

## First Read

- `/orchestration/README.md`
- `/orchestration/AGENTS.md`
- `/orchestration/architecture/styling-design.md`
- `/orchestration/architecture/i18n-a11y.md`
- `/orchestration/design-system/brand.md`
- `/orchestration/design-system/tokens.md`
- `/orchestration/design-system/primitives.md`
- `/orchestration/design-system/motion-interaction.md`
- `/orchestration/architecture/routing-entrypoints.md`

## Retrieve First

- Official Vite React docs.
- Official Tailwind docs.
- Official TanStack Query docs.
- Official TanStack Virtual docs.
- React accessibility guidance.

## Own These Paths

- `/apps/web/src/app/**`
- `/apps/web/src/components/**`
- `/apps/web/src/i18n/**`
- `/apps/web/src/routes/**` placeholders only
- `/apps/web/src/styles/**`
- `/apps/web/src/lib/**` frontend-only utilities
- `/apps/web/src/api/**` base client skeleton only
- `/apps/web/src/test/**` or frontend test setup

## Starting Reality Check

- Foundation Vite shell exists.
- Product APIs are not fully implemented.
- Feature UI agents will own Drive/Photos/Jobs later.

## Deliver

- CSS token variables and Tailwind mapping.
- Shared primitives listed in design-system docs.
- App shell with sidebar, top search, main region, status indicator placeholder.
- Client-side routes for required surfaces with placeholders.
- Spanish default i18n dictionary and helper.
- Typed API client skeleton with central URL handling.
- Accessibility behaviors for primitives.

## Constraints

- Do not implement Drive, Photos, Search results, Jobs, or Settings feature behavior beyond placeholders.
- Do not hard-code user-visible strings outside i18n.
- Do not add another design system library unless approved by orchestration update.
- Do not edit backend files.

## Required Tests

- Primitive render tests.
- App shell route smoke tests.
- Keyboard/focus tests for menu/dialog where implemented.
- i18n no-missing-key smoke for placeholders.

## Definition Of Done

- Feature agents can compose screens using shared primitives.
- Shell is responsive and accessible.
- No domain-specific component logic leaked into primitives.
