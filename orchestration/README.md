# Orchestration Contract

Purpose: this folder is the implementation contract for clean-context AI agents building the Telegram Private Cloud MVP Lite. It describes what to build, in what order, who owns each path, and how to verify work without implementing product code here.

Assumption: the repository is currently empty, so agents must create a new Docker-first monorepo using the stack in the product specification.

## Reading Order

1. `README.md`
2. `AGENTS.md`
3. `architecture/system-overview.md`
4. `architecture/repo-structure.md`
5. Relevant `product/*.md` and `api/*.md`
6. `testing/*.md`
7. `execution/build-order.md`
8. `execution/parallel-workstreams.md`
9. Assigned `execution/agent-prompts/*.md`

## Directory Map

- `architecture/`: system architecture, layers, data, routes, UI, integration, security, performance.
- `design-system/`: brand book (`brand.md`), UI tokens, primitives, interaction and motion rules.
- `product/`: behavior contracts for every user-facing and backend module.
- `api/`: HTTP, event, error, and external service contracts.
- `testing/`: required test strategy, layers, critical journeys, merge gates.
- `execution/`: build order, parallel workstreams, and agent prompts.

## Core Principles

- Local-first, Docker-first, CPU-first.
- Telegram-first: the user's own Telegram account (MTProto) is the encrypted blob store and the replication log between devices; each device's SQLite is its local source of truth (see `architecture/telegram-first.md`).
- Everything leaving the device is end-to-end encrypted; Telegram and the pairing relay only see ciphertext.
- The app must still work with `STORAGE_BACKEND=local` (single device, no Telegram).
- Embeddings and OCR are optional capabilities; FTS/name/metadata search must keep working when they are disabled.
- Clean/Hexagonal Architecture is mandatory.
- Domain code imports no FastAPI, SQLite, Telegram, OCR, embedding, media, or React libraries.
- UI must never block on OCR, embeddings, or long media jobs.
- Background work is progressive, retryable, observable, and safe to resume.
- Root/shared files have exactly one owner per implementation stage.

## Feature And Module List

- Foundation and developer workflow.
- Domain entities, ports, DTOs, and use cases.
- SQLite schema, repositories, FTS5, sqlite-vec, settings, manifest events, jobs.
- Local and Telegram blob stores.
- Upload, ingestion, metadata, previews, thumbnails, PDF/video basics.
- OCR indexing.
- Embedding indexing.
- Hybrid search and explanations.
- Global Search UI and Documents filtered view.
- Drive UI.
- Photos UI.
- Jobs/settings/status UI.
- Configuración editable con validación, secretos protegidos y aplicación/reinicio controlados.
- Aplicación de escritorio multiplataforma con Electron y sidecars locales de API/worker.
- Seed data, doctor script, docs, release hardening.
- Telegram-first program (Stages 14-17): MTProto account login, encrypted vault, multi-device sync, QR/code pairing via relay, automatic backup, end-user product polish. See `execution/telegram-first-program.md`.

## Non-Goals

- No product implementation code belongs in `/orchestration`.
- No microservices; the only hosted component is the stateless pairing relay (`apps/relay`).
- No GPU-required mode.
- No public links, native mobile app, OS files-on-demand, shared family vaults (specified as deferred in `product/telegram-first-experience.md`), advanced multiuser auth, facial recognition, audio transcription, automatic captions, long-video deep indexing, PostgreSQL, or Qdrant.
- No external cloud AI services.
