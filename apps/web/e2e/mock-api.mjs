import http from "node:http";
import {
  claimFixture,
  emptyFrontPageFixture,
  frontPageFixture,
} from "./fixture-data.mjs";

const port = 8001;
let frontPageFailuresRemaining = 0;
let frontPageMode = "full";

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
    frontPageMode = url.searchParams.get("value") === "empty" ? "empty" : "full";
    json(response, 200, { mode: frontPageMode });
    return;
  }
  if (request.method === "GET" && url.pathname === "/api/front-page/current") {
    if (frontPageFailuresRemaining > 0) {
      frontPageFailuresRemaining -= 1;
      json(response, 503, { detail: "fixture publication service unavailable" });
      return;
    }
    const etag = '"fixture-front-page:en"';
    if (request.headers["if-none-match"] === etag) {
      response.writeHead(304, { ETag: etag }).end();
      return;
    }
    response.setHeader("ETag", etag);
    json(response, 200, frontPageMode === "empty" ? emptyFrontPageFixture : frontPageFixture);
    return;
  }
  if (request.method === "GET" && url.pathname.startsWith("/api/claims/")) {
    const claimId = decodeURIComponent(url.pathname.split("/").at(-1) ?? claimFixture.claim.id);
    json(response, 200, { ...claimFixture, claim: { ...claimFixture.claim, id: claimId } });
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
