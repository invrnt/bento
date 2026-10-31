# Public site

`apps/site` is Bento’s public website: home and downloads, security, privacy and terms pages, and the `/join` page that turns a pairing web link into a `bento://` deep link. It is plain HTML, CSS and two small ES modules, with no framework and no runtime dependencies, deployed to Cloudflare Pages.

## Layout

| Path | What it is |
|---|---|
| `src/index.html`, `src/{join,security,privacy,terms}/index.html` | Spanish pages (default). |
| `src/en/**` | English pages; every Spanish page has one. |
| `src/404.html` | Not-found page. Its presence also stops Pages from treating the site as a single-page app. |
| `src/assets/site.css` | Styles. Tokens mirror `apps/web/src/styles/tokens.css`; light/dark follows `prefers-color-scheme`. |
| `src/assets/join-code.js`, `src/assets/join.js` | Pairing-code parser and the `/join` page behaviour. |
| `src/assets/fonts/` | Geist and Geist Mono (Latin subset) with their OFL licenses. |
| `src/_headers` | Content-Security-Policy and other response headers for Pages. |
| `site.config.json` | Repository and (optionally) the exact release whose files the download buttons point to. |
| `scripts/` | `build.mjs` (copy and conservative minify), `serve.mjs` (local preview with the real headers), `check-placeholders.mjs` (publishing guard). |
| `test/` | `node:test` suites. |
| `wrangler.jsonc` | Pages project name, output directory and compatibility date. |

Header and footer markup is repeated in every page on purpose (no templating). When you change navigation, change all eleven pages; the tests catch broken links and missing counterparts.

## Privacy rules the site must keep

- No external fonts, scripts, styles, images, analytics or trackers. The CSP in `_headers` is `default-src 'none'` with `'self'` only where needed and `connect-src 'none'`; the tests fail if a page or script reaches another origin.
- `/join` reads the code from `location.hash` only. The fragment never reaches a server; the page validates it, shows it, builds `bento://join?v=1&c=<code>` and sends it nowhere.
- External links (GitHub, telegram.org) are plain navigation links and are allow-listed in the tests.

## Develop and test

```sh
npm --prefix apps/site test        # builds dist/ and runs every check
npm --prefix apps/site run preview # http://127.0.0.1:8788 with the same _headers
```

The tests cover: internal links and anchors, es/en parity and alternates, the absence of external requests and inline code, the CSP and privacy headers, accessibility basics (language, title, one `h1`, skip link, labelled navigation, hidden decorative SVGs), the Telegram API disclosure on every page, the join-code parser and the `/join` page states, the release-link rewrite and the placeholder guard. They also check every relative link and heading anchor in `README.md` and `docs/**`.

Try `/join` locally with `http://127.0.0.1:8788/join/#v=1&c=K7Q2-MXR9-T4WA`.

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
