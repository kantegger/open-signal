import http from "node:http";
import {
  claimFixture,
  emptyFrontPageFixture,
  frontPageFixture,
  topicFixture,
} from "./fixture-data.mjs";

const port = Number(process.argv[2] ?? 8001);
let frontPageFailuresRemaining = 0;
let frontPageMode = "full";
const topicIndexFixtures = [
  {
    id: topicFixture.topic.id,
    title: topicFixture.topic.title,
    event_type: topicFixture.topic.event_type,
    current_probability: topicFixture.markets[0].current_probability,
    delta_24h_percentage_points: topicFixture.markets[0].delta_24h_percentage_points,
  },
  {
    id: "f1111111-1111-4111-8111-111111111111",
    title: "Will U.S. headline inflation fall below 3% this quarter?",
    event_type: "macroeconomics",
    current_probability: 0.58,
    delta_24h_percentage_points: -4,
  },
  {
    id: "f2222222-2222-4222-8222-222222222222",
    title: "Will the EU publish the next AI Act implementation guidance this month?",
    event_type: "regulation",
    current_probability: 0.73,
    delta_24h_percentage_points: 6,
  },
  {
    id: "f3333333-3333-4333-8333-333333333333",
    title: "Will a solid-state battery pilot clear its next energy-density milestone?",
    event_type: "research",
    current_probability: 0.41,
    delta_24h_percentage_points: 3,
  },
].map((topic) => ({
  ...topic,
  resolution_deadline_at: topicFixture.topic.resolution_deadline_at,
  status: "active",
  source_market_count: 1,
  updated_at: topicFixture.topic.updated_at,
  current_observed_at: topicFixture.markets[0].current_observed_at,
  baseline_observed_at: topicFixture.markets[0].baseline_observed_at,
}));

const exploreEventGroups = [
  {
    key: "polymarket:event:f1-2026",
    title: "2026 F1 Drivers' Champion",
    event_type: "sports",
    external_event_id: "f1-2026",
    source_label: "Polymarket Gamma",
    source_url: "https://polymarket.com/event/2026-f1-drivers-champion",
    source_member_count: 20,
    eligible_member_count: 12,
    suppressed_member_count: 17,
    is_exclusive_slate: true,
    selection_reason: "material_repricing",
    volume_24h: 432000,
    largest_move_24h_percentage_points: 6,
    latest_observed_at: topicFixture.topic.updated_at,
    resolution_deadline_at: topicFixture.topic.resolution_deadline_at,
    members: [
      {
        topic_id: topicFixture.topic.id,
        title: "Will Kimi Antonelli be the 2026 F1 Drivers' Champion?",
        option_label: "Kimi Antonelli",
        event_type: "sports",
        current_probability: 0.74,
        baseline_probability_24h: 0.72,
        delta_24h_percentage_points: 2,
        observed_at: topicFixture.topic.updated_at,
        resolution_deadline_at: topicFixture.topic.resolution_deadline_at,
        selection_reason: "leader",
        recent_claim_id: claimFixture.claim.id,
      },
      {
        topic_id: "f1111111-1111-4111-8111-111111111111",
        title: "Will Lewis Hamilton be the 2026 F1 Drivers' Champion?",
        option_label: "Lewis Hamilton",
        event_type: "sports",
        current_probability: 0.1,
        baseline_probability_24h: 0.04,
        delta_24h_percentage_points: 6,
        observed_at: topicFixture.topic.updated_at,
        resolution_deadline_at: topicFixture.topic.resolution_deadline_at,
        selection_reason: "largest_material_move",
        recent_claim_id: null,
      },
      {
        topic_id: "f2222222-2222-4222-8222-222222222222",
        title: "Will Max Verstappen be the 2026 F1 Drivers' Champion?",
        option_label: "Max Verstappen",
        event_type: "sports",
        current_probability: 0.09,
        baseline_probability_24h: 0.09,
        delta_24h_percentage_points: 0,
        observed_at: topicFixture.topic.updated_at,
        resolution_deadline_at: topicFixture.topic.resolution_deadline_at,
        selection_reason: "credible_challenger",
        recent_claim_id: null,
      },
    ],
  },
  ...Array.from({ length: 12 }, (_, index) => ({
    key: `polymarket:event:fixture-${index}`,
    title: `Material event ${index + 1}`,
    event_type: index % 2 ? "macroeconomics" : "regulation",
    external_event_id: `fixture-${index}`,
    source_label: "Polymarket Gamma",
    source_url: null,
    source_member_count: 1,
    eligible_member_count: 1,
    suppressed_member_count: 0,
    is_exclusive_slate: false,
    selection_reason: "observed_move",
    volume_24h: 10000 + index,
    largest_move_24h_percentage_points: index % 2 ? -2 : 2,
    latest_observed_at: topicFixture.topic.updated_at,
    resolution_deadline_at: topicFixture.topic.resolution_deadline_at,
    members: [{
      topic_id: `a${String(index).padStart(7, "0")}-1111-4111-8111-111111111111`,
      title: `Will material event ${index + 1} resolve YES?`,
      option_label: null,
      event_type: index % 2 ? "macroeconomics" : "regulation",
      current_probability: 0.5 + index / 100,
      baseline_probability_24h: 0.48 + index / 100,
      delta_24h_percentage_points: 2,
      observed_at: topicFixture.topic.updated_at,
      resolution_deadline_at: topicFixture.topic.resolution_deadline_at,
      selection_reason: "largest_material_move",
      recent_claim_id: null,
    }],
  })),
];

