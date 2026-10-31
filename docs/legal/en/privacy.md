# Bento privacy policy

Español: [Política de privacidad](../es/privacidad.md). Published on the site at `/en/privacy/`.

Last updated: [[COMPLETAR: fecha de entrada en vigor]]

> Draft pending legal review: a professional must review it before it is published. [[COMPLETAR: eliminar este aviso tras la revisión legal]]

## In short

- Bento runs on your devices. There are no Bento accounts and none of our servers receive your files, their names or your Telegram credentials.
- What Bento stores in your Telegram is encrypted on your computer. Telegram sees content-free data: that you use Bento, sizes, times and your devices’ sessions.
- The pairing relay only passes encrypted messages between two devices for a few minutes.
- No analytics, telemetry, ads or cookies. We don’t sell data or use it to train artificial intelligence.
- Bento uses the Telegram API and is not affiliated with Telegram.

## 1. Who is responsible

Bento is offered by [[COMPLETAR: nombre legal del responsable]], located at [[COMPLETAR: domicilio del responsable]] (“we”). For any privacy matter, write to [[COMPLETAR: correo de contacto de privacidad]].

## 2. What Bento is

Bento is a desktop app that keeps your photo and file library on your devices and, if you connect your Telegram account, an encrypted copy in private channels of that account to sync your devices. Bento runs on your devices: we do not receive your files, their names or metadata, your phone number, your messages or your Telegram credentials.

## 3. Data that stays on your devices

- Your library: files, thumbnails, previews, names, folders, albums, favorites, metadata (dates, camera, location) and the search index (recognized text and smart search data).
- Each device’s Telegram session, your cloud’s keys and the device identity, encrypted with a key protected by the system.
- Settings, technical logs and the state of background tasks. Logs do not include credentials or keys.

You can delete them by uninstalling Bento and removing its data folder.

## 4. Data stored in your Telegram account

Telegram processes your account data under its own [privacy policy](https://telegram.org/privacy), as the provider of your account. Bento stores your files and library in three private channels of your account, encrypted on your computer before upload.

Telegram can see the title and description of those channels, the number and size of the encrypted parts, upload and download times, your devices’ sessions (app name, model or system and IP) and a technical message with internal identifiers, the creation date and an encrypted copy of your keys. What you choose to send unencrypted (sharing via Telegram, the inbox and pairing without the relay) is explained in the [privacy and security guide](../../user/en/privacy-and-security.md#what-you-choose-to-send-unencrypted).

## 5. External services Bento connects to

| Service | When | What it receives |
|---|---|---|
| Telegram | While you use your cloud | What section 4 describes. |
| Pairing relay (operated by us on Cloudflare) | Only while you add a device | Both devices’ IP addresses, the first 4 characters of the code, the time, and the number and size of encrypted messages. Each room’s state lasts at most 10 minutes; logs contain no IP addresses or content. |
| GitHub | When checking for and downloading updates | Your IP and the version requested, under GitHub’s privacy statement. |
| Smart search model source | Only if you turn on smart search | Your IP when downloading the model from [[COMPLETAR: origen de descarga del modelo de búsqueda inteligente]]. |

Cloudflare provides services to us for the relay and this website. Cloudflare and GitHub may process data outside your country. [[COMPLETAR: garantías aplicables a las transferencias internacionales]]

## 6. This website

This site is hosted on Cloudflare Pages. It uses no cookies, analytics or third-party content. Cloudflare processes the IP and technical details of each visit to serve the pages and protect them from abuse. The page for adding a device reads the pairing code in your browser, from the part of the address after “#”, which is not sent to the server.

## 7. What we don’t do

- We don’t create user accounts or profiles.
- We don’t include analytics, telemetry or ads.
- We don’t sell or share data.
- We don’t use your files or data obtained from Telegram to train artificial intelligence models. Text recognition and search run on your devices.

## 8. Legal bases

We process the little data that reaches us (IP and technical details on the relay and the website) to provide the service you ask for and for our legitimate interest in keeping it secure and preventing abuse. [[COMPLETAR: confirmar las bases jurídicas según la ley aplicable]]

## 9. Retention

- Relay: each room’s state, at most 10 minutes; technical logs, without IP addresses or content, for [[COMPLETAR: plazo de conservación de los registros del relay]].
- Website: Cloudflare’s logs, under its policy.
- On your devices and in your Telegram: until you delete it. The trash keeps deleted items for 30 days, and the inbox deletes imported messages after 24 hours (you can change this).

## 10. Your rights

Because we don’t receive your library, you control it directly: you can delete files and empty the trash, remove devices, delete Bento’s channels in Telegram or remove Bento’s data folder. Rights over the data Telegram processes are exercised with Telegram.

For any other request (access, rectification, erasure, objection, restriction or portability), write to [[COMPLETAR: correo de contacto de privacidad]]. You can also complain to [[COMPLETAR: autoridad de protección de datos competente]].

## 11. Children

Bento is not intended for people below the minimum age to use Telegram in their country.

## 12. Security

We explain how we protect your data, and the limits of that protection, in the [privacy and security guide](../../user/en/privacy-and-security.md).

## 13. Changes

If we change this policy, we will update the date above and, if the change is significant, announce it in the release notes.
