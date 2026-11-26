# Embedding Models for On-Device Smart Search (research, 2026-11-26)

Purpose: choose a replacement for `jina-embeddings-v5-omni-nano`, and pin the files and runtime that `execution/smart-search-program.md` builds on.

All facts here were checked on **2026-11-26**. The sources are the Hugging Face model API and tree API (file sizes and LFS SHA-256), the model cards and LICENSE pages, the llama.cpp source and README at master `0e4e925e`, and the GitHub releases API. No weights were downloaded; GGUF headers were read with HTTP range requests only. Anything marked **(est.)** is an estimate, not a measurement. Re-verify every pin when you bump.

## Why Jina is out

- Every Jina v5 repo is **CC BY-NC 4.0**: `jina-embeddings-v5-text-nano`/`-small`, `-omni-nano`, and their per-task GGUF repos. The cards say "for commercial use, contact sales@jina.ai". Since 2026-08-10 Elastic sells Jina commercial licenses by quote. Jina v3 is also CC BY-NC 4.0; v4 is under the Qwen Research License.
- `huggingface.co/jinaai/jina-embeddings-v5-omni-nano-GGUF` returns **401**. HF returns that for repos that don't exist or are private; it is not a login gate. The real repos are per task (`…-omni-nano-retrieval-GGUF`, Q8_0 232,894,336 B, plus a vision mmproj of 203 MB). They need Jina's fork of llama.cpp (`jina-ai/llama.cpp`, branch `feat-v5-omni`, "not yet upstream").
- The current adapter's image request shape is also not what llama-server accepts (see the program doc, §Why).

## Candidates

The "Official GGUF" column counts only the publisher's own repo or `ggml-org` (the llama.cpp maintainers). The MMTEB column is MTEB Multilingual v2, Mean(Task), as reported on the model card.

