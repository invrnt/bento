# Photos UI Agent

## Mission

Implement Photos, Albums, Favorites, timeline, lightbox, and basic video viewing UI.

## First Read

- `/orchestration/README.md`
- `/orchestration/AGENTS.md`
- `/orchestration/product/photos.md`
- `/orchestration/api/endpoint-map.md`
- `/orchestration/design-system/brand.md`
- `/orchestration/design-system/primitives.md`
- `/orchestration/architecture/styling-design.md`
- `/orchestration/architecture/i18n-a11y.md`

## Retrieve First

- TanStack Query docs.
- TanStack Virtual docs.
- React accessibility guidance for dialogs/lightbox.

## Own These Paths

- `/apps/web/src/features/photos/**`
- `/apps/web/src/features/albums/**`
- `/apps/web/src/features/favorites/**`
- `/apps/web/src/routes/photos*`
- `/apps/web/src/routes/albums*`
- `/apps/web/src/routes/favorites*`
- `/apps/web/src/api/photos*`
- `/apps/web/src/api/albums*`
- `/apps/web/src/i18n/**` Photos/Albums/Favorites keys only
- `/apps/web/src/test/photos/**`

## Starting Reality Check

- App shell and primitives exist.
- Photos/album APIs are implemented or stable.

## Deliver

- Virtualized timeline grouped by day/month.
- Photo grid.
- Lightbox.
- Basic video viewer.
- Favorite toggle.
- Album list/detail/create.
- Add/remove album items where API supports it.
- Photo upload path.
- Indexing state display.
- Search scoped to Photos.

## Constraints

- Do not edit Drive or Jobs feature paths.
- Do not duplicate thumbnail or API URL helpers.
- Do not implement facial recognition/persons/captions.

## Required Tests

- Timeline grouping render.
- Lightbox keyboard close/focus behavior.
- Favorite toggle API call.
- Album create/add item flow with mocked API.
- Video viewer smoke.
- Photos scoped search call.

## Definition Of Done

- A user can browse photos/videos, favorite, use albums, and see indexing state.
