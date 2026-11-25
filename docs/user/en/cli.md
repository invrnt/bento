# Bento in the terminal

`bento` is Bento without windows: a program you use by typing commands in a terminal. It is good for two things:

- **Letting an AI assistant organize your files for you.** Assistants such as Claude Code or Codex know how to use a terminal. Tell one “put these 40 photos and 3 PDFs where they belong in my Bento” and it does it with `bento`.
- **Running Bento on a computer without a screen**, such as a Debian or Ubuntu server or a Raspberry Pi, that receives and keeps files all day.

It is the same library you see in the app: whatever you change with `bento` reaches all your devices within seconds, because your cloud lives in your Telegram.

Español: [Bento en la terminal](../es/cli.md).

> Bento’s messages are in Spanish by default. Add `--lang en` to any command (or set `BENTO_LANG=en`) to get English.

## Install

You don’t need Python or anything else: the program brings everything it needs.

**Linux and macOS.** Open a terminal and paste:

```sh
curl -fsSL https://raw.githubusercontent.com/invrnt/bento/main/scripts/install/install.sh | sh
```

It installs for your user only (in `~/.local/share/bento-cli`) and never asks for an administrator password. Before installing, it checks that the download is the genuine one (its SHA-256 fingerprint); if it doesn’t match, nothing is installed. If it ends by asking you to add `~/.local/bin` to your `PATH`, copy the line it shows and open a new terminal.

