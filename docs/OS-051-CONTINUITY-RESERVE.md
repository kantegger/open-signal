# OS-051 — Front-page continuity reserve

Status: accepted implementation contract
Depends on: OS-048 rolling front page, OS-050 event-aware selection

## Product decision

Current serves two legitimate reading rhythms at once:

- high-frequency readers need the newest verified changes first;
- daily or occasional readers still benefit from important signals published
  several hours or days earlier, provided their age is explicit and they remain
  materially valid.

An Edition refresh therefore does not mean that every item from the previous
Edition became irrelevant. The page has a fresh layer and a continuity layer.
The continuity layer exists to use otherwise-empty editorial capacity, never to
make old observations look new.

## Deterministic contract

The compiler applies these stages in order:

1. Compile new verified Section output and still-active items from the current
   Edition under the normal Slot, diversity, and repetition rules.
2. Measure the Secondary Signals Slot against its target of three items.
3. If capacity remains, inspect full editorial surfaces from immutable Editions
   generated within the last 720 hours.
4. Re-evaluate every historical candidate at the new composition time. Reject
   it when the Claim is invalid, the freshness hard age is exceeded, the source
   or canonical topic is no longer active, or an expectation deadline has
   passed.
5. Deduplicate by source event, canonical topic, Section subject, then Claim.
   Only one representative from an event family may enter the reserve.
6. Rank eligible candidates for Section and component-family diversity first,
   then current-vs-aging state, previous editorial importance, material recency,
   and visual priority.
7. Fill only the Secondary deficit. New and current candidates always keep
   priority over continuity candidates.

The bounded reserve may relax the ordinary per-Section and consecutive-family
layout caps only for the remaining Secondary deficit. It does not relax
verification, evidence, semantic validity, source state, deadline, or freshness.

## Public honesty and lineage

A continuity item preserves its original:

- `data_as_of`;
- `assessed_at`;
- `materially_updated_at`;
- Claim and Evidence Bundle links.

The UI already renders relative `Data as of` time and an `Aging · still valid`
state where applicable. The new Render Plan also stores
`hidden_detail_fields.publication_continuity` with its source Edition, source
Slot, continuity identity, and retained data timestamp. The Edition payload
records the carried-item count and source Edition IDs.

`composed_at` changes because the page is a new immutable snapshot. Observation
times do not change. This distinction is the trust boundary.

## Retirement and failure behaviour

- Hard expiry and semantic invalidators always win over density.
- A past expectation deadline is ineligible even if upstream source status has
  not yet changed from `active`.
- A composer-version change is a material reconciliation transition, so the
  next scheduled freshness run recompiles the page under this policy.
- If no eligible reserve item exists, a sparse page remains acceptable. The
  compiler never invents a card or repeats the same event to hit a quota.
