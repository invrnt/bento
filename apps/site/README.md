# Bento site

Static public website (no framework, no runtime dependencies) deployed to Cloudflare Pages.

```sh
npm --prefix apps/site test      # build to dist/ and run the checks
npm --prefix apps/site run preview   # serve dist/ on http://127.0.0.1:8788 with the real _headers
```

Pages live in `src/` (Spanish at the root, English under `src/en/`). Build, configuration, release links and deployment are documented in [docs/dev/site.md](../../docs/dev/site.md).
