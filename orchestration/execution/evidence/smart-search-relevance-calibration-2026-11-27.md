# Smart search: relevance floor and hybrid ranking, calibrated on the real model (Linux, 2026-11-27)

Follow-up to findings 2 and 3 of `smart-search-real-model-pass-2-2026-11-27.md`. Finding 2: there was no minimum similarity, so every asset came back as a `semantic` hit and a nonsense query returned 10. Finding 3: weak lexical matches outranked relevant semantic hits («de» inside `ideas-regalos…` and `endesa…`, "car" inside `carbonara`, a file name containing "ticket"). This pass measured the score distributions first, then set a per-model, per-dims floor in the model manifest and changed the lexical rules and the fusion weights. It re-ran the measurements afterwards.

**Result.** The floor is 0.60 at 768 dims, with a margin of 0.15 under the query's best hit. On the 30-query cross-language set, recall@5 stays at **0.983**, and every relevant document of all 62 labelled queries is kept. On the 200-document fixture, the floor and margin keep 20 other documents per query on average instead of all 199. Off-topic queries keep 148 of their 3,200 hits (−95 %). On the small library of pass 2, mean nDCG@6 went from 0.923 to **0.961**. The two off-topic queries went from 6 + 6 `semantic` hits to 2 + 0. Every body-only and exact-name query still puts its file first.

The floor cannot remove every off-topic hit. With this model the hardest real cross-language match ("mortgage deed" → `hipoteca`, cosine 0.606) scores below the best hit of 10 of the 16 off-topic queries (up to 0.664 for "lorem ipsum dolor sit amet"). Any floor above 0.606 loses that match and drops recall@5 to 0.950. The remaining off-topic hits are documented below, not hidden.

## Setup

| Item | Value |
|---|---|
| Machine | AMD Ryzen 7 5800H (8 cores / 16 threads), 15 GiB RAM, Linux 7.2.15 (Arch-based), Python 3.13.15 (uv venv, `--extra dev --extra desktop`), sqlite-vec 0.1.6 |
| llama.cpp | `b12777`. `dist/llama-server/linux-x64/` was copied from the pass-2 worktree, not rebuilt. `llama-server --version` → `version: 1.1.0-dev (build 12777, commit caea914e9)`, and every file matched its `SHA256SUMS` |
| Model | `ggml-org/embeddinggemma-2-GGUF@6ea3e3a309d12a4779cfda98b8c19800d2d5da71`, `embeddinggemma-2-Q8_0.gguf`, downloaded from the manifest's pinned Hugging Face URL (309,855,456 B, 4 min at 1.2 MB/s). `sha256sum` → `2188ac1d…40b09135`, the manifest value |
| Code | `main` at `c40504f4` for "before", this PR for "after" |

The measurements come from three opt-in tests (`-m real_model`; they are skipped unless `BENTO_REAL_LLAMA_SERVER` and `BENTO_REAL_EMBEDDING_MODEL` point at local files):

- `tests/integration/embeddings/test_real_model_recall.py`: the existing recall test (30 cross-language queries, 200 documents), now on the shared `real_model_support.py`.
- `tests/integration/embeddings/test_real_model_calibration.py` (new) uses the same 200 documents with 62 labelled queries: the 30 cross-language queries plus the spike's es/en queries. It adds 16 off-topic queries (8 es, 8 en), for example "zzzz quantum chromodynamics", «partitura de violonchelo barroco» and "lorem ipsum dolor sit amet". It records the cosine of every relevant and every other document per query. It sweeps a floor from 0.30 to 0.80 in 0.01 steps and a margin over {none, 0.05 … 0.30} at each Matryoshka dimension. It asserts the manifest's values. `BENTO_REAL_MODEL_CALIBRATION_REPORT=<file>` writes the full JSON.
- `tests/integration/embeddings/test_real_model_hybrid_ranking.py` (new) builds a 39-file library shaped like pass 2's (`small_library.py`) in a temporary SQLite database, with OCR off. PDFs with a text layer and text files get document text, while scans and PNGs are embedded by file name only. It embeds the library for real and runs the production `CompositeSearchIndex.search` for pass 2's queries, its two reported misses, body-only queries, «endesa» and two off-topic queries. It reports the top 6 and nDCG@6 against labelled relevant files (`BENTO_REAL_MODEL_RANKING_REPORT=<file>`).

