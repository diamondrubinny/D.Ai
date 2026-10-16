# Security Policy

## Supported versions

D.Ai OS is pre-alpha. Only the latest commit on `main` receives security fixes.

## Reporting a vulnerability

**Please do not report security issues in public issues, discussions or pull requests.**

Use GitHub's private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability**.

Include, where possible:
- Affected component (image build, firewall, AI service, voice, installer, ...) and version/commit
- Steps to reproduce or a proof of concept
- Impact assessment

Target response times (best effort, volunteer project):
- Acknowledgement: within 5 business days
- Initial assessment: within 14 days

We follow coordinated disclosure and will credit reporters who want to be credited.

## Scope highlights

- Default image hardening (sysctl, nftables, AppArmor, account lockdown)
- The AI service and anything that lets AI output modify files or execute commands
- Microphone/voice handling and local data encryption
- Build pipeline and supply chain (package lists, model download verification)

Vulnerabilities in upstream Debian packages should also be reported to Debian: https://www.debian.org/security/
