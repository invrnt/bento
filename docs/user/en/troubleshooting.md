# Troubleshooting

Start with the sidebar footer and **Activity**: that is where Bento tells you what is happening and, when needed, offers a button to fix it.

## Telegram asked to wait

You see “Telegram asked to wait 4 min” (or some other time).

- Telegram limits how much an app can do in a short time. It is not an error or a penalty, and nothing is lost.
- Bento waits exactly as long as Telegram asks and carries on by itself.
- Don’t restart Bento or repeat the sign-in over and over: it can make the wait longer.
- If it happens while signing in, wait for the time shown before asking for another code.

## Offline

You see “Offline — will resume on its own”.

- You can keep browsing your library, searching and opening what is already on the computer.
- What you add or change is saved and sent when the connection is back. You don’t need to do anything.
- If your connection works but Bento still can’t connect, check whether a VPN, proxy, firewall or your work network blocks Telegram. If Telegram is blocked on your network or in your country, Bento cannot reach your cloud.

## Expired or invalid code

When adding a device:

- The code expires after **10 minutes** and works **once**. If it expired, was already used or an attempt failed, create a new one in Settings › Devices › Add device.
- Type the whole code: three groups of four characters. Upper case, lower case and dashes don’t matter.
- If the code doesn’t connect, try [the alternative method](add-a-device.md#if-pairing-with-a-code-doesnt-work) through Telegram.

## The emojis don’t match

Press **Not me** on the computer that already uses Bento. Someone may have tried to use your code. Create a new code and try again, making sure you type it on your own computer.

## Session ended from Telegram

If you ended Bento’s session in Telegram › Settings › Devices (or Telegram ended it), that computer stops syncing and Bento asks you to connect your Telegram again.

1. Your library is still on the computer: nothing has been deleted.
2. Go to Settings › Account and cloud and connect **the same** Telegram account with the QR code or your number.
3. Sync carries on by itself. You don’t need the recovery kit, because the computer keeps its keys.

If you ended the session because you didn’t recognize that computer, remove it from another computer in Settings › Devices to change the keys. If the computer had been removed, add it again with a code.

## “Check the code” when using the recovery kit

- Make sure you type all 36 characters. Spaces, dashes and lower case don’t matter; neither do O and 0, or I, L and 1.
- If you created a new kit (or removed a device), the old kit no longer works: use the most recent one.

## The link doesn’t open Bento

- Check that Bento is installed on that computer and open it once.
- If your browser asks whether to open Bento, accept.
- If it still doesn’t open, open Bento, choose **I already use Bento on another device** and type the code shown on the page.
- There is no Bento mobile app yet: open the link on the computer you want to add.

## Backup isn’t moving

- Check whether backup is paused: on the Bento icon or in Settings › Backup.
- On laptops, backup pauses on battery by default. Plug in the charger or change **Pause on battery**.
- Check whether you set a **speed limit**.
- If a file fails, it appears in Activity with **Retry**.

## Secure storage warning (Linux)

Bento protects each computer’s key with the system’s secure storage (Secret Service or KWallet). If none is available or it is locked, Bento keeps working with a protected file inside its data folder and tells you. For the best protection, set up or unlock your desktop’s secure storage and protect your session with a password.

## Bento doesn’t open

Follow [Settings, data and recovery](../../desktop/settings-recovery.md#recuperación) (in Spanish). If you need help, you can export a diagnostic report in Settings › Advanced; it does not include your files or your keys.
