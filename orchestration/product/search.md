# Product: Global Search

## Scope

Global search finds assets, folders, photos, videos, documents, PDF pages, OCR blocks, and albums using name, folder, OCR, metadata, date, type, and optional semantic embeddings.

## Endpoint

`GET /api/search?q=&type=&folder_id=&date_from=&date_to=&limit=&cursor=`

## Result Types

- `asset`
- `folder`
- `photo`
- `video`
- `document`
- `pdf_page`
- `ocr_block`
- `album`

## Required Behavior

- Search by filename.
- Search by folder.
- Search by OCR text.
- Search by textual metadata.
- Filter/boost by date.
- Filter by type.
- Semantic image search when embeddings are indexed.
- Grouped UI results.
- Type filters.
- Match explanation for every result.
- Thumbnail preview when available.
- Show "indexing" state when OCR/embeddings are missing.
- Documents sidebar view as a filtered search/list for document and PDF assets.

## Scoring

```txt
score_final =
  text_score * w_text
+ vector_score * w_vector
+ metadata_score * w_meta
+ recency_score * w_recency
```

Rules:

- If query contains numbers, emails, document-like names, or terms like `cedula`, `factura`, `contrato`, `pasaporte`, boost text and metadata.
- If query describes a scene, boost vector score.
- If query contains date/month/year, apply temporal filter or boost.
- If embeddings are disabled/unavailable, vector score is omitted.
- With smart search the weights are `HYBRID_WEIGHTS_BY_INTENT` (general: text 0.35, vector 0.45, metadata 0.10, recency 0.10). Without it, text-only search uses `WEIGHTS_BY_INTENT` without `vector`, renormalised, as before. Both are in `application/search/scoring.py`.
- With smart search, text found only in a file, folder or album name counts `NAME_ONLY_TEXT_WEIGHT` (0.5) of text found in the file's content.

### Lexical matching (`domain/search_terms.py`)

- Spanish and English stop words («de», «la», "the", "of" …) are ignored by FTS and by name, metadata, folder, album and OCR matching. They count inside a quoted phrase (`"viaje a la playa"`, matched word for word, in order), and when the query has nothing else.
- A query word matches a whole word of a name or text, ignoring case, accents and a plain plural («facturas» finds `factura-luz.pdf`, «reunión» finds `reunion`). It matches the start of a longer word only from 4 characters, for half credit («carb» → `carbonara`; "car" → nothing).
- Typed name pieces with separators (`recibo-abril`, `IMG_2210`, a full file name) match as substrings of the name, so exact file-name searches keep working.

## Smart search (search by meaning)

Contract: `api/smart-search-contract.md`. Program: `execution/smart-search-program.md`.

- `vector_score` comes only from the **active embedding space**. Vectors from other spaces, including legacy and foreign peer spaces, are never compared.
- Queries are embedded with the model's query prefix; documents are embedded with the document prefix and the file name as title.
- An asset's `vector_score` is the best cosine among its chunks (≤ 16 chunks of ≤ 512 tokens).
- A vector hit counts only at or above the model's calibrated floor for the space's dims (`min_similarity` in the manifest, 0.60 at 768 for EmbeddingGemma 2) and within `similarity_margin` (0.15) of the query's best hit. Below that it is not a result, and `semantic` does not appear. Kept hits are rescaled from the floor to the best hit before fusion (`api/smart-search-contract.md` §Embedding spaces).
- Vector search is used only while `search_available` (`ready` or `indexing`). In every other state, and whenever the API cannot reach the local embedding server, search silently uses name, folder, OCR, metadata and FTS as today, and `semantic` never appears in `match_reasons`.
- v1 is text only. Photos match by meaning through their OCR text and metadata (album, place, date, file name), not their pixels (D5).
- Android does not offer it in v1 (D6).
- Default space: EmbeddingGemma 2 at 768 dims (D1, D9; 512 until 2026-11-27, existing 512 spaces keep working). Measured on a Ryzen 7 5800H: about 21 ms per query embedding at p50.

## Explanation

Every result includes a human-readable reason, such as `Coincidio por OCR y tipo de documento`.

## Ownership

Backend behavior owner: hybrid-search agent.

User-visible Search UI and Documents view owner: search-ui agent.