**Debian, Ubuntu and Raspberry Pi OS (`.deb` package).** If you prefer a system package, download `bento-cli_<version>_amd64.deb` (or `_arm64.deb` for a Raspberry Pi and other ARM computers) from the [releases page](https://github.com/invrnt/bento/releases) and install it:

```sh
sudo apt install ./bento-cli_0.1.0_amd64.deb
```

**Windows.** Open PowerShell and paste:

```powershell
irm https://raw.githubusercontent.com/invrnt/bento/main/scripts/install/install.ps1 | iex
```

Close PowerShell and open it again so it finds `bento`.

To check that it works:

```sh
bento --version
```

## Getting started: `bento setup`

This is the only thing you have to do. Type:

```sh
bento setup
```

and follow what it asks. You can stop at any time and type it again: it picks up where you left off.

1. **Connect your Telegram.** A QR code is drawn in the terminal. On your phone open Telegram › **Settings** › **Devices** › **Link Desktop Device** and scan it. If your account has two-step verification, it asks for your Telegram password. Can’t scan? Use your number: `bento setup --phone +447700900000`.
2. **If this is your first time using Bento**, it creates your cloud and shows your [recovery kit](recovery-kit.md) **only once**. Write it down and keep it safe: with your Telegram and that code you get everything back even if you lose your computers.
3. **If you already use Bento on another computer**, it offers to join this computer to your cloud with a code (see the next section).

When it is done, `bento status` tells you on one screen whether everything is fine.

> If the Bento app is open on this same computer, `bento` uses it directly: it is the same library and you don’t need `bento setup`. If no app is open, `bento` starts its own Bento in the background the first time it needs it.

## Join this computer to your Bento: `bento join`

If you already have Bento on another computer, you can add this one with a code, just like when you [add a device](add-a-device.md):

1. **On the computer that already uses Bento**, go to Settings › Devices › **Add device**. You will see a code like `K7Q2-MXR9-T4WA`.
2. **On this computer**, type the code:

   ```sh
   bento join K7Q2-MXR9-T4WA
   ```

   Pasting the whole link instead of the code works too.
3. The terminal shows **four emojis** and “Confirm on your other device”.
4. **On the other computer** you are asked whether to add this computer, with four emojis. Check that they are **the same and in the same order** and press **Add**. If they don’t match, press **Not me**.

The terminal tells you how your library is downloading. The code expires after 10 minutes and works once.

Don’t have the other computer at hand? Type `bento setup` and, when it asks how to join this computer, choose your [recovery kit](recovery-kit.md).

It also works the other way round, from the terminal to another device: `bento pair` creates a code (with its QR) for another device to join.

## Everyday commands

Bento folders are written with slashes, starting from the top: `/Documents/Invoices/2024`.

| I want to… | I type |
|---|---|
| See what’s in a folder | `bento ls /Documents` |
| See the folder tree | `bento tree` |
| Create a folder (and any missing ones along the way) | `bento mkdir -p /Documents/Invoices/2024` |
| Upload files or a whole folder | `bento upload ~/Downloads/photos --to /Photos/Trip` |
| Move something | `bento mv /invoice.pdf /Documents/Invoices` |
| Rename | `bento rename /Photos/IMG_001.jpg beach.jpg` |
| Search (also the text in photos and PDFs) | `bento find "rental contract"` |
| Download | `bento download /Documents/Invoices -r --to ~/Invoices` |
| Move something to the trash | `bento rm /draft.pdf` |
| Get it back from the trash | `bento trash`, then `bento trash restore …` |
| Check that everything is uploaded | `bento status` or `bento activity` |
| See your devices | `bento devices` |
| Help for any command | `bento --help`, `bento upload --help` |

Good to know:

- **Uploading the same thing twice never duplicates it.** Bento recognizes files you already have and skips them. If an upload is interrupted, run it again and only what is missing is uploaded.
- **Deleting is not final.** `bento rm` moves things to the [trash](trash-and-storage.md), where you can get them back for 30 days.
- Files are encrypted on your computer before they go to your Telegram; the upload to Telegram continues in the background after the command finishes.

## Asking an AI assistant to organize your files

Open your assistant (Claude Code, Codex or another one that can use the terminal) on the computer where you installed `bento` and ask in your own words. For example:

> I have loose photos and PDFs in `~/Downloads`. Use the `bento` command (read `bento guide` first) to upload them to my Bento and put them in the right folders. Use the folders I already have before creating new ones. Don’t delete anything permanently and, when you’re done, tell me what you put where.

What the assistant will do:

1. Read `bento guide`, a guide written for assistants that explains how to use Bento carefully.
2. Look at how your library is organized (`bento tree`).
3. Create only the folders that are missing, with names similar to the ones you already use.
4. Upload the files to their place and check the result.
5. Tell you what it did.

For your peace of mind:

- The assistant works with **your** Bento, on **your** computer. Bento does not send your files to any AI service; what the assistant reads depends on the assistant you use and what you let it see.
- Anything the assistant moves to the trash can be recovered. Commands that delete forever (emptying the trash, removing a device) require explicit confirmation.
- If you want to review before anything is uploaded, ask it to do a dry run first: `bento upload … --dry-run` shows what it would do without uploading anything.

## Keeping it running on a server

On a server you want Bento to keep running after you log out.

**Linux (systemd):**

```sh
bento daemon install-service
```

It shows the two remaining commands to turn it on; usually:

```sh
systemctl --user enable --now bento.service
sudo loginctl enable-linger "$USER"   # keeps it running without an open session
```

**macOS:** `bento daemon install-service` makes it start on its own when you log in.

**Windows:** nothing to do; `bento` starts Bento whenever it needs it.

To stop or start it by hand: `bento daemon stop` and `bento daemon start`. `bento daemon status` tells you whether it is running.

> On a computer without a screen, the key that protects your Telegram session on that computer is kept in a file in your user folder that only you can read. Protect that computer as you would your phone: anyone who logs in as you can use your Bento. If you lose it or sell it, [remove it from another device](add-a-device.md#remove-a-device).

## If something isn’t working

- `bento status`: a one-screen summary and, if something is missing, which command to type.
- `bento doctor`: checks the Telegram connection, disk space and version.
- `bento daemon logs`: what has been happening in the background.
- More help in [Troubleshooting](troubleshooting.md).

## Uninstall

- Linux and macOS (installed with the script): `bento daemon stop`, then delete `~/.local/share/bento-cli/app` and `~/.local/bin/bento`.
- `.deb` package: `sudo apt remove bento-cli`.
- Windows: `bento daemon stop`, then delete the `app` folder in `%LOCALAPPDATA%\Bento CLI`.

This removes only the program. This computer’s library stays in `bento`’s data folder (`~/.local/share/bento-cli/profiles` on Linux; `~/Library/Application Support/Bento CLI` on macOS; `%LOCALAPPDATA%\Bento CLI` on Windows). Before deleting it, remove this computer from another device so it no longer has access to your cloud.
