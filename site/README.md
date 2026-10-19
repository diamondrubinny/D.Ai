# D.Ai OS website: rubinny.com

The plan is in [docs/SITE.md](../docs/SITE.md).

## What is here

- **The source:**
  - `src/strings/<lang>.json`: the landing page's words, in eight languages.
  - `src/legal/{he,en}/*.html`: the privacy policy, the terms of use and the accessibility statement.
- **Generated pages** (do not edit them by hand): `index.html` (Hebrew), `<lang>/index.html`, `privacy.html`, `terms.html`, `accessibility.html`, `en/*.html` and `sitemap.xml`. Build them with:

  ```sh
  python3 build/scripts/site-build.py          # writes the pages
  python3 build/scripts/site-build.py --check  # what CI runs
  ```

- `style.css`, `img/` (WebP screenshots from CI, and `og.jpg` for link previews), `CNAME`, `robots.txt`, and `_headers` (security headers for Cloudflare Pages or Netlify, if one of them hosts the site instead).

## Rules

- No scripts, cookies, trackers or third-party resources.
- A strict Content-Security-Policy.
- WCAG 2.1 AA contrast, keyboard navigation, RTL, and a phone layout.
- `tests/site/test_site.py` checks all of this in CI.

## Publishing (GitHub Pages)

`.github/workflows/site.yml` publishes `site/` (without `src/`) on every change in `main`. It needs, once:

1. Settings → Pages → Source: **GitHub Actions**.
2. Point the domain's DNS at GitHub Pages, then set Settings → Pages → Custom domain to `rubinny.com` and turn on Enforce HTTPS. The records are listed in GitHub's documentation on custom domains for Pages. **This requires checking against the official documentation.**
3. Create the mailboxes `privacy@rubinny.com` and `accessibility@rubinny.com`.

**Before publishing:** a lawyer reviews the privacy policy and terms of use, and an accessibility consultant reviews the accessibility statement (docs/SITE.md §3).

© 2026 Diamond Rubinny (d.Ai) · Apache-2.0
