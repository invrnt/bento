# Security policy

Bento keeps people's photos and files, encrypted end to end, in their own Telegram account. We take reports
about it seriously and are grateful for them.

## Supported versions

Bento has one product version for the desktop app, the `bento` CLI, the backend and the Android app
([versioning](docs/dev/releasing.md#versions-and-tags)).

| Version | Security fixes |
|---|---|
| The latest release (`vX.Y.Z` and `android-vX.Y.Z`) | Yes |
| Earlier releases | No: update to the latest release |
| Unreleased code on `main` or other branches | Best effort, reports welcome |

No version has been published yet; this table applies from the first release, `0.1.0`. While Bento is `0.y.z`,
fixes ship only in a new release, not as backports.

## Reporting a vulnerability

**Please report privately. Do not open a public issue, discussion or pull request for a vulnerability.**

Use GitHub's private vulnerability reporting:
[**Report a vulnerability**](https://github.com/invrnt/bento/security/advisories/new)
(the repository's *Security* tab → *Report a vulnerability*). Only the maintainers see the report.

Include what you can: the affected component and version (`bento --version`, Ajustes › Acerca de, or the
release tag), the platform, steps to reproduce or a proof of concept, and the impact you expect. Never include
real Telegram sessions, login codes, recovery kits or other people's data; a test account is enough.

What to expect:

- Acknowledgement within 7 days, and an initial assessment within 14 days.
- We keep you informed while we fix it, agree on a disclosure date with you (normally within 90 days of the
  report, sooner once a fix is released), publish a GitHub Security Advisory and credit you unless you prefer
  otherwise.
- Bento is maintained by a small team without a bug bounty; we cannot pay for reports.

We will not pursue or support legal action against good-faith research that follows this policy: test only your
own accounts and devices, do not access or modify other people's data, avoid degrading the service for others
(for example the pairing relay), and give us reasonable time to fix before disclosure.

## Scope

In scope, in this repository:

- The desktop app (`apps/desktop`, `apps/web`) and its local backend and worker (`apps/api`): for example a way
  for another local user, a web page or a file to reach the API, bypass the per-start credentials, or read
  decrypted data.
- End-to-end encryption, vault keys, recovery kits and multi-device sync: anything that lets Telegram, the
  relay, or someone with access to the user's Telegram account read or alter files or metadata.
- Pairing (`apps/relay`, QR codes and join codes, `/join` on the site): impersonating a device, joining a vault
  without approval, or learning pairing secrets.
- The Android app (`apps/android`): exported components, intents, App Links, the share target, the updater
  and the APK signature checks.
- The `bento` CLI, its daemon and its installers (`scripts/install`).
- Release integrity: signed `SHA256SUMS`, update manifests and their signatures, the release tooling in
  `scripts/release`.
- The public site (`apps/site`) and its pages.

Out of scope:

- Vulnerabilities in Telegram, its apps or its servers (report them to Telegram), and in Cloudflare, GitHub or
  the operating system, unless Bento uses them in an unsafe way.
- Attacks that need an already compromised or rooted device, malware running as the same user, or physical
  access to an unlocked device (Bento's own threat model is described in
  [privacy and security](docs/user/en/privacy-and-security.md)).
- Builds you made yourself with modified code, dry-run or unsigned packages, and unreleased branches beyond
  best effort.
- Rate limiting, missing security headers or TLS settings without a demonstrated impact, automated scanner
  output without a proof of concept, and social engineering of maintainers or users.

## Verifying a download

Every release lists the SHA-256 of each file in `SHA256SUMS`, signed with the Bento release key
(`SHA256SUMS.sig`, an OpenSSH signature in the `bento-release` namespace). The public key is in
[`scripts/release/allowed_signers`](scripts/release/allowed_signers) in this repository, not in the release
itself, so a tampered release cannot replace both.

```sh
# In the folder with the files you downloaded from the release page
curl -fsSLO https://raw.githubusercontent.com/invrnt/bento/main/scripts/release/allowed_signers
ssh-keygen -Y verify -f allowed_signers -I bento-release -n bento-release -s SHA256SUMS.sig < SHA256SUMS
sha256sum --check --ignore-missing SHA256SUMS          # macOS: shasum -a 256 --check --ignore-missing SHA256SUMS
```

The first command must print `Good "bento-release" signature`, the second `OK` for each file you downloaded.
Windows (PowerShell, OpenSSH is built in):

```powershell
cmd /c "ssh-keygen -Y verify -f allowed_signers -I bento-release -n bento-release -s SHA256SUMS.sig < SHA256SUMS"
(Get-FileHash .\Bento-X.Y.Z-Setup.exe -Algorithm SHA256).Hash.ToLower()   # compare with its line in SHA256SUMS
```

Beyond the checksums, installers are signed by the platform: Windows Authenticode, Apple Developer ID with
notarization, and Android APK signature v2/v3 with the certificate fingerprint published on the site. Bento's
own updaters additionally check an Ed25519 signature on their update manifests before downloading anything.
Step-by-step guides: [English](docs/user/en/verify-downloads.md), [español](docs/user/es/verificar-descargas.md).
