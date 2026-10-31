# Primeros pasos

Bento guarda tus fotos y archivos en tu equipo y, si conectas tu cuenta de Telegram, una copia cifrada en tu propio Telegram. Así tienes tu biblioteca en todos tus equipos y una copia fuera de ellos.

## Antes de empezar

- Un ordenador con Windows (x64), macOS 13 o posterior (Apple silicon o Intel) o Ubuntu 22.04 (x64).
- Tu cuenta de Telegram y el móvil donde la usas, para escanear un código QR. Si prefieres no usar Telegram, puedes usar Bento solo en un equipo.
- Bento todavía no tiene app para móvil.

## Instalar Bento

- **Windows:** descarga el instalador (`.exe`) y ábrelo. Bento se instala para tu usuario y aparece en Inicio.
- **macOS:** descarga el `.dmg` de tu procesador (Apple silicon o Intel), arrastra Bento a Aplicaciones y ábrelo.
- **Linux:** instala el paquete `.deb` con tu gestor de software o con `sudo apt install ./bento_*.deb`. También hay una versión portátil (`.zip`).

Las descargas están en la [página de versiones](https://github.com/invrnt/bento/releases/latest). Para comprobar que el archivo es auténtico, sigue [Instalar Bento Desktop](../../desktop/install-first-run.md).

## Primer inicio

1. **Bienvenida.** Pulsa **Empezar**. Si ya usas Bento en otro equipo, elige **Ya uso Bento en otro dispositivo** y sigue [Añadir un dispositivo](anadir-dispositivo.md).
2. **Conecta tu Telegram.** Abre Telegram en tu móvil › Ajustes › Dispositivos › Vincular dispositivo de escritorio y escanea el QR. También puedes usar tu número de teléfono. Más detalles en [Conectar tu Telegram](conectar-telegram.md).
3. **Creando tu nube.** En unos segundos Bento crea tus canales privados y tus llaves, y te muestra «Conectado como» y tu nombre.
4. **Elige qué respaldar.** Activa las carpetas que quieras subir (Bento te sugiere Imágenes, Documentos y Escritorio) o añade otras con **Añadir carpeta…**. Pulsa **Continuar** y el respaldo empieza en segundo plano. Puedes elegir **Ahora no**. Más en [Respaldo automático](respaldo-automatico.md).
5. **Guarda tu kit de recuperación.** Es la llave de repuesto de tu nube. Guárdalo en PDF, imprímelo o cópialo, y confirma escribiendo su último grupo. Puedes pulsar **Más tarde**, pero Bento te lo recordará hasta que lo guardes. Más en [Kit de recuperación](kit-de-recuperacion.md).
6. **Listo.** Todo lo que guardes en Bento estará también en tu Telegram, cifrado.

### Usar Bento solo en este equipo

En la bienvenida, el enlace **Usar solo en este equipo** deja tu biblioteca únicamente en ese equipo: sin Telegram, sin nube, sin sincronización con otros dispositivos y sin kit de recuperación. Si cambias de idea, el tipo de almacenamiento está en Ajustes › Avanzado.

## Saber qué está haciendo Bento

- **Pie de la barra lateral:** tu foto de Telegram, el espacio que ocupa tu nube y una línea de estado, por ejemplo «Todo al día ✓», «Subiendo 12 archivos · 3 min», «Sin conexión — se reanudará solo» o «Telegram pidió esperar 4 min». Haz clic para abrir **Actividad**.
- **Actividad:** lo que se está subiendo o descargando, la cola, si está en pausa y los avisos que necesitan algo de ti, cada uno con un botón (**Reintentar**, **Abrir ajustes**, **Guardar kit**).
- **Icono en la bandeja del sistema o en la barra de menús:** el mismo estado y las opciones **Abrir Bento**, **Pausar respaldo** o **Reanudar respaldo** y **Salir**.

Bento solo te avisa con notificaciones cuando tienes que hacer algo.

## Bento sigue funcionando en segundo plano

Al cerrar la ventana, Bento sigue respaldando y sincronizando en segundo plano; la primera vez te lo avisa. Para cerrarlo del todo, usa **Salir** en el icono. Después del primer inicio, Bento se abre solo al iniciar sesión en el equipo. Puedes cambiar ambas cosas en Ajustes › General.

## Añadir archivos

- Arrastra archivos o carpetas a cualquier parte de la ventana, o pega desde el portapapeles.
- Desde tu sistema: **Enviar a › Bento** en Windows, o **Abrir con › Bento** en macOS y Linux.
- Desde el móvil: reenvíalos a la [Bandeja de Telegram](bandeja-de-telegram.md).
- O deja que el [respaldo automático](respaldo-automatico.md) suba tus carpetas.

## Buscar y ver

- <kbd>Ctrl</kbd> + <kbd>K</kbd> (<kbd>⌘</kbd> + <kbd>K</kbd> en macOS) abre la búsqueda: por nombre y, si está activado, por el texto que aparece en tus imágenes y PDF.
- El reconocimiento de texto se activa automáticamente en equipos con al menos 4 núcleos y 8 GB de RAM; en otros puedes activarlo en Ajustes › Búsqueda inteligente. La **búsqueda inteligente** (buscar por significado) es opcional: actívala en el mismo lugar y Bento descargará el modelo en segundo plano. Todo funciona en tu equipo.
- Pulsa <kbd>Espacio</kbd> sobre un archivo para verlo al momento: fotos, vídeos (con avance), PDF y texto.

## Siguientes pasos

- [Añadir otro equipo](anadir-dispositivo.md)
- [Privacidad y seguridad](privacidad-y-seguridad.md)
- [Preguntas frecuentes](preguntas-frecuentes.md)
