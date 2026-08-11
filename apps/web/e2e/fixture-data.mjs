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
  topic: section === "expectations-moved" ? {
    id: ids.topic,
    title: "Will the Federal Reserve cut rates by September?",
    event_type: "monetary_policy",
    resolution_deadline_at: validUntil,
  } : null,
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
  topic: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
};

const expectationSeriesTimestamps = Array.from({ length: 29 }, (_, index) => (
  new Date(fixtureNow - (28 - index) * 6 * 60 * 60_000).toISOString()
));
const observedVariation = [0, 0.8, -0.35, 0.5, -0.65, 0.3, -0.15, 0.7, -0.45];

const seriesFor = (baseline, current, variant) => {
  const sevenDayStart = baseline - (current - baseline) * 0.35;
  const variationScale = Math.min(0.012, Math.max(0.003, Math.abs(current - baseline) * 0.12));
  return expectationSeriesTimestamps.map((timestamp, index) => {
    const anchored = index <= 24
      ? sevenDayStart + (baseline - sevenDayStart) * index / 24
      : baseline + (current - baseline) * (index - 24) / 4;
    const isAnchor = index === 24 || index === 28;
    const variation = isAnchor ? 0 : observedVariation[(index + variant) % observedVariation.length] * variationScale;
    return [timestamp, Number(Math.min(0.99, Math.max(0.01, anchored + variation)).toFixed(3))];
  });
};

const seriesQuality = (observations, coverageStatus) => {
  const values = observations.map((point) => point[1]);
  const timestamps = observations.map((point) => new Date(point[0]).getTime());
  const gaps = timestamps.slice(1).map((timestamp, index) => timestamp - timestamps[index]);
  return {
    coverage_status: coverageStatus,
    requested_window_hours: 168,
    observation_count: observations.length,
    points_returned: observations.length,
    first_observed_at: observations.at(0)?.[0] ?? null,
    last_observed_at: observations.at(-1)?.[0] ?? null,
    span_hours: timestamps.length > 1 ? (timestamps.at(-1) - timestamps[0]) / 3_600_000 : 0,
    max_gap_hours: gaps.length ? Math.max(...gaps) / 3_600_000 : 0,
    probability_range_percentage_points: values.length
      ? Number(((Math.max(...values) - Math.min(...values)) * 100).toFixed(2))
      : 0,
  };
};

const expectationObservations = [
  [ids.topic, "Will the Federal Reserve cut rates by September?", "monetary_policy", 0.85, 21, 0.64],
  ["f1111111-1111-4111-8111-111111111111", "Will U.S. headline inflation fall below 3% this quarter?", "macroeconomics", 0.58, -4, 0.62],
  ["f2222222-2222-4222-8222-222222222222", "Will the EU publish the next AI Act implementation guidance this month?", "regulation", 0.73, 6, 0.67],
  ["f3333333-3333-4333-8333-333333333333", "Will a solid-state battery pilot clear its next energy-density milestone?", "research", 0.41, 3, 0.38],
  ["f4444444-4444-4444-8444-444444444444", "Will the Bank of England hold its policy rate at the next meeting?", "monetary_policy", 0.69, 2.4, 0.666],
  ["f5555555-5555-4555-8555-555555555555", "Will U.S. GDP growth remain above 2% this quarter?", "macroeconomics", 0.62, -1.8, 0.638],
  ["f6666666-6666-4666-8666-666666666666", "Will an AI model top the current reasoning benchmark this month?", "technology", 0.54, 8.2, 0.458],
  ["f7777777-7777-4777-8777-777777777777", "Will the next climate disclosure rule survive judicial review?", "regulation", 0.47, -5.1, 0.521],
].map(([id, title, eventType, probability, delta, baseline], index) => {
  const completeSeries = seriesFor(baseline, probability, index);
  let capturedSeries = completeSeries;
  let coverageStatus = "complete";
  if (index === 3) {
    capturedSeries = completeSeries.slice(-11);
    coverageStatus = "insufficient_observations";
  } else if (index === 4) {
    capturedSeries = completeSeries.slice(-24);
    coverageStatus = "partial_window";
  } else if (index === 5) {
    capturedSeries = completeSeries.map(([timestamp]) => [timestamp, probability]);
    coverageStatus = "no_material_variation";
  } else if (index === 6) {
    capturedSeries = completeSeries.slice(0, -3);
    coverageStatus = "stale_endpoint";
  } else if (index === 7) {
    capturedSeries = [];
    coverageStatus = "insufficient_observations";
  }
  return {
    id,
    title,
    event_type: eventType,
    resolution_deadline_at: validUntil,
    status: "active",
    updated_at: dataAsOf,
    source_market_count: 1,
    source_market_status: "active",
    source_label: "Polymarket",
    current_probability: probability,
    current_observed_at: dataAsOf,
    baseline_probability_24h: baseline,
    baseline_observed_at: previousComposedAt,
    delta_24h_percentage_points: delta,
    series: capturedSeries,
    series_quality: seriesQuality(capturedSeries, coverageStatus),
  };
});

