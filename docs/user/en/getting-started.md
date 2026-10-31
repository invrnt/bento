# Getting started

Bento keeps your photos and files on your computer and, if you connect your Telegram account, an encrypted copy in your own Telegram. That way your library is on all your computers and there is a copy outside them.

## Before you start

- A computer with Windows (x64), macOS 13 or later (Apple silicon or Intel) or Ubuntu 22.04 (x64).
- Your Telegram account and the phone you use it on, to scan a QR code. If you’d rather not use Telegram, you can use Bento on a single computer.
- There is no Bento mobile app yet.

## Install Bento

- **Windows:** download the installer (`.exe`) and open it. Bento installs for your user and appears in Start.
- **macOS:** download the `.dmg` for your processor (Apple silicon or Intel), drag Bento to Applications and open it.
- **Linux:** install the `.deb` package with your software manager or with `sudo apt install ./bento_*.deb`. A portable version (`.zip`) is also available.

Downloads are on the [releases page](https://github.com/invrnt/bento/releases/latest). To check that a file is authentic, follow [Install Bento Desktop](../../desktop/install-first-run.md) (in Spanish).

## First run

1. **Welcome.** Press **Get started**. If you already use Bento on another computer, choose **I already use Bento on another device** and follow [Add a device](add-a-device.md).
2. **Connect your Telegram.** Open Telegram on your phone › Settings › Devices › Link Desktop Device and scan the QR code. You can also use your phone number. More in [Connect your Telegram](connect-telegram.md).
3. **Creating your cloud.** In a few seconds Bento creates your private channels and your keys, and shows “Connected as” with your name.
4. **Choose what to back up.** Turn on the folders you want to upload (Bento suggests Pictures, Documents and Desktop) or add others with **Add folder…**. Press **Continue** and the backup starts in the background. You can choose **Not now**. More in [Automatic backup](automatic-backup.md).
5. **Save your recovery kit.** It is the spare key to your cloud. Save it as a PDF, print it or copy it, and confirm by typing its last group. You can press **Later**, but Bento will remind you until you save it. More in [Recovery kit](recovery-kit.md).
6. **Done.** Everything you keep in Bento will also be in your Telegram, encrypted.

### Use Bento only on this computer

On the welcome screen, the **Use only on this computer** link keeps your library on that computer only: no Telegram, no cloud, no sync with other devices and no recovery kit. If you change your mind, the storage type is in Settings › Advanced.

## Knowing what Bento is doing

- **Sidebar footer:** your Telegram picture, how much space your cloud uses and a status line, for example “All up to date ✓”, “Uploading 12 files · 3 min”, “Offline — will resume on its own” or “Telegram asked to wait 4 min”. Click it to open **Activity**.
- **Activity:** what is uploading or downloading, the queue, whether it is paused and any alerts that need you, each with one button (**Retry**, **Open settings**, **Save kit**).
- **System tray or menu bar icon:** the same status plus **Open Bento**, **Pause backup** or **Resume backup** and **Quit**.

Bento only sends notifications when you need to do something.

## Bento keeps running in the background

When you close the window, Bento keeps backing up and syncing in the background; the first time, it tells you. To quit completely, use **Quit** on the icon. After the first run, Bento opens on its own when you sign in to your computer. You can change both in Settings › General.

## Adding files

- Drag files or folders anywhere onto the window, or paste from the clipboard.
- From your system: **Send to › Bento** on Windows, or **Open with › Bento** on macOS and Linux.
- From your phone: forward them to the [Telegram inbox](telegram-inbox.md).
- Or let [automatic backup](automatic-backup.md) upload your folders.

## Search and preview

- <kbd>Ctrl</kbd> + <kbd>K</kbd> (<kbd>⌘</kbd> + <kbd>K</kbd> on macOS) opens search: by name and, when it is on, by the text inside your images and PDFs.
- Text recognition turns on automatically on computers with at least 4 cores and 8 GB of RAM; on others you can turn it on in Settings › Smart search. **Smart search** (search by meaning) is optional: turn it on in the same place and Bento downloads the model in the background. Everything runs on your computer.
- Press <kbd>Space</kbd> on a file to preview it right away: photos, videos (with seeking), PDFs and text.

## Next steps

- [Add another computer](add-a-device.md)
- [Privacy and security](privacy-and-security.md)
- [Frequently asked questions](faq.md)
