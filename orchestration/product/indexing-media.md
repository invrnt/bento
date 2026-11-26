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
- Default model: EmbeddingGemma 2 Q8_0 at 512 Matryoshka dims; the fallback is Qwen3-Embedding-0.6B (D1, D9). The person turns it on with an explicit consent sheet. Onboarding may suggest it but never enables it (D8). It is off on Android in v1 (D6).
- Text is cut into ≤ 512-token chunks: sentences first, windows never span pages, at most 16 chunks per asset, first pages first. Chunks are sent in batches of 8 after thumbnails and OCR. Images are embedded as text (OCR + filename/album/place/date) in v1 (D5).
- Every vector carries its embedding space id (`<model_id>@<revision>/<dims>`). A model or dims change re-embeds into a new space and flips atomically when it reaches 100 %. Peer vectors from another space are stored but not indexed.
- Measured indexing cost (EG2, 4 threads, Ryzen 7 5800H): about 0.75 s per full 512-token chunk and about 13 short items per second; about 530 MiB RSS for the server.
- Mock and disabled providers are required for tests and fallback.
- Embeddings write `asset_embeddings` (with `space_id`), `asset_embedding_chunks` and per-space sqlite-vec records. `sqlite-vec` is bundled on desktop (D7), with the Python fallback elsewhere.
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