Run times: the server was ready in 0.8 s, the 200 documents were indexed in 15.6 s, and query embedding took 21.0 ms at p50. The three tests together take 62 s.

## Score distributions (cosine, best chunk per document)

62 labelled queries × 200 documents: 71 relevant pairs and 12,329 other pairs. "Other" includes near-duplicates, for example 11 more electricity bills for "electricity bill for March", so it is an upper bound on noise.

| Dims | Relevant min / p5 / p50 | Other p50 / p95 / p99 / max | Best other per query, p50 | Off-topic best hit min / p50 / max |
|---|---|---|---|---|
| **768** | **0.606** / 0.670 / 0.766 | 0.555 / 0.649 / 0.694 / 0.791 | 0.673 | 0.532 / 0.592 / **0.664** |
| 512 | 0.616 / 0.677 / 0.768 | 0.559 / 0.656 / 0.703 / 0.794 | 0.677 | 0.540 / 0.604 / 0.680 |
| 256 | 0.617 / 0.693 / 0.784 | 0.577 / 0.677 / 0.725 / 0.813 | 0.701 | 0.549 / 0.616 / 0.696 |
| 128 | 0.706 / 0.771 / 0.837 | 0.686 / 0.772 / 0.805 / 0.882 | 0.792 | 0.699 / 0.745 / 0.797 |

- Real matches start at about 0.61 and off-topic best hits end at 0.66, so the two ranges overlap. The lowest relevant pairs at 768 are "mortgage deed" → `hipoteca` 0.606 (the best other document is 0.606), «postre de chocolate» → `receta-brownies` 0.642, "speeding ticket fine" → `multa` 0.666, and «receta de arroz con mariscos» → `receta-paella` 0.670.
- A relevant document is at most 0.136 below the query's best hit («receta de arroz con mariscos»: `receta-paella-marisco` 0.806, `receta-paella` 0.670), and at most 0.085 below it for every other query.
- The distributions move up as dims shrink; 128 is about 0.10 higher. So the floor is per dimension, not one number per model.
- Off-topic best hits at 768: "lorem ipsum dolor sit amet" 0.664, "asdf qwerty uiop" 0.643, «zzzz cromodinámica cuántica» 0.642, «xkcd blorp fnord» 0.624, «apertura de ajedrez siciliana» 0.618, "zzzz quantum chromodynamics" 0.605, then ten queries at 0.532-0.597. Gibberish sits higher than real but unrelated topics.

### Other rules that were tried

Measured on the same vectors, and dropped because the overlap between real and off-topic queries was no smaller:

