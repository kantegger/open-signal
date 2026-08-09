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
    frontPageMode = requestedMode === "empty" || requestedMode === "no-live-feed"
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
    const etag = `"fixture-front-page:${frontPageMode}:en"`;
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
        : frontPageFixture;
    json(response, 200, fixture);
    return;
  }
  if (request.method === "GET" && url.pathname.startsWith("/api/claims/")) {
    const claimId = decodeURIComponent(url.pathname.split("/").at(-1) ?? claimFixture.claim.id);
    json(response, 200, { ...claimFixture, claim: { ...claimFixture.claim, id: claimId } });
    return;
  }
  if (request.method === "GET" && url.pathname.startsWith("/api/topics/")) {
    const topicId = decodeURIComponent(url.pathname.split("/").at(-1) ?? topicFixture.topic.id);
    json(response, 200, { ...topicFixture, topic: { ...topicFixture.topic, id: topicId } });
    return;
  }
  if (request.method === "GET" && /^\/api\/editions\/[^/]+\/front-page$/.test(url.pathname)) {
    const editionId = decodeURIComponent(url.pathname.split("/")[3] ?? frontPageFixture.snapshot.id);
    json(response, 200, {
      ...frontPageFixture,
      snapshot: { ...frontPageFixture.snapshot, id: editionId, is_current: false },
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
