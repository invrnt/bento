# Public site

`apps/site` is Bento’s public website: home and downloads, the Android download page, security, privacy and terms pages, the `/join` page that turns a pairing web link into a `bento://` deep link (or offers “Instala Bento” on Android), and the `/.well-known/assetlinks.json` that verifies the Android App Link. It is plain HTML, CSS and three small ES modules, with no framework and no runtime dependencies, deployed to Cloudflare Pages.

## Layout

| Path | What it is |
|---|---|
| `src/index.html`, `src/{android,join,security,privacy,terms}/index.html` | Spanish pages (default). |
| `src/en/**` | English pages; every Spanish page has one. |
| `src/404.html` | Not-found page. Its presence also stops Pages from treating the site as a single-page app. |
| `src/assets/site.css` | Styles. Tokens mirror `apps/web/src/styles/tokens.css`; light/dark follows `prefers-color-scheme`. |
| `src/assets/join-code.js`, `src/assets/join.js`, `src/assets/platform.js` | Pairing-code parser, the `/join` page behaviour and the Android/desktop switch (progressive enhancement). |
| `src/assets/motion.js` | Progressive enhancement for every page: header behaviour, scroll-linked effects, reveals and the home-page demos. Sets `html.motion` only without `prefers-reduced-motion`; without it (or without JavaScript) everything renders in its final, still state. |
| `src/assets/android/` | Phone screenshots for `/android/` (WebP from the Roborazzi goldens, see below). |
| `src/assets/fonts/` | Geist and Geist Mono (Latin subset) with their OFL licenses. |
| `src/_headers` | Content-Security-Policy and other response headers for Pages. |
| `site.config.json` | Repository, the public `origin` for link previews, (optionally) the exact desktop release, and the `android` block: package, signing-certificate fingerprints and (optionally) the exact APK release. |
| `scripts/` | `build.mjs` (copy, conservative minify, release links, `assetlinks.json`), `serve.mjs` (local preview with the real headers), `check-placeholders.mjs` (publishing guard), `import-android-screenshots.mjs` (goldens → WebP). |
| `test/` | `node:test` suites. |
| `wrangler.jsonc` | Pages project name, output directory and compatibility date. |

### Home page design

The home page tells Bento’s story as a bento box: the hero box opens (the lid lifts) and its compartments drift apart as you scroll; *Cómo funciona* is a sticky stage that fills the box, wraps it in a *furoshiki* (encryption) and ties the knot (the recovery kit); the privacy “lens” shows the same files as you see them and as Telegram stores them; downloads sit in a lacquered tray. Brand rules from `orchestration/design-system/brand.md` still apply: tokens only, one shu (ume) per screen: the hero and story use no shu, and the closing mark’s ume lands while scrolling down, when the header has tucked itself away.

Header and footer markup is repeated in every page on purpose (no templating). When you change navigation, change every page; the tests catch broken links and missing counterparts.

## Privacy rules the site must keep

- No external fonts, scripts, styles, images, analytics or trackers. The CSP in `_headers` is `default-src 'none'` with `'self'` only where needed and `connect-src 'none'`; the tests fail if a page or script reaches another origin.
- `/join` reads the code from `location.hash` only. The fragment never reaches a server; the page validates it, shows it, builds `bento://join?v=1&c=<code>` and sends it nowhere. No script logs anything (the tests forbid `console`).
- The Android/desktop variant of `/join` is chosen from `navigator.userAgentData.platform` or the user-agent string, only to reorder help. Without JavaScript or with a wrong guess, both paths stay reachable through plain links.
- External links (GitHub, telegram.org) are plain navigation links and are allow-listed in the tests.

## Develop and test

```sh
npm --prefix apps/site test        # builds dist/ and runs every check
npm --prefix apps/site run preview # http://127.0.0.1:8788 with the same _headers
```

The tests cover: internal links and anchors, es/en parity and alternates, the absence of external requests and inline code, the CSP and privacy headers, accessibility basics (language, title, one `h1`, skip link, labelled navigation, hidden decorative SVGs), the Telegram API disclosure on every page, the join-code parser and the `/join` page states, the release-link rewrite, the link-preview tags, the placeholder guard, `assetlinks.json` generation and serving (preview server, `application/json`, no redirect), the production fingerprint guard, the Android release links and screenshots, and the Android “Instala Bento” variant of `/join`. They also check every relative link and heading anchor in `README.md` and `docs/**`.

Try `/join` locally with `http://127.0.0.1:8788/join/#v=1&c=K7Q2-MXR9-T4WA`.

## Link previews

Both home pages declare Open Graph and Twitter card tags with a 1200×630 image (`src/assets/social/og-es.jpg`, `og-en.jpg`). Link previews need absolute URLs, so `site.config.json` sets `"origin": "https://bentocloud.app"` (https, no trailing slash). The build then turns the `og:url`, `og:image` and `twitter:image` paths into absolute URLs. With `"origin": null` they stay root-relative, which some apps resolve and others ignore.

## Download links

