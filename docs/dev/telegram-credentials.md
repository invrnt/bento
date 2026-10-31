# Telegram API credentials

Bento signs users in to their own Telegram accounts through MTProto (Telethon). Every MTProto client needs an application identity: an `api_id` and `api_hash` registered by the developer. Bento ships its **own** pair as build configuration; users never see or enter them.

## Register Bento’s application

1. Sign in at <https://my.telegram.org> with the Telegram account that will own the application (use a maintainer account you control long-term, not a personal throwaway).
2. Open **API development tools** and fill in the form:
   - **App title:** `Bento`. Telegram’s API terms forbid “Telegram” in an app’s title unless preceded by “Unofficial”, so keep it as Bento.
   - **Short name:** for example `bento`.
   - **URL:** the public site, if it is deployed.
   - **Platform:** Desktop.
   - **Description:** say that Bento uses the Telegram API to store end-to-end encrypted backups in the user’s own account.
3. Copy the `api_id` (a number) and the `api_hash` (a 32-character hex string).

Read and follow the [Telegram API terms of service](https://core.telegram.org/api/terms). The ones that shape Bento:

- Use your own `api_id`; never reuse another app’s.
- Users must know the app uses the Telegram API (the site, onboarding and about pages say so: “Bento usa la API de Telegram y no está afiliado a Telegram”).
- Don’t use “Telegram” in the product name or the official logo.
- Don’t use data obtained from Telegram to train AI models.
- Guard users’ privacy; Telegram may revoke API access for violations not fixed within 10 days.

## Store them as CI secrets

The desktop build reads them from the environment at package time (`resources/build-config.json`). Store them as GitHub Actions **secrets** (repository Settings › Secrets and variables › Actions), or with the GitHub CLI:

```sh
gh secret set BENTO_TELEGRAM_API_ID     # paste the number when prompted
gh secret set BENTO_TELEGRAM_API_HASH   # paste the hash when prompted
```

Typing the values at the prompt keeps them out of your shell history. Never commit them, paste them into issues, or print them in workflow logs.

> These values identify the **application**, not a user, and they end up inside every packaged build, where a determined person can extract them; every Telegram client works this way. Keeping them out of the repository and logs still matters: an `api_id` abused by someone else can be limited or banned by Telegram, which would break sign-in for every Bento user.

## Local development

The API and worker read the same variables. Export them in the shell that starts the processes, or put them in the git-ignored root `.env`:

```dotenv
STORAGE_BACKEND=telegram
BENTO_TELEGRAM_API_ID=123456
BENTO_TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef
```

Recommendations:

- Develop against the [fake Telegram cloud](multi-device.md) (`STORAGE_BACKEND=fake`); use a real account only to verify MTProto behaviour.
- For real-account testing, use a secondary Telegram account. Repeated logins and bulk uploads trigger `FLOOD_WAIT`, and aggressive automation can get an account limited.
- If the variables are missing, sign-in fails with the `telegram_not_available` error code.

## Rotating

If the hash leaks or is abused, register a replacement application, update both secrets and ship a new release. Before publishing, test both a fresh sign-in and an existing installation upgraded to the new build.
