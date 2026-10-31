# Release de escritorio

## Flujo de ramas y versiones

Bento usa GitHub Flow: `main` es la única rama permanente; cada cambio nace en una rama corta `feature/<tema>` o `fix/<tema>`, pasa por pull request y se integra solo con los checks requeridos en verde. No existen ramas `beta`/`stable` ni canales de prerelease. Los releases usan SemVer estable `MAJOR.MINOR.PATCH` y tags inmutables `vMAJOR.MINOR.PATCH`:

- `patch`: corrección compatible o hardening sin cambio funcional incompatible.
- `minor`: funcionalidad compatible nueva.
- `major`: contrato o migración incompatible que requiera intervención explícita.

Mientras Bento permanezca en `0.y.z`, un cambio incompatible puede avanzar `minor`, pero debe documentar migración y recuperación. Se favorecen releases pequeños y frecuentes; nunca se reutiliza ni mueve un tag publicado.

Desde Actions, ejecuta **Desktop version bump PR** sobre `main` y elige `patch`, `minor` o `major`. El workflow sincroniza la versión del host Electron y del sidecar Python, abre `release/vX.Y.Z` y despacha la validación nativa requerida sobre ese commit. El dispatch es explícito porque GitHub no vuelve a disparar workflows a partir de un pull request creado con `GITHUB_TOKEN`; la concurrencia por rama evita trabajo duplicado en reintentos. Un reintento reutiliza la rama solo si contiene exactamente los archivos de versión esperados con metadata idéntica y reutiliza su PR abierto. Si la rama difiere o contiene archivos adicionales, falla sin forzar ni sobrescribir historia.

Después de que el PR pase revisión, la matriz nativa y se integre en `main`:

```sh
git fetch origin main
git tag -s vX.Y.Z origin/main -m "Bento vX.Y.Z"
git push origin vX.Y.Z
```

La firma GPG del tag proporciona trazabilidad humana; no sustituye la firma de código. El pipeline verifica además que el tag coincida exactamente con `package.json#version` y que su commit pertenezca a `origin/main`. Cada workflow serializa sus propias ejecuciones para impedir bumps duplicados o dos publicaciones de producción simultáneas.

## Matriz soportada

Los sidecars PyInstaller se construyen en su sistema nativo; no se cruzan arquitecturas.

| Destino | Runner | Makers publicados |
| --- | --- | --- |
| Windows x64 | `windows-2025` | Squirrel `Setup.exe`, `.nupkg`, `RELEASES` |
| macOS 13+ x64 | `macos-15-intel` | `.dmg`, `.zip` |
| macOS 13+ arm64 | `macos-15` | `.dmg`, `.zip` |
| Ubuntu 22.04 x64 | `ubuntu-22.04` | `.deb`, `.zip` |

Cada fila usa Node 24 y Python 3.12, instala dependencias bloqueadas, ejecuta tests backend/web/desktop, construye el renderer y sidecar, ejecuta Forge `make`, abre dos veces el paquete nativo y verifica makers, ausencia de `.env` y URLs de desarrollo. Después lleva makers y SBOM a un staging plano, rechaza nombres colisionados y genera `SHA256SUMS` con los basenames finales descargables. El job de publicación vuelve a aplanar las cuatro matrices y rechaza también colisiones globales antes de crear el GitHub Release.

`desktop-native.yml` corre en PR/main sin secretos y publica artefactos marcados `unsigned` durante 14 días. No representan soporte de distribución ni deben renombrarse como release.

## Release firmado

Un tag `v*` activa `desktop-release.yml`. Antes de instalar o construir, el gate exige que el tag sea exactamente `v` seguido de `apps/desktop/package.json#version`; por ejemplo, la versión `0.1.0` solo admite `v0.1.0`. También resuelve el commit real de un tag anotado y exige que sea ancestro de `origin/main`. El gate bloquea el release completo si falta cualquier credencial obligatoria; no existe fallback silencioso a artefactos de producción sin firma.

Secrets requeridos:

- `APPLE_CERTIFICATE_BASE64`: PKCS#12 Developer ID Application en base64.
- `APPLE_CERTIFICATE_PASSWORD`.
- `APPLE_SIGNING_IDENTITY`.
- `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_TEAM_ID` para `notarytool`.
- `WINDOWS_CERTIFICATE_BASE64`: PFX de firma de código en base64.
- `WINDOWS_CERTIFICATE_PASSWORD`.

Los certificados se decodifican únicamente en el directorio temporal efímero del runner, nunca se suben como artefacto. macOS verifica `codesign`, Gatekeeper y el ticket grapado; Windows exige estado Authenticode `Valid`. La publicación recibe permisos de escritura solo después de que todas las filas terminen, adjunta procedencia de GitHub y crea primero un draft desde el tag ya existente. Los reintentos reutilizan únicamente ese draft, vuelven a subir los assets y comparan inventario y SHA-256 remoto antes de publicarlo; un release ya publicado solo se acepta si coincide exactamente y nunca se muta silenciosamente.

