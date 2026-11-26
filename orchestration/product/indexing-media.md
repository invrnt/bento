# Product: Indexing And Media Processing

## Scope

Media processing creates thumbnails/previews and searchable units for assets.

## Thumbnails And Previews

Images:

- `thumb_sm`: 256px max side.
- `thumb_md`: 512px max side.
- `preview`: 1600px max side.

Videos:

- One thumbnail at second `1` or `10%`, whichever is smaller.
- No multiple keyframes in MVP.

PDFs:

- Thumbnail of first page.
- OCR pages in background.

## OCR

- RapidOCR adapter extracts text from images and PDF page renders.
- OCR writes `asset_text`, `ocr_blocks`, and FTS index records.
- Disabled OCR adapter is valid and must not break search by filename/metadata.

## Embeddings

- A managed GGUF embedding model (one-click download, pinned SHA-256; `execution/smart-search-program.md`) embeds document text and image OCR/metadata text through a local llama.cpp server; image-pixel embeddings are an opt-in later track. The earlier Jina v5 omni nano target was dropped (CC BY-NC 4.0, no official GGUF).
- Mock and disabled providers are required for tests and fallback.
- Embeddings write `asset_embeddings` and sqlite-vec records.
- Embeddings are optional; the app must still work without them.

## Constraints

- CPU-first.
- Small batches.
- Worker concurrency default `1`.
- Do not load original Telegram blobs for listing.
- Cache generated thumbnails/previews locally.

## Ownership

Media owner: ingestion-media agent.
OCR owner: ocr-indexing agent.
Embedding owner: embeddings-agent.
