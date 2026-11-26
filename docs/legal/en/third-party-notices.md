# Third-party notices

Español: [Avisos de terceros](../es/avisos-de-terceros.md).

## Telegram

Bento uses the Telegram API and is not affiliated with Telegram. Bento is not an official Telegram app and is not endorsed by Telegram. Bento uses its own Telegram API application ID and follows the [Telegram API terms of service](https://core.telegram.org/api/terms).

Telegram is a trademark of its respective owners. The name is used only to say which service Bento works with.

To use Bento’s cloud you need your own Telegram account, subject to Telegram’s [terms of service](https://telegram.org/tos) and [privacy policy](https://telegram.org/privacy).

## Other services

- **Cloudflare** hosts Bento’s website (Cloudflare Pages) and the pairing relay (Cloudflare Workers).
- **GitHub** publishes Bento’s releases and the metadata Bento checks for updates.

## Open-source software

Bento is built with open-source components. This list summarizes the main ones; the complete list for each release, with exact versions and licenses, is in the CycloneDX SBOM (`bento-*.cdx.json`) published with every GitHub release. The full license texts ship with each component.

### Desktop app

| Component | License |
|---|---|
| Electron | MIT |
| Chromium (bundled with Electron) | BSD-3-Clause and other third-party licenses listed by Electron |
| Node.js (bundled with Electron) | MIT |
| PyInstaller (packages the local processes) | GPL-2.0-or-later with a bootloader exception that allows distributing packaged apps |
| Python | PSF-2.0 |

### Local processes (API and background tasks)

| Component | License |
|---|---|
| FastAPI | MIT |
| Starlette | BSD-3-Clause |
| Uvicorn | BSD-3-Clause |
| Pydantic, pydantic-settings | MIT |
| python-dotenv | BSD-3-Clause |
| python-multipart | Apache-2.0 |
| SQLAlchemy | MIT |
| Alembic | MIT |
| SQLite | Public domain |
| Telethon | MIT |
| pyaes | MIT |
| rsa | Apache-2.0 |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| spake2 | MIT |
| segno | BSD-3-Clause |
| watchdog | Apache-2.0 |
| websockets | BSD-3-Clause |
| Pillow | MIT-CMU |
| pypdfium2 and PDFium | (Apache-2.0 OR BSD-3-Clause) and PDFium third-party licenses |
| RapidOCR | Apache-2.0 |
| ONNX Runtime | MIT |

### Interface

| Component | License |
|---|---|
| React, React DOM | MIT |
| Radix UI | MIT |
| Tailwind CSS | MIT |
| Lucide (icons) | ISC |
| Geist and Geist Mono (typefaces) | SIL Open Font License 1.1 |

The website includes the Geist and Geist Mono typefaces (SIL Open Font License 1.1, licenses in `apps/site/src/assets/fonts/`) and Lucide icon paths (ISC).

### Smart search

Smart search (search by meaning) is off until you turn it on. The model is not included in the installers: Bento downloads it only when you turn the feature on, from the publisher's Hugging Face repository pinned to a commit or, if that is unavailable, from a copy on Bento's GitHub releases. Both copies must match the same SHA-256, pinned in the app. Bento shows the model's license in Settings › Smart search before the download and keeps a copy of it next to the downloaded file.

| Component | What it is | License |
|---|---|---|
| **EmbeddingGemma 2** (Google), file `embeddinggemma-2-Q8_0.gguf` converted by ggml-org | Embedding model, downloaded only when you turn smart search on | Apache-2.0 |
| llama.cpp `llama-server` (ggml-org), tag `b12777` | Local embedding server, built by Bento from source and included in the installers | MIT |
| sqlite-vec (Alex Garcia) | SQLite extension for the vector index | Apache-2.0 OR MIT |

- **EmbeddingGemma 2**: source [`ggml-org/embeddinggemma-2-GGUF`](https://huggingface.co/ggml-org/embeddinggemma-2-GGUF/tree/6ea3e3a309d12a4779cfda98b8c19800d2d5da71) at commit `6ea3e3a309d12a4779cfda98b8c19800d2d5da71` (converted from `google/embeddinggemma-2`), 309,855,456 bytes, SHA-256 `2188ac1deca4b77dffefd603c2776a9d76d9d74ec01841392982ebb840b09135`. The model card asks that deployments follow the [Gemma Prohibited Use Policy](https://ai.google.dev/gemma/prohibited_use_policy). The fallback model, [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF/tree/370f27d7550e0def9b39c1f16d3fbaa13aa67728) (Qwen, Apache-2.0, SHA-256 `06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439`), is downloaded the same way only if you choose it.
- **llama.cpp**: built from the [`b12777` source](https://github.com/ggml-org/llama.cpp/tree/b12777) with the components it compiles in: cpp-httplib (MIT), nlohmann/json (MIT), xxHash (BSD-2-Clause), rotate-bits (MIT), sha1 and sha256 (public domain), miniaudio (public domain or MIT-0), stb_image (public domain or MIT) and subprocess.h (Unlicense). Their license texts ship in the `llama-server/licenses/` folder of the app.
- **sqlite-vec**: bundled with the desktop app and the CLI.

ffmpeg is not bundled with Bento: if it is installed on your system, Bento uses it to create video thumbnails, under the license of that installation.
