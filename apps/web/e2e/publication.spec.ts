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

test("uses the full ultrawide canvas without letting ledger text cross its columns", async ({ page }) => {
  await page.setViewportSize({ width: 2560, height: 1300 });
  await page.goto("/");

  const layout = await page.evaluate(() => {
    const frontPage = document.querySelector<HTMLElement>(".front-page");
    const header = document.querySelector<HTMLElement>(".site-header-inner");
    return {
      clientWidth: document.documentElement.clientWidth,
      documentWidth: document.documentElement.scrollWidth,
      frontPageWidth: frontPage?.getBoundingClientRect().width ?? 0,
      headerWidth: header?.getBoundingClientRect().width ?? 0,
    };
  });
  expect(layout.frontPageWidth).toBeGreaterThanOrEqual(layout.clientWidth - 1);
  expect(layout.headerWidth).toBeGreaterThanOrEqual(layout.clientWidth - 1);
  expect(layout.documentWidth).toBe(layout.clientWidth);

  const ledgerBounds = await page.locator(".claim-ledger-row:not(.claim-ledger-head)").evaluateAll((rows) => (
    rows.map((row) => {
      const claimCell = row.children.item(1) as HTMLElement | null;
      const claimLink = claimCell?.querySelector<HTMLElement>("a");
      const cellRect = claimCell?.getBoundingClientRect();
      const linkRect = claimLink?.getBoundingClientRect();
      return {
        cellRight: cellRect?.right ?? 0,
        linkRight: linkRect?.right ?? 0,
      };
    })
  ));
  expect(ledgerBounds.length).toBeGreaterThan(0);
  for (const bounds of ledgerBounds) {
    expect(bounds.linkRight).toBeLessThanOrEqual(bounds.cellRight + 1);
  }
});

test("keeps public information readable and encodes direction semantically", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Verified judgment ledger" })).toBeVisible();

  const signalHref = await page.locator(".claim-ledger-row:not(.claim-ledger-head) a").first().getAttribute("href");
  const topicHref = await page.getByRole("link", { name: "Track topic" }).getAttribute("href");
  const currentSizes = await page.evaluate(() => ({
    navigation: parseFloat(getComputedStyle(document.querySelector(".primary-link")!).fontSize),
    feedHeadline: parseFloat(getComputedStyle(document.querySelector(".feed-headline")!).fontSize),
    ledgerStatement: parseFloat(getComputedStyle(document.querySelector(".claim-ledger-row:not(.claim-ledger-head) strong")!).fontSize),
    watchHeadline: parseFloat(getComputedStyle(document.querySelector(".watch-list article > strong")!).fontSize),
    sourceLabel: parseFloat(getComputedStyle(document.querySelector(".source-coverage-band article > span")!).fontSize),
  }));
  expect(currentSizes.navigation).toBeGreaterThanOrEqual(11);
  expect(currentSizes.feedHeadline).toBeGreaterThanOrEqual(15);
  expect(currentSizes.ledgerStatement).toBeGreaterThanOrEqual(13);
  expect(currentSizes.watchHeadline).toBeGreaterThanOrEqual(12);
  expect(currentSizes.sourceLabel).toBeGreaterThanOrEqual(11);

  const [upColor, downColor] = await Promise.all([
    page.locator(".ledger-direction.trend-up").first().evaluate((element) => getComputedStyle(element).color),
    page.locator(".ledger-direction.trend-down").first().evaluate((element) => getComputedStyle(element).color),
  ]);
  expect(upColor).not.toBe(downColor);
  const movementStyle = await page.locator(".claim-ledger .statement-movement").first().evaluate((element) => ({
    color: getComputedStyle(element).color,
    fontStyle: getComputedStyle(element).fontStyle,
    fontWeight: Number.parseInt(getComputedStyle(element).fontWeight, 10),
  }));
  expect([upColor, downColor]).toContain(movementStyle.color);
  expect(movementStyle.fontStyle).toBe("italic");
  expect(movementStyle.fontWeight).toBeGreaterThanOrEqual(600);
  await page.goto("/explore");
  await expect(page.getByRole("heading", { name: "Recent Signals" })).toBeVisible();
  expect(await fontSize(page.locator(".signal-directory-row:not(.signal-directory-head)").first())).toBeGreaterThanOrEqual(11);

  await page.goto("/editions");
  await expect(page.getByRole("heading", { name: "All public Editions" })).toBeVisible();
  expect(await fontSize(page.locator(".edition-directory-row:not(.edition-directory-head)").first())).toBeGreaterThanOrEqual(11);
  const editionHref = await page.locator(".edition-directory-row:not(.edition-directory-head) a").first().getAttribute("href");

  expect(editionHref).toBeTruthy();
  await page.goto(editionHref!);
  await expect(page.locator('[data-component-family="document-change"]')).toBeVisible();
  expect(await fontSize(page.locator(".publication-module .eyebrow").first())).toBeGreaterThanOrEqual(12);
  expect(await fontSize(page.locator(".publication-module .trust-line").first())).toBeGreaterThanOrEqual(10);
  expect(await fontSize(page.locator(".document-diff p").first())).toBeGreaterThanOrEqual(11);
  expect(await fontSize(page.locator(".resolution-grid strong").first())).toBeGreaterThanOrEqual(11);

  await page.goto("/method");
  expect(await fontSize(page.locator(".method-flow li > p").first())).toBeGreaterThanOrEqual(15);

  expect(topicHref).toBeTruthy();
  await page.goto(topicHref!);
  await expect(page.getByRole("heading", { name: "Current market state" })).toBeVisible();
  expect(await fontSize(page.locator(".topic-signal-table article").first())).toBeGreaterThanOrEqual(12);
  await expect(page.locator(".topic-probability .trend-up, .topic-probability .trend-down").first()).toContainText(/↗|↘/);

  expect(signalHref).toBeTruthy();
  await page.goto(signalHref!);
  await expect(page.getByRole("heading", { name: "Published evidence bundle" })).toBeVisible();
  expect(await fontSize(page.locator(".claim-record-header dl > div").first())).toBeGreaterThanOrEqual(11);
  await expect(page.locator(".claim-record-header .statement-movement")).toHaveCount(1);
});

