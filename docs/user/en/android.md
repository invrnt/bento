# Bento for Android

Bento for Android backs up your phone’s photos and videos, encrypted, to your own Telegram account and puts your whole library in your pocket: Photos, Files, Search and Collections, just like on your computer.

> The app is Spanish-first. Button and menu names here are the English wording; if your phone shows Bento in Spanish, the [Spanish guide](../es/android.md) uses the exact labels.

- [Install](#install)
- [First run](#first-run)
- [Join from your computer](#join-from-your-computer)
- [Camera roll backup](#camera-roll-backup)
- [Free up space](#free-up-space)
- [Share to Bento](#share-to-bento)
- [App lock](#app-lock)
- [Updates](#updates)
- [Troubleshooting](#troubleshooting)

## Install

You need **Android 10 or later** on a 64-bit phone or tablet (almost every one from 2019 on). Bento is not on Google Play yet: you install it from a signed APK published in [Bento’s GitHub releases](https://github.com/invrnt/bento/releases) and on the download page of the Bento website (`/en/android/`).

1. **Download the APK on the phone.** Pick **arm64** (recommended, for almost every phone). The **universal** one is larger and only needed on Chromebooks with Intel or AMD processors.
2. **Open the file** from the download notification or from the Files app › Downloads.
3. **Allow installing unknown apps.** If Android asks, tap **Settings** and turn on **Allow from this source** for your browser. The setting is also under Settings › Apps › Special app access › Install unknown apps (the exact wording varies a little by brand).
4. **Tap Install.** If Google Play Protect says it doesn’t recognize the app, you can let it scan the app or install anyway.
5. When it’s done, you can turn the permission from step 3 off again. Bento doesn’t need it to work.

### Verify the download (optional)

The download page shows each APK’s SHA-256, and the GitHub release includes a `SHA256SUMS-android` file. On a computer:

```sh
sha256sum <downloaded-file>.apk   # macOS: shasum -a 256 <downloaded-file>.apk
```

The result must match the published value exactly. Every Bento APK is signed with the same certificate; Android refuses an update signed with a different one.

## First run

The welcome screen offers three paths:

- **Get started:** connect your Telegram and create your cloud. If the Telegram app is on the phone, **Continue with Telegram** asks you to confirm the sign-in there. You can also use your phone number: Telegram sends a code to its app and, if you use two-step verification, asks for your password. Bento then creates your cloud, offers to back up the phone’s photos and gives you your **recovery kit**: save it (PDF, print or copy); it is the spare key to your cloud.
- **I already use Bento on another device:** add the phone to the cloud you already have (next section).
- **Use only on this phone:** no Telegram. Your photos and files stay on the phone, with no cloud and no sync. You can connect your Telegram later from Settings.

Bento asks for permissions only when it needs them and always says why: photos and videos when you turn on backup, notifications to show progress, the camera to scan a QR code. If you say no, everything else keeps working.

## Join from your computer

The fastest way is three taps and nothing to type:

1. On your computer with Bento: Settings › Devices › **Add device**. A QR code and a code like `K7Q2-MXR9-T4WA` appear.
2. On the phone, scan the QR code with the camera or Google Lens.
   - **If Bento is installed**, it opens straight on the join screen with the code filled in.
   - **If it isn’t**, the browser opens Bento’s page with **Install Bento**: download the APK, install it (see [Install](#install)) and go back to that page to tap **Open Bento**, or scan the QR code again.
3. The phone shows four emojis and “Confirm on your computer”. Check that the computer shows **the same ones in the same order** and click **Add** there. If they don’t match, click **Not me**.

If the phone wasn’t signed in to Telegram, you usually don’t need to do anything else: the computer authorizes the phone when you approve. You’ll see “Downloading your library…” for a few seconds and land in Photos while the rest fills in.

You can also start in the app: **I already use Bento on another device** opens the scanner; below it, **Type the code** lets you type it or paste the link. The code expires after 10 minutes and works once.

Don’t have the other device at hand? Choose **I don’t have the other device**: you sign in to Telegram and type (or scan) the code from your recovery kit. More in [Add a device](add-a-device.md) and [Recovery kit](recovery-kit.md).

## Camera roll backup

Bento uploads your phone’s photos and videos, encrypted, to your cloud in the background.

- **What is backed up:** **Camera** and **Screenshots** are on. You can add other phone folders (for example WhatsApp Images or Downloads) in Settings › Phone backup. In your library they appear under Files › From this phone › *phone name*, and in the Photos timeline.
- **When:** **Wi-Fi only** by default; videos on Wi-Fi only unless you change it. You can choose **Only while charging**. Bento pauses backup on low battery and respects Data Saver. **Back up now** skips the Wi-Fi rule once.
- **No duplicates:** a photo already in your cloud (for example, uploaded by your computer) is not uploaded again.
- **Location:** if you allow access to photo locations, the original location is kept (encrypted). If not, Bento tells you once that photos will be saved without it.
- **Partial access:** if on Android 14 or later you choose **Select photos**, Bento backs up only those and says so on a card; it never nags.

During a long backup you’ll see a single notification with progress and a **Pause** button. The status is in Settings › Phone backup (“All backed up”, “340 left · waiting for Wi-Fi”…) and in the ring around your avatar, top right.

## Free up space

Once your photos are in the cloud, you can remove the originals from the phone: Settings › Phone backup › **Free up space**.

- Bento only offers photos and videos that are **fully uploaded and verified**.
- Android does the deleting and asks you to confirm; on most phones they go to the system trash first.
- It is never automatic.
- Bento keeps the thumbnails, so your timeline doesn’t change. When you open a photo, the original downloads from your cloud.

Separately, Settings › Storage on this phone shows how much the thumbnails, cached originals and items you marked **Available offline** take, and lets you clear the cache or change its limit.

## Share to Bento

From any app (Gallery, Chrome, a PDF reader…) tap **Share** and choose **Bento**. A sheet opens over the app:

1. Check what you’re saving and pick the folder (the last one you used is preselected). For photos or videos you can also add them to an album.
2. Tap **Save to Bento**. The sheet closes right away; copying, encryption and upload continue in the background.

Your most-used folders also appear as shortcuts in the share menu. Text or a link shared on its own is saved as a `.txt` note. If something couldn’t be read, you’ll see it in the activity list with the file name.

## App lock

In Settings › General › **App lock** you can require your fingerprint, your face or the phone’s PIN to open Bento: immediately, or after 1, 5 or 15 minutes away. With the lock on, Bento also hides its content in the recent apps view.

The lock protects the screen; backup and sync keep running in the background.

## Updates

Bento checks for new versions on its own and tells you with a calm card and in Settings › About: “A new version is available”.

- The version list is **signed**; Bento ignores any notice whose signature isn’t valid.
- Before installing, Bento checks the downloaded APK’s **SHA-256** and that it is signed with **the same certificate** as the app you have.
- Android’s installer does the install and asks you to confirm. **It never updates silently.** The first time, Android may ask you to allow Bento to install apps.
- Your data and your session stay. An upload that was halfway continues where it left off.

You can also update by hand: download the new APK from the download page and install it over the current one.

## Troubleshooting

**The QR code opens the browser even though Bento is installed.** This happens when you scan with an app that opens links in its own browser. Tap **Open Bento** on that page, or open Bento › **I already use Bento on another device** and scan from there. If it always happens, check Settings › Apps › Bento › Open by default and make sure Bento’s links are turned on.

**“App not installed” or “App not compatible”.** Check that you have Android 10 or later. If you used the arm64 APK on a Chromebook or an emulator, download the universal one. If a Bento version installed from somewhere else (signed with a different key) is already on the phone, uninstall it first.

**“There was a problem parsing the package”.** The download was cut short. Delete it and download it again; check the SHA-256 if you want to be sure.

**Backup is stuck.** Open your avatar › Account and activity: it tells you whether it is waiting for Wi-Fi, charging or battery. Check Settings › Phone backup (Wi-Fi only, Only while charging). If photos have been pending for more than a day without you opening the app, Bento shows a card with help for your phone’s brand.

**Manufacturer battery savers.** Some brands (Xiaomi, Huawei/Honor, Samsung, OnePlus, Oppo/Realme, Vivo) aggressively close apps in the background. If backup only moves while Bento is open:

- In Settings › Apps › Bento › Battery, choose **Unrestricted** (or **Don’t optimize**).
- Samsung: remove Bento from **Sleeping apps** and **Deep sleeping apps** (Settings › Battery › Background usage limits).
- Xiaomi/HyperOS: turn on **Autostart** for Bento and choose **No restrictions** in Battery saver.
- Huawei/Honor: in App launch, manage Bento manually and allow all three options.

Bento doesn’t ask for permission to bypass these restrictions; you only need them if your phone stops the backup.

**You removed the photos or notifications permission.** Bento keeps working: backup pauses, or progress is only visible inside the app. Turn it back on from Settings › Phone backup or from Android’s settings.

**“Bento disconnected from Telegram”.** You ended Bento’s session from Telegram or from another device. Your library stays visible; tap **Reconnect** and sign in again.

**I lost my phone.** From another of your devices, Settings › Devices › remove the phone: Bento ends its Telegram session, changes your cloud’s keys and gives you a new recovery kit.

More help: [Troubleshooting](troubleshooting.md) · [Privacy and security](privacy-and-security.md).

Bento uses the Telegram API and is not affiliated with Telegram.
