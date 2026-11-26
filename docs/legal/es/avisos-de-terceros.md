# Avisos de terceros

English: [Third-party notices](../en/third-party-notices.md).

## Telegram

Bento usa la API de Telegram y no está afiliado a Telegram. Bento no es una app oficial de Telegram ni está respaldado por Telegram. Bento usa su propio identificador de aplicación de la API de Telegram y se rige por las [condiciones de la API de Telegram](https://core.telegram.org/api/terms).

Telegram es una marca de sus respectivos titulares. El nombre se usa solo para indicar con qué servicio funciona Bento.

Para usar la nube de Bento necesitas tu propia cuenta de Telegram, sujeta a las [condiciones de servicio](https://telegram.org/tos) y a la [política de privacidad](https://telegram.org/privacy) de Telegram.

## Otros servicios

- **Cloudflare** aloja el sitio web de Bento (Cloudflare Pages) y el relay de emparejamiento (Cloudflare Workers).
- **GitHub** publica las versiones de Bento y los metadatos que Bento consulta para buscar actualizaciones.

## Software de código abierto

Bento se construye con componentes de código abierto. Esta lista resume los principales; la lista completa de cada versión, con versiones exactas y licencias, está en el SBOM CycloneDX (`bento-*.cdx.json`) publicado junto a cada versión en GitHub. Los textos completos de las licencias acompañan a cada componente.

### Aplicación de escritorio

| Componente | Licencia |
|---|---|
| Electron | MIT |
| Chromium (incluido en Electron) | BSD-3-Clause y otras licencias de terceros listadas por Electron |
| Node.js (incluido en Electron) | MIT |
| PyInstaller (empaqueta los procesos locales) | GPL-2.0-or-later con excepción para el cargador, que permite distribuir aplicaciones empaquetadas |
| Python | PSF-2.0 |

### Procesos locales (API y tareas en segundo plano)

| Componente | Licencia |
|---|---|
| FastAPI | MIT |
| Starlette | BSD-3-Clause |
| Uvicorn | BSD-3-Clause |
| Pydantic, pydantic-settings | MIT |
| python-dotenv | BSD-3-Clause |
| python-multipart | Apache-2.0 |
| SQLAlchemy | MIT |
| Alembic | MIT |
| SQLite | Dominio público |
| Telethon | MIT |
| pyaes | MIT |
| rsa | Apache-2.0 |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| spake2 | MIT |
| segno | BSD-3-Clause |
| watchdog | Apache-2.0 |
| websockets | BSD-3-Clause |
| Pillow | MIT-CMU |
| pypdfium2 y PDFium | (Apache-2.0 OR BSD-3-Clause) y licencias de terceros de PDFium |
| RapidOCR | Apache-2.0 |
| ONNX Runtime | MIT |

### Interfaz

| Componente | Licencia |
|---|---|
| React, React DOM | MIT |
| Radix UI | MIT |
| Tailwind CSS | MIT |
| Lucide (íconos) | ISC |
| Geist y Geist Mono (tipografías) | SIL Open Font License 1.1 |

El sitio web incluye las tipografías Geist y Geist Mono (SIL Open Font License 1.1, con sus licencias en `apps/site/src/assets/fonts/`) y trazados de íconos de Lucide (ISC).

### Búsqueda inteligente

La búsqueda inteligente (búsqueda por significado) está apagada hasta que la activas. El modelo no viene en los instaladores: Bento lo descarga solo cuando activas la función, desde el repositorio de Hugging Face de quien lo publica, fijado a un commit, o, si no está disponible, desde una copia en las versiones de Bento en GitHub. Las dos copias deben coincidir con el mismo SHA-256, fijado en la app. Bento muestra la licencia del modelo en Ajustes › Búsqueda inteligente antes de la descarga («Ver licencia») y guarda una copia junto al archivo descargado.

| Componente | Qué es | Licencia |
|---|---|---|
| **EmbeddingGemma 2** (Google), archivo `embeddinggemma-2-Q8_0.gguf` convertido por ggml-org | Modelo de embeddings, descargado solo cuando activas la búsqueda inteligente | Apache-2.0 |
| `llama-server` de llama.cpp (ggml-org), etiqueta `b12777` | Servidor local de embeddings, compilado por Bento desde el código fuente e incluido en los instaladores | MIT |
| sqlite-vec (Alex Garcia) | Extensión de SQLite para el índice de vectores | Apache-2.0 OR MIT |

- **EmbeddingGemma 2**: fuente [`ggml-org/embeddinggemma-2-GGUF`](https://huggingface.co/ggml-org/embeddinggemma-2-GGUF/tree/6ea3e3a309d12a4779cfda98b8c19800d2d5da71) en el commit `6ea3e3a309d12a4779cfda98b8c19800d2d5da71` (convertido de `google/embeddinggemma-2`), 309.855.456 bytes, SHA-256 `2188ac1deca4b77dffefd603c2776a9d76d9d74ec01841392982ebb840b09135`. La ficha del modelo pide que su uso respete la [Política de uso prohibido de Gemma](https://ai.google.dev/gemma/prohibited_use_policy). El modelo alternativo, [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF/tree/370f27d7550e0def9b39c1f16d3fbaa13aa67728) (Qwen, Apache-2.0, SHA-256 `06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439`), se descarga de la misma forma solo si lo eliges.
- **llama.cpp**: compilado desde el [código de `b12777`](https://github.com/ggml-org/llama.cpp/tree/b12777) con los componentes que incorpora: cpp-httplib (MIT), nlohmann/json (MIT), xxHash (BSD-2-Clause), rotate-bits (MIT), sha1 y sha256 (dominio público), miniaudio (dominio público o MIT-0), stb_image (dominio público o MIT) y subprocess.h (Unlicense). Sus textos de licencia van en la carpeta `llama-server/licenses/` de la app.
- **sqlite-vec**: incluido en la app de escritorio y en la CLI.

ffmpeg no se incluye con Bento: si está instalado en tu sistema, Bento lo usa para generar miniaturas de vídeo y se rige por la licencia de esa instalación.