const leadSeries = seriesFor(0.64, 0.85, 9).slice(-11);
const leadSeriesQuality = seriesQuality(leadSeries, "insufficient_observations");
const secondarySeries = seriesFor(0.55, 0.68, 8).slice(-11);
const secondarySeriesQuality = seriesQuality(secondarySeries, "insufficient_observations");

const judgmentStatements = [
  [ids.lead, "expectations-moved", "September rate cut repriced to 85%.", "up", "+21.0pp", "CME FedWatch"],
  [ids.time, "expectations-moved", "Q3 GDP nowcast moved above its prior range.", "up", "+13.0pp", "Atlanta Fed GDPNow"],
  [ids.state, "rules-moved", "EU AI Act implementation phase is effective.", "neutral", "adopted → effective", "Official Journal of the EU"],
  [ids.feed1, "expectations-moved", "Headline inflation below 3% became less likely.", "down", "-4.0pp", "Polymarket"],
  [ids.feed2, "rules-moved", "Two adopted rules become effective this week.", "neutral", null, "Federal Register"],
  [ids.feed3, "research-frontier", "Battery materials work crossed into pilot evidence.", "up", null, "OpenAlex"],
  [ids.document, "rules-moved", "Article 5 expanded the prohibited-practices test.", "neutral", null, "Official Journal of the EU"],
  [ids.evidence, "research-frontier", "Independent replication appeared for the battery benchmark.", "up", null, "OpenAlex"],
  [ids.resolution, "expectations-moved", "EU AI implementation forecast resolved in line with the recorded probability.", "neutral", null, "Open Signal resolver"],
  ["12121212-1212-4212-8212-121212121212", "rules-moved", "Cybersecurity reporting requirements entered final review.", "neutral", "proposed → review", "Federal Register"],
  ["13131313-1313-4313-8313-131313131313", "expectations-moved", "A new reasoning benchmark leader became more likely.", "up", "+8.2pp", "Polymarket"],
  ["14141414-1414-4414-8414-141414141414", "rules-moved", "Climate disclosure litigation moved to merits briefing.", "neutral", "filed → briefing", "Federal Register"],
].map(([id, sectionId, statement, direction, change, sourceLabel], index) => ({
  id,
  section_id: sectionId,
  claim_type: sectionId === "rules-moved" ? "source_fact" : "derived_observation",
  statement,
  direction,
  change,
  confidence: 0.86,
  confidence_label: index % 4 === 0 ? "medium-high" : "high",
  epistemic_status: "verified observation",
  status: "verified",
  source_label: sourceLabel,
  evidence_count: 3 + index % 5,
  issued_at: assessedAt,
  updated_at: assessedAt,
  valid_until: validUntil,
}));