test("fills an empty lead column with derived signal context", async ({ page, request }) => {
  await request.post("http://127.0.0.1:8001/__control/front-mode?value=no-live-feed");
  await revalidate(request, "e2e-no-live-feed");
  await page.goto("/");

  await expect(page.getByRole("heading", { name: /Signal pulse/ })).toBeVisible();
  await expect(page.getByText("Derived context · not a new Claim")).toBeVisible();
  await expect(page.getByText("24h breadth")).toBeVisible();
  await expect(page.getByText("Largest observed move")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Live signal feed" })).toHaveCount(0);

  const pulse = await page.locator(".signal-pulse").boundingBox();
  const side = await page.locator(".dashboard-side").boundingBox();
  expect(pulse).not.toBeNull();
  expect(side).not.toBeNull();
  expect(Math.abs((pulse!.y + pulse!.height) - (side!.y + side!.height))).toBeLessThanOrEqual(1);

  await page.setViewportSize({ width: 375, height: 812 });
  await page.reload();
  await expect(page.locator(".signal-pulse")).toBeVisible();
  await expect(page.locator(".secondary-region")).toBeVisible();
  const mobileOrder = await Promise.all([
    page.locator(".coverage-strip").boundingBox(),
    page.locator(".lead-region").boundingBox(),
    page.locator(".signal-pulse").boundingBox(),
    page.locator(".secondary-region").boundingBox(),
  ]);
  for (const box of mobileOrder) expect(box).not.toBeNull();
  expect(mobileOrder[0]!.y).toBeLessThan(mobileOrder[1]!.y);
  expect(mobileOrder[1]!.y).toBeLessThan(mobileOrder[2]!.y);
  expect(mobileOrder[2]!.y).toBeLessThan(mobileOrder[3]!.y);
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
  const mobileWidth = await page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(mobileWidth.scroll).toBe(mobileWidth.client);
  const mobileDeskFits = await page
    .locator(".claim-ledger-row:not(.claim-ledger-head) > :first-child")
    .first()
    .evaluate((element) => element.scrollWidth <= element.clientWidth + 1);
  expect(mobileDeskFits).toBeTruthy();
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

async function fontSize(locator: import("@playwright/test").Locator): Promise<number> {
  return locator.evaluate((element) => parseFloat(getComputedStyle(element).fontSize));
}
