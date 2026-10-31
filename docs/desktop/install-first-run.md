# Instalar Bento Desktop y completar el primer inicio

Bento Desktop incluye la interfaz, la API y el worker. No requiere Docker, Python, Node ni un archivo `.env`. Puedes usarlo con tu cuenta de Telegram (nube cifrada y varios dispositivos) o solo en este equipo.

Guía para usuarios, paso a paso: [Primeros pasos](../user/es/primeros-pasos.md) · English: [Getting started](../user/en/getting-started.md).

## Antes de instalar

Descarga únicamente un release de producción y el archivo `SHA256SUMS-<plataforma>`. Cada línea usa el nombre final plano del archivo descargado, por lo que puede verificarse desde una sola carpeta sin reconstruir rutas internas de CI. Los artefactos de validación que incluyen `unsigned` en el nombre no están destinados a usuarios finales.

Comprueba el hash desde la carpeta de descargas:

```sh
# macOS o Linux
grep '  <nombre-exacto-del-instalador>$' SHA256SUMS-<plataforma> | shasum -a 256 -c -
```

Si descargas todos los archivos listados para ese destino, también puedes ejecutar `shasum -a 256 -c SHA256SUMS-<plataforma>` y exigir que cada línea sea `OK`.

En Windows usa PowerShell y compara el resultado con la línea del instalador:

```powershell
Get-FileHash '.\Bento-<version> Setup.exe' -Algorithm SHA256
```

## Windows x64

Ejecuta el `Setup.exe` de Squirrel. Windows debe mostrar un editor válido en la firma digital. Bento se instala por usuario, puede abrirse desde Inicio y añade **Bento** al menú **Enviar a** del Explorador. Desinstalar la aplicación elimina sus binarios, pero no borra automáticamente el directorio de datos.

## macOS 13+ Intel y Apple silicon

Elige el `.dmg` que coincida con el procesador, arrastra Bento a Aplicaciones y ábrelo. El release de producción debe superar Gatekeeper sin instrucciones para eludirlo: se firma con Developer ID y se notariza. No instales un DMG de otra arquitectura bajo la expectativa de soporte nativo.

## Ubuntu 22.04 x64

Instala el `.deb` con el gestor gráfico o con:

```sh
sudo apt install ./bento_*.deb
```

El `.zip` es una distribución portátil sin integración de instalación (sin enlaces `bento://` ni «Abrir con»). En otros Linux puede funcionar, pero solo Ubuntu 22.04 x64 se declara soportado cuando el smoke nativo está verde.

Bento protege la llave de cada equipo con el almacén seguro del escritorio (Secret Service/libsecret en GNOME o KWallet). Si no hay ninguno disponible o está bloqueado, Bento sigue funcionando: guarda esa llave en un archivo con permisos `0600` dentro de su carpeta de datos y te lo avisa. Para la mejor protección, configura o desbloquea el keyring antes del primer inicio y protege tu sesión con contraseña.

## Primer inicio

1. **Bienvenida:** **Empezar**, **Ya uso Bento en otro dispositivo** o el enlace **Usar solo en este equipo** (sin Telegram ni sincronización).
2. **Conecta tu Telegram:** QR desde Telegram en el móvil (Ajustes › Dispositivos › Vincular dispositivo de escritorio) o número de teléfono. Bento usa su propia identidad de aplicación de Telegram; no hay que crear bots, canales ni claves.
3. **Creando tu nube:** Bento crea sus canales privados y las llaves en unos segundos.
4. **Elige qué respaldar:** carpetas sugeridas y **Añadir carpeta…**; el respaldo corre en segundo plano.
5. **Guarda tu kit de recuperación:** PDF, impresión o copia; se confirma escribiendo el último grupo.
6. **Listo.**

Bento migra la base local, inicia API y worker en puertos efímeros de loopback y abre la interfaz solo cuando están listos. El reconocimiento de texto se activa automáticamente en equipos con al menos 4 núcleos y 8 GB de RAM; la búsqueda inteligente es opcional en Ajustes. La ubicación de datos ya no forma parte del primer inicio: está en Ajustes › Avanzado.

## Segundo plano, inicio de sesión y enlaces

- Cerrar la ventana deja Bento funcionando en la bandeja del sistema o la barra de menús (la primera vez muestra un aviso). **Salir** en el icono detiene primero los procesos locales y luego cierra la aplicación.
- Después del primer inicio, Bento se abre al iniciar sesión en el equipo. Ambas preferencias están en Ajustes › General.
- Una segunda apertura enfoca la ventana existente; los archivos que se le pasan (Enviar a, Abrir con) se suben a Bento.
- Bento registra el esquema `bento://`. Los enlaces `bento://join?v=1&c=<código>` abren directamente la pantalla para añadir este equipo.

Las elecciones se conservan al actualizar o reinstalar porque viven en el directorio de datos/usuario, no dentro del paquete ejecutable.

## Migrar un `.env` existente

En **Ajustes → Avanzado → Importar `.env`**, selecciona el archivo, revisa valores reconocidos, desconocidos o bloqueados y confirma una sola vez. Los secretos aparecen únicamente como presentes/ausentes; nunca se muestran en la vista previa. Los valores del antiguo modo bot de Telegram (`TELEGRAM_BOT_TOKEN`, IDs de canales, secreto de webhook, `BENTO_ENCRYPTION_KEY`) ya no se usan. Tras importar correctamente, Bento deja de releer el archivo. Conserva el original fuera de carpetas sincronizadas hasta verificar la migración y luego elimínalo de forma segura si ya no lo necesitas.

Los despliegues Docker/headless siguen usando variables de entorno con mayor precedencia. En esa modalidad la UI muestra esos valores bloqueados y los secretos continúan siendo environment-only.
