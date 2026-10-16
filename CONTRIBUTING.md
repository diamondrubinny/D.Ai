# Contributing to D.Ai OS

Thank you for helping! D.Ai OS is open to everyone — code, docs, translations (especially Hebrew/RTL), accessibility testing and hardware reports are all valuable.

## Ground rules

1. Be respectful — see the [Code of Conduct](CODE_OF_CONDUCT.md).
2. Security vulnerabilities go through [SECURITY.md](SECURITY.md), never public issues.
3. Discuss large changes (new components, architecture, new dependencies) in an issue first.

## Developer Certificate of Origin (DCO)

We use the [DCO](https://developercertificate.org/) instead of a CLA. Sign off every commit:

```bash
git commit -s -m "feat: describe your change"
```

This adds `Signed-off-by: Your Name <you@example.com>`, certifying you have the right to submit the work under the project's license (Apache-2.0).

## Workflow

1. Fork and create a branch: `feat/...`, `fix/...`, `docs/...`.
2. Keep changes focused; one topic per pull request.
3. Run the checks below locally.
4. Open a pull request describing **what** changed, **why**, and **how you tested it**.

## Local checks

```bash
shellcheck build/scripts/*.sh tests/boot/*.sh \
  build/live-build/common/hooks/normal/*.hook.chroot
# Full build + boot test (Debian trixie container, see README.md)
```

## Conventions

- Code, identifiers and code comments in English; user-facing text must support Hebrew and RTL.
- Shell: `bash` with `set -euo pipefail`, ShellCheck-clean.
- New packages in the image must justify their size and security impact in the PR.
- Never commit secrets, keys, tokens or personal data.
- Accessibility is a requirement, not an extra: keyboard navigation, screen-reader labels, contrast.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `build:`, `ci:`, `security:`, `refactor:`, `test:`.

---

© 2026 Diamond Rubinny (d.Ai) · D.Ai OS · Apache-2.0
