# Privacidad y seguridad

English: [Privacy and security](../en/privacy-and-security.md). Política de privacidad: [docs/legal](../../legal/es/privacidad.md).

Bento está hecho para que tu nube sea ilegible para todos menos para tus equipos. Esta guía explica, sin letra pequeña, qué se cifra, qué puede ver Telegram, qué ve el relay de emparejamiento y qué no podemos proteger. Es el mismo texto que la página de seguridad del sitio web.

## En pocas palabras

- Todo lo que Bento sube a Telegram se cifra antes en tu equipo, con llaves que solo tienen tus equipos y tu kit de recuperación.
- Telegram guarda datos ilegibles. Sabe que usas Bento, cuánto ocupa tu nube y cuándo subes o descargas.
- El relay solo pasa mensajes cifrados entre dos equipos mientras los emparejas y no guarda nada más de 10 minutos.
- Bento no tiene cuentas propias ni servidores con tus archivos, y no envía analíticas.
- Si pierdes todos tus equipos y también tu kit de recuperación, nadie puede recuperar tu nube. Tampoco nosotros.

## Qué se cifra

Antes de subir nada, Bento cifra en tu equipo:

- el contenido de cada archivo, sus miniaturas y sus vistas previas;
- los nombres de archivos, carpetas y álbumes, y el tipo de cada archivo;
- las fechas, los datos de la cámara y la ubicación guardados en tus fotos;
- tus favoritos y cómo organizas tu biblioteca;
- el texto que Bento reconoce en imágenes y PDF, y los datos de la búsqueda inteligente;
- la lista de cambios con la que tus equipos se mantienen sincronizados.

### Cómo se cifra

- **AES-256-GCM**, un cifrado autenticado estándar: además de ocultar el contenido, detecta cualquier modificación. Si alguien altera, reordena o recorta un archivo cifrado, Bento lo rechaza.
- Cada nube tiene una **llave maestra aleatoria de 256 bits**. De ella salen llaves distintas para archivos, sincronización y cada uso, y cada archivo se cifra con su propia llave.
- Los archivos se cifran en bloques de 1 MiB, así Bento puede reproducir un vídeo o reanudar una descarga sin bajarlo entero. Al terminar comprueba la huella SHA-256 del archivo completo.
- En cada equipo, la sesión de Telegram y las llaves se guardan cifradas con una llave del dispositivo protegida por el almacén seguro del sistema (Llavero en macOS, protección de datos de Windows, Secret Service o KWallet en Linux). Si el sistema no ofrece almacén seguro, Bento usa un archivo protegido dentro de su carpeta de datos y te lo avisa.

## Qué ve Telegram

Telegram es donde se guarda tu nube, así que conoce algunos datos sin contenido:

- **Que usas Bento.** Los tres canales privados se llaman «Bento · Archivos», «Bento · Sync» y «Bento · Bandeja», están en una carpeta de chats «Bento» y su descripción indica que los creó Bento.
- **Cuánto guardas y cuándo.** El número y el tamaño de las partes cifradas, y la hora de cada subida y descarga.
- **Tus equipos.** Cada equipo con Bento es una sesión de tu cuenta, visible en Telegram › Ajustes › Dispositivos con el nombre de la app, el modelo o sistema del equipo y su dirección IP, como cualquier otra app de Telegram.
- **Datos técnicos de tu nube.** Un mensaje fijado en «Bento · Sync» con identificadores internos, la fecha de creación, cuántas veces se cambiaron las llaves y una copia de tus llaves cifrada con tu código de recuperación.
- **Lo que ya sabe de tu cuenta.** Tu número de teléfono, tus contactos y tus chats. Bento no cambia nada de eso.

Telegram **no** ve el contenido de tus archivos, sus nombres, tipos, fechas o ubicación, tus carpetas, álbumes y favoritos, tus búsquedas ni el texto reconocido.

Los chats normales de Telegram se cifran entre tu app y los servidores de Telegram, pero Telegram puede leerlos. Por eso Bento cifra tus archivos antes de subirlos.

## Lo que tú decides enviar sin cifrar

Algunas funciones usan Telegram tal cual. Bento siempre te lo indica antes:

- **Compartir por Telegram**: Envía una copia normal, sin cifrar y con su nombre original, al chat que elijas. Telegram y las personas de ese chat pueden verla.
- **Bandeja de Telegram**: Lo que reenvías a «Bento · Bandeja» es un mensaje normal de Telegram. Bento lo importa, lo cifra en tu nube y borra el mensaje de la Bandeja a las 24 horas (puedes cambiar el plazo). El mensaje original sigue donde estaba.
- **Importar de Telegram**: Bento copia a tu nube, cifrados, los archivos de los chats que elijas. Los mensajes originales no se tocan.
- **Emparejar sin relay**: Si el relay no está disponible, el equipo nuevo publica en «Bento · Sync» una solicitud con su nombre, su sistema y su llave pública, y la borra al terminar. Las llaves de tu nube nunca viajan sin cifrar.

