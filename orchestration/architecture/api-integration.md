# API And Integration Architecture

## API Shape

All API routes live under `/api`. Request/response bodies use JSON except uploads/downloads/previews/thumbnails.

Use stable response envelopes for errors, not for successful resource responses unless a list needs pagination metadata.

## API Client

Frontend owns one typed API client in `apps/web/src/api`. Feature hooks use that client and TanStack Query.

Do not duplicate endpoint URLs in feature components.

## External Integrations

- Telegram Bot API local server: accessed only by `TelegramBlobStoreAdapter` and Telegram webhook interface.
- ffmpeg: accessed only through media/thumbnail adapter code.
- RapidOCR: accessed only through `OCRProviderPort` adapter.
- llama.cpp server + managed GGUF model: accessed only through `EmbeddingProviderPort`/`EmbeddingRuntimePort` adapters; model files only through `ModelDownloaderPort`/`ModelStorePort`.
- sqlite-vec: accessed only through search/vector adapter.

## Configuration

Environment variables:

- `STORAGE_BACKEND=local|telegram`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_RAW_CHAT_ID`
- `TELEGRAM_THUMBS_CHAT_ID`
- `TELEGRAM_JOURNAL_CHAT_ID`
- DB/cache/upload/model/journal/config paths.
- Worker concurrency and feature toggles for OCR/embeddings.

Missing Telegram config is not an error when `STORAGE_BACKEND=local`.

## OpenAPI

FastAPI-generated OpenAPI must stay available. API agents must keep route summaries, response models, and error responses current enough for the frontend to rely on them.
