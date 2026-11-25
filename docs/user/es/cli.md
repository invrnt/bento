# Bento en la terminal

`bento` es Bento sin ventanas: un programa que se usa escribiendo órdenes en la terminal. Sirve para dos cosas:

- **Que un asistente de inteligencia artificial ordene tus archivos por ti.** Asistentes como Claude Code o Codex saben usar la terminal. Les dices «pon estas 40 fotos y estos 3 PDF donde correspondan en mi Bento» y lo hacen con `bento`.
- **Tener Bento en un equipo sin pantalla**, como un servidor con Debian o Ubuntu o una Raspberry Pi, que recibe y guarda archivos todo el día.

Es la misma biblioteca que ves en la app: lo que cambies con `bento` llega a todos tus dispositivos en pocos segundos, porque tu nube vive en tu Telegram.

English: [Bento in the terminal](../en/cli.md).

## Instalar

No necesitas instalar Python ni nada más: el programa trae todo lo que necesita.

**Linux y macOS.** Abre la terminal y pega:

```sh
curl -fsSL https://raw.githubusercontent.com/invrnt/bento/main/scripts/install/install.sh | sh
```

Se instala solo para tu usuario (en `~/.local/share/bento-cli`) y no pide contraseña de administrador. Antes de instalar, comprueba que la descarga es la auténtica (su huella SHA-256); si no coincide, no instala nada. Si al final te dice que añadas `~/.local/bin` a tu `PATH`, copia la línea que te muestra y abre otra terminal.