## Qué ve el relay de emparejamiento

Para que dos equipos se encuentren al emparejarlos, Bento usa un relay: un pequeño servicio en Cloudflare que reenvía mensajes entre ellos durante unos minutos.

- **Ve** las direcciones IP de los dos equipos (Cloudflare las procesa para entregar la conexión), los cuatro primeros caracteres del código, que nombran la «sala», la hora, y cuántos mensajes cifrados pasan y de qué tamaño.
- **No ve** los otros ocho caracteres del código, que nunca salen de tus equipos, ni el contenido de los mensajes, cifrados de extremo a extremo. Tampoco puede hacerse pasar por uno de tus equipos: sin esos ocho caracteres cualquier intento falla y el código se anula.
- **No guarda** nada: cada sala dura como máximo 10 minutos y después se borra. Sus registros solo contienen nombres de eventos, cantidades y códigos de error. Para frenar abusos usa una huella de tu IP, nunca la IP tal cual.

## Emparejar equipos con seguridad

Un código de emparejamiento como `K7Q2-MXR9-T4WA` tiene dos partes: los cuatro primeros caracteres identifican la sala en el relay y los ocho restantes son una contraseña de un solo uso.

- Con esa contraseña, tus dos equipos acuerdan una llave secreta con SPAKE2, un protocolo pensado para contraseñas cortas: quien observe o controle la conexión no puede deducir la contraseña ni probar otras sin que se note.
- Los cuatro emojis salen de esa llave. Si coinciden en las dos pantallas, estás conectado con tu equipo y no con otro. Si no coinciden, pulsa «No soy yo».
- Solo cuando apruebas en el equipo que ya usas, este envía las llaves de tu nube al nuevo, cifradas para ese equipo en concreto.
- El código caduca a los 10 minutos y sirve una sola vez.
- El enlace web lleva el código después del signo «#»: tu navegador no lo envía a ningún servidor.

## Kit de recuperación

- Es un código de 36 caracteres en 9 grupos, con 160 bits aleatorios y una suma de control que detecta errores al escribirlo.
- Tu nube en Telegram guarda una copia de tus llaves cifrada con ese código. Sin el código, esa copia no sirve: es imposible de adivinar.
- Con tu cuenta de Telegram y el código, cualquiera puede abrir tu nube. Guárdalo fuera de tus equipos: impreso o en un gestor de contraseñas.
- Tus equipos no guardan el código. Si lo pierdes, genera uno nuevo desde cualquier equipo con Bento; el anterior deja de funcionar.
- Bento no puede recuperarlo ni restablecerlo por ti.

## Quitar un equipo

Cuando quitas un equipo desde Ajustes › Dispositivos:

1. Bento cierra la sesión de Telegram de ese equipo. Si Telegram todavía no lo permite (ocurre cuando el equipo desde el que lo quitas inició sesión hace poco), te pedirá que la cierres en Telegram › Ajustes › Dispositivos.
2. Crea llaves nuevas para tu nube y se las da solo a los equipos que siguen.
3. Te muestra un kit de recuperación nuevo; el anterior deja de servir.

Lo que el equipo quitado ya había descargado sigue en ese equipo: no se puede borrar a distancia.

## Tus equipos

Bento no pide contraseña al abrirse. En cada equipo, tu biblioteca (nombres, miniaturas y archivos descargados) está al alcance de tu usuario del sistema: protégelo con contraseña de inicio de sesión y, si puedes, con cifrado de disco.

## Lo que Bento no puede proteger

- Un equipo con software malicioso o en manos de otra persona con tu sesión abierta.
- Tu nube frente a quien consiga a la vez tu cuenta de Telegram y tu kit de recuperación.
- Tu nube si Telegram elimina o restringe tu cuenta, o si borras los canales de Bento.
- Las copias que compartes sin cifrar y lo que otras personas hagan con ellas.
- Los datos sin contenido que Telegram puede ver, descritos arriba.

## Actualizaciones

Bento consulta GitHub para saber si hay versiones nuevas. Las descarga en segundo plano, comprueba su tamaño y su huella SHA-256 antes de ofrecerlas y nunca se instala sin que pulses «Reiniciar para actualizar». Las versiones publicadas están firmadas en Windows y firmadas y notarizadas en macOS.

## Este sitio web

- No usa cookies, analíticas, fuentes ni scripts de terceros. Una política de seguridad de contenido estricta impide que sus páginas carguen o envíen nada fuera de este dominio.
- La página para añadir un equipo lee el código de la parte de la dirección que va tras «#», que los navegadores no envían al servidor, y no lo transmite.
- El sitio está alojado en Cloudflare Pages, que, como cualquier servidor web, recibe tu IP y los datos técnicos de cada visita.

## Reportar un problema de seguridad

Escríbenos a [[COMPLETAR: correo para reportes de seguridad]]. Te pedimos que no publiques los detalles hasta que hayamos podido corregirlo.
