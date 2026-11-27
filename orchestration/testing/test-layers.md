# Test Layers

## Backend Unit

- Domain entities and value objects.
- Use cases with fake ports.
- Query parsing and scoring rules.
- Job state transitions.

Target: fast, no DB, no network, no Docker.

## Backend Integration

- SQLAlchemy repositories with temporary SQLite.
- Alembic migration smoke.
- SQLite FTS5 behavior.
- sqlite-vec adapter with skip/fallback when extension unavailable in local dev.
- Local blob store with temp filesystem.
- Job queue claim/retry semantics.

## API

- FastAPI route tests with dependency overrides.
- Upload success/duplicate/error paths.
- Drive/Photos/Search/Jobs endpoints.
- Error model shape.

## Worker

- Handler dispatch.
- Retry/backoff.
- Thumbnail/text extraction/OCR/embedding handlers with fake providers; job order (thumbnail → `text_extract` → OCR → embedding).
- Text extraction adapters on small generated files: encodings (UTF-8, BOM, Latin-1/Windows-1252), binary content, size caps, PDF text layers (hand-written PDFs in `tests/fakes/pdf_documents.py`), malformed PDFs.

## Frontend

- Component tests for primitives and feature flows.
- API hook tests with mocked API.
- Accessibility checks for menus/dialogs/lightbox where feasible.

## E2E/Smoke

- Docker Compose smoke.
- `make doctor`.
- Upload, list in Drive, view Photos, search by filename, download.
- OCR/embedding smoke can use fakes or small fixtures.
