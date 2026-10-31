# Ajustes, datos, copias de seguridad y recuperación

## Ajustes

Ajustes se organiza en seis apartados:

- **General:** idioma, abrir al iniciar sesión, mantener en segundo plano, tema (claro, oscuro o sistema) y actualizaciones.
- **Cuenta y nube:** cuenta de Telegram (cerrar sesión), uso de la nube y kit de recuperación (verificar o generar uno nuevo).
- **Dispositivos:** la lista de equipos, con «este dispositivo», renombrar, quitar y añadir.
- **Respaldo:** carpetas, pausa, pausa con batería y límite de velocidad.
- **Búsqueda inteligente:** reconocimiento de texto y búsqueda por significado, un interruptor cada uno.
- **Avanzado:** almacenamiento (local o Telegram), ubicación de datos, rendimiento, tamaño de partes, relay, exportar diagnóstico y restaurar valores.

En los ajustes avanzados, cada campo indica si requiere reiniciar worker, servicios o aplicación. **Guardar cambios** valida el borrador completo; **Guardar y reiniciar** aplica el cambio mínimo y confirma la nueva revisión. Si la salud falla, Bento restaura automáticamente la última revisión válida.

Los secretos no vuelven al renderer ni a la API en texto plano. La sesión de Telegram, las llaves de la nube y la identidad del equipo se guardan cifradas en `secure/` dentro del directorio de datos, con una llave del equipo protegida por `safeStorage` y el almacén seguro del sistema. Exportar configuración y copiar diagnósticos excluye secretos.

Guías de usuario relacionadas: [Añadir un dispositivo](../user/es/anadir-dispositivo.md), [Kit de recuperación](../user/es/kit-de-recuperacion.md), [Respaldo automático](../user/es/respaldo-automatico.md) y [Papelera y espacio en el equipo](../user/es/papelera-y-espacio.md).

## Ubicaciones y logs

Las ubicaciones exactas dependen del sistema y del usuario. Usa **Ajustes → Avanzado → Abrir logs** para evitar adivinar rutas. El log principal es `desktop.jsonl` dentro del directorio de logs de Electron; rota al superar aproximadamente 5 MiB y conserva una generación anterior. Los tokens de lanzamiento, contraseñas y secretos conocidos se redactan.

Los binarios y recursos instalados son de solo lectura. La base SQLite, la caché, el almacén cifrado y la configuración viven bajo los directorios de usuario/datos. Bento nunca debe escribir configuración dentro de `resources` o `app.asar`.

## Copia de seguridad

**Con Telegram**, tu biblioteca ya tiene una copia cifrada en tu cuenta y en tus otros equipos. Lo que protege el acceso es el [kit de recuperación](../user/es/kit-de-recuperacion.md): guárdalo fuera de tus equipos. No hace falta copiar el directorio de datos.

- Para usar Bento en otro equipo, [añádelo con un código](../user/es/anadir-dispositivo.md). **No copies el directorio de datos de un equipo a otro** para clonarlo: contiene la identidad y la sesión de ese equipo, y dos equipos con la misma identidad confunden la sincronización.
- Para recuperar todo en un equipo nuevo sin tener otro, usa tu cuenta de Telegram y el kit de recuperación.

**En modo local** (sin Telegram), el directorio de datos es la única copia:

1. Sal de Bento (**Salir** en el icono) y espera a que desaparezca su proceso; así API y worker liberan SQLite.
2. Copia el directorio de datos completo a un destino protegido.
3. Verifica tamaño, fecha y posibilidad de leer la copia antes de actualizar o mover datos.

Para restaurar una copia local, instala la misma versión o una posterior compatible, sal de Bento, restaura el directorio completo y selecciónalo como ubicación de datos. Nunca combines parcialmente dos bases activas.

## Actualizar, reinstalar y desinstalar

Bento busca actualizaciones al iniciar y cada 6 horas, las descarga y verifica en segundo plano, y solo se instalan cuando pulsas **Reiniciar para actualizar** (en Linux, Bento te entrega el instalador ya verificado). Una actualización sustituye el paquete ejecutable y conserva el user-data/directorio de datos.

La desinstalación conserva los datos deliberadamente para evitar pérdidas. Tampoco cierra la sesión de Telegram de ese equipo: si dejas de usarlo, [quítalo desde otro dispositivo](../user/es/anadir-dispositivo.md#quitar-un-dispositivo) para cerrar su sesión y cambiar las llaves. Para borrar los datos locales, confirma primero la ubicación en Ajustes, sal de Bento y elimina solo esa ruta explícita. Borrar los datos locales no borra tu nube en Telegram.

Los modelos descargados y la caché pueden ocupar espacio. Limpiarlos no debe interpretarse como borrar la biblioteca.

## Recuperación

Si el inicio falla, la ventana de recuperación muestra un diagnóstico seguro. Prueba en este orden:

1. Reabre Bento una vez y comprueba espacio libre y permisos de la carpeta de datos.
2. Revisa el final de `desktop.jsonl`; comparte solo el código/error ya redactado, nunca archivos de `secure/`, `.env` ni la carpeta de datos.
3. Revierte el último cambio desde Ajustes si la pantalla sigue disponible. Tres caídas rápidas detienen el bucle y dejan Bento en modo recuperación.
4. Reinstala la misma versión para reparar binarios. La reinstalación no debe requerir borrar datos.
5. Con Telegram, si el directorio de datos quedó dañado, puedes empezar con uno nuevo: elige **Ya uso Bento en otro dispositivo** y añade el equipo con un código o con tu kit de recuperación. Después quita la entrada antigua de ese equipo desde Ajustes › Dispositivos.
6. En modo local, restaura la copia completa del directorio de datos.

No edites `bootstrap.json`, `secrets.json`, `secure/` ni SQLite mientras Bento está abierto.

## Telegram en escritorio

Bento se conecta directamente a tu cuenta de Telegram desde los procesos locales; no necesita bots, el servidor Telegram Bot API ni ningún otro servicio aparte. La guía antigua basada en bots se retiró: ver [Configurar Telegram en Bento](../telegram-setup.md).
