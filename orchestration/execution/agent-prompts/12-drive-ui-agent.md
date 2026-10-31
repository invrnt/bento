# Drive UI Agent

## Mission

Implement the Drive user interface for folder browsing, file actions, upload, preview, download, and scoped search.

## First Read

- `/orchestration/README.md`
- `/orchestration/AGENTS.md`
- `/orchestration/product/drive.md`
- `/orchestration/api/endpoint-map.md`
- `/orchestration/design-system/brand.md`
- `/orchestration/design-system/primitives.md`
- `/orchestration/architecture/styling-design.md`
- `/orchestration/architecture/i18n-a11y.md`

## Retrieve First

- TanStack Query docs.
- TanStack Virtual docs.
- React drag-and-drop/file input guidance.

## Own These Paths

- `/apps/web/src/features/drive/**`
- `/apps/web/src/routes/drive*`
- `/apps/web/src/api/drive*`
- `/apps/web/src/i18n/**` Drive keys only
- `/apps/web/src/test/drive/**`

## Starting Reality Check

- App shell and primitives exist.
- Assets/Drive APIs are implemented.
- Shared API client path may require coordination with jobs-settings-ui in Stage 9.

## Deliver

- Folder browser with breadcrumb.
- Grid/list toggle.
- Folder/file cards.
- Drag-and-drop upload and file picker upload.
- Rename file/folder.
- Move file/folder.
- Logical delete.
- Download.
- Preview when available.
- Search scoped to Drive/folder.
- Empty/loading/error/indexing states.

## Constraints

- Do not create new shared primitives; request additions if needed.
- Do not duplicate API client base code.
- Do not edit Photos or Jobs feature paths.
- No business rules beyond UI validation and API calls.

## Required Tests

- Folder listing render.
- Upload interaction with mocked API.
- Rename/move/delete action tests.
- Download/preview link behavior.
- Keyboard-accessible context menu.
- Drive scoped search call.

## Definition Of Done

- A user can manage files/folders in Drive through implemented APIs.
- UI remains responsive while indexing is pending.
