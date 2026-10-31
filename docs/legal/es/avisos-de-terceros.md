# Avisos de terceros

English: [Third-party notices](../en/third-party-notices.md).

> Borrador pendiente de revisión legal antes de publicarse. Consulta [el índice de documentos legales](../README.md).

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

El modelo de búsqueda inteligente se descarga solo si activas esa función. Licencia del modelo: [[COMPLETAR: verificar y citar la licencia del modelo de búsqueda inteligente]].

ffmpeg no se incluye con Bento: si está instalado en tu sistema, Bento lo usa para generar miniaturas de vídeo y se rige por la licencia de esa instalación.
