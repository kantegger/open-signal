import { expect, test, type APIRequestContext } from "@playwright/test";

const families = [
  "signal-hero",
  "time-series",
  "state-transition",
  "document-change",
  "signal-feed",
  "evidence-relationship",
  "resolution-comparison",
  "archive-snapshot",
];

test.beforeEach(async ({ request }) => {
  await request.post("http://127.0.0.1:8001/__control/front-fail?count=0");
  await request.post("http://127.0.0.1:8001/__control/front-mode?value=full");
  await revalidate(request, "e2e-full");
});

test("hard retirement recompiles a complete page without empty modules", async ({ page, request }) => {
  await request.post("http://127.0.0.1:8001/__control/front-mode?value=empty");
  await revalidate(request, "e2e-empty");
  await page.goto("/");

  await expect(page.getByText("Current front page", { exact: true })).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "No Open Signal judgment is currently published." }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: /Explore Signals and Topics/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /Browse Editions/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /Read the Method/ })).toBeVisible();
  await expect(page.locator("[data-component-family]")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Secondary signals" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Live signal feed" })).toHaveCount(0);
});

test("keeps Current compact and preserves the complete grammar in Editions", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/Open Signal/);
  await expect(page.getByText("Current front page", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "September rate cut became 21 points more likely." })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Expectation tape/ })).toBeVisible();
  await expect(page.getByText("Source observations · not forecasts")).toBeVisible();
  await expect(page.locator(".topic-monitor-list article")).toHaveCount(8);
  await expect(page.getByRole("heading", { name: "Verified judgment ledger" })).toBeVisible();
  await expect(page.locator(".claim-ledger-row:not(.claim-ledger-head)")).toHaveCount(12);
  await expect(page.getByRole("heading", { name: /Rule watch/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Research screening/ })).toBeVisible();
  await expect(page.getByText("12 eligible public watches · not Claims")).toBeVisible();
  await expect(page.locator(".research-watch-list article")).toHaveCount(6);
  await expect(
    page.locator(".research-watch-list article > strong", { hasText: "Microsoft Research" }),
  ).toHaveCount(0);
  await expect(
    page.getByText("New institutional output appeared in Generative AI and foundation models"),
  ).toBeVisible();
  await expect(page.getByText("Microsoft Research Asia", { exact: true })).toBeVisible();
  await expect(page.getByText("Trial portfolio · investigated", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Source coverage/ })).toBeVisible();
  await expect(page.locator(".mini-sparkline")).toHaveCount(3);
  await expect(page.locator(".sparkline-evidence", { hasText: /7d · 29 obs/ })).toHaveCount(3);
  await expect(page.locator(".sparkline-fallback")).toHaveCount(5);
  await expect(page.locator('.sparkline-fallback[data-series-status="insufficient_observations"]')).toHaveCount(2);
  await expect(page.locator('.sparkline-fallback[data-series-status="partial_window"]')).toHaveCount(1);
  await expect(page.locator('.sparkline-fallback[data-series-status="no_material_variation"]')).toHaveCount(1);
  await expect(page.locator('.sparkline-fallback[data-series-status="stale_endpoint"]')).toHaveCount(1);
  await expect(page.locator('.lead-region .probability-direction[data-series-status="insufficient_observations"]')).toBeVisible();
  await expect(page.locator(".lead-region .probability-chart")).toHaveCount(0);
  await expect(page.locator('[data-component-family="document-change"]')).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Archive" })).toHaveCount(0);

  await page.getByRole("link", { name: /Browse Editions/ }).click();
  await expect(page).toHaveURL(/\/editions$/);
  await page.locator(".edition-directory-row:not(.edition-directory-head) a").first().click();
  for (const family of families) {
    await expect(page.locator(`[data-component-family="${family}"]`).first()).toBeVisible();
  }
  await expect(page.getByRole("heading", { name: "Archive" })).toBeVisible();
  await expect(page.getByText("No signals today.")).toHaveCount(0);
});