const exploreSignals = Array.from({ length: 25 }, (_, index) => ({
  id: index === 0
    ? claimFixture.claim.id
    : `b${String(index).padStart(7, "0")}-1111-4111-8111-111111111111`,
  title: index === 0
    ? claimFixture.claim.public_statement
    : `Verified source signal ${index + 1} changed materially.`,
  claim_type: claimFixture.claim.claim_type,
  desk_id: index % 2 ? "rules-desk" : claimFixture.claim.desk_id,
  section_id: index % 2 ? "rules-moved" : "expectations-moved",
  confidence_label: claimFixture.assessment.confidence_label,
  epistemic_status: claimFixture.assessment.epistemic_status,
  status: claimFixture.claim.status,
  published_at: claimFixture.claim.issued_at,
  updated_at: claimFixture.claim.materially_updated_at,
  valid_until: claimFixture.claim.valid_until,
  subject_type: index % 2 ? "canonical_rule" : "source_market",
  subject_id: null,
  event_key: index === 0 ? "polymarket:event:f1-2026" : null,
  event_title: index === 0 ? "2026 F1 Drivers' Champion" : null,
  topic_id: index === 0 ? topicFixture.topic.id : null,
  selection_reason: index === 0 ? "event_representative" : "latest_for_subject",
}));

