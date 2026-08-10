# OS-050 — Event-Aware Expectation Selection Contract

## Status

Implementation contract for public Expectations discovery and presentation.
It extends OS-048 and OS-049 without changing proposition-level canonical
truth or the append-only Claim Ledger.

## Product invariant

Open Signal is a signal system, not a prediction-market directory. A source
event may expose dozens of binary outcome markets, but their existence does not
grant each outcome equal public attention. The system preserves the underlying
records while presenting only the propositions that explain why the event is
important now.

The pipeline therefore has four distinct layers:

1. **Discovery inventory** — source events and markets seen by the adapter.
2. **Monitoring cohort** — a bounded set sampled often enough to detect change.
3. **Public truth inventory** — eligible Canonical Expectations and permanent
   Topic and Claim URLs.
4. **Editorial projection** — event-ranked representatives used by Current and
   Explore.

A market leaving the monitoring cohort is not closed, resolved, or retired.
Monitoring membership and canonical lifecycle are separate states. The
canonical object and its history remain available; only the current projection
changes.

## Identity and grouping

- Canonical Expectations remain one binary proposition per source market.
- Event grouping is presentation-only and never merges Claim identities,
  resolution rules, histories, or calibration records.
- The primary family key is `(source_id, external_event_id)`.
- A market without trustworthy event identity is a singleton family keyed by
  `(source_id, source_market_id)`.
- Mutual exclusivity may be asserted only from explicit source metadata such as
  a Polymarket negative-risk slate. Shared wording alone is insufficient.

## Monitoring cohort

Polymarket discovery starts from event envelopes. Within each active event the
adapter preserves roles before applying the per-event monitoring cap:

- the three highest current probabilities;
- the two largest absolute 24-hour moves;
- the highest true 24-hour activity;
- the explicit `Other` outcome when present;
- remaining markets by 24-hour activity, then lifetime activity, liquidity,
  and probability as deterministic tie-breakers.

Retained event cohorts are consumed round-robin so one large slate cannot use
the entire global monitoring budget. A probability leader must not disappear
because zero-volume longshots accumulated high lifetime volume.

Volume windows are never substituted for one another. `volume24hr` and
lifetime `volume` remain separate dimensions; lifetime volume may only break a
tie after 24-hour activity.

The current cohort is derived from `monitoring_last_seen_at` relative to the
latest monitoring timestamp for that source. Falling outside that cohort hides
a proposition from the current projection but does not mutate its canonical
status.

## Public eligibility

An Expectations observation may enter the public projection only when all hard
gates pass:

- canonical and source-market status are active;
- the resolution deadline is in the future;
- it belongs to the current monitoring cohort;
- its latest probability is valid and no more than 72 hours old;
- its data-quality flags do not include stale, sparse, or unavailable.

An event then needs at least one public-interest reason:

- an active verified Claim in the last 72 hours;
- an absolute 24-hour probability move of at least 0.5 percentage points;
- at least USD 5,000 of aggregated 24-hour activity; or
- resolution within seven days.

These values belong to `expectation-selection-1.0.0`. A threshold change must
bump the selection version and add fixture-backed regression tests.

## Representative outcomes

Each selected event exposes at most three propositions. For an explicitly
exclusive slate the selector first preserves the current leader, then fills
remaining positions from distinct roles:

- latest verified Signal;
- largest material 24-hour mover;
- qualified tail anomaly;
- credible challenger;
- highest 24-hour activity.

A qualified tail anomaly has probability at or below 5%, at least a 0.5pp
24-hour move, at least USD 5,000 of 24-hour activity, and an absolute log-odds
change of at least `ln(2)`. Static near-zero outcomes are not signal.

Every returned member carries a machine-readable selection reason. The event
card exposes how many source outcomes were folded away. Missing baselines render
as missing; the UI must not manufacture a flat sparkline.

## Ordering and diversity

Event rank is deterministic and prioritizes:

1. verified Signal;
2. material repricing of at least 3pp;
3. observed move of at least 0.5pp;
4. near resolution;
5. current source activity.

Magnitude, same-window activity, observation time, deadline, and stable event
key break ties. Within each page, event-type concentration has a soft cap so a
single sports, elections, or crypto cluster cannot monopolise discovery.

## Surface contracts

- `/api/seo-index` remains the durable, broad crawlability inventory.
- `/api/explore` is the event-aware, independently paginated public projection.
- Explore Topics are event cards with no more than three representative
  propositions, not one card per binary outcome.
- Explore Recent Signals keeps only the latest current Claim per subject and no
  more than one Expectations representative per source event. Older snapshots
  remain accessible in the Claim Ledger and SEO index.
- Current captures the same selector output into its immutable Edition payload;
  it does not independently re-rank mutable live data.
- An Expectations editorial batch may create no more than one new Claim per
  source event in one run.

## Acceptance cases

The test suite must preserve these cases:

1. In a 20-outcome F1 slate, a 74% leader remains monitored and public even when
   zero-volume longshots have much higher lifetime volume.
2. The event renders once with at most three role-labelled outcomes and a folded
   count; it does not render 20 equal cards.
3. A material negative move is retained just like a positive move.
4. A qualified low-probability tail anomaly can be selected, while a static
   0.1% outcome cannot.
5. All canonical Topic URLs remain in the SEO inventory even when most members
   are absent from Explore.
6. Topic and Signal pagination advance independently against the same
   `ranking_as_of` snapshot.
