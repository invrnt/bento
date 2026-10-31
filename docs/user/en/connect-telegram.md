# Connect your Telegram

Bento uses your own Telegram account to store your cloud. You don’t need to create bots, channels or keys: Bento does it for you.

## With a QR code (recommended)

1. On the **Connect your Telegram** screen, Bento shows a QR code that refreshes on its own every few seconds.
2. On your phone, open Telegram › **Settings** › **Devices** › **Link Desktop Device**.
3. Scan the QR code with your phone.
4. If your account has two-step verification, Bento asks for your Telegram password (and shows your hint, if you set one).
5. Bento shows “Connected as” with your name and creates your cloud.

## With your phone number

1. Press **Use my phone number**.
2. Type your number with your country code.
3. Telegram sends you a code, usually inside the Telegram app itself. Type it into Bento.
4. If you have two-step verification, type your Telegram password.

## What Bento creates in your account

| Channel | What it is for | How it appears |
|---|---|---|
| “Bento · Archivos” | Your files, thumbnails and previews, encrypted | Muted and archived |
| “Bento · Sync” | The changes that keep your devices the same, encrypted | Muted and archived |
| “Bento · Bandeja” | The inbox: send things to Bento from any Telegram app | Muted, visible |

All three are private channels where you are the only member, grouped in a chat folder called “Bento”. Their names are the same whatever language you use.

> **Don’t delete, edit or leave these channels or their messages.** Your cloud lives there: if you delete them, you lose what you stored.

## What Bento does with your account

- Each computer with Bento is a session of your account and appears in Telegram › Settings › Devices, like any other Telegram app.
- Bento reads your chat list to find its channels and to show you who to send something to. It doesn’t open or change your conversations, except the ones you choose to [share to or import from](share-and-import.md).
- Bento respects Telegram’s limits. If Telegram asks it to wait, Bento waits and carries on by itself.

## Disconnect Telegram on a computer

Settings › Account and cloud › **Sign out**. That computer’s library stays where it is, but it stops syncing with your cloud until you connect the same account again.

If you want to stop using a computer for good, remove it from another one instead: [Remove a device](add-a-device.md#remove-a-device).

## If something goes wrong

- **The QR code expired:** it refreshes on its own. If not, press the button to retry.
- **The code doesn’t arrive or is wrong:** check the number and country code and ask for a new code.
- **“Telegram asked to wait”:** Telegram limits sign-in attempts. Wait for the time shown.

More cases in [Troubleshooting](troubleshooting.md).

Bento uses the Telegram API with its own application ID and is not affiliated with Telegram.
