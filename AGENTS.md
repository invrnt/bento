# Global Agent Rules

These rules apply to every implementation agent.

## Required Read Order

1. `/orchestration/README.md`
2. `/orchestration/architecture/system-overview.md`
3. `/orchestration/architecture/repo-structure.md`
4. Assigned agent prompt.
5. Prompt-specific product, API, architecture, and testing docs.

## Architecture Rules

- Use a modular monolith with separate runtime processes: `api`, `worker`, `web`, plus the Electron `desktop` host; the only hosted component is the stateless pairing relay (`apps/relay`).
- Use one backend Python package under `apps/api/src/bento` for API and worker code.
- Keep dependency direction: `interfaces -> application -> domain`, `adapters -> ports`, `infrastructure -> adapters`, `domain -> nothing external`.
- Put all external systems behind ports/adapters.
- Do not place business rules in FastAPI endpoints or React components.
- Do not duplicate helpers, constants, stores, API clients, DTOs, domain entities, or primitives.

## Ownership Boundaries

- Edit only paths listed in your agent prompt.
- If a required edit is outside owned paths, stop and document the needed change in your stage handoff.
- Shared files have one temporary owner per stage in `execution/parallel-workstreams.md`.
- Agents in the same stage may run in parallel only with non-overlapping owned paths.
- Later stages start only after prior stages are merged and green.

## Dependencies

- Backend: Python, FastAPI, SQLAlchemy 2, Alembic, Pydantic, Telethon 1.x (MTProto), cryptography, spake2, segno, watchdog, websockets, Uvicorn, pytest.
- Relay: Cloudflare Workers + SQLite-backed Durable Objects, TypeScript, Wrangler, Vitest.
- Worker: same backend package, SQLite persistent queue, controlled concurrency, retry/backoff.
- Frontend: React + Vite, TypeScript, Tailwind, TanStack Query, virtualized grid/list.
- IA Lite: RapidOCR, local Jina v5 omni nano GGUF via isolated llama.cpp server/wrapper, mock and disabled providers.
- Media: ffmpeg, Pillow or pyvips, pypdfium2 or equivalent.
- Do not introduce a new framework, state library, ORM, queue, vector DB, or design system without updating orchestration docs first.

## Docs Retrieval

- Before coding against external APIs or libraries, retrieve current official docs for FastAPI, SQLAlchemy 2, Alembic, Telethon/MTProto, cryptography, sqlite-vec, RapidOCR, llama.cpp, Vite, TanStack Virtual, Tailwind, Electron, Cloudflare Workers/Durable Objects, and Docker Compose as relevant to your prompt.
- Prefer official documentation and pinned package docs over blog posts.
- Record any important version assumption in the implementation PR notes.

## Style

- Python: typed, small modules, explicit ports, async boundaries where IO occurs.
- TypeScript: strict types, feature folders, query hooks separate from UI components.
- Use deterministic kebab-case for web route paths and snake_case for Python modules.
- Keep comments sparse and useful.

## Testing

- Write tests in the same stage as implementation.
- Domain/application tests must not require SQLite, Telegram, OCR, embeddings, ffmpeg, or Docker.
- Adapter tests may use temporary SQLite/filesystem/fakes.
- API tests use FastAPI TestClient or async client with dependency overrides.
- UI tests cover components and critical journeys without relying on real AI providers.
- Do not merge while tests owned by the stage are failing.

## i18n, A11y, Security, Performance

- User-facing strings must be routed through the frontend i18n dictionary.
- Default locale is Spanish; English can be added by dictionary only.
- UI must be keyboard navigable, screen-reader labeled, and maintain visible focus.
- Bind local services to localhost by default; never log secrets, Telegram sessions, login tokens, recovery codes, pairing codes, or keys.
- Everything that leaves the device (Telegram, relay) must be end-to-end encrypted; see `orchestration/architecture/telegram-first.md`.
- Validate upload paths, file names, MIME handling, and archive/path traversal cases.
- Use thumbnails/previews for listing; never load original blobs for grids or search results.
- Worker defaults must be CPU-safe: concurrency `1`, small OCR/embedding batches, thumbnails before OCR/embeddings.