const ruleWatch = [
  ["rw-1", "EU AI Act implementation guidance", "adopted", "effective", "European Commission", "EU"],
  ["rw-2", "Cyber incident reporting requirements", "proposed", "final review", "CISA", "US"],
  ["rw-3", "Climate disclosure implementation schedule", "filed", "briefing", "SEC", "US"],
  ["rw-4", "Professional fireworks certification rule", "proposed", "final", "Transportation Department", "US"],
  ["rw-5", "Pesticide tolerance exemption", "proposed", "final", "EPA", "US"],
  ["rw-6", "Class D and E airspace amendment", "notice", "final", "FAA", "US"],
].map(([id, title, previousState, currentState, authority, jurisdiction]) => ({
  id,
  title,
  rule_type: "rule",
  previous_state: previousState,
  current_state: currentState,
  announced_at: previousComposedAt,
  adopted_at: assessedAt,
  effective_at: validUntil,
  enforcement_at: null,
  updated_at: assessedAt,
  authority,
  jurisdiction,
  transition_at: assessedAt,
  transition_confidence: 0.96,
  source_label: "Federal Register",
}));

const researchWatch = [
  {
    id: "rs-1", candidate_type: "institution_entry",
    headline: "New institutional output appeared in Generative AI and foundation models",
    entity: "Microsoft Research Asia", topic_label: "Generative AI and foundation models",
    topic_ids: ["generative-ai"], metric: "0 → 5 works", direction: "up",
    window_label: "2025–2026 YTD", baseline_label: "Before 2025", evidence_count: 5,
    screening_stage: "investigated", source_label: "OpenAlex", detected_at: assessedAt,
  },
  {
    id: "rs-2", candidate_type: "institution_entry",
    headline: "Institutional research activity accelerated in Quantum computing",
    entity: "Xanadu", topic_label: "Quantum computing", topic_ids: ["quantum-computing"],
    metric: "4 → 18 works", direction: "up", window_label: "2025–2026 YTD",
    baseline_label: "Before 2025", evidence_count: 18, screening_stage: "detected",
    source_label: "OpenAlex", detected_at: assessedAt,
  },
  {
    id: "rs-3", candidate_type: "stage_transition",
    headline: "Oncology immunotherapy trials span Phase 1 and Phase 2",
    entity: "National Cancer Institute", topic_label: "Oncology immunotherapy",
    topic_ids: ["oncology-immunotherapy"], metric: "2 phases · 7 studies", direction: "neutral",
    window_label: "Registry portfolio as of Aug 2026", baseline_label: "Cross-sectional phase coverage",
    evidence_count: 7, screening_stage: "investigated", source_label: "ClinicalTrials.gov",
    detected_at: assessedAt,
  },
  {
    id: "rs-4", candidate_type: "stage_transition",
    headline: "Synthetic biology trials span Early Phase 1 and Phase 2",
    entity: "Orchard Therapeutics", topic_label: "Synthetic biology", topic_ids: ["synthetic-biology"],
    metric: "2 phases · 4 studies", direction: "neutral", window_label: "Registry portfolio as of Aug 2026",
    baseline_label: "Cross-sectional phase coverage", evidence_count: 4, screening_stage: "detected",
    source_label: "ClinicalTrials.gov", detected_at: assessedAt,
  },
  {
    id: "rs-5", candidate_type: "cross_topic_relation",
    headline: "Research connections increased: Generative AI and foundation models × Oncology immunotherapy",
    entity: "Cross-topic literature", topic_label: "Generative AI and foundation models × Oncology immunotherapy",
    topic_ids: ["generative-ai", "oncology-immunotherapy"], metric: "2 → 9 papers", direction: "up",
    window_label: "2025–2026 YTD", baseline_label: "Before 2025", evidence_count: 9,
    screening_stage: "investigated", source_label: "OpenAlex", detected_at: assessedAt,
  },
  {
    id: "rs-6", candidate_type: "cross_topic_relation",
    headline: "Research connections increased: Quantum computing × Synthetic biology",
    entity: "Cross-topic literature", topic_label: "Quantum computing × Synthetic biology",
    topic_ids: ["quantum-computing", "synthetic-biology"], metric: "1 → 4 papers", direction: "up",
    window_label: "2025–2026 YTD", baseline_label: "Before 2025", evidence_count: 4,
    screening_stage: "detected", source_label: "OpenAlex", detected_at: assessedAt,
  },
];