Desktop release files carry the version in their names (for example `Bento-0.2.0 Setup.exe`), so GitHub’s `releases/latest/download/<name>` cannot give permanent links. By default every download button opens the [latest release page](https://github.com/invrnt/bento/releases/latest), which always works.

After a release is published, you can point the buttons at the exact files. Copy the file names from the release page into `site.config.json`:

```json
{
  "repository": "invrnt/bento",
  "release": {
    "tag": "v0.2.0",
    "assets": {
      "windows-x64": "Bento-0.2.0 Setup.exe",
      "macos-arm64": "Bento-0.2.0-arm64.dmg",
      "macos-x64": "Bento-0.2.0-x64.dmg",
      "linux-x64-deb": "bento_0.2.0_amd64.deb",
      "linux-x64-zip": "Bento-linux-x64-0.2.0.zip"
    }
  }
}
```

The names above are examples; use the real ones. The build rewrites every anchor marked `data-asset` / `data-checksums` (checksums link to `SHA256SUMS-<target>`), validates the configuration and fails if an asset is missing. Run the tests, commit and deploy. Set `release` back to `null` to return to the latest-release page.

## Android App Links and downloads

### `/.well-known/assetlinks.json`

The build writes it from the `android` block of `site.config.json`:

```json
"android": {
  "package": "dev.bento.app",
  "sha256CertFingerprints": ["14:6D:E9:…:44:E5"],
  "release": null
}
```

- `package` must equal the app's `applicationId` (a test compares it with `apps/android/app/build.gradle.kts`).
- `sha256CertFingerprints` lists every certificate allowed to open `https://<site>/join` links: the release certificate and, if you use one, the Play upload/app-signing certificate. Get them as described in [Android development](android.md#signing-certificate-fingerprint). Upper or lower case with colons is accepted; the file is written upper-case.
- While the list holds the `[[COMPLETAR: …]]` placeholder, preview builds publish an empty fingerprint list (App Links stay unverified) and **`npm run deploy` fails** (`build.mjs --production`). `deploy:preview` still works.
- `_headers` serves it as `application/json`. Pages serves the file at that exact path with no redirect, which Android's verifier requires. After deploying, check `https://<domain>/.well-known/assetlinks.json` and Google's [statement list tester](https://developers.google.com/digital-asset-links/tools/generator).
- The app's intent filter host comes from the Android build property `bentoSiteHost`; it must be the same domain.

### APK download links

The Android page, the Android card on the home page and the “Instala Bento” block of `/join` mark their anchors with `data-android-asset` (`android-arm64`, `android-universal`), the checksum link with `data-android-checksums`, and the hashes with `<code data-android-sha256="…">`. With `android.release` set to `null` they open the latest-release page and say the hash is in the release. After publishing APKs, fill:

```json
"release": {
  "tag": "android-v0.1.0",
  "assets": {
    "android-arm64": "<exact arm64 APK file name>",
    "android-universal": "<exact universal APK file name>"
  },
  "sha256": {
    "android-arm64": "<64 hex characters>",
    "android-universal": "<64 hex characters>"
  },
  "checksums": "SHA256SUMS-android"
}
```

`tag` may be `vX.Y.Z` or `android-vX.Y.Z`; `checksums` is optional (default `SHA256SUMS-android`). The build validates everything and fails on a missing or malformed value.

### Screenshots

`/android/` shows light Roborazzi goldens in a CSS phone frame. `node apps/site/scripts/import-android-screenshots.mjs` (ImageMagick 7 with WebP) converts the goldens listed in the script to 480 px WebP in `src/assets/android/`; commit the result. The tests check that every image exists, is WebP, is at most 40 KB and that the `width`/`height` attributes match.

## Deploy to Cloudflare Pages

Deploys use Wrangler pinned in the npm scripts (`npx --yes wrangler@4.151.3`), so the package keeps zero dependencies.

### First time

1. Sign in: `npx --yes wrangler@4.151.3 login`.
2. Create the project (Direct Upload) once:

   ```sh
   npx --yes wrangler@4.151.3 pages project create bento-site --production-branch main
   ```

3. Fill every `[[COMPLETAR: …]]` placeholder and finish the legal review (see [docs/legal](../legal/README.md)).
4. Deploy:

   ```sh
   npm --prefix apps/site run deploy
   ```

   The script builds, refuses to continue while placeholders remain, and runs `wrangler pages deploy --branch main`. `wrangler.jsonc` supplies the project name and `./dist`.

For a review deployment that may still contain placeholders, use `npm --prefix apps/site run deploy:preview` (branch `preview`). Preview URLs on `*.pages.dev` are public unless you protect them with Cloudflare Access.

### Custom domain

In the Cloudflare dashboard: Workers & Pages › `bento-site` › Custom domains › Set up a domain. Then configure the site URL in Bento builds (below).

### Keep Cloudflare from injecting scripts

The CSP blocks third-party scripts, so anything Cloudflare injects would only fail and clutter the console. For this project and its zone, keep these off: Web Analytics automatic setup (Pages project › Metrics), Rocket Loader, Email Address Obfuscation and Zaraz. Do not add analytics: the privacy policy says the site has none.

### From CI

Wrangler runs non-interactively with `CLOUDFLARE_API_TOKEN` (a token with the *Cloudflare Pages: Edit* permission) and `CLOUDFLARE_ACCOUNT_ID` in the environment:

```sh
CLOUDFLARE_API_TOKEN=… CLOUDFLARE_ACCOUNT_ID=… npm --prefix apps/site run deploy
```

A GitHub Actions job only needs Node 22+, those two secrets and that command; no `npm ci` is required. (A Pages project created for Direct Upload cannot be switched to Git integration later. If you prefer Git integration, create the project from the dashboard instead with root directory `apps/site`, build command `npm run build` and output directory `dist`; the placeholder guard then needs to run in your CI before merging.)

## Configure Bento builds

The pairing dialog offers a web link only when the build knows the site URL. Set the public origin, with no trailing slash, as a repository variable:

```sh
gh variable set BENTO_PUBLIC_SITE_URL --body "https://<your-domain>"
```

Bento builds links as `https://<your-domain>/join#v=1&c=K7Q2-MXR9-T4WA`. Pages serves `/join/` and redirects `/join` there; browsers keep the fragment across that redirect. The desktop release workflow writes the value into `resources/build-config.json`; headless and development runs read the `BENTO_PUBLIC_SITE_URL` environment variable.
