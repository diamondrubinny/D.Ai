# D.Ai OS website

A static Hebrew (RTL) landing page: `index.html`, `privacy.html` (draft), `accessibility.html` (draft).
No scripts, cookies, trackers or third-party resources; a strict Content-Security-Policy; WCAG 2.1 AA
contrast, keyboard navigation and phone layout are tested in `tests/site/test_site.py` (CI).

**Before publishing:** add contact details to `privacy.html` and an accessibility coordinator to
`accessibility.html`, and have both reviewed (legal / accessibility). Screenshots in `img/` come from CI
(`ci-screenshots` branch).

**Publishing (GitHub Pages):** Settings → Pages → Source: GitHub Actions, then deploy this folder with
`actions/upload-pages-artifact` + `actions/deploy-pages`. Not enabled automatically — it is the
repository owner's decision.

© 2026 Diamond Rubinny (d.Ai) · Apache-2.0
