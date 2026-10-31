# Search UI Agent

## Mission

Implement global Search UI and the Documents filtered view using the hybrid search API.

## First Read

- `/orchestration/README.md`
- `/orchestration/AGENTS.md`
- `/orchestration/product/search.md`
- `/orchestration/api/search-contract.md`
- `/orchestration/design-system/brand.md`
- `/orchestration/design-system/primitives.md`
- `/orchestration/architecture/styling-design.md`
- `/orchestration/architecture/i18n-a11y.md`

## Retrieve First

- TanStack Query docs.
- TanStack Virtual docs.
- React accessibility guidance for search/listbox/results patterns.

## Own These Paths

- `/apps/web/src/features/search/**`
- `/apps/web/src/features/documents/**`
- `/apps/web/src/routes/search*`
- `/apps/web/src/routes/documents*`
- `/apps/web/src/api/search*`
- `/apps/web/src/i18n/**` Search/Documents keys only
- `/apps/web/src/test/search/**`
- `/apps/web/src/test/documents/**`

## Starting Reality Check

- App shell has a global search bar primitive.
- `/api/search` is implemented.
- Shared API client path changes go through jobs-settings-ui as Stage 9 temporary owner.

## Deliver

- Global search route with grouped results.
- Type/date/folder filters.
- Result thumbnails, title, subtitle, score-safe ordering, match explanation.
- Indexing state when OCR/embeddings are pending or disabled.
- `Cmd/Ctrl+K` behavior wired to global search if not already completed by shell.
- Documents route as filtered search/list for documents and PDFs.
- Empty/loading/error states.

## Constraints

- Do not implement backend search logic.
- Do not duplicate the shared API client base.
- Do not edit Drive, Photos, Jobs, or Settings feature paths.
- Do not create new shared primitives; request additions if needed.

## Required Tests

- Search query submit calls `/api/search`.
- Grouped results render with explanations and thumbnails.
- Filters update query parameters/API calls.
- Indexing pending/disabled state renders.
- Documents route applies document/PDF filter.
- `Cmd/Ctrl+K` focus behavior.

## Definition Of Done

- Users can search globally, understand why each result matched, filter results, and access a Documents view backed by search.