test("opens an accessible evidence sheet and restores focus", async ({ page }) => {
  await page.goto("/");
  const trigger = page.getByRole("button", { name: "View full evidence" });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "Evidence and Claim" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Observation", { exact: true })).toBeVisible();
  await expect(dialog.getByText("Analysis", { exact: true })).toBeVisible();
  await expect(dialog.getByText("Open Signal assessment", { exact: true })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Close evidence" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
});

test("links the evidence sheet to the permanent Claim record", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "View full evidence" }).click();
  await page.getByRole("link", { name: /Open full Claim page/ }).click();
  await expect(page).toHaveURL(/\/claims\/11111111/);
  await expect(page.getByRole("heading", { name: "Published evidence bundle" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Immutable public versions" })).toBeVisible();
  await expect(page.getByText("v1", { exact: true })).toBeVisible();
});

test("publishes crawlable Signal, Topic, and Edition routes", async ({ page }) => {
  await page.goto("/");
  const leadHeading = page.getByRole("heading", { name: "September rate cut became 21 points more likely." });
  await leadHeading.getByRole("link").click();
  await expect(page).toHaveURL(/\/signals\/september-rate-cut-became-21-points-more-likely--11111111/);
  await expect(page.getByRole("heading", { name: "Published evidence bundle" })).toBeVisible();

  await page.goto("/");
  await page.getByRole("link", { name: "Track topic" }).click();
  await expect(page).toHaveURL(/\/topics\/will-the-federal-reserve-cut-rates-by-september--eeeeeeee/);
  await expect(page.getByRole("heading", { name: "Current market state" })).toBeVisible();
  await expect(page.getByText("85%", { exact: true })).toBeVisible();

  await page.goto("/");
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("link", { name: "Archive" }).click();
  await expect(page).toHaveURL(/\/editions$/);
  await page.locator(".edition-directory-row:not(.edition-directory-head) a").first().click();
  await expect(page).toHaveURL(/\/editions\/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/);
  await expect(page.getByRole("heading", { name: /Edition/ })).toBeVisible();
});

test("uses real destination pages while Evidence remains an overlay", async ({ page }) => {
  await page.goto("/");
  const currentUrl = page.url();
  await page.getByRole("button", { name: "View full evidence" }).click();
  await expect(page).toHaveURL(currentUrl);
  await page.getByRole("button", { name: "Close evidence" }).click();

  const primaryNavigation = page.getByRole("navigation", { name: "Primary navigation" });
  await expect(primaryNavigation.locator('a[href*="#"]')).toHaveCount(0);
  await primaryNavigation.getByRole("link", { name: "Explore" }).click();
  await expect(page).toHaveURL(/\/explore$/);
  await expect(page.getByRole("heading", { name: "Active Topics" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Recent Signals" })).toBeVisible();
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("link", { name: "Method" }).click();
  await expect(page).toHaveURL(/\/method$/);
  await expect(page.getByRole("heading", { name: "How Open Signal makes a public claim" })).toBeVisible();
});

test("mobile order prioritizes the live feed and navigation remains usable", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  const liveFeed = page.getByRole("heading", { name: "Live signal feed" });
  const secondary = page.getByRole("heading", { name: "Secondary signals" });
  const [liveBox, secondaryBox] = await Promise.all([liveFeed.boundingBox(), secondary.boundingBox()]);
  expect(liveBox).not.toBeNull();
  expect(secondaryBox).not.toBeNull();
  expect(liveBox!.y).toBeLessThan(secondaryBox!.y);
  const topicMonitor = page.getByRole("heading", { name: /Expectation tape/ });
  const topicBox = await topicMonitor.boundingBox();
  expect(topicBox).not.toBeNull();
  expect(secondaryBox!.y).toBeLessThan(topicBox!.y);
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByRole("navigation", { name: "Mobile navigation" }).getByRole("link", { name: "Method" })).toBeVisible();
});

test("initial publication failure offers a working retry", async ({ page, request }) => {
  await request.post("http://127.0.0.1:8001/__control/front-fail?count=2");
  await revalidate(request, "e2e-failure");
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "The current verified snapshot could not be loaded." })).toBeVisible();
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("heading", { name: "September rate cut became 21 points more likely." })).toBeVisible();
});

async function revalidate(request: APIRequestContext, editionId: string) {
  const response = await request.post("http://127.0.0.1:3000/api/revalidate", {
    headers: { Authorization: "Bearer e2e-revalidation-token" },
    data: { edition_id: editionId, locale: "en", claim_ids: [] },
  });
  expect(response.ok()).toBeTruthy();
}
