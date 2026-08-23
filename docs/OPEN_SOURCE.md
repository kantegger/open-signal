# Open-source readiness

Open Signal is licensed under Apache License 2.0. The hosted site at
`os.yhleo.com` is a reference deployment; operators can choose their own data
sources, infrastructure, model providers, budgets, and update cadence.

## Pre-publication security review

On 2026-08-23, the complete Git history (105 commits) was scanned with
Gitleaks 8.30.1 in addition to a tracked-file and sensitive-filename review.
No credentials, private keys, or production connection strings were found.

Three `generic-api-key` findings were manually verified as public fixture
data: two ClinicalTrials.gov pagination tokens and one public reCAPTCHA site
key captured from a Federal Register page. `.gitleaks.toml` allows only those
specific rule, path, and line-pattern combinations. It does not exclude the
fixture directories from scanning.

CI scans the full fetched history on every pull request and every push to
`main`. Contributors should never commit secrets, including test credentials
that grant access to an external service. Use local environment files and
GitHub/Cloudflare/Vercel secret stores instead.