| Model (HF @ main sha) | License | Official GGUF, file, bytes | Params | Dims / Matryoshka | Context | Multilingual / Spanish evidence | Multimodal | llama.cpp status |
|---|---|---|---|---|---|---|---|---|
| **google/embeddinggemma-2** @`f9972ac2` (2026-09-14) | **Apache-2.0** (tag, card and GGUF `general.license`). The card also says "Deployments must adhere to the Gemma Prohibited Use Policy", see §Licenses | **yes**: `ggml-org/embeddinggemma-2-GGUF` @`6ea3e3a3`. `embeddinggemma-2-Q8_0.gguf` **309,855,456**; BF16 557,950,176; `mmproj-embeddinggemma-2-Q8_0.gguf` 554,821,056 (vision+audio); mmproj BF16 982,074,816 | 740M total; text path 270M | 768 / 512, 256, 128 | 8,192 | MMTEB **61.36** (61.17 @512, 60.41 @256, 57.89 @128); 100+ languages; no Spanish-specific score published | **yes**: text, image, video, audio in one 768-d space, through the optional mmproj | Upstream arch `gemma-embedding2`, mean pooling. Needs **≥ b11454** (PR #30054, 2026-10-06). Multimodal `/v1/embeddings` with `--mmproj` landed in PR #29556 (2026-09-28) |
| google/embeddinggemma-300m @`57c266a7` (gated) | **Gemma Terms of Use** (custom) | yes: `ggml-org/embeddinggemma-300M-GGUF` @`0f741b5a`. `embeddinggemma-300M-Q8_0.gguf` 333,590,944; QAT q8_0 328,577,056; QAT q4_0 277,852,192 | ~300M | 768 / 512, 256, 128 | 2,048 | MMTEB 61.15 | no | Supported (`gemma-embedding`) |
| Qwen/Qwen3-Embedding-0.6B @`97b0c614` | Apache-2.0 | **yes**: `Qwen/Qwen3-Embedding-0.6B-GGUF` @`370f27d7`. `Qwen3-Embedding-0.6B-Q8_0.gguf` **639,150,592** (sha256 `06507c7b…49c3e439`); f16 1,197,629,632; no smaller official quant | 0.6B | 1024 / any 32-1024 | 32K | MMTEB **64.33**, retrieval 64.64; 100+ languages | no | Mature (`qwen3`, last-token pooling, EOS required) |
| BAAI/bge-m3 @`5617a9f6` | MIT | yes: `ggml-org/bge-m3-Q8_0-GGUF`. `bge-m3-q8_0.gguf` 634,553,760 | 568M | 1024 / no | 8,192 | MMTEB 59.56, retrieval 54.60 (per the Qwen card) | no | Mature (XLM-R `bert`, CLS) |
| nomic-ai/nomic-embed-text-v2-moe @`1066b659` | Apache-2.0 | yes: `nomic-ai/nomic-embed-text-v2-moe-GGUF` @`ffbcf4c9`. Q8_0 512,225,120; **Q6_K 397,149,152**; Q5_K_M 370,828,256; Q4_K_M 344,120,288 | 475M (305M active, MoE) | 768 / down to 256 | **512** | MIRACL 65.80 (includes es); MMTEB not reported | no | Supported (`nomic-bert-moe`) |
| ibm-granite/granite-embedding-311m-multilingual-r2 @`44399559` (2026-04) | Apache-2.0, **but the card says the tokenizer is "subject to the Gemma Terms of Use"** | no (IBM: "convert yourself"); community only | 311M | 768 / 512, 384, 256, 128 | 32K | Multilingual retrieval (18) 65.2 | no | `modern-bert` supported; GGUF unofficial |
| ibm-granite/granite-embedding-278m-multilingual (r1) | Apache-2.0 | no (community bartowski Q8_0 303 MB) | 278M | 768 | 512 | **MIRACL-es 49.69** | no | Supported (XLM-R) |
| Snowflake/snowflake-arctic-embed-m-v2.0 / l-v2.0 | Apache-2.0 | no | 305M / 568M | 768 / 1024, MRL 256 | 8,192 | MIRACL 55.2 / 55.8 | no | m-v2.0: **GteModel arch not supported by the converter**; l-v2.0 is XLM-R (community GGUF) |
| intfloat/multilingual-e5-small / base / large-instruct | MIT | no (community only) | 118M / 278M / 560M | 384 / 768 / 1024, no MRL | 512 | large-instruct MMTEB 63.22 | no | Supported (XLM-R, mean) |
| microsoft/harrier-oss-v1-270m / 0.6b (2026-03) | MIT tag; the 270m uses a Gemma 3 backbone, so Gemma ToU flow-down is unclear | no (community) | 270M / 0.6B | 640 / 1024 | 32K | MMTEB 66.5 / 69.0 (self-reported) | no | Supported archs; GGUF unofficial |
| microsoft/bitnet-embedding-270m / 0.6b (2026-07) | MIT | official `*-i2_s.gguf` 367 / 428 MB | 270M / 0.6B | 640 / 1024 | 32K | MMTEB 66.26 / 67.49 (self-reported) | no | **I2_S is not in mainline ggml**; needs the microsoft/BitNet fork |
| jinaai v5 text nano / small / omni nano | **CC BY-NC 4.0** | per-task repos, e.g. text-nano-retrieval Q8_0 232,883,776 | 239M / 0.6B / 1.04B | 768 / MRL | — | MMTEB 65.5 (nano) | omni: yes | omni needs a fork |

### Image↔text options (permissive only)

| Option | License | Extra download | Spanish | Runtime | Evidence | Cost |
|---|---|---|---|---|---|---|
| **EmbeddingGemma 2 mmproj** (same space as the text model) | Apache-2.0 | `mmproj-embeddinggemma-2-Q8_0.gguf` 554,821,056 B. It holds both the vision and audio encoders; a vision-only split would be about 180 MB **(est.)**, and none is published | text side 100+ languages | same `llama-server --mmproj`; `/v1/embeddings` with `input: [{content: [{type: "image_url", …}]}]` | MIEB-lite 65.67, MMEB-v2 Image 57.28 | Lowest complexity: same server, and no re-embedding of text when added later. About 0.3-1 s per photo **(est.)**. **Open issue #30195** (closed as stale): some images produced 3.6k-13k tokens instead of about 280. Must be measured before committing |
| SigLIP2-base-patch16-224 (ONNX, `onnx-community/…-ONNX`) | Apache-2.0 | vision int8 94.6 MB + text int8 283.4 MB (≈378 MB) | **Measured**: Immich Spanish table (XTD-10/Crossmodal-3600), ViT-B-16-SigLIP2 **83.61 %** | onnxruntime, already bundled on desktop; not on Android Chaquopy | Used in production by Immich | Medium: a second vector space, our own preprocessing and tokenizer, and two models in memory. llama.cpp does not support CLIP/SigLIP dual encoders |
| Captions: Qwen3.5-0.8B (`ggml-org/Qwen3.5-0.8B-GGUF`, Q4_0 563.0 MB + mmproj Q8_0 115.9 MB), then embedded as text | Apache-2.0 | ≈679 MB | yes | llama-server (a second instance in chat mode) | — | High: 4-10 s per photo **(est.)**, hallucinated captions, two models. Conflicts with the "no automatic captions" non-goal |
| Rejected | | | | | | jina-clip-v2 (NC), MobileCLIP2 (Apple research-only), MetaCLIP 2 (NC), nomic-embed-multimodal-3b (Qwen research), nomic-embed-vision v1.5 (English-only text), OpenAI CLIP (deployed use is out of scope per its card), LFM2-VL (custom license with a US$10M revenue cap) |

## Licenses that need care

- **EmbeddingGemma 2** is Apache-2.0, which allows commercial use, modification and redistribution with the LICENSE text. The source repo has no NOTICE file and no LICENSE file; the card links `gemma.ai/resources/apache-2/`. Bento must ship the Apache-2.0 text with the downloaded or mirrored file. The card line "Deployments must adhere to the Gemma Prohibited Use Policy" is not part of the Apache text. Our reading is that it is a card-level expectation that Bento's use (private, local search) does not conflict with. That reading is not legal advice; owner decision D2.
- **Gemma Terms of Use** (EmbeddingGemma-300m; last modified 2026-04-01). §3.1 requires that redistribution pass the use restrictions on "as an enforceable provision", give recipients a copy of the terms, and ship a NOTICE file ("Gemma is provided under and subject to the Gemma Terms of Use…"). §3.2 incorporates the Prohibited Use Policy and says "Google reserves the right to restrict (remotely or otherwise) usage." Commercial use is allowed, but these terms would flow into Bento's terms. That is the reason to prefer EG2.
- **IBM Granite r2 311m**: Apache weights, but the card says the tokenizer is under the Gemma ToU. That is ambiguous; avoid it.

## Runtime: llama.cpp

- License MIT. Release archives also vendor cpp-httplib, nlohmann/json, miniaudio, stb and sheredom (MIT/public domain), and link BoringSSL (OpenSSL/ISC-style). Only `LICENSE-jsonhpp` ships separately, so Bento assembles the notices.
- Versioning: `releases/latest` is `v1.1.0` (2026-11-26) and carries only `nightly-tag.txt`. The binaries are on build tags; the newest is **b12777**. The minimum for EG2 is **b11454** (2026-10-06).
- b12777 CPU assets:
  - Windows: `llama-b12777-bin-win-cpu-x64.zip` 25.2 MB, `…-win-cpu-arm64.zip` 13.3 MB.
  - macOS: `…-macos-arm64.tar.gz` 16.8 MB, `…-macos-x64.tar.gz` 12.6 MB.
  - Linux: `…-ubuntu-x64.tar.gz` 23.4 MB, `…-ubuntu-arm64.tar.gz` 19.0 MB.
  - Android: `…-android-arm64.tar.gz` 82.9 MB (the full toolset, not just a library).
- Integrity: GitHub `sha256:` digests per asset and `actions/attest` build provenance (`gh attestation verify`). There is no SHA256SUMS file, no GPG signature and no Authenticode.
- **No macOS codesign or notarization**, so a downloaded binary would be blocked by Gatekeeper. Windows Defender has false-flagged the CPU zip before (issue #15874).
- CPU dispatch: Linux, Windows x64 and Android builds use `GGML_BACKEND_DL=ON GGML_NATIVE=OFF GGML_CPU_ALL_VARIANTS=ON`, so they pick a CPU backend at runtime and **AVX2 is not required**. The **macOS x64 build sets neither flag**, so it may need the CI runner's ISA (unverified). Windows arm64 uses `ALL_VARIANTS=OFF`.
- Server facts used by the plan (README at master):
  - `--embeddings`, `--pooling`, `--mmproj`, `--api-key-file`, `--no-webui`, `--offline`, and `--host` accepting a Unix `.sock` path.
  - The default port is 9931 (not 8080).
  - `/v1/embeddings` returns L2-normalized vectors and accepts string, string-array, and content-part inputs for multimodal.
  - No prompt prefixes are applied server-side; the client prepends them.
  - Non-causal models need `-ub` at least as large as the longest input.
  - The EG2 GGUF advertises 262,144 context, so `-c` must be set explicitly (2048-8192).
- Alternatives considered:
  - **llama-cpp-python** 0.3.38 (MIT): wheels for most targets, but **no macOS x86_64 or Android wheel**, and image embeddings would need low-level mtmd glue. Rejected.
  - **ONNX Runtime** (already bundled on desktop): `onnx-community/embeddinggemma-2-ONNX` has `model_quantized` 313.7 MB + `vision_encoder_quantized` 195.2 MB. In-process with no extra binary, but it needs tokenizer and image-preprocessing glue (the official examples are Transformers.js only), the last macOS x86_64 ORT wheel is 1.23.2, and Chaquopy has no onnxruntime. Kept as the plan-B runtime if shipping a signed llama-server proves impossible.

## Latency and RAM (est., 4-core x86 laptop, Q8_0, llama-server, `-np 1`; superseded by §Measured)

No published CPU benchmark exists for these models. The figures below come from FLOP counts (about 2 × non-embedding params per token, at an effective 100-300 GFLOPS).

| Model | 16-token query | 512-token chunk | Indexing | RSS |
|---|---|---|---|---|
| EmbeddingGemma 2 text (Q8_0) | ~10-30 ms | ~0.2-0.6 s | ~2-5 chunks/s | ~0.45-0.6 GB at `-c 2048` |
| EmbeddingGemma 2 + mmproj (image) | — | ~0.3-1 s per photo at about 280 image tokens | — | +~0.6 GB |
| Qwen3-Embedding-0.6B (Q8_0) | ~30-80 ms | ~0.7-2 s | ~1-3 chunks/s | ~0.8-1.1 GB |

The Stage 23 spike measured them; see §Measured below. Stage 24's opt-in `real_model` test records further numbers in `execution/evidence/`.

## Measured on a Ryzen 7 5800H laptop (Stage 23 spike, 2026-11-26)

This replaces the estimates above for this class of machine. The script and fixture are in `scripts/spikes/smart-search/` (`bench.py`, `dataset.py`), and the raw output is in `results-2026-11-26.json`.

**Setup**
- Machine: AMD Ryzen 7 5800H (8 cores / 16 threads, Zen 3), 16 GB RAM, NVMe, Linux 7.2 (Arch-based), Python 3.13.15.
- Runtime: the official release `llama-b12777-bin-ubuntu-x64.tar.gz`. Its sha256 `15b16eeb…5717730` matched the GitHub asset digest, and it reports `version: 1.1.0-dev (build 12777, commit caea914e9)`. The CPU backend is picked at runtime (`GGML_BACKEND_DL`).
- Models: downloaded from the pinned `resolve/<commit>` URLs. **Both SHA-256 values matched the pins above**: `2188ac1d…40b09135` (EG2 Q8_0) and `06507c7b…49c3e439` (Qwen3 Q8_0).
- Server: `llama-server --embeddings --pooling <mean|last> -c 2048 -ub 2048 -b 2048 -np 1 -t 4 -tb 4 --host 127.0.0.1 --api-key-file … --no-ui --offline`.
- Client: one client on the same host. Batches of 8 inputs per `/v1/embeddings` request, with the manifest prefixes.
- The machine was otherwise idle (load average under 2 before each run). The numbers are from one run; a first run differed by under 15 % except for throughput, which is explained below.

**Performance (4 threads)**

| | EmbeddingGemma 2 Q8_0 | Qwen3-Embedding-0.6B Q8_0 |
|---|---|---|
| Cold start to `/health` 200 (page cache evicted with `posix_fadvise`) | 0.96 s | 0.73 s |
| Warm start | 0.77 s | 0.40 s |
| First query after a cold start | 16 ms | 65 ms |
| RSS idle (anon + file-mapped weights) | 473 MiB (174 + 300) | 940 MiB (316 + 624) |
| RSS / peak after indexing 200 docs | 528 / 528 MiB | 975 / 975 MiB |
| Query latency p50 / p95 (126 single queries) | **20.8 / 24.2 ms** | 77.8 / 89.3 ms |
| Throughput, chunker windows ("512" estimated, 380 real tokens on average) | **1.74 chunks/s** (≈ 660 tokens/s) | 0.64 chunks/s (≈ 270 tokens/s) |
| ⇒ at a full 512 real tokens per chunk | ≈ 1.3 chunks/s | ≈ 0.5 chunks/s |
| Short docs (20-60 tokens) | 12.8 docs/s | 6.0 docs/s |

- The research estimate of 2-5 chunks/s for EG2 was optimistic. Real CPU cost is about 0.75 s per full 512-token chunk on 4 Zen 3 threads.
- A 16-chunk PDF takes about 12 s of background CPU, and a library of 10 k short items takes about 13 minutes. That fits the "poco a poco" UI promise.
- The first run used the old 4-characters-per-token chunker, so its windows were larger (621 real tokens on average) and its throughput was 0.93 chunks/s.

**Retrieval quality (200 docs, 42 queries)**

The fixture is 200 synthetic documents shaped like Bento content: invoices for several months as hard negatives, IDs, recipes, travel, payslips, health, home, bank, school, photo metadata text and English work documents. The 42 queries are labelled: 30 es, 7 en, 4 es→en, 1 en→es. Recall@5 is computed as `|relevant ∩ top5| / min(|relevant|, 5)`; MRR uses the full ranking.

| Model / dims | recall@5 | MRR | es (30) | en (7) | es→en (4) | en→es (1) |
|---|---|---|---|---|---|---|
| EmbeddingGemma 2 · 768 | **0.995** | **0.988** | 0.993 / 1.000 | 1.000 / 1.000 | 1.000 / 0.875 | 1.000 / 1.000 |
| EmbeddingGemma 2 · 512 (MRL) | 0.971 | 0.978 | 0.993 / 1.000 | 1.000 / 1.000 | 0.750 / 0.768 | 1.000 / 1.000 |
| EmbeddingGemma 2 · 256 (MRL) | 0.971 | 0.977 | 0.993 / 1.000 | 1.000 / 1.000 | 0.750 / 0.759 | 1.000 / 1.000 |
| Qwen3-Embedding-0.6B · 1024 | 0.948 | 0.885 | 0.960 / 0.892 | 1.000 / 0.905 | 0.750 / 0.775 | 1.000 / 1.000 |

(Per-language cells are recall@5 / MRR.)

- **768 → 512** changes exactly one query. q37, «informe trimestral de ingresos», whose target is the English Q3 report, goes from rank 2 to rank 14. Every monolingual query ranks the same.
- 256 ranks the same as 512 on this set.
- Qwen3 mostly loses MRR: it ranks the month-specific invoices and payslips below a bank statement for the same month (q01, q15, q31), and it misses «presupuesto para cambiarnos de casa» (q27).
- The fixture is small and near the ceiling for EG2, so it can confirm "no regression on Spanish". It cannot resolve differences under about 3 points. Cross-language is the weakest point for every model and has only 5 queries.
- Not tested: real OCR noise, long multi-chunk documents and image pixels. Stage 24's opt-in `real_model` test and Stage 26 cover those.

**Token estimator check** (real counts from `/tokenize`, BOS/EOS excluded)
- The first rule, 4 characters per token, under-counted Spanish: real tokens were up to 1.83× the estimate, because Gemma and Qwen split digits one per token.
- The new rule counts letters and spaces at 3 characters per token, and digits, CJK and punctuation as 1 token each. Estimate ÷ real is ≥ 1.03 for EG2 (median 1.24) and ≥ 0.93 for Qwen3 (median 1.13).
- A "512" window is at most 437 real EG2 tokens (459 Qwen3), well under `-ub 2048`.

**Facts confirmed at b12777**
- EG2 loads under the `gemma-embedding2` arch with mean pooling. No NaN appeared at Q8_0.
- The server adds BOS/EOS for EG2 (`[2, …, 1]`) and **appends EOS (151643) for Qwen3 itself**, so clients must not add `<|endoftext|>`.
- `--api-key-file` and `--offline` work. `--no-webui` is now a deprecated alias of `--no-ui`.
- `/tokenize` accepts `add_special`.

**Conclusions for the owner**
- **D1:** the numbers support EmbeddingGemma 2. On this machine it is better than the Qwen3 fallback on every axis: quality (+4.7 recall@5, +10 MRR points), query latency (3.7× faster), indexing (2.7× faster) and RAM (½). There is no reason to change the default.
- **D9:** 512 shows no clear loss. The only change is one of four es→en queries, a single-query effect on a small set. Keep 512, and extend the cross-language part of the Stage 24 `real_model` fixture (≥ 20 cross-language queries) before release. If that shows a consistent gap at 512, recommend 768, at +50 % index size.

## Recommendation

**Default: EmbeddingGemma 2, text GGUF `ggml-org/embeddinggemma-2-GGUF` @`6ea3e3a309d12a4779cfda98b8c19800d2d5da71`, `embeddinggemma-2-Q8_0.gguf`, 309,855,456 B, sha256 `2188ac1deca4b77dffefd603c2776a9d76d9d74ec01841392982ebb840b09135`.**
- It is the only candidate that meets every hard requirement: Apache-2.0, a GGUF from the llama.cpp maintainers converted from the current Google sha, mainline llama.cpp support, 310 MB, and a light CPU cost.
- It has 100+ languages with an 8K context, and Matryoshka down to 256 dims with about 1 MMTEB point lost.
- It is the only permissive, upstream-supported model whose optional mmproj adds **image search in the same vector space**. Turning on photo search later needs no re-embedding of documents.
- Use 768 dims by default; 512 is near-lossless if index size matters (D9). Queries use `task: search result | query: {q}`; documents use `title: {filename or none} | text: {chunk}`. Image inputs take no prefix. Pin llama.cpp **b12777** (≥ b11454). Do not use F16 weights (the card warns of NaN).
- Weaknesses: the llama.cpp support is about 7 weeks old; its MMTEB (61.36) is below Qwen3-0.6B (64.33); there is no Spanish-specific score.

**Fallback: Qwen3-Embedding-0.6B, `Qwen/Qwen3-Embedding-0.6B-GGUF` @`370f27d7550e0def9b39c1f16d3fbaa13aa67728`, `Qwen3-Embedding-0.6B-Q8_0.gguf`, 639,150,592 B, sha256 `06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439`.**
- It covers the risk that EG2's new llama.cpp path misbehaves on some CPU. It is Apache-2.0, published by Qwen itself, has had mature llama.cpp support since mid-2025, has the highest verified multilingual score here, and allows flexible dims.
- Cost: it is about 2× the size (it exceeds the ~500 MB guideline by 139 MB), about 3-4× slower per chunk, and text-only.
- If the 500 MB ceiling is hard, the in-budget alternative is `nomic-embed-text-v2-moe.Q6_K.gguf` (397,149,152 B, Apache-2.0, official). It is limited to 512-token context, has no MMTEB number, and is text-only.
- The manifest carries both default and fallback entries. Switching between them is a re-index into a new space, not a migration.

**Images:** ship v1 text-only (OCR + metadata through EG2 text). Offer "Buscar fotos por lo que muestran" as an opt-in add-on with the EG2 mmproj (+555 MB), after a spike measures issue #30195's token counts and the per-photo time. If the spike fails, the next path is SigLIP2-base on onnxruntime (desktop only, +378 MB, a separate space, best measured Spanish image retrieval). Captioning is not recommended.

## Could not verify

- Real CPU latency and RAM on ARM, macOS, Windows or low-end x86 (only one Zen 3 laptop was measured; §Measured).
- Published Spanish-specific retrieval scores for EG2, Qwen3-0.6B, nomic v2 or Granite r2. The only published Spanish numbers found were Granite r1 MIRACL-es and Immich's SigLIP/CLIP Spanish table. The spike's own small Spanish fixture (§Measured) is the only Bento-side evidence.
- The MTEB leaderboard Space itself; card numbers were used.
- Quality of the EG2 Q8_0 GGUF against full precision (Google reports only full-precision scores). The spike measured Q8_0 only.
- Whether the "Gemma Prohibited Use Policy" line on an Apache-2.0 card binds users. This needs counsel.
- Whether issue #30195 (image token blow-up) is still present at b12777.
- Whether a vision-only mmproj could be cut from the 555 MB vision+audio file, and whether llama-server keeps the audio half resident.
- The ISA baseline of the macOS x64 release build; the per-ABI size of an NDK llama `.so`; whether llama-server's request-level `dimensions` parameter honours MRL (the plan truncates client-side anyway).
- Jina v5 commercial pricing.

## Sources (checked 2026-11-26)

- HF model and tree API: `https://huggingface.co/api/models/{repo}` and `/tree/main` for every repo above.
- Cards:
  - https://huggingface.co/google/embeddinggemma-2
  - https://huggingface.co/ggml-org/embeddinggemma-2-GGUF
  - https://huggingface.co/google/embeddinggemma-300m
  - https://huggingface.co/Qwen/Qwen3-Embedding-0.6B
  - https://huggingface.co/BAAI/bge-m3
  - https://huggingface.co/nomic-ai/nomic-embed-text-v2-moe-GGUF
  - https://huggingface.co/ibm-granite/granite-embedding-311m-multilingual-r2
  - https://huggingface.co/Snowflake/snowflake-arctic-embed-m-v2.0
  - https://huggingface.co/intfloat/multilingual-e5-large-instruct
  - https://huggingface.co/microsoft/harrier-oss-v1-270m
  - https://huggingface.co/microsoft/bitnet-embedding-270m
  - https://huggingface.co/jinaai/jina-embeddings-v5-omni-nano
  - https://huggingface.co/jinaai/jina-embeddings-v5-text-nano
  - https://huggingface.co/google/siglip2-base-patch16-224
  - https://huggingface.co/onnx-community/embeddinggemma-2-ONNX
  - https://huggingface.co/ggml-org/Qwen3.5-0.8B-GGUF
- Licenses:
  - https://gemma.ai/resources/apache-2/
  - https://gemma.ai/resources/terms/
  - https://gemma.ai/resources/prohibited-use/
  - https://www.elastic.co/search-labs/blog/on-prem-ai-jina-embedding-models
- llama.cpp:
  - https://github.com/ggml-org/llama.cpp (`tools/server/README.md` at `0e4e925e`, `.github/workflows/release.yml`)
  - PRs #30054 and #29556, issues #30195, #30082, #15874 and #17635
  - releases `b11454` and `b12777`
- Immich CLIP/SigLIP multilingual table: https://github.com/immich-app/immich/blob/main/docs/docs/features/searching.md
