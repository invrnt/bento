# Privacy and security

Español: [Privacidad y seguridad](../es/privacidad-y-seguridad.md). Privacy policy: [docs/legal](../../legal/en/privacy.md).

Bento is built so your cloud is unreadable to everyone but your devices. This guide explains, without fine print, what is encrypted, what Telegram can see, what the pairing relay sees and what we cannot protect. It is the same text as the security page on the website.

## In short

- Everything Bento uploads to Telegram is encrypted first on your computer, with keys that only your devices and your recovery kit hold.
- Telegram stores unreadable data. It knows you use Bento, how much space your cloud takes and when you upload or download.
- The relay only passes encrypted messages between two devices while you pair them, and keeps nothing for more than 10 minutes.
- Bento has no accounts of its own and no servers holding your files, and it sends no analytics.
- If you lose all your devices and your recovery kit too, nobody can recover your cloud. Not even us.

## What is encrypted

Before uploading anything, Bento encrypts on your computer:

- the contents of every file, its thumbnails and its previews;
- the names of files, folders and albums, and the type of each file;
- the dates, camera details and location stored in your photos;
- your favorites and how you organize your library;
- the text Bento recognizes in images and PDFs, and smart search data;
- the list of changes your devices use to stay in sync.

### How it is encrypted

- **AES-256-GCM**, a standard authenticated cipher: besides hiding the contents, it detects any modification. If someone alters, reorders or truncates an encrypted file, Bento rejects it.
- Each cloud has a **random 256-bit master key**. Separate keys are derived from it for files, sync and each other use, and every file is encrypted with its own key.
- Files are encrypted in 1 MiB blocks, so Bento can play a video or resume a download without fetching the whole file. When it finishes, it checks the SHA-256 fingerprint of the complete file.
- On each device, the Telegram session and the keys are stored encrypted with a device key protected by the system’s secure store (Keychain on macOS, Windows data protection, Secret Service or KWallet on Linux). If the system has no secure store, Bento uses a protected file inside its data folder and tells you.

## What Telegram sees

Telegram is where your cloud is stored, so it knows some data without content:

- **That you use Bento.** The three private channels are called “Bento · Archivos”, “Bento · Sync” and “Bento · Bandeja”, sit in a chat folder called “Bento”, and their description says Bento created them.
- **How much you store and when.** The number and size of the encrypted parts, and the time of every upload and download.
- **Your devices.** Each computer with Bento is a session of your account, visible in Telegram › Settings › Devices with the app name, the computer’s model or system and its IP address, like any other Telegram app.
- **Technical details of your cloud.** A pinned message in “Bento · Sync” with internal identifiers, the creation date, how many times the keys were changed and a copy of your keys encrypted with your recovery code.
- **What it already knows about your account.** Your phone number, contacts and chats. Bento changes none of that.

Telegram does **not** see the contents of your files, their names, types, dates or locations, your folders, albums and favorites, your searches or the recognized text.

Regular Telegram chats are encrypted between your app and Telegram’s servers, but Telegram can read them. That is why Bento encrypts your files before uploading them.

## What you choose to send unencrypted

Some features use Telegram as it is. Bento always tells you first:

- **Share via Telegram**: Sends a regular, unencrypted copy with its original name to the chat you pick. Telegram and the people in that chat can see it.
- **Telegram inbox**: What you forward to “Bento · Bandeja” is a regular Telegram message. Bento imports it, encrypts it into your cloud and deletes the inbox message after 24 hours (you can change this). The original message stays where it was.
- **Import from Telegram**: Bento copies files from the chats you choose into your cloud, encrypted. The original messages are left untouched.
- **Pairing without the relay**: If the relay is not available, the new device posts a request in “Bento · Sync” with its name, system and public key, and deletes it when done. Your cloud’s keys never travel unencrypted.

## What the pairing relay sees

So two devices can find each other while pairing, Bento uses a relay: a small service on Cloudflare that forwards messages between them for a few minutes.

- **It sees** the IP addresses of both devices (Cloudflare processes them to deliver the connection), the first four characters of the code, which name the “room”, the time, and how many encrypted messages pass and how large they are.
- **It does not see** the other eight characters of the code, which never leave your devices, or the contents of the messages, which are end-to-end encrypted. Nor can it impersonate one of your devices: without those eight characters every attempt fails and the code is cancelled.
- **It keeps nothing**: each room lasts at most 10 minutes and is then erased. Its logs contain only event names, counts and error codes. To prevent abuse it uses a fingerprint of your IP, never the IP itself.

## Pairing devices safely

A pairing code such as `K7Q2-MXR9-T4WA` has two parts: the first four characters identify the room on the relay and the remaining eight are a one-time password.

- With that password your two devices agree on a secret key using SPAKE2, a protocol designed for short passwords: anyone watching or controlling the connection cannot work out the password or try others without being noticed.
- The four emojis come from that key. If they match on both screens, you are connected to your own device and not another one. If they don’t match, press “Not me”.
- Only when you approve on the device you already use does it send your cloud’s keys to the new one, encrypted for that specific device.
- The code expires after 10 minutes and works once.
- The web link carries the code after the “#” sign: your browser never sends it to any server.

## Recovery kit

- It is a 36-character code in 9 groups, with 160 random bits and a checksum that catches typing mistakes.
- Your cloud in Telegram keeps a copy of your keys encrypted with that code. Without the code, that copy is useless: it cannot be guessed.
- With your Telegram account and the code, anyone can open your cloud. Keep it away from your computers: printed or in a password manager.
- Your devices do not store the code. If you lose it, create a new one from any computer with Bento; the old one stops working.
- Bento cannot recover or reset it for you.

## Removing a device

When you remove a device in Settings › Devices:

1. Bento signs that device out of Telegram. If Telegram does not allow it yet (this happens when the computer you remove it from signed in recently), it asks you to end the session in Telegram › Settings › Devices.
2. It creates new keys for your cloud and gives them only to the remaining devices.
3. It shows you a new recovery kit; the old one stops working.

Whatever the removed device had already downloaded stays on that device: it cannot be erased remotely.

## Your devices

Bento does not ask for a password when it opens. On each computer your library (names, thumbnails and downloaded files) is available to your system user: protect it with a sign-in password and, if you can, disk encryption.

## What Bento cannot protect

- A computer with malicious software, or in someone else’s hands with your session open.
- Your cloud against someone who gets both your Telegram account and your recovery kit.
- Your cloud if Telegram deletes or restricts your account, or if you delete Bento’s channels.
- Copies you share unencrypted and what other people do with them.
- The content-free data Telegram can see, described above.

## Updates

Bento checks GitHub for new versions. It downloads them in the background, verifies their size and SHA-256 fingerprint before offering them and never installs without you pressing “Restart to update”. Published versions are signed on Windows and signed and notarized on macOS.

## This website

- It uses no cookies, analytics, or third-party fonts or scripts. A strict content security policy stops its pages from loading or sending anything outside this domain.
- The page for adding a device reads the code from the part of the address after “#”, which browsers never send to the server, and does not transmit it.
- The site is hosted on Cloudflare Pages, which, like any web server, receives your IP and the technical details of each visit.

## Reporting a security problem

Write to [[COMPLETAR: correo para reportes de seguridad]]. Please don’t publish details until we have been able to fix it.
