# OS-048 — Rolling Front Page and Publication Design Contract

## Decision status

Accepted for the Public Beta implementation.

This contract turns the existing `DailyEdition`, `RenderPlan`, Slot Registry,
Component Registry, Claim ledger, and verification gates into a continuously
recomposed public front page. `DailyEdition` remains the database name for
backward compatibility; product language calls each row an immutable edition
snapshot rather than a once-per-day issue.

## Product contract

Open Signal is a public signal institution, not a dashboard or a news feed.
Its first screen must let an informed generalist understand the most important
current change in roughly 30 seconds. The same published object must let a
professional verify the evidence, counterevidence, method, lineage, and version
history without encountering a second, contradictory interpretation.

The launch surface is English-first. Content and interface architecture must
support versioned localizations for Chinese, Japanese, French, RTL scripts, and
other future locales without creating a separate Claim truth per language.

## Atomic publication lifecycle

```text
verified Section output or expiry event
                 ↓
        active publication pool
                 ↓
      deterministic eligibility gate
                 ↓
       full seven-Slot composition
                 ↓
 Render Plan validation + page-level checks
                 ↓
  immutable snapshot stored transactionally
                 ↓
     current pointer changes atomically
```

- Section refreshes are independent. New verified output from one Section does
  not force unchanged Sections to pretend they also refreshed.
- A hard-expired item is removed from the active pool before composition.
- The compiler may omit an entire content Section. It must never publish a blank
  card, empty placeholder, partial page, or transient hole.
- Sparse pages are valid. Archive, Method, and System State preserve rhythm
  without manufacturing low-quality current content.
- A snapshot becomes public only after all Render Plans and page-level rules pass.
- If composition, persistence, or verification fails, the last verified snapshot
  stays current. Public freshness metadata makes that state visible.
- Corrections and rollbacks create new immutable snapshots; they do not mutate
  previous public history.

## Freshness and retirement policy

Freshness is evaluated per content item, not by a global “today” boundary.

| Content class | Soft age | Hard age | Behaviour after soft age |
|---|---:|---:|---|
| Live Feed | 6 hours | 24 hours | visually de-emphasize; remain truthful |
| Expectations | 24 hours | 72 hours | eligible outside Lead; show age |
| Rules | 3 days | 14 days | eligible while the legal state remains valid |
| Research | 7 days | 30 days | eligible while evidence remains current |
| Utility | event-driven | 24 hours after event | retire after semantic event or hard age |
| Lead tenure | — | 24 hours without material evidence | demote before retirement |

Claim `valid_until`, withdrawal, supersession, source retraction, resolution, and
other semantic invalidators override these maximum ages. Policy values belong in
a versioned machine-readable registry so that the compiler and operations views
use the same rules.

## Time semantics

Every public item may expose four distinct timestamps:

- `data_as_of`: when the underlying observation was true or sampled;
- `assessed_at`: when the Claim was verified or editorially assessed;
- `composed_at`: when the containing snapshot was compiled;
- `materially_updated_at`: when new evidence last changed the public meaning.

The interface must not collapse these into a generic “updated” label.

## Information architecture

The fixed shell contains Current, Expectations, Rules, Research, Method, Archive,
and System State. The current page uses all seven Slot types as a publication
grammar, while allowing optional content Slots to disappear cleanly:

1. Lead Region
2. Secondary Signals
3. Live Signal Feed
4. Significant Changes (Digest)
5. Main Content
6. Utility
7. Archive Region

Desktop order follows the registry. Mobile deliberately moves Live Feed before
Secondary Signals and uses a full-screen evidence sheet.

## Component family inventory

The renderer supports all eight registry families. It renders only fields present
in a verified Render Plan and degrades toward a simpler, more conservative form.

