# Bento para Android

Bento para Android respalda las fotos y videos de tu teléfono cifrados en tu propia cuenta de Telegram y te da toda tu biblioteca en el bolsillo: Fotos, Archivos, Buscar y Colecciones, igual que en tu computador.

- [Instalar](#instalar)
- [Primer inicio](#primer-inicio)
- [Unirte desde tu computador](#unirte-desde-tu-computador)
- [Respaldo del carrete](#respaldo-del-carrete)
- [Liberar espacio](#liberar-espacio)
- [Compartir a Bento](#compartir-a-bento)
- [Bloqueo de la app](#bloqueo-de-la-app)
- [Actualizaciones](#actualizaciones)
- [Solución de problemas](#solución-de-problemas)

## Instalar

Necesitas **Android 10 o posterior** en un teléfono o tableta de 64 bits (casi todos los de 2019 en adelante). Bento todavía no está en Google Play: se instala desde un APK firmado que se publica en las [versiones de Bento en GitHub](https://github.com/invrnt/bento/releases) y en la página de descarga del sitio de Bento (`/android/`).

1. **Descarga el APK desde el teléfono.** Elige **arm64** (la recomendada, para casi todos los teléfonos). La **universal** es más grande y solo hace falta en Chromebooks con procesador Intel o AMD.
2. **Abre el archivo** desde la notificación de descarga o desde la app Archivos › Descargas.
3. **Permite instalar apps desconocidas.** Si Android lo pide, toca **Configuración** y activa **Permitir de esta fuente** para tu navegador. El ajuste también está en Ajustes › Apps › Acceso especial › Instalar apps desconocidas (el nombre exacto cambia un poco según la marca).
4. **Toca Instalar.** Si Google Play Protect dice que no conoce la app, puedes pedirle que la analice o instalarla de todas formas.
5. Cuando termine, puedes volver a desactivar el permiso del paso 3. Bento no lo necesita para funcionar.

### Comprobar la descarga (opcional)

La página de descarga muestra el SHA-256 de cada APK, y la versión en GitHub incluye el archivo `SHA256SUMS-android`. En un computador:

```sh
sha256sum <archivo-descargado>.apk   # macOS: shasum -a 256 <archivo-descargado>.apk
```

El resultado debe ser idéntico al publicado. Todos los APK de Bento están firmados con el mismo certificado; Android no deja instalar una actualización firmada con otro.

## Primer inicio

En la bienvenida tienes tres caminos:

- **Empezar:** conecta tu Telegram y crea tu nube. Si tienes la app de Telegram en el teléfono, **Continuar con Telegram** te pide confirmar allí el inicio de sesión. También puedes usar tu número de teléfono: Telegram te envía un código a su app y, si tienes verificación en dos pasos, te pide tu contraseña. Después, Bento crea tu nube, te ofrece respaldar las fotos del teléfono y te da tu **kit de recuperación**: guárdalo (PDF, imprimir o copiar), es la llave de repuesto de tu nube.
- **Ya uso Bento en otro dispositivo:** une el teléfono a la nube que ya tienes (siguiente apartado).
- **Usar solo en este teléfono:** sin Telegram. Tus fotos y archivos se quedan en el teléfono, sin nube ni sincronización. Puedes conectar tu Telegram más tarde desde Ajustes.

Bento te pide permisos solo cuando los necesita y siempre te explica para qué: fotos y videos al activar el respaldo, notificaciones para avisarte del progreso, la cámara al escanear un QR. Si dices que no, todo lo demás sigue funcionando.

## Unirte desde tu computador

Lo más rápido son tres toques y nada que escribir:

1. En tu computador con Bento: Ajustes › Dispositivos › **Añadir dispositivo**. Aparece un QR y un código como `K7Q2-MXR9-T4WA`.
2. En el teléfono, escanea el QR con la cámara o con Google Lens.
   - **Si Bento ya está instalado**, se abre directamente en la pantalla para unirte, con el código puesto.
   - **Si no lo está**, el navegador abre la página de Bento con **Instala Bento**: descarga el APK, instálalo (ver [Instalar](#instalar)) y vuelve a esa página para tocar **Abrir Bento**, o escanea el QR otra vez.
3. El teléfono muestra cuatro emojis y «Confirma en tu computador». Comprueba que en el computador aparecen **los mismos y en el mismo orden** y pulsa **Añadir** allí. Si no coinciden, pulsa **No soy yo**.

Si el teléfono no tenía Telegram conectado, normalmente no tienes que hacer nada más: el computador autoriza al teléfono al aprobar. Después verás «Descargando tu biblioteca…» unos segundos y llegarás a Fotos mientras el resto se va completando.

También puedes ir por la app: **Ya uso Bento en otro dispositivo** abre el escáner; debajo tienes **Escribir el código** si prefieres escribirlo o pegar el enlace. El código caduca a los 10 minutos y sirve una sola vez.

¿No tienes el otro equipo a mano? Elige **No tengo el otro dispositivo**: entras con tu Telegram y escribes (o escaneas) el código de tu kit de recuperación. Más detalle en [Añadir un dispositivo](anadir-dispositivo.md) y [Kit de recuperación](kit-de-recuperacion.md).

## Respaldo del carrete

Bento sube las fotos y videos del teléfono cifrados a tu nube, en segundo plano.

- **Qué se respalda:** **Cámara** y **Capturas de pantalla** vienen activadas. Puedes añadir otras carpetas del teléfono (por ejemplo WhatsApp Images o Descargas) en Ajustes › Respaldo del teléfono. En tu biblioteca aparecen en Archivos › Del teléfono › *nombre del teléfono*, y en la línea de tiempo de Fotos.
- **Cuándo:** por defecto **Solo con Wi-Fi**; los videos solo con Wi-Fi salvo que lo cambies. Puedes elegir **Solo mientras carga**. Bento pausa el respaldo con batería baja y respeta el ahorro de datos. **Respaldar ahora** se salta la regla del Wi-Fi una vez.
- **Sin duplicados:** si una foto ya está en tu nube (por ejemplo, porque la subió tu computador), no se vuelve a subir.
- **Ubicación:** si permites el acceso a la ubicación de las fotos, se guarda la original (cifrada). Si no, Bento te avisa una vez de que se guardarán sin ubicación.
- **Acceso parcial:** si en Android 14 o posterior eliges **Seleccionar fotos**, Bento respalda solo esas y te lo dice con una tarjeta; nunca insiste.

Durante un respaldo largo verás una sola notificación con el progreso y el botón **Pausar**. El estado está en Ajustes › Respaldo del teléfono («Todo respaldado», «Quedan 340 · esperando Wi-Fi»…) y en el anillo de tu avatar, arriba a la derecha.

## Liberar espacio

Cuando tus fotos ya están en la nube, puedes borrar los originales del teléfono: Ajustes › Respaldo del teléfono › **Liberar espacio**.

- Bento solo propone fotos y videos **completamente subidos y verificados**.
- El borrado lo hace Android, que te pide confirmarlo; en la mayoría de teléfonos van primero a la papelera del sistema.
- Nunca es automático.
- Bento conserva las miniaturas, así que tu línea de tiempo no cambia. Al abrir una foto, el original se descarga de tu nube.

Aparte, Ajustes › Espacio en este teléfono muestra cuánto ocupan las miniaturas, los originales en caché y lo que marcaste como **Disponible sin conexión**, y te deja vaciar la caché o cambiar su límite.

## Compartir a Bento

Desde cualquier app (Galería, Chrome, un lector de PDF…) toca **Compartir** y elige **Bento**. Se abre una hoja encima de la app:

1. Revisa lo que vas a guardar y elige la carpeta (la última que usaste viene puesta). Con fotos o videos puedes añadirlos además a un álbum.
2. Toca **Guardar en Bento**. La hoja se cierra al instante; la copia, el cifrado y la subida siguen en segundo plano.

Las carpetas que más usas aparecen también como accesos directos en el menú de compartir. El texto o un enlace compartidos solos se guardan como una nota `.txt`. Si algo no se pudo leer, lo verás en la actividad con el nombre del archivo.

## Bloqueo de la app

En Ajustes › General › **Bloqueo de la app** puedes pedir tu huella, tu rostro o el PIN del teléfono al abrir Bento: de inmediato, o tras 1, 5 o 15 minutos fuera. Con el bloqueo activo, Bento también oculta su contenido en la vista de apps recientes.

El bloqueo protege la pantalla; el respaldo y la sincronización siguen funcionando en segundo plano.

## Actualizaciones

Bento busca versiones nuevas por su cuenta y te avisa con una tarjeta discreta y en Ajustes › Acerca de: «Hay una versión nueva».

- La lista de versiones está **firmada**; Bento ignora cualquier aviso cuya firma no sea válida.
- Antes de instalar, Bento comprueba el **SHA-256** del APK descargado y que esté firmado con **el mismo certificado** que la app que tienes.
- La instalación la hace el instalador de Android, que te pide confirmar. **Nunca se actualiza en silencio.** La primera vez, Android puede pedirte permitir que Bento instale apps.
- Tus datos y tu sesión se conservan. Si una subida estaba a medias, sigue donde se quedó.

También puedes actualizar a mano: descarga el APK nuevo de la página de descarga e instálalo encima.

## Solución de problemas

**El QR abre el navegador aunque Bento está instalado.** Pasa si escaneaste con una app que abre los enlaces en su propio navegador. En esa página toca **Abrir Bento**, o abre Bento › **Ya uso Bento en otro dispositivo** y escanea desde allí. Si te ocurre siempre, en Ajustes › Apps › Bento › Abrir de forma predeterminada comprueba que los enlaces de Bento estén activados.

**«No se instaló la app» o «La app no es compatible».** Comprueba que tienes Android 10 o posterior. Si usaste la versión arm64 en un Chromebook o un emulador, descarga la universal. Si ya tenías una versión de Bento instalada desde otro sitio (firmada con otra llave), desinstálala primero.

**«El paquete parece no ser válido».** La descarga se cortó. Bórrala y descárgala otra vez; comprueba el SHA-256 si quieres asegurarte.

**El respaldo se queda parado.** Abre el avatar › Cuenta y actividad: te dice si espera Wi-Fi, carga o batería. Comprueba Ajustes › Respaldo del teléfono (Solo con Wi-Fi, Solo mientras carga). Si tiene fotos pendientes desde hace más de un día sin abrir la app, Bento te mostrará una tarjeta con ayuda para tu marca.

**Ahorro de batería del fabricante.** Algunas marcas (Xiaomi, Huawei/Honor, Samsung, OnePlus, Oppo/Realme, Vivo) cierran las apps en segundo plano de forma agresiva. Si el respaldo solo avanza con Bento abierto:

- En Ajustes › Apps › Bento › Batería, elige **Sin restricciones** (o **No optimizar**).
- Samsung: quita Bento de **Apps en suspensión** y **Apps en suspensión profunda** (Ajustes › Batería › Límites de uso en segundo plano).
- Xiaomi/HyperOS: activa **Inicio automático** para Bento y elige **Sin restricciones** en Ahorro de batería.
- Huawei/Honor: en Inicio de apps, gestiona Bento manualmente y permite las tres opciones.

Bento no pide permisos para saltarse estas restricciones; solo las necesitas si tu teléfono detiene el respaldo.

**Quitaste el permiso de fotos o de notificaciones.** Bento sigue funcionando: el respaldo se pausa o el progreso solo se ve dentro de la app. Vuelve a activarlo desde Ajustes › Respaldo del teléfono o desde los ajustes de Android.

**«Bento se desconectó de Telegram».** Cerraste la sesión de Bento desde Telegram o desde otro dispositivo. Tu biblioteca sigue visible; toca **Volver a conectar** e inicia sesión otra vez.

**Perdí el teléfono.** Desde otro de tus equipos, Ajustes › Dispositivos › quita el teléfono: Bento cierra su sesión de Telegram, cambia las llaves de tu nube y te da un kit de recuperación nuevo.

Más ayuda: [Solución de problemas](solucion-de-problemas.md) · [Privacidad y seguridad](privacidad-y-seguridad.md).

Bento usa la API de Telegram y no está afiliado a Telegram.
