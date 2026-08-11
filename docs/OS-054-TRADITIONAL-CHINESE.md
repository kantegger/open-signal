# OS-054 — Traditional Chinese publication view

## Decision

Traditional Chinese is Open Signal's first non-English publication language.
It is a versioned view over the same verified public record, not a second Claim
system.

- English remains at `/`, `/explore`, `/editions`, `/method`, and permanent
  record routes.
- Traditional Chinese uses `/zh-Hant` plus the same route suffix and stable
  entity identifier.
- `/zh-TW` and `/zh-HK` permanently redirect to `/zh-Hant`.
- No browser-language redirect is performed. Readers and search engines choose
  an explicit, stable URL.

## Truth and translation boundary

PostgreSQL Claims, structured propositions, statuses, confidence values,
timestamps, source evidence, and evidence URLs are locale-neutral truth. The
publication localizer may translate only presentation strings after verification.

The localizer protects URLs, UUIDs, numbers, dates, percentages, percentage
points, and time windows with exact placeholders. It rejects an incomplete
translation map, missing or duplicated placeholders, changed numeric tokens, or
an unsupported target locale. Evidence and structured-proposition subtrees are
never submitted for translation.

Each translated payload records:

- requested and published locale;
- whether fallback was used;
- translator, model, and localization-policy version;
- token use and estimated cost in the immutable localization bundle.

The original English Claim statement and slot headline are retained beside the
localized presentation for stable canonical routes and audit.

## Atomic delivery

The hourly publication queue runs English first and `zh-Hant` second. For a
Traditional Chinese Edition, delivery writes in this order:

1. one immutable localization bundle for the Edition;
2. immutable localized front-page and Claim snapshots;
3. the localized manifest;
4. current localized Claim projections;
5. the `zh-Hant` front-page pointer;
6. the signed Vercel revalidation receipt.

Retries reuse the sealed localization bundle, so a failed notification cannot
produce a different translation for the same Edition. English and Traditional
Chinese failures are isolated. Until the first localized snapshot exists, the
web may use the English API projection only with a visible fallback notice.

## Search and interface contract

Every localized route sets `html[lang=zh-Hant]`, locale-specific metadata and
structured data, a canonical URL, and reciprocal English/Traditional Chinese
`hreflang` links. Sitemap entries include both language variants.

Static interface and method copy is maintained in code. Source titles and
dynamic records without a sealed localized presentation remain in English with
an explicit notice; the interface never implies that machine-localized text is
source wording.

Future Japanese and French support should extend the same locale registry,
translation safety layer, immutable key scheme, schedule, and browser tests.
They must not introduce locale-specific Claim truth.
