# Verificar tus descargas

Antes de instalar Bento puedes comprobar dos cosas: que el archivo que descargaste es exactamente el que
publicamos, y que la lista de archivos la firmamos nosotros. Toma un par de minutos y no necesitas instalar
nada: las herramientas vienen con Windows 10 y 11, macOS y Linux.

English: [Verify your downloads](../en/verify-downloads.md).

## Qué hay en cada versión

En la [página de versiones](https://github.com/invrnt/bento/releases), cada versión trae, además de los
instaladores:

- `SHA256SUMS`: la huella SHA-256 de cada archivo de esa versión.
- `SHA256SUMS.sig`: la firma de esa lista, hecha con la clave de versiones de Bento.

La clave pública para comprobar la firma no está en la versión, sino en el repositorio de Bento:
[`allowed_signers`](https://github.com/invrnt/bento/blob/main/scripts/release/allowed_signers). Así, si alguien
cambiara los archivos de una versión, no podría cambiar también la clave.

Las versiones para Android están aparte (empiezan por `android-v`) y tienen su propio `SHA256SUMS`.

## 1. Descarga los archivos

En una misma carpeta (por ejemplo, Descargas), guarda:

1. el instalador que quieras, por ejemplo `Bento-0.1.0-Setup.exe`, `Bento-0.1.0-arm64.dmg` o
   `bento_0.1.0_amd64.deb`;
2. `SHA256SUMS` y `SHA256SUMS.sig` de la misma versión;
3. el archivo de la clave: abre
   [este enlace](https://raw.githubusercontent.com/invrnt/bento/main/scripts/release/allowed_signers) y guárdalo
   como `allowed_signers` (sin extensión).

## 2. Comprueba la firma

Abre una terminal en esa carpeta (en Windows, PowerShell; en macOS, Terminal) y ejecuta:

**macOS y Linux**

```sh
ssh-keygen -Y verify -f allowed_signers -I bento-release -n bento-release -s SHA256SUMS.sig < SHA256SUMS
```

**Windows (PowerShell)**

```powershell
cmd /c "ssh-keygen -Y verify -f allowed_signers -I bento-release -n bento-release -s SHA256SUMS.sig < SHA256SUMS"
```

Debe decir `Good "bento-release" signature`. Si dice otra cosa, o un error, **no instales** y avísanos.

## 3. Comprueba tu archivo

**Linux**

```sh
sha256sum --check --ignore-missing SHA256SUMS
```

**macOS**

```sh
shasum -a 256 --check --ignore-missing SHA256SUMS
```

Cada archivo que descargaste debe aparecer con `OK`.

**Windows (PowerShell)**

```powershell
(Get-FileHash .\Bento-0.1.0-Setup.exe -Algorithm SHA256).Hash.ToLower()
Select-String -Path SHA256SUMS -Pattern "Bento-0.1.0-Setup.exe"
```

Las dos líneas deben mostrar la misma huella de 64 caracteres.

## La firma del sistema

Además, cada instalador lleva la firma de su plataforma:

- **Windows:** en Propiedades › Firmas digitales del instalador aparece un editor válido.
- **macOS:** Bento está firmado y notarizado por Apple; se abre sin avisos de «desarrollador no identificado».
- **Android:** el APK está firmado; la huella de su certificado es la que publica el sitio de Bento en
  `/.well-known/assetlinks.json`. Bento solo se actualiza desde dentro de la app si la nueva versión está
  firmada con el mismo certificado.

Las actualizaciones automáticas de Bento hacen estas comprobaciones por ti: verifican una firma propia antes
de descargar nada.

## Si algo no coincide

No instales el archivo. Bórralo, descárgalo de nuevo solo desde
[github.com/invrnt/bento/releases](https://github.com/invrnt/bento/releases) y repite los pasos. Si sigue sin
coincidir, puede tratarse de un problema de seguridad: repórtalo de forma privada como se explica en la
[política de seguridad](https://github.com/invrnt/bento/blob/main/SECURITY.md).