**Debian, Ubuntu y Raspberry Pi OS (paquete `.deb`).** Si prefieres un paquete del sistema, descarga `bento-cli_<versión>_amd64.deb` (o `_arm64.deb` para Raspberry Pi y otros equipos ARM) de la [página de versiones](https://github.com/invrnt/bento/releases) e instálalo:

```sh
sudo apt install ./bento-cli_0.1.0_amd64.deb
```

**Windows.** Abre PowerShell y pega:

```powershell
irm https://raw.githubusercontent.com/invrnt/bento/main/scripts/install/install.ps1 | iex
```

Cierra PowerShell y ábrelo de nuevo para que encuentre `bento`.

Para comprobar que funciona:

```sh
bento --version
```

## Empezar: `bento setup`

Es lo único que tienes que hacer. Escribe:

```sh
bento setup
```

y sigue lo que te pide. Puedes cortarlo cuando quieras y volver a escribirlo: sigue donde lo dejaste.

1. **Conecta tu Telegram.** Aparece un código QR dibujado en la terminal. En tu móvil abre Telegram › **Ajustes** › **Dispositivos** › **Vincular dispositivo de escritorio** y escanéalo. Si tu cuenta tiene verificación en dos pasos, te pide tu contraseña de Telegram. ¿No puedes escanear? Usa tu número: `bento setup --phone +34600000000`.
2. **Si es la primera vez que usas Bento**, crea tu nube y te muestra tu [kit de recuperación](kit-de-recuperacion.md) **una sola vez**. Apúntalo y guárdalo bien: con tu Telegram y ese código recuperas todo aunque pierdas tus equipos.
3. **Si ya usas Bento en otro equipo**, te ofrece unir este equipo a tu nube con un código (mira la sección siguiente).

Cuando termina, `bento status` te dice en una pantalla si todo está bien.

> Si la app de Bento está abierta en este mismo equipo, `bento` la usa directamente: es la misma biblioteca y no hace falta `bento setup`. Si no hay app abierta, `bento` arranca su propio Bento en segundo plano la primera vez que lo necesita.

## Unir este equipo a tu Bento: `bento join`

Si ya tienes Bento en otro equipo, puedes añadir este con un código, igual que cuando [añades un dispositivo](anadir-dispositivo.md):

1. **En el equipo que ya usa Bento**, ve a Ajustes › Dispositivos › **Añadir dispositivo**. Verás un código como `K7Q2-MXR9-T4WA`.
2. **En este equipo**, escribe el código:

   ```sh
   bento join K7Q2-MXR9-T4WA
   ```

   También vale pegar el enlace completo en lugar del código.
3. La terminal muestra **cuatro emojis** y «Confirma en tu otro dispositivo».
4. **En el otro equipo** aparece la pregunta de si quieres añadir este equipo, con cuatro emojis. Comprueba que son **los mismos y en el mismo orden** y pulsa **Añadir**. Si no coinciden, pulsa **No soy yo**.

La terminal te va contando cómo se descarga tu biblioteca. El código caduca a los 10 minutos y sirve una sola vez.

¿No tienes el otro equipo a mano? Escribe `bento setup` y, cuando te pregunte cómo unir este equipo, elige tu [kit de recuperación](kit-de-recuperacion.md).

También puedes hacerlo al revés, desde la terminal hacia otro equipo: `bento pair` crea un código (con su QR) para que otro dispositivo se una.

## Órdenes del día a día

Las carpetas de Bento se escriben con barras, empezando por la raíz: `/Documentos/Facturas/2024`.

| Quiero… | Escribo |
|---|---|
| Ver qué hay en una carpeta | `bento ls /Documentos` |
| Ver el árbol de carpetas | `bento tree` |
| Crear una carpeta (y las que falten por el camino) | `bento mkdir -p /Documentos/Facturas/2024` |
| Subir archivos o una carpeta entera | `bento upload ~/Descargas/fotos --to /Fotos/Viaje` |
| Mover algo | `bento mv /factura.pdf /Documentos/Facturas` |
| Cambiar un nombre | `bento rename /Fotos/IMG_001.jpg playa.jpg` |
| Buscar (también por el texto de fotos y PDF) | `bento find "contrato alquiler"` |
| Descargar | `bento download /Documentos/Facturas -r --to ~/Facturas` |
| Mandar algo a la papelera | `bento rm /borrador.pdf` |
| Recuperarlo de la papelera | `bento trash` y luego `bento trash restore …` |
| Ver si está todo subido | `bento status` o `bento activity` |
| Ver tus equipos | `bento devices` |
| Ayuda de cualquier orden | `bento --help`, `bento upload --help` |

Bueno saber:

- **Subir dos veces lo mismo no duplica nada.** Bento reconoce los archivos que ya tienes y los salta. Si una subida se corta, vuelve a lanzarla y solo sube lo que falta.
- **Borrar no es definitivo.** `bento rm` manda a la [papelera](papelera-y-espacio.md), y de ahí se recupera durante 30 días.
- Los archivos se cifran en tu equipo antes de ir a tu Telegram; la subida a Telegram sigue en segundo plano después de que la orden termine.
- Los mensajes salen en español. Para verlos en inglés: `bento --lang en …`.

## Pedirle a un asistente de IA que ordene tus archivos

Abre tu asistente (Claude Code, Codex u otro que pueda usar la terminal) en el equipo donde instalaste `bento` y pídeselo con tus palabras. Por ejemplo:

> Tengo fotos y PDF sueltos en `~/Descargas`. Usa la orden `bento` (primero lee `bento guide`) para subirlos a mi Bento y ponerlos en las carpetas que correspondan. Usa las carpetas que ya tengo antes de crear otras nuevas. No borres nada definitivamente y, al terminar, dime qué pusiste en cada sitio.

Qué hará el asistente:

1. Leer `bento guide`, una guía pensada para asistentes que explica cómo usar Bento con cuidado.
2. Mirar cómo tienes organizada tu biblioteca (`bento tree`).
3. Crear solo las carpetas que falten, con nombres parecidos a los que ya usas.
4. Subir los archivos a su sitio y comprobar el resultado.
5. Contarte qué ha hecho.

Para tu tranquilidad:

- El asistente trabaja con **tu** Bento, en **tu** equipo. Bento no envía tus archivos a ningún servicio de IA; lo que el asistente lea depende del asistente que uses y de lo que le dejes ver.
- Lo que el asistente mande a la papelera lo puedes recuperar. Las órdenes que borran para siempre (vaciar la papelera, quitar un dispositivo) piden confirmación expresa.
- Si quieres revisar antes de que suba nada, pídele que haga primero una prueba: `bento upload … --dry-run` muestra lo que haría sin subir nada.

## Dejarlo funcionando en un servidor

En un servidor quieres que Bento siga en marcha aunque cierres la sesión.

**Linux (systemd):**

```sh
bento daemon install-service
```

Te muestra las dos órdenes que faltan para activarlo; normalmente son:

```sh
systemctl --user enable --now bento.service
sudo loginctl enable-linger "$USER"   # para que siga en marcha sin sesión abierta
```

**macOS:** `bento daemon install-service` lo deja arrancando solo cuando inicias sesión.

**Windows:** no hace falta nada; `bento` arranca Bento cuando lo necesita.

Para pararlo o arrancarlo a mano: `bento daemon stop` y `bento daemon start`. `bento daemon status` dice si está en marcha.

> En un equipo sin pantalla, la llave que protege tu sesión de Telegram en ese equipo se guarda en un archivo de tu carpeta de usuario que solo tú puedes leer. Protege ese equipo como protegerías tu móvil: quien entre con tu usuario puede usar tu Bento. Si lo pierdes o lo vendes, [quítalo desde otro dispositivo](anadir-dispositivo.md#quitar-un-dispositivo).

## Si algo no va

- `bento status`: resumen de una pantalla y, si falta algo, qué orden escribir.
- `bento doctor`: revisa la conexión con Telegram, el espacio en disco y la versión.
- `bento daemon logs`: lo que ha ido pasando en segundo plano.
- Más ayuda en [Solución de problemas](solucion-de-problemas.md).

## Desinstalar

- Linux y macOS (instalado con el script): `bento daemon stop` y borra `~/.local/share/bento-cli/app` y `~/.local/bin/bento`.
- Paquete `.deb`: `sudo apt remove bento-cli`.
- Windows: `bento daemon stop` y borra la carpeta `app` de `%LOCALAPPDATA%\Bento CLI`.

Así quitas solo el programa. Tu biblioteca de este equipo sigue en la carpeta de datos de `bento` (`~/.local/share/bento-cli/profiles` en Linux; `~/Library/Application Support/Bento CLI` en macOS; `%LOCALAPPDATA%\Bento CLI` en Windows). Antes de borrarla, quita este equipo desde otro dispositivo para que deje de tener acceso a tu nube.