| Family | Primary visual grammar | Conservative fallback |
|---|---|---|
| Signal Hero | editorial lead with one domain-native visual | textual lead |
| Time Series | line or stepped change with explicit units | numeric comparison |
| State Transition | named states and authoritative dates | ordered state list |
| Document Change | old/new material text comparison | significant-change row |
| Signal Feed | compact chronological observations | plain chronological list |
| Evidence Relationship | sourced timeline or typed relations | evidence list |
| Resolution Comparison | forecast contract versus outcome | outcome table row |
| Archive Snapshot | frozen edition/resolution record | dated archive link |

## Visual system

The approved concepts establish a dark editorial instrument rather than a
financial terminal.

### Color tokens

- canvas: deep blue-charcoal (`#0b1217` family);
- raised shell: slightly lighter blue-charcoal, with no ornamental shadow;
- primary ink: warm off-white (`#eeeae0` family);
- secondary ink: cool neutral gray;
- rules: amber; expectations: clear blue; research: restrained green;
- destructive/correction: muted red;
- borders: one-pixel cool gray hairlines.

Color is always paired with text, shape, or position. Section color never doubles
as confidence or direction.

### Typography

- editorial serif for headlines and narrative emphasis;
- humanist sans-serif for prose and controls;
- monospaced face for numbers, timestamps, IDs, state labels, and provenance;
- body text is at least 16 px on mobile and remains usable at 200% zoom.

### Geometry and rhythm

- four-pixel spacing foundation;
- near-square corners, no floating-card grid, no decorative gradients;
- desktop navigation rail around 210 px and a fluid reading canvas;
- one-pixel rules create groups; whitespace creates hierarchy;
- charts use real SVG geometry derived from Render Plan data.

### Motion

- 150 ms feedback and 250–300 ms sheet transitions;
- transform and opacity only for continuous animation;
- `prefers-reduced-motion` removes nonessential movement;
- live updates do not reorder content while the reader is interacting with it.

## Trust layer and evidence disclosure

Every front-page item carries the smallest useful trust layer: source, confidence,
evidence count, Claim ID or evidence action, and semantically named time.

Selecting evidence opens a sheet over the current page. It presents, in order:

1. public Claim and status;
2. Observation, Analysis, and Open Signal Assessment;
3. confidence, coverage, rationale, and main uncertainty;
4. primary evidence and counterevidence;
5. alternative explanation and method/calculation summary;
6. agent lineage, model, and charter versions;
7. Claim version history and resolution contract;
8. link to the permanent Claim page.

The permanent page preserves the same hierarchy and complete public record.

## Accessibility and internationalization

- WCAG AA contrast is the minimum; focus indication is visible on all controls.
- The evidence sheet is a labelled modal dialog, closes with Escape, traps focus,
  and restores focus to its trigger.
- Tables have a semantic small-screen representation; no required horizontal
  scrolling for the main reading path.
- Layout uses logical properties and avoids fixed English-length assumptions.
- Claims remain locale-neutral truth objects. Localized presentations are
  versioned, carry translation provenance, and may never silently alter numbers,
  dates, confidence, or Claim status.

## Acceptance criteria

- Public API returns validated Render Plans grouped by all seven Slot types.
- Every stored component item has its own Render Plan row; no slot silently drops
  all but its first item.
- The current endpoint exposes immutable snapshot identity, composition state,
  semantic timestamps, Section freshness, and ordered Slot contents.
- Expiring a Section item recompiles a complete page and cannot reveal a partial
  publication state.
- If retirement removes the final active content Section, the compiler may
  publish a verified zero-content snapshot: all seven Slot descriptors, Site
  Shell, Method, System State, and Archive remain intact, with no empty cards.
- Desktop, tablet, and mobile layouts preserve the approved reading hierarchy.
- Loading uses structural skeletons; recoverable errors offer retry without
  discarding the last good snapshot.
- All eight Component Families and sparse/fallback states have automated fixtures.
- Homepage, evidence sheet, permanent Claim page, retry flow, keyboard flow, and
  mobile ordering are covered by browser tests.
