# The website, rubinny.com: plan (v2)

> Written on 2026-10-19 after "a designed landing page in several languages, a download link from GitHub, terms of use and a privacy policy that are final for publishing, at rubinny.com, with screenshots from the system, an explanation of everything, and what we offer compared with competitors".

## 1. What there is today (v1) and what changes

- **v1:**
  - Eight hand-written pages, with a language switcher.
  - Terms, privacy and accessibility statement in Hebrew only, marked as drafts.
  - 6 screenshots, some of them from before the new taskbar.
- **v2:**
  - **One source, eight languages:** `site/src/strings/<lang>.json` plus `build/scripts/site-build.py`, which writes `site/index.html` and `site/<lang>/index.html`. No page is edited by hand, so the languages cannot drift apart. The site test checks that the pages match the source.
  - **A new design:**
    - The hero has the diamond's light behind it.
    - A tour of the system, screenshot next to text.
    - "Everything inside" in 6 groups.
    - A comparison table, editions, and the switch from Windows 10.
  - Still the same rules: **no scripts, cookies or third-party resources**, a strict CSP, AA contrast, RTL, phone layout and "reduce motion".
  - **New screenshots** (WebP, about 10 times smaller):
    - From CI: desktop, Diamond answering, "+install antivirus", an app Forge built, Quick, Clip, the installer.
    - From the docs: J and MOM in Hebrew.
  - **Comparison with Windows 11, macOS, Ubuntu and ChromeOS:**
    - Only rows that can be stated with confidence: price, open source, where the AI runs, a required account, ads, diagnostic data, old computers, undoing an update, encryption, and maturity.
    - Includes "D.Ai is alpha" (honesty).
    - Marked "default settings, as of October 2026".
  - **Legal:**
    - Privacy, terms of use and an accessibility statement, complete and written to be published, in **Hebrew and English**. The other languages link to the English text.
    - Contact addresses on the domain: `privacy@rubinny.com`, `accessibility@rubinny.com`.
  - **Domain and publishing:**
    - `site/CNAME` = `rubinny.com`, plus `robots.txt`, `sitemap.xml` and an Open Graph image (PNG).
    - A GitHub Pages workflow (`site.yml`) that publishes from `main`.
    - `_headers` for Cloudflare Pages, if that is chosen instead (HSTS, frame-ancestors, CSP as headers).

## 2. Decisions and assumptions

| Decision | Choice | Alternative |
|----------|--------|-------------|
| Hosting | GitHub Pages (free, next to the code, HTTPS) | Cloudflare Pages (security headers, logs on a CDN) |
| The download link | `github.com/diamondrubinny/D.Ai/releases/latest` (the latest regular release); all releases on a secondary link | Direct links to an ISO: break with every version |
| Legal languages | Hebrew and English | All 8: requires a professional translator |

## 3. Requires the owner's action (not code)

1. **Create the mailboxes** `privacy@rubinny.com` and `accessibility@rubinny.com` (or change them in `site/src/legal`).
2. **DNS:** for GitHub Pages, A records for `rubinny.com` to GitHub's Pages addresses and a CNAME for `www`, then Settings → Pages → Custom domain plus Enforce HTTPS. **Requires checking against GitHub's official documentation.**
3. **Legal review:** the texts were written to be published, but **a lawyer must approve them** before they go live. In particular:
   - Israeli law, amendment 13;
   - consumer protection;
   - GDPR for visitors from Europe;
   - the liability clause.
4. **Accessibility review** by an accessibility consultant (Israeli standard 5568) before publishing the statement.
5. **GitHub Sponsors:** enable it for the account `diamondrubinny` (GitHub → Sponsors → Get sponsored; it asks
   for a Stripe Connect account and tax details, and GitHub reviews the profile). Until then the "Sponsor" button
   (`.github/FUNDING.yml`) is hidden and the amount buttons on `#support` land on a page that says the profile is
   not set up. Suggested tiers in the profile, matching the site's buttons (US dollars, the only currency GitHub
   Sponsors bills in): one-time $5, $10, $25, $100; monthly $5, $10, $25. Each with a plain text: what the money
   goes to, no perks that would make it a purchase. The site's buttons pre-fill the amount through URL parameters
   (`?frequency=one-time&amount=25`); **requires verification** against GitHub's documentation after enabling,
   and the amounts on the site and in the profile are kept the same (`build/scripts/site-build.py`: `ONE_TIME`,
   `MONTHLY`). Tax and receipts: GitHub Sponsors does not issue donation receipts for tax purposes in Israel;
   **requires a check** with an accountant before saying anything about deductibility.

---

© 2026 Diamond Rubinny (d.Ai) · D.Ai OS · Apache-2.0