- **Contrast with an empty document** (score minus the query's cosine to `title: none | text: ` or `none`): the lowest real match is at −0.060, against +0.027 for the highest off-topic query.
- **Distribution shape of one query** (best minus the 5th, 10th or 20th hit; best minus the median; z-score of the best hit): "mortgage deed" and «informe trimestral de ingresos» look like nonsense on every one of these features. "chess opening theory" looks like a real query. Using the median or z-score would also need every vector scanned per query, not the `vec0` top-k.

## Sweep and chosen values

At each dimension, the chosen floor is the highest one that keeps every relevant document. The margin is the smallest one that keeps them all at that floor.

| Dims | Rule | recall@5, 30 cross-language | recall@5, all 62 | Relevant kept | Other documents kept per query, mean / p90 | Off-topic queries with a hit | Off-topic hits |
|---|---|---|---|---|---|---|---|
| 768 | none (before) | 0.983 | 0.989 | 1.000 | 198.9 / 199 | 16/16 | 3,200 |
| 768 | floor 0.60 | 0.983 | 0.989 | 1.000 | 39.4 / 92 | 6/16 | 148 |
| **768** | **floor 0.60 + margin 0.15** | **0.983** | **0.989** | **1.000** | **20.3 / 53** | 6/16 | 148 |
| 512 | none | 0.950 | 0.973 | 1.000 | 198.9 / 199 | 16/16 | 3,200 |
| 512 | floor 0.61 + margin 0.15 | 0.950 | 0.973 | 1.000 | 20.4 / 61 | 6/16 | 140 |
| 256 | none | 0.917 | 0.957 | 1.000 | 198.9 / 199 | 16/16 | 3,200 |
| 256 | floor 0.61 + margin 0.15 | 0.917 | 0.957 | 1.000 | 27.7 / 77 | 9/16 | 313 |
| 128 | none | 0.883 | 0.940 | 1.000 | 198.9 / 199 | 16/16 | 3,200 |
| 128 | floor 0.70 + margin 0.15 | 0.883 | 0.940 | 1.000 | 65.4 / 157 | 15/16 | 723 |

The floor at 768, with a 0.15 margin:

| Floor | recall@5, 30 | recall@5, 62 | Relevant kept | Other kept, mean | Off-topic queries with a hit | Off-topic hits |
|---|---|---|---|---|---|---|
| 0.55 | 0.983 | 0.989 | 1.000 | 32.0 | 11/16 | 823 |
| 0.58 | 0.983 | 0.989 | 1.000 | 24.9 | 9/16 | 346 |
| 0.59 | 0.983 | 0.989 | 1.000 | 22.7 | 8/16 | 230 |
| **0.60** | **0.983** | **0.989** | **1.000** | **20.3** | **6/16** | **148** |
| 0.61 | 0.950 | 0.973 | 0.986 | 17.9 | 5/16 | 92 |
| 0.63 | 0.950 | 0.973 | 0.986 | 13.4 | 3/16 | 30 |
| 0.65 | 0.917 | 0.957 | 0.958 | 9.1 | 1/16 | 3 |

The margin at 768, with a 0.60 floor. The margin cannot help off-topic queries, because their best hit always passes it:

| Margin | recall@5, 30 | recall@5, 62 | Relevant kept | Other kept, mean |
|---|---|---|---|---|
| none | 0.983 | 0.989 | 1.000 | 39.4 |
| 0.05 | 0.983 | 0.981 | 0.958 | 1.5 |
| 0.10 | 0.983 | 0.981 | 0.986 | 7.9 |
| 0.12 | 0.983 | 0.981 | 0.986 | 12.3 |
| **0.15** | **0.983** | **0.989** | **1.000** | **20.3** |
| 0.20 | 0.983 | 0.989 | 1.000 | 36.0 |

The manifest's EmbeddingGemma 2 entry now carries `"min_similarity": {"768": 0.6, "512": 0.61, "256": 0.61, "128": 0.7}` and `"similarity_margin": 0.15`. Qwen3-Embedding-0.6B was not measured. It has no values, so it uses the domain fallback `DEFAULT_MIN_SIMILARITY = 0.30` with no margin. That fallback is low enough not to cut an uncalibrated model's real matches and still drops the near-zero cosines of mock and hash vectors.

## Ranking changes

| Change | Where | Why (pass 2 finding 3) |
|---|---|---|
| Vector hits below `min_similarity_for(dims)` or more than `similarity_margin` below the best kept hit are dropped before fusion. They neither rank nor show `semantic` | `domain/smart_search.py` (`similarity_rule`, `relevant_semantic_scores`), applied in `CompositeSearchIndex._add_vector_hits` | Finding 2 |
| A kept hit's vector evidence is `(cosine − floor) / max(best − floor, 0.20)`, so it ranges over [0, 1] instead of the raw 0.60-0.85 band. A best hit that sits just above the floor stays weak | `semantic_strength` | A raw cosine of 0.75 × weight 0.20 could not beat any normalised text hit |
| Spanish and English stop words are dropped from FTS and from name, metadata, folder, album and OCR matching. They count inside a quoted phrase, and when the query has nothing else | `domain/search_terms.py` | «de» matched `i-de-as`, `en-de-sa` and `water-bill-de-cember` |
| Words match whole words of a name, ignoring case, accents and a plain plural («facturas» → `factura-luz`, «reunión» → `reunion`). A prefix counts only from 4 characters and only half («carb» → `carbonara` 0.5; "car" → nothing). Typed name pieces with separators («recibo-abril», `IMG_2210`, the full name) still match as substrings | `domain/search_terms.py` | "car" → `carbonara`; «a» matched nearly every name |
| With smart search on, text found only in a name counts 0.5 of text found in the file's own content, and the name no longer counts a second time as metadata | `application/search/scoring.py` (`NAME_ONLY_TEXT_WEIGHT`, `hybrid_text_score`) | `ticket-supermercado.png` outranked the speeding fine |
| Hybrid weights (text / vector / metadata / recency): general 0.35 / 0.45 / 0.10 / 0.10 (was 0.55 / 0.20 / 0.15 / 0.10), document 0.40 / 0.20 / 0.30 / 0.10 (was 0.50 / 0.05 / 0.35 / 0.10), scene 0.30 / 0.50 / 0.10 / 0.10 (was 0.25 / 0.55 / 0.10 / 0.10), date 0.25 / 0.20 / 0.15 / 0.40 (was 0.30 / 0.05 / 0.20 / 0.45). Text-only search keeps the old table, renormalised as before | `HYBRID_WEIGHTS_BY_INTENT` | Semantic-only hits were capped at about 0.30 |

Weighted fusion was kept, not replaced by RRF. RRF would give a stop-word name match the same rank credit as a real one, and it would discard the floor's information about how strong a hit is.

### Weight sweep

On the small library, the general, document and scene weights were swept together: text 0.25-0.55, vector 0.20-0.55, metadata = 0.90 − text − vector, recency 0.10, and name-only weight 0.4-1.0 (199 combinations). Results are mean nDCG@6 over the 12 labelled queries, plus the number of the 6 "must be first" queries that put their file first:

| Vector weight | Mean nDCG@6 over all combinations | Fewest "first" checks passed |
|---|---|---|
| 0.20 (the old general weight) | 0.929 | 5/6 |
| 0.30 | 0.942 | 5/6 |
| 0.40 | 0.953 | 5/6 |
| 0.45 | 0.956 | 5/6 |
| 0.50 | 0.960 | 6/6 |
| 0.55 | 0.962 | 6/6 |

The best combinations reach 0.964 (text 0.25-0.30, vector 0.45-0.55, name-only weight 0.4). The chosen general weights (0.35 / 0.45 / 0.10, name-only weight 0.5) reach 0.961 and pass 6/6. A difference of 0.003 is one rank on one query of 12, so the choice keeps more text weight: exact names and body matches stay strong for libraries this corpus does not cover. The fake-based tests below pin that behaviour.

## Before and after: top 6 on the small library

Flags: `name` = `filename`, `sem` = `semantic`, `meta` = `metadata`, `text` = `indexed_text`. The library has the same files as pass 2, with synthetic text written for this test, so the lists are close to pass 2's but not the same.

| Query | Before (`main` `c40504f4`) | After (this PR) |
|---|---|---|
| «facturas de luz» | 1 factura-luz-enero-2026 (name, sem, meta) · 2 factura-luz-febrero-2026 (name, sem, meta) · 3 endesa-recibo-abril.png (name: «de») · 4 water-bill-december-2025 (name: «de») · 5 ideas-regalos-navidad.txt (name: «de») · 6 factura-gas-natural-febrero (sem) | 1 factura-luz-enero-2026 (name, sem, meta) · 2 factura-luz-febrero-2026 (name, sem, meta) · 3 factura-gas-natural-febrero (name: «facturas», sem) · 4 factura-agua-marzo-2026 (name, sem) · 5 escaneo-recibo-electricidad-marzo (sem) · 6 gastos-hogar-2026.csv (sem) |
| «receta de pasta» | 1 receta-pasta-carbonara (name, sem, meta, text) · 2 pesto-pasta-recipe · 3 receta-lasana-verduras · 4 receta-gazpacho · 5 receta-tortilla.md · 6 ideas-regalos-navidad.txt (name: «de») | 1 receta-pasta-carbonara (name, sem, meta, text) · 2 pesto-pasta-recipe · 3 receta-lasana-verduras · 4 receta-gazpacho · 5 receta-tortilla.md · 6 lista-compra.txt (sem) |
| «viaje a la playa» | 1 viaje-cadiz-playa-agosto (name, sem, meta, text) · 2 packing-list-beach.txt (name: «a») · 3 beach-vacation-itinerary-hawaii (name: «a») · 4 nota-taller.txt (name: «a») · 5 reserva-hotel-mallorca · 6 lista-compra.txt (name: «a») | 1 viaje-cadiz-playa-agosto (name, sem, meta, text) · 2 packing-list-beach.txt (sem) · 3 beach-vacation-itinerary-hawaii (sem) · 4 reserva-hotel-mallorca (sem) · 5 nota-taller.txt (sem) · 6 inventario-trastero.csv (sem) |
| "electricity bill" | 1 electric-bill-october-2025 (name, sem, meta, text) · 2 water-bill-december-2025 (name) · 3 phone-bill-january (name) · 4 factura-luz-enero-2026 (sem) · 5 factura-luz-febrero-2026 (sem) · 6 escaneo-recibo-electricidad-marzo (sem) | 1 electric-bill-october-2025 (name, sem, meta, text) · **2 factura-luz-enero-2026 (sem) · 3 factura-luz-febrero-2026 (sem)** · 4 water-bill-december-2025 (name, sem) · 5 phone-bill-january (name, sem) · 6 escaneo-recibo-electricidad-marzo (sem) |
| «reunión de presupuesto» | 1 notas-reunion-presupuesto-q3 (name, sem, meta, text) · 2 budget-meeting-minutes (sem) · 3 endesa-recibo-abril.png (name: «de») · 4 gastos-hogar-2026.csv (sem) · 5 water-bill-december-2025 (name: «de») · 6 nota-taller.txt (sem) | 1 notas-reunion-presupuesto-q3 (name, sem, meta, text) · 2 budget-meeting-minutes (sem) · 3 gastos-hogar-2026.csv (sem). Nothing else passes the margin |
| "beach holiday" | 1 beach-vacation-itinerary-hawaii (name, sem, meta) · 2 packing-list-beach.txt (name, sem, meta) · 3 viaje-cadiz-playa-agosto (sem) · 4 reserva-hotel-mallorca (sem) · 5 project-roadmap.md (sem) · 6 scan-0093 (sem) | Same order. Ranks 5 and 6 are unrelated files whose cosine is just above the cut (about 0.60) |
| "car brakes repair" | 1 nota-taller.txt (sem) · 2-6 scan-0093, budget-meeting-minutes, project-roadmap, doc-2026-0417, annual-revenue-report (sem, noise) | 1 nota-taller.txt (sem) only |
| "speeding ticket" | **1 ticket-supermercado.png (name: "ticket")** · 2 doc-2026-0601 (sem) · 3-6 noise (sem) | **1 doc-2026-0601 (sem)** · 2 ticket-supermercado.png (name, meta; no longer `semantic`) · 3 scan-0093 (sem) |
| «vacuna del perro» | 1 doc-2026-0417 (sem, text) · 2-6 noise (sem) | 1 doc-2026-0417 (sem, text) only |
| «contraseña del wifi» | 1 apuntes.txt (sem, text) · 2-6 noise (sem) | 1 apuntes.txt (sem, text) only |
| "mortgage interest rate" | 1 notes-0312.txt (sem, text) · 2-6 noise (sem) | 1 notes-0312.txt (sem, text) only |
| «endesa» | 1 endesa-recibo-abril.png (name, sem, meta) · 2-6 electricity bills (sem) | Same |
| "zzzz quantum chromodynamics" | 6 `semantic` hits (project-roadmap.md, scan-0093, phone-bill-january, apuntes.txt, captura-whatsapp-cena.png, notes-0312.txt) | 2 `semantic` hits: project-roadmap.md and scan-0093, both just above the 0.60 floor |
| «partitura de violonchelo barroco» | 1 endesa-recibo-abril.png (name: «de») · 2 water-bill-december-2025 (name: «de») · 3-6 noise (sem) | Nothing |

Mean nDCG@6 over the 12 labelled queries is 0.923 before and **0.961** after. Per query, "speeding ticket" goes from 0.631 to 1.000, "electricity bill" from 0.737 to 0.844, and «viaje a la playa» from 0.983 to 1.000. «facturas de luz» drops from 0.723 to 0.684. Before, `endesa-recibo-abril.png` was #3 only because its name contains «de». Its cosine (0.704, name only, OCR off) is below the gas bill's (0.739), and the plural rule now also gives the gas and water bills a name match on «facturas». Nothing else got worse.

## Tests

- **Fakes, in the default suite:**
  - `tests/unit/search/test_search_terms.py`: stop words, phrases, the 4-character prefix rule and its credit, plurals, accents, name fragments and the SQL needles.
  - `tests/unit/smart_search/test_similarity_floor.py`: manifest parsing and validation of the floor and margin, the fallback, `similarity_rule` for other revisions and spec-less providers, and the cutoff and strength functions.
  - `tests/integration/search/test_relevance_ranking.py`: controlled cosines through the real `CompositeSearchIndex`. It covers hits below the floor, the margin, a nonsense query that returns nothing, «de» and "car" no longer outranking a strong semantic hit, a name-only match ranking below a strong semantic hit, body text beating the same words in a name, «endesa» and the full file name staying first, and text-only search with the stop-word, prefix and phrase rules.
  - The PR #15 regression test `test_filename_match_finds_an_asset_older_than_the_candidate_window` is unchanged and passes.
- **Adjusted tests:**
  - `test_text_and_pdf_content_is_searchable_without_ocr` listed both files with one query, «arrendamiento tomates», which matched neither by text. It relied on vector noise, so it now searches each word.
  - `tiny_spec` (the stand-in model of the activation tests) has no floor, because the fake llama-server returns hash vectors whose cosine is about 0.
- **Real model, opt-in:** the three tests above, `3 passed` after the change.

## Not covered

- Qwen3-Embedding-0.6B: not downloaded, so it has no calibrated floor and runs on the 0.30 fallback.
- OCR text (OCR was off) and long multi-chunk documents. The fixture documents are one chunk each.
- Libraries much larger than 200 files. The margin keeps about 20 hits per query on 200 near-duplicate documents; with thousands of files the `candidate_limit` of the vector search (at most 200) caps it anyway.
- Off-topic queries whose best hit is above 0.60 still show a few `semantic` hits (6 of 16 here, 148 hits on 200 documents). Removing them needs a better model or a signal other than the cosine.

## Cleanup

All `llama-server` processes started by the tests were stopped by the tests themselves (`pgrep llama-server` printed nothing afterwards). The model file and the scratch data under `~/.cache/bento-calib` and `/tmp/calib` were deleted. Kept: `dist/llama-server/linux-x64/` in this worktree (git-ignored).