const server = http.createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", `http://127.0.0.1:${port}`);
  response.setHeader("Access-Control-Allow-Origin", "*");
  response.setHeader("Access-Control-Allow-Headers", "*");
  response.setHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  if (request.method === "OPTIONS") {
    response.writeHead(204).end();
    return;
  }
  if (request.method === "POST" && url.pathname === "/__control/front-fail") {
    frontPageFailuresRemaining = Number(url.searchParams.get("count") ?? "0");
    json(response, 200, { failures: frontPageFailuresRemaining });
    return;
  }
  if (request.method === "POST" && url.pathname === "/__control/front-mode") {
    const requestedMode = url.searchParams.get("value");
    frontPageMode = requestedMode === "empty"
      || requestedMode === "no-live-feed"
      || requestedMode === "no-research"
      || requestedMode === "sparse-research"
      ? requestedMode
      : "full";
    json(response, 200, { mode: frontPageMode });
    return;
  }
  if (request.method === "GET" && url.pathname === "/api/front-page/current") {
    if (frontPageFailuresRemaining > 0) {
      frontPageFailuresRemaining -= 1;
      json(response, 503, { detail: "fixture publication service unavailable" });
      return;
    }
    const requestedLocale = url.searchParams.get("locale") === "zh-Hant"
      ? "zh-Hant"
      : "en";
    const etag = `"fixture-front-page:${frontPageMode}:${requestedLocale}"`;
    if (request.headers["if-none-match"] === etag) {
      response.writeHead(304, { ETag: etag }).end();
      return;
    }
    response.setHeader("ETag", etag);
    const fixture = frontPageMode === "empty"
      ? emptyFrontPageFixture
      : frontPageMode === "no-live-feed"
        ? {
            ...frontPageFixture,
            slots: frontPageFixture.slots.map((publicationSlot) => (
              publicationSlot.type === "live_feed"
                ? { ...publicationSlot, items: [] }
                : publicationSlot
            )),
          }
        : frontPageMode === "no-research"
          ? {
              ...frontPageFixture,
              publication_context: {
                ...frontPageFixture.publication_context,
                counts: {
                  ...frontPageFixture.publication_context.counts,
                  research_screening: 0,
                },
                research: [],
              },
            }
          : frontPageMode === "sparse-research"
            ? {
                ...frontPageFixture,
                publication_context: {
                  ...frontPageFixture.publication_context,
                  counts: {
                    ...frontPageFixture.publication_context.counts,
                    research_screening: 2,
                  },
                  research: frontPageFixture.publication_context.research.slice(0, 2),
                },
              }
        : frontPageFixture;
    json(response, 200, {
      ...fixture,
      locale: {
        requested: requestedLocale,
        published: "en",
        fallback_used: requestedLocale !== "en",
        translation_provenance: null,
      },
    });
    return;
  }
  if (request.method === "GET" && url.pathname.startsWith("/api/claims/")) {
    const claimId = decodeURIComponent(url.pathname.split("/").at(-1) ?? claimFixture.claim.id);
    const requestedLocale = url.searchParams.get("locale") === "zh-Hant"
      ? "zh-Hant"
      : "en";
    json(response, 200, {
      ...claimFixture,
      claim: { ...claimFixture.claim, id: claimId },
      locale: {
        requested: requestedLocale,
        published: "en",
        fallback_used: requestedLocale !== "en",
        translation_provenance: null,
      },
    });
    return;
  }
  if (request.method === "GET" && url.pathname.startsWith("/api/topics/")) {
    const topicId = decodeURIComponent(url.pathname.split("/").at(-1) ?? topicFixture.topic.id);
    json(response, 200, { ...topicFixture, topic: { ...topicFixture.topic, id: topicId } });
    return;
  }
  if (request.method === "GET" && /^\/api\/editions\/[^/]+\/front-page$/.test(url.pathname)) {
    const editionId = decodeURIComponent(url.pathname.split("/")[3] ?? frontPageFixture.snapshot.id);
    const requestedLocale = url.searchParams.get("locale") === "zh-Hant"
      ? "zh-Hant"
      : "en";
    json(response, 200, {
      ...frontPageFixture,
      snapshot: { ...frontPageFixture.snapshot, id: editionId, is_current: false },
      locale: {
        requested: requestedLocale,
        published: "en",
        fallback_used: requestedLocale !== "en",
        translation_provenance: null,
      },
    });
    return;
  }
  if (request.method === "GET" && url.pathname === "/api/editions") {
    const items = frontPageFixture.archive.map((edition) => ({
      id: edition.id,
      edition_date: edition.edition_date,
      generated_at: edition.composed_at,
      status: edition.status,
      sections: edition.sections,
      claim_count: edition.claim_count,
      correction_count: edition.correction_count,
      trigger_type: edition.trigger_type,
      first_published_at: edition.composed_at,
      record_class: "public_permanent",
      payload_hash: "a".repeat(64),
      event_count: 1,
      latest_event_type: "published",
      latest_event_at: edition.composed_at,
    }));
    json(response, 200, {
      items,
      next_cursor: null,
      has_more: false,
      page_size: 50,
      total_count: items.length,
      filters: { year: null, section: null, status: null },
      facets: {
        years: [...new Set(items.map((item) => Number(item.edition_date.slice(0, 4))))],
        sections: [...new Set(items.flatMap((item) => item.sections))],
        statuses: [...new Set(items.map((item) => item.status))],
      },
    });
    return;
  }
  if (request.method === "GET" && /^\/api\/editions\/[^/]+$/.test(url.pathname)) {
    const editionId = decodeURIComponent(url.pathname.split("/").at(-1));
    const composedAt = frontPageFixture.snapshot.composed_at;
    json(response, 200, {
      id: editionId,
      edition_date: frontPageFixture.snapshot.edition_date,
      generated_at: composedAt,
      status: frontPageFixture.snapshot.status,
      first_published_at: composedAt,
      record_class: "public_permanent",
      payload_hash: "a".repeat(64),
      events: [
        {
          id: "d1111111-1111-4111-8111-111111111111",
          sequence_no: 1,
          event_type: "published",
          actor: "composer/os-052",
          reason: "scheduled",
          related_edition_id: null,
          previous_event_hash: null,
          event_hash: "b".repeat(64),
          created_at: composedAt,
        },
      ],
    });
    return;
  }
  if (request.method === "GET" && url.pathname === "/api/seo-index") {
    json(response, 200, {
      claims: [{
        id: claimFixture.claim.id,
        title: claimFixture.claim.public_statement,
        claim_type: claimFixture.claim.claim_type,
        desk_id: claimFixture.claim.desk_id,
        confidence_label: claimFixture.assessment.confidence_label,
        epistemic_status: claimFixture.assessment.epistemic_status,
        status: claimFixture.claim.status,
        published_at: claimFixture.claim.issued_at,
        updated_at: claimFixture.claim.materially_updated_at,
        valid_until: claimFixture.claim.valid_until,
      }],
      topics: topicIndexFixtures,
      editions: frontPageFixture.archive.map((edition) => ({
        id: edition.id,
        edition_date: edition.edition_date,
        updated_at: edition.composed_at,
        status: edition.status,
        sections: edition.sections,
        claim_count: edition.claim_count,
        correction_count: edition.correction_count,
        trigger_type: edition.trigger_type,
      })),
    });
    return;
  }
  if (request.method === "GET" && url.pathname === "/api/explore") {
    const topicPage = Math.max(1, Number(url.searchParams.get("topic_page") ?? "1"));
    const signalPage = Math.max(1, Number(url.searchParams.get("signal_page") ?? "1"));
    const topicPageSize = 12;
    const signalPageSize = 24;
    json(response, 200, {
      selection_version: "expectation-selection-1.1.0",
      ranking_as_of: "2026-08-10T00:45:00+00:00",
      topics: {
        items: exploreEventGroups.slice(
          (topicPage - 1) * topicPageSize,
          topicPage * topicPageSize,
        ),
        page: topicPage,
        page_size: topicPageSize,
        page_count: Math.ceil(exploreEventGroups.length / topicPageSize),
        total_count: exploreEventGroups.length,
        public_inventory_count: 551,
        selected_group_count: exploreEventGroups.length,
        represented_proposition_count: 15,
        suppressed_proposition_count: 536,
      },
      signals: {
        items: exploreSignals.slice(
          (signalPage - 1) * signalPageSize,
          signalPage * signalPageSize,
        ),
        page: signalPage,
        page_size: signalPageSize,
        page_count: Math.ceil(exploreSignals.length / signalPageSize),
        total_count: exploreSignals.length,
        public_record_count: 141,
        current_record_count: 63,
        current_subject_count: 25,
        suppressed_snapshot_count: 38,
      },
    });
    return;
  }
  if (request.method === "GET" && url.pathname === "/health") {
    json(response, 200, { status: "ok" });
    return;
  }
  json(response, 404, { detail: "not found" });
});

server.listen(port, "127.0.0.1");

function json(response, status, body) {
  response.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  response.end(JSON.stringify(body));
}
