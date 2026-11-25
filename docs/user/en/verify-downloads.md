# Verify your downloads

Before installing Bento you can check two things: that the file you downloaded is exactly the one we
published, and that we signed the list of files. It takes a couple of minutes and you don't need to install
anything: the tools come with Windows 10 and 11, macOS and Linux.

Español: [Verificar tus descargas](../es/verificar-descargas.md).

## What each release contains

On the [releases page](https://github.com/invrnt/bento/releases), each release includes, besides the
installers:

- `SHA256SUMS`: the SHA-256 fingerprint of every file in that release.
- `SHA256SUMS.sig`: the signature of that list, made with the Bento release key.

The public key that checks the signature is not in the release but in Bento's repository:
[`allowed_signers`](https://github.com/invrnt/bento/blob/main/scripts/release/allowed_signers). That way, if
someone changed the files of a release, they could not change the key as well.

Android releases are separate (they start with `android-v`) and have their own `SHA256SUMS`.

## 1. Download the files

Into one folder (for example, Downloads), save:

1. the installer you want, for example `Bento-0.1.0-Setup.exe`, `Bento-0.1.0-arm64.dmg` or
   `bento_0.1.0_amd64.deb`;
2. `SHA256SUMS` and `SHA256SUMS.sig` from the same release;
3. the key file: open
   [this link](https://raw.githubusercontent.com/invrnt/bento/main/scripts/release/allowed_signers) and save it
   as `allowed_signers` (no extension).

## 2. Check the signature

Open a terminal in that folder (on Windows, PowerShell; on macOS, Terminal) and run:

**macOS and Linux**

```sh
ssh-keygen -Y verify -f allowed_signers -I bento-release -n bento-release -s SHA256SUMS.sig < SHA256SUMS
```

**Windows (PowerShell)**

```powershell
cmd /c "ssh-keygen -Y verify -f allowed_signers -I bento-release -n bento-release -s SHA256SUMS.sig < SHA256SUMS"
```

It must say `Good "bento-release" signature`. If it says anything else, or an error, **don't install** and let
us know.

## 3. Check your file

**Linux**

```sh
sha256sum --check --ignore-missing SHA256SUMS
```

**macOS**

```sh
shasum -a 256 --check --ignore-missing SHA256SUMS
```

Every file you downloaded must show `OK`.

**Windows (PowerShell)**

```powershell
(Get-FileHash .\Bento-0.1.0-Setup.exe -Algorithm SHA256).Hash.ToLower()
Select-String -Path SHA256SUMS -Pattern "Bento-0.1.0-Setup.exe"
```

Both lines must show the same 64-character fingerprint.

## The system's signature

Each installer also carries its platform's signature:

- **Windows:** the installer's Properties › Digital Signatures shows a valid publisher.
- **macOS:** Bento is signed and notarized by Apple; it opens without "unidentified developer" warnings.
- **Android:** the APK is signed; its certificate fingerprint is the one Bento's site publishes in
  `/.well-known/assetlinks.json`. Bento only updates itself from inside the app if the new version is signed
  with the same certificate.

Bento's automatic updates do these checks for you: they verify a signature of their own before downloading
anything.

## If something doesn't match

Don't install the file. Delete it, download it again only from
[github.com/invrnt/bento/releases](https://github.com/invrnt/bento/releases) and repeat the steps. If it still
doesn't match, it may be a security problem: report it privately as explained in the
[security policy](https://github.com/invrnt/bento/blob/main/SECURITY.md).