Actualmente no hay certificados ni cuentas de desarrollador en el repositorio. Hasta configurarlos como GitHub Actions secrets, los tags de producción quedan intencionalmente bloqueados. No se debe afirmar que un build local/PR está firmado o notarizado.

### Configuración de compilación de Bento

Además de la firma, cada build empaquetado lleva la configuración que conecta Bento con Telegram, el relay y el sitio. El empaquetado la escribe en `resources/build-config.json` a partir del entorno y omite los valores ausentes; nunca se imprime en los logs.

| Nombre | Tipo en GitHub Actions | Sin él |
| --- | --- | --- |
| `BENTO_TELEGRAM_API_ID` | secret | El inicio de sesión de Telegram devuelve `telegram_not_available`. |
| `BENTO_TELEGRAM_API_HASH` | secret | Igual que el anterior. |
| `BENTO_RELAY_URL` | variable | El emparejamiento usa el canal Sync de Telegram. |
| `BENTO_PUBLIC_SITE_URL` | variable | El diálogo de emparejamiento no ofrece enlace web. |

Cómo obtener cada valor: [credenciales de Telegram](../dev/telegram-credentials.md), [relay](../dev/relay.md) y [sitio público](../dev/site.md). Un release de producción debe llevar los cuatro.

### Después de publicar

1. Comprueba en la página del release que están los instaladores, los `SHA256SUMS-*` y los manifiestos del updater.
2. Si quieres que los botones del sitio descarguen directamente los archivos de esta versión, copia sus nombres en `apps/site/site.config.json` y vuelve a desplegar el sitio ([instrucciones](../dev/site.md#download-links)). Sin ese paso, los botones abren la página del último release, que siempre funciona.

## Manifiestos del updater controlado

Solo después de que las cuatro matrices firmen, prueben y reúnan sus assets, el release publica un manifiesto por destino:

- `bento-update-win32-x64.json`
- `bento-update-darwin-x64.json`
- `bento-update-darwin-arm64.json`
- `bento-update-linux-x64.json`

El renderer nunca descarga binarios. El proceso principal consulta únicamente este metadata, valida `schemaVersion`, SemVer estable, plataforma/arquitectura y HTTPS; cualquier esquema, destino o host inesperado falla cerrado. Cada asset declara `kind`, `filename`, URL exacta del GitHub Release, SHA-256 y tamaño. Windows incluye además el SHA-1/tamaño del `.nupkg` y un contenido `RELEASES` con URL absoluta para que, tras descargar y verificar todo, el runtime pueda servir el feed Squirrel desde loopback. La comprobación remota no instala nada: la descarga, verificación, confirmación del usuario y feed local pertenecen al runtime controlado.

`publishedAt` usa el timestamp del commit etiquetado para que el manifiesto sea determinista antes de crear el GitHub Release. `commit` enlaza el metadata con el SHA completo validado en `main`. El propio manifiesto queda incluido en el `SHA256SUMS-<destino>` y en la atestación de procedencia. Nunca se publica un manifiesto apuntando a un archivo ausente: la publicación ocurre en un único job después de reunir las cuatro matrices.

No hay actualización silenciosa ni downgrade automático. Una descarga terminada persiste con metadata privada, sobrevive al relanzamiento y vuelve a validar ruta, destino, tamaño y hashes antes de ofrecer instalación; el staging conserva solo ese candidato válido y purga parciales/versiones antiguas. Los requests y streams inactivos abortan con un error reintentable. macOS requiere aplicación firmada para `autoUpdater`; Windows requiere la cadena Squirrel firmada. Si la firma, el hash, el tamaño, el feed local o la instalación fallan, Bento conserva la versión y datos actuales, recupera los sidecars y muestra recuperación manual. Linux entrega instalador/archivo verificado, sin prometer reemplazo transaccional por el updater.

## Ejecución local

En el sistema destino:

```sh
make desktop-release-artifacts
```

Esto crea `dist/desktop/make`, ejecuta el smoke, genera `bento-sbom.cdx.json` y `SHA256SUMS`. Sin las variables `BENTO_MAC_SIGNING=1` o `BENTO_WINDOWS_SIGNING=1`, el resultado es explícitamente un build de prueba sin firma.

Para validar únicamente tooling de versión/manifiestos:

```sh
npm --prefix apps/desktop test -- tests/release-scripts.test.ts tests/packaging.test.ts
```

## Versiones y fuentes consultadas

- Electron `43.4.1`, Electron Forge `7.11.2`, PyInstaller `6.22.2`, uv `0.12.5`.
- ONNX Runtime `1.23.2` on macOS Intel (the final release with an x64 wheel) and the current locked release on other targets.
- Documentación oficial de Electron sobre distribución, firma, notarización y updates.
- Documentación oficial de Electron Forge de Packager/makers y firma.
- Documentación oficial de GitHub Actions sobre runners nativos, permisos mínimos, SHA completos y attestations.
- SemVer 2.0.0 para `MAJOR.MINOR.PATCH` estable.
