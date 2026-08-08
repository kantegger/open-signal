const fixtureNow = Date.now();
const composedAt = new Date(fixtureNow - 3 * 60_000).toISOString();
const dataAsOf = new Date(fixtureNow - 10 * 60_000).toISOString();
const assessedAt = new Date(fixtureNow - 6 * 60_000).toISOString();
const validFrom = new Date(fixtureNow - 10 * 60_000).toISOString();
const validUntil = new Date(fixtureNow + 7 * 24 * 60 * 60_000).toISOString();
const previousComposedAt = new Date(fixtureNow - 24 * 60 * 60_000).toISOString();

const trust = (claimId, source, evidence = 5) => ({
  claim_id: claimId,
  claim_status: "verified",
  claim_type: "derived_observation",
  confidence: 0.86,
  confidence_label: "high",
  epistemic_status: "verified observation",
  source_label: source,
  evidence_count: evidence,
  counterevidence_count: 1,
  snapshot_hash: "fixture-snapshot-hash",
});

const times = (observedAt = dataAsOf) => ({
  data_as_of: observedAt,
  assessed_at: assessedAt,
  composed_at: composedAt,
  materially_updated_at: assessedAt,
  expires_at: validUntil,
});

const item = ({ id, slot, position = 0, section, family, component, headline, fields, source, claimId }) => ({
  id,
  slot_id: slot,
  position,
  section_instance_id: null,
  section_id: section,
  claim_ids: [claimId],
  component_id: component,
  component_family: family,
  component_version: "1.0.0",
  component_variant: slot === "lead" ? "lead" : ["live_feed", "digest", "utility"].includes(slot) ? "compact" : "standard",
  headline,
  dek: null,
  display_fields: fields,
  hidden_detail_fields: {},
  visual_priority: position + 1,
  mobile_priority: position + 1,
  generated_by: "fixture-composer",
  freshness_state: "current",
  trust: trust(claimId, source),
  times: times(),
  evidence_preview: {
    primary: [{ title: source, type: "primary source" }],
    supporting: [],
    counter: [{ title: "Alternative data release", type: "counterevidence" }],
    source_coverage: { sources: 4 },
    unresolved_questions: ["Whether the change persists after the next release."],
    known_limitations: ["The current window covers seven days."],
  },
  locale: { requested: "en", published: "en", fallback_used: false },
});

const ids = {
  lead: "11111111-1111-4111-8111-111111111111",
  time: "22222222-2222-4222-8222-222222222222",
  state: "33333333-3333-4333-8333-333333333333",
  feed1: "44444444-4444-4444-8444-444444444444",
  feed2: "55555555-5555-4555-8555-555555555555",
  feed3: "66666666-6666-4666-8666-666666666666",
  document: "77777777-7777-4777-8777-777777777777",
  evidence: "88888888-8888-4888-8888-888888888888",
  resolution: "99999999-9999-4999-8999-999999999999",
  archive: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
};

const series = [
  ["2026-08-01T00:00:00Z", 0.64],
  ["2026-08-02T00:00:00Z", 0.66],
  ["2026-08-03T00:00:00Z", 0.66],
  ["2026-08-04T00:00:00Z", 0.67],
  ["2026-08-05T00:00:00Z", 0.70],
  ["2026-08-06T00:00:00Z", 0.78],
  ["2026-08-07T00:00:00Z", 0.84],
  ["2026-08-08T00:00:00Z", 0.85],
];

