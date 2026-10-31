# Solución de problemas

Empieza por el pie de la barra lateral y por **Actividad**: ahí Bento te dice qué pasa y, si hace falta, te ofrece un botón para resolverlo.

## Telegram pidió esperar

Ves «Telegram pidió esperar 4 min» (o el tiempo que sea).

- Telegram limita cuántas cosas puede hacer una app en poco tiempo. No es un error ni un castigo, y no se pierde nada.
- Bento espera exactamente lo que Telegram pide y sigue solo.
- No reinicies Bento ni repitas el inicio de sesión una y otra vez: puede alargar la espera.
- Si ocurre al iniciar sesión, espera el tiempo indicado antes de pedir otro código.

## Sin conexión

Ves «Sin conexión — se reanudará solo».

- Puedes seguir viendo tu biblioteca, buscar y abrir lo que ya está en el equipo.
- Lo que añadas o cambies se guarda y se envía cuando vuelva la conexión. No tienes que hacer nada.
- Si tu conexión funciona pero Bento sigue sin conectar, revisa si una VPN, un proxy, un cortafuegos o la red de tu trabajo bloquean Telegram. Si Telegram está bloqueado en tu red o en tu país, Bento no puede conectar con tu nube.

## Código expirado o no válido

Al añadir un dispositivo:

- El código caduca a los **10 minutos** y sirve **una sola vez**. Si caducó, ya se usó o un intento falló, crea uno nuevo en Ajustes › Dispositivos › Añadir dispositivo.
- Escribe el código completo: tres grupos de cuatro caracteres. Mayúsculas, minúsculas y guiones dan igual.
- Si el código no conecta, prueba [el método alternativo](anadir-dispositivo.md#si-el-emparejamiento-por-código-no-funciona) por Telegram.

## Los emojis no coinciden

Pulsa **No soy yo** en el equipo que ya usa Bento. Puede que alguien haya intentado usar tu código. Crea un código nuevo y vuelve a intentarlo, comprobando que lo escribes en tu propio equipo.

## Sesión cerrada desde Telegram

Si cerraste la sesión de Bento en Telegram › Ajustes › Dispositivos (o Telegram la cerró), ese equipo deja de sincronizarse y Bento te pide conectar tu Telegram de nuevo.

1. Tu biblioteca sigue en el equipo: no se ha borrado nada.
2. Ve a Ajustes › Cuenta y nube y conecta **la misma cuenta** de Telegram con el QR o tu número.
3. La sincronización sigue sola. No necesitas el kit de recuperación, porque el equipo conserva sus llaves.

Si cerraste la sesión porque no reconocías ese equipo, quítalo desde otro equipo en Ajustes › Dispositivos para cambiar las llaves. Si el equipo había sido quitado, vuelve a añadirlo con un código.

## «Revisa el código» al usar el kit de recuperación

- Comprueba que escribes los 36 caracteres. Los espacios, los guiones y las minúsculas dan igual; la O y el 0, y la I, la L y el 1, también.
- Si generaste un kit nuevo (o quitaste un dispositivo), el kit anterior ya no sirve: usa el más reciente.

## El enlace no abre Bento

- Comprueba que Bento está instalado en ese equipo y ábrelo una vez.
- Si el navegador pregunta si quieres abrir Bento, acepta.
- Si aun así no se abre, abre Bento, elige **Ya uso Bento en otro dispositivo** y escribe el código que aparece en la página.
- Bento todavía no tiene app para móvil: abre el enlace en el ordenador que quieres añadir.

## El respaldo no avanza

- Mira si el respaldo está en pausa: en el icono de Bento o en Ajustes › Respaldo.
- En portátiles, el respaldo se pausa con batería de serie. Conecta el cargador o cambia la opción **Pausar con batería**.
- Revisa si pusiste un **límite de velocidad**.
- Si un archivo falla, aparece en Actividad con **Reintentar**.

## Aviso sobre el almacén seguro (Linux)

Bento protege la llave de cada equipo con el almacén seguro del sistema (Secret Service o KWallet). Si no hay ninguno disponible o está bloqueado, Bento sigue funcionando con un archivo protegido dentro de su carpeta de datos y te lo avisa. Para la mejor protección, configura o desbloquea el almacén seguro de tu escritorio y protege tu sesión con contraseña.

## Bento no se abre

Sigue [Ajustes, datos y recuperación](../../desktop/settings-recovery.md#recuperación). Si necesitas ayuda, en Ajustes › Avanzado puedes exportar un diagnóstico; no incluye tus archivos ni tus llaves.
