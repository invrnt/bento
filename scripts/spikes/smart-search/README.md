# Smart search spike (Stage 23)

A one-off measurement of the pinned embedding models on a real `llama-server`. Results are in `orchestration/research/embedding-models-2026.md` §Measured, and the raw numbers are in `results-2026-11-26.json`. This is not part of any test suite or local CI.

- `dataset.py`: 200 synthetic Bento-like documents and 42 labelled queries (es, en, es→en, en→es).
- `bench.py`: cold/warm start, RSS, query p50/p95, chunk throughput, token-estimator check, and recall@5/MRR per model and Matryoshka dims. It imports the pure chunker and truncation from `bento.domain.smart_search`.

Model files and the llama.cpp release stay outside the repo:

```sh
mkdir -p ~/.cache/bento-spike/{llama,models}
# llama.cpp official release (check the GitHub asset sha256 digest)
curl -L -o ~/.cache/bento-spike/llama/llama.tar.gz \
  https://github.com/ggml-org/llama.cpp/releases/download/b12777/llama-b12777-bin-ubuntu-x64.tar.gz
tar -C ~/.cache/bento-spike/llama -xzf ~/.cache/bento-spike/llama/llama.tar.gz
# Pinned models (verify against the manifest sha256)
curl -L -o ~/.cache/bento-spike/models/embeddinggemma-2-Q8_0.gguf \
  https://huggingface.co/ggml-org/embeddinggemma-2-GGUF/resolve/6ea3e3a309d12a4779cfda98b8c19800d2d5da71/embeddinggemma-2-Q8_0.gguf
curl -L -o ~/.cache/bento-spike/models/Qwen3-Embedding-0.6B-Q8_0.gguf \
  https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF/resolve/370f27d7550e0def9b39c1f16d3fbaa13aa67728/Qwen3-Embedding-0.6B-Q8_0.gguf
sha256sum ~/.cache/bento-spike/models/*.gguf

uv run --project apps/api python scripts/spikes/smart-search/bench.py \
  --server ~/.cache/bento-spike/llama/llama-b12777/llama-server \
  --models ~/.cache/bento-spike/models --out /tmp/bench.json
rm -rf ~/.cache/bento-spike   # about 1 GB
```

The servers bind to `127.0.0.1` on a random port with a per-run API key file. They are stopped at the end of each model's run.

The recorded run passed `--no-webui`, the deprecated alias. The script now passes `--no-ui`, which was checked to start the same way.