export const frontPageFixture = {
  snapshot: {
    id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    edition_date: composedAt.slice(0, 10),
    composed_at: composedAt,
    published_at: composedAt,
    status: "published",
    trigger_type: "section_refresh",
    supersedes_edition_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    previous_edition_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    composer_version: "os-048",
    policy_version: "1.0.0",
    correction_count: 0,
    is_current: true,
    publication_mode: "rolling_snapshot",
  },
  freshness: {
    state: "current",
    items: { current: 10, aging: 0 },
    sections: {
      "expectations-moved": { current: 4, aging: 0 },
      "rules-moved": { current: 4, aging: 0 },
      "research-frontier": { current: 2, aging: 0 },
    },
    retired_during_compile: 1,
    last_successful_compile_at: composedAt,
    channel_updated_at: composedAt,
  },
  sections: ["expectations-moved", "rules-moved", "research-frontier"],
  slots: [
    {
      id: "lead-region", type: "lead", size: "lead_large", required: true, collapsible: false, desktop_order: 10, mobile_order: 10,
      items: [item({
        id: "plan-lead", slot: "lead", section: "expectations-moved", family: "signal-hero", component: "signal-hero.expectations", claimId: ids.lead,
        headline: "September rate cut became 21 points more likely.", source: "CME FedWatch",
        fields: { expectation_title: "September rate cut", headline: "September rate cut became 21 points more likely.", start_probability: 64, current_probability: 85, delta_percentage_points: 21, window: "past 7 days", series, observation: "Three sustained upward moves occurred in the period.", analysis: "The repricing persisted after the initial spike.", assessment: "The system does not infer participant motivation.", trend: "up" },
      })],
    },
    {
      id: "secondary-signals", type: "secondary", size: "medium", required: true, collapsible: false, desktop_order: 20, mobile_order: 30,
      items: [
        item({ id: "plan-time", slot: "secondary", section: "expectations-moved", family: "time-series", component: "time-series.probability-move", claimId: ids.time, headline: "Q3 GDP nowcast moved above its prior range.", source: "Atlanta Fed GDPNow", fields: { start_probability: 55, current_probability: 68, delta_percentage_points: 13, series, observation: "The change persisted across three releases." } }),
        item({ id: "plan-state", slot: "secondary", position: 1, section: "rules-moved", family: "state-transition", component: "state-transition.rule-stage", claimId: ids.state, headline: "EU AI obligations entered the implementation phase.", source: "Official Journal of the EU", fields: { previous_state: "adopted", current_state: "effective", transition_date: "2026-08-02", observation: "The implementation phase began on 2 August 2026." } }),
      ],
    },
    {
      id: "live-signal-feed", type: "live_feed", size: "strip", required: true, collapsible: false, desktop_order: 30, mobile_order: 20,
      items: [
        item({ id: "plan-feed-1", slot: "live_feed", section: "expectations-moved", family: "signal-feed", component: "signal-feed.compact-change", claimId: ids.feed1, headline: "September rate cut probability: 85% (was 83%).", source: "CME FedWatch", fields: { trend: "up", change_value: "+2pp" } }),
        item({ id: "plan-feed-2", slot: "live_feed", position: 1, section: "rules-moved", family: "signal-feed", component: "signal-feed.upcoming-event", claimId: ids.feed2, headline: "EU AI Act entered implementation phase.", source: "Official Journal of the EU", fields: { current_state: "verified" } }),
        item({ id: "plan-feed-3", slot: "live_feed", position: 2, section: "research-frontier", family: "signal-feed", component: "signal-feed.compact-change", claimId: ids.feed3, headline: "Solid-state battery pilot results published.", source: "Energy Materials Journal", fields: { current_state: "verified" } }),
      ],
    },
    {
      id: "significant-changes", type: "digest", size: "full_width", required: true, collapsible: false, desktop_order: 40, mobile_order: 40,
      items: [
        item({ id: "plan-digest-1", slot: "digest", section: "expectations-moved", family: "signal-feed", component: "signal-feed.compact-change", claimId: ids.feed1, headline: "September rate cut repriced to 85%.", source: "CME FedWatch", fields: { trend: "up" } }),
        item({ id: "plan-digest-2", slot: "digest", position: 1, section: "rules-moved", family: "signal-feed", component: "signal-feed.compact-change", claimId: ids.feed2, headline: "EU AI Act implementation phase is effective.", source: "Official Journal of the EU", fields: { current_state: "effective" } }),
      ],
    },
    {
      id: "main-content", type: "main", size: "medium", required: false, collapsible: true, desktop_order: 50, mobile_order: 50,
      items: [
        item({ id: "plan-document", slot: "main", section: "rules-moved", family: "document-change", component: "document-change.rule-diff", claimId: ids.document, headline: "Article 5 materially expanded the prohibited-practices test.", source: "Official Journal of the EU", fields: { old_text: "Systems that deploy subliminal techniques are prohibited.", new_text: "Systems that exploit vulnerabilities related to age, disability, or socio-economic situation are prohibited.", change_type: "substantive", diff_summary: "The effective text expands the protected circumstances." } }),
        item({ id: "plan-evidence", slot: "main", position: 1, section: "research-frontier", family: "evidence-relationship", component: "evidence-relationship.evidence-timeline", claimId: ids.evidence, headline: "Battery materials work crossed from benchmark to pilot evidence.", source: "Energy Materials Journal", fields: { events: [{ date: "2026-07-28", title: "Energy density benchmark released", source: "NREL" }, { date: "2026-08-03", title: "Independent replication posted", source: "OpenAlex" }, { date: "2026-08-08", title: "Pilot results published", source: "Energy Materials Journal" }] } }),
        item({ id: "plan-resolution", slot: "main", position: 2, section: "expectations-moved", family: "resolution-comparison", component: "resolution.forecast-vs-outcome", claimId: ids.resolution, headline: "EU AI Act implementation forecast resolved.", source: "Official Journal of the EU", fields: { original_claim: "EU AI Act entered implementation phase", final_probability: 0.85, outcome: "Adopted → Effective", brier_contribution: "0.0225" } }),
      ],
    },
    {
      id: "utility", type: "utility", size: "small", required: false, collapsible: true, desktop_order: 60, mobile_order: 60,
      items: [item({ id: "plan-utility", slot: "utility", section: "rules-moved", family: "signal-feed", component: "signal-feed.near-deadline", claimId: ids.feed2, headline: "Two adopted rules become effective this week.", source: "Official registers", fields: { current_state: "near deadline" } })],
    },
    {
      id: "archive-region", type: "archive", size: "full_width", required: true, collapsible: false, desktop_order: 70, mobile_order: 70,
      items: [item({ id: "plan-archive", slot: "archive", section: "archive", family: "archive-snapshot", component: "archive-snapshot.archive-card", claimId: ids.archive, headline: "Previous verified front page", source: "Open Signal ledger", fields: { edition_date: "2026-08-07", primary_signal: "EU AI Act implementation", resolved_claim_ids: 12, correction_count: 0 } })],
    },
  ],
  archive: [
    { id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", edition_date: composedAt.slice(0, 10), composed_at: composedAt, status: "published", sections: ["expectations-moved", "rules-moved", "research-frontier"], claim_count: 10, correction_count: 0, trigger_type: "section_refresh" },
    { id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", edition_date: previousComposedAt.slice(0, 10), composed_at: previousComposedAt, status: "published", sections: ["expectations-moved", "rules-moved"], claim_count: 7, correction_count: 0, trigger_type: "scheduled" },
  ],
  method: { summary: "Open Signal separates observation, analysis, and assessment; publishes only verified Render Plans; and preserves every snapshot.", composer_version: "os-048", policy_version: "1.0.0" },
  system_state: { status: "operational", publication_channel: "front-page", last_checked_at: composedAt },
  locale: { requested: "en", published: "en", fallback_used: false, translation_provenance: null },
};

export const emptyFrontPageFixture = {
  ...frontPageFixture,
  snapshot: {
    ...frontPageFixture.snapshot,
    id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    status: "sparse",
    trigger_type: "hard_expiry",
    supersedes_edition_id: frontPageFixture.snapshot.id,
    previous_edition_id: frontPageFixture.snapshot.id,
  },
  freshness: {
    ...frontPageFixture.freshness,
    items: { current: 0, aging: 0 },
    sections: {},
    retired_during_compile: 10,
  },
  sections: [],
  slots: frontPageFixture.slots.map((publicationSlot) => ({
    ...publicationSlot,
    items: [],
  })),
  archive: [
    {
      ...frontPageFixture.archive[0],
      id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
      sections: [],
      claim_count: 0,
      trigger_type: "hard_expiry",
      status: "sparse",
    },
    ...frontPageFixture.archive,
  ],
};

export const claimFixture = {
  claim: { id: ids.lead, claim_type: "derived_observation", public_statement: "September rate cut became 21 points more likely.", status: "verified", desk_id: "expectations-desk", issued_at: assessedAt, valid_from: validFrom, valid_until: validUntil, materially_updated_at: assessedAt },
  observation: "Three sustained upward moves occurred in the seven-day period.",
  analysis: { summary: "The repricing persisted after the initial spike and appeared across independent market inputs.", structured_proposition: { predicate: "probability_move", operator: "increased_by", value: 21 }, predicate: "probability_move", operator: "increased_by", value: 21 },
  assessment: { summary: "Open Signal does not infer participant motivation; the durable change is the supported claim.", confidence: 0.86, confidence_label: "high", epistemic_status: "verified observation", model_version: "lead-signal-v2.3", charter_version: "os-charter-v1.4" },
  evidence: { items: [{ title: "CME FedWatch probability series", type: "market-implied probability", value: "64% → 85%", observed_at: "2026-08-08T14:25:00Z" }, { title: "Open Signal numeric replay", type: "deterministic calculation", value: "+21 percentage points" }], snapshot_hash: "fixture-evidence-snapshot-hash" },
  supporting_evidence: { items: [{ title: "Atlanta Fed GDPNow", type: "economic forecast", observed_at: "2026-08-08T13:58:00Z" }], snapshot_hash: "fixture-evidence-snapshot-hash" },
  counterevidence: { items: [{ title: "FOMC member remarks", type: "official communication", observed_at: "2026-08-08T10:15:00Z" }], snapshot_hash: "fixture-evidence-snapshot-hash" },
  uncertainty: { unresolved_questions: ["Whether the repricing persists after the CPI release."], known_limitations: ["Market positioning can move without a policy probability change."] },
  method: { calculation_ids: ["calc-fixture-001"], source_coverage: { sources: 4, independent_sources: 3 } },
  agent_lineage: { lineage_id: "expectations-lead-v2", desk_id: "expectations-desk", name: "Expectations Desk", foundation_model: "DeepSeek", model_version: "v2.3", charter_id: "expectations-charter", charter_version: "v1.4", status: "active" },
  version_history: [{ version_number: 1, public_statement: "September rate cut became 21 points more likely.", change_type: "create", change_reason: "Initial verified publication", confidence: 0.86, created_at: assessedAt }],
  resolution_contract: { id: "resolution-fixture", evaluation_deadline: validUntil, status: "locked" },
  locale: { requested: "en", published: "en", fallback_used: false, translation_provenance: null },
};

export { ids };