const publicationContext = {
  version: "1.2.0",
  snapshot_bound: true,
  captured_at: composedAt,
  counts: {
    verified_claims: judgmentStatements.length,
    expectation_observations: expectationObservations.length,
    rules_tracked: ruleWatch.length,
    research_screening: 12,
    source_records_24h: 266,
  },
  claims: judgmentStatements,
  expectations: expectationObservations,
  rules: ruleWatch,
  research: researchWatch,
  coverage: [
    ["openalex", "OpenAlex", 220, 220],
    ["federal-register", "Federal Register", 40, 34],
    ["polymarket-gamma", "Polymarket", 8, 8],
    ["clinicaltrials-gov", "ClinicalTrials.gov", 6, 4],
  ].map(([source_slug, source_label, records_total, records_24h]) => ({
    source_slug,
    source_label,
    records_total,
    records_24h,
    latest_ingested_at: dataAsOf,
  })),
};

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
  publication_context: publicationContext,
  slots: [
    {
      id: "lead-region", type: "lead", size: "lead_large", required: true, collapsible: false, desktop_order: 10, mobile_order: 10,
      items: [item({
        id: "plan-lead", slot: "lead", section: "expectations-moved", family: "signal-hero", component: "signal-hero.expectations", claimId: ids.lead,
        headline: "September rate cut became 21 points more likely.", source: "CME FedWatch",
        fields: { expectation_title: "September rate cut", headline: "September rate cut became 21 points more likely.", start_probability: 64, current_probability: 85, delta_percentage_points: 21, window: "past 24 hours", series: leadSeries, series_quality: leadSeriesQuality, observation: "Three sustained upward moves occurred in the period.", analysis: "The repricing persisted after the initial spike.", assessment: "The system does not infer participant motivation.", trend: "up" },
      })],
    },
    {
      id: "secondary-signals", type: "secondary", size: "medium", required: true, collapsible: false, desktop_order: 20, mobile_order: 30,
      items: [
        item({ id: "plan-time", slot: "secondary", section: "expectations-moved", family: "time-series", component: "time-series.probability-move", claimId: ids.time, headline: "Q3 GDP nowcast moved above its prior range.", source: "Atlanta Fed GDPNow", fields: { start_probability: 55, current_probability: 68, delta_percentage_points: 13, series: secondarySeries, series_quality: secondarySeriesQuality, observation: "The change persisted across three releases." } }),
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
  publication_context: {
    ...publicationContext,
    counts: { ...publicationContext.counts, verified_claims: 0 },
    claims: [],
  },
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
  claim: { id: ids.lead, claim_type: "derived_observation", public_statement: "September rate cut became 21 points more likely.", status: "verified", desk_id: "expectations-desk", issued_at: assessedAt, valid_from: validFrom, valid_until: validUntil, materially_updated_at: assessedAt, evidence_policy_version: "sealed-v1" },
  observation: "Three sustained upward moves occurred in the seven-day period.",
  analysis: { summary: "The repricing persisted after the initial spike and appeared across independent market inputs.", structured_proposition: { predicate: "probability_move", operator: "increased_by", value: 21 }, predicate: "probability_move", operator: "increased_by", value: 21 },
  assessment: { summary: "Open Signal does not infer participant motivation; the durable change is the supported claim.", confidence: 0.86, confidence_label: "high", epistemic_status: "verified observation", model_version: "lead-signal-v2.3", charter_version: "os-charter-v1.4" },
  evidence: { items: [{ title: "CME FedWatch probability series", type: "market-implied probability", value: "64% → 85%", observed_at: "2026-08-08T14:25:00Z" }, { title: "Open Signal numeric replay", type: "deterministic calculation", value: "+21 percentage points" }], snapshot_hash: "fixture-evidence-snapshot-hash" },
  supporting_evidence: { items: [{ title: "Atlanta Fed GDPNow", type: "economic forecast", observed_at: "2026-08-08T13:58:00Z" }], snapshot_hash: "fixture-evidence-snapshot-hash" },
  counterevidence: { items: [{ title: "FOMC member remarks", type: "official communication", observed_at: "2026-08-08T10:15:00Z" }], snapshot_hash: "fixture-evidence-snapshot-hash" },
  evidence_record: { object_hash: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", object_key: "public/evidence/v1/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.json", byte_size: 2048, content_type: "application/json; charset=utf-8", policy_version: "1.0.0", sealed_at: assessedAt, url: "https://evidence.open-signal.test/public/evidence/v1/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.json" },
  uncertainty: { unresolved_questions: ["Whether the repricing persists after the CPI release."], known_limitations: ["Market positioning can move without a policy probability change."] },
  method: { calculation_ids: ["calc-fixture-001"], source_coverage: { sources: 4, independent_sources: 3 } },
  agent_lineage: { lineage_id: "expectations-lead-v2", desk_id: "expectations-desk", name: "Expectations Desk", foundation_model: "DeepSeek", model_version: "v2.3", charter_id: "expectations-charter", charter_version: "v1.4", status: "active" },
  version_history: [{ version_number: 1, public_statement: "September rate cut became 21 points more likely.", change_type: "create", change_reason: "Initial verified publication", confidence: 0.86, created_at: assessedAt }],
  resolution_contract: { id: "resolution-fixture", evaluation_deadline: validUntil, status: "locked" },
  topic: { id: ids.topic, title: "Will the Federal Reserve cut rates by September?", event_type: "monetary_policy", resolution_deadline_at: validUntil },
  locale: { requested: "en", published: "en", fallback_used: false, translation_provenance: null },
};

export const topicFixture = {
  topic: {
    id: ids.topic,
    title: "Will the Federal Reserve cut rates by September?",
    event_type: "monetary_policy",
    outcome_type: "binary",
    resolution_deadline_at: validUntil,
    resolution_authority: "Federal Reserve",
    resolution_rule_summary: "Resolves Yes if the target federal funds range is lowered on or before the September meeting.",
    status: "active",
    canonicalization_version: "canonicalizer-v1",
    created_at: previousComposedAt,
    updated_at: assessedAt,
  },
  source_event: {
    id: "polymarket-fed-september",
    title: "Federal Reserve policy by September",
    slug: "fed-rate-cut-september",
    tags: ["Federal Reserve", "interest rates", "monetary policy"],
    source_url: "https://polymarket.com/",
  },
  markets: [
    {
      id: "market-fixture-1",
      external_market_id: "fed-september-cut",
      question: "Will the Federal Reserve cut rates by September?",
      description: "Binary prediction market.",
      outcome_labels: ["Yes", "No"],
      ends_at: validUntil,
      liquidity: 2_450_000,
      volume: 18_700_000,
      status: "active",
      current_probability: 0.85,
      current_observed_at: dataAsOf,
      baseline_probability_24h: 0.64,
      baseline_observed_at: previousComposedAt,
      delta_24h_percentage_points: 21,
      source_url: "https://polymarket.com/",
      tags: ["Federal Reserve", "rates"],
    },
  ],
  signals: [
    {
      id: ids.lead,
      public_statement: "September rate cut became 21 points more likely.",
      claim_type: "derived_observation",
      status: "verified",
      confidence: 0.86,
      confidence_label: "high",
      epistemic_status: "verified observation",
      issued_at: assessedAt,
      updated_at: assessedAt,
    },
  ],
  method: { summary: "Open Signal preserves the source resolution contract and separates market probability from editorial assessment." },
};

export { ids };
