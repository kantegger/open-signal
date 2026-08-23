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
  await expect(page.getByRole("heading", { name: "The event, not one market" })).toBeVisible();
  await expect(page.getByText("5 of 8 source options monitored")).toBeVisible();
  await expect(page.getByText("+ 2 monitored options folded")).toBeVisible();
  await expect(page.getByText(/lower-signal options suppressed/)).toHaveCount(0);
  await expect(page.locator(".event-comparison li")).toHaveCount(3);
  await expect(page.getByRole("heading", { name: "Expectations in motion" })).toBeVisible();
  await expect(page.getByText("Real 7-day histories · event-diverse")).toBeVisible();
  await expect(page.locator(".expectation-signal-grid article")).toHaveCount(4);
  await expect(page.getByRole("heading", { name: "Verified judgment ledger" })).toBeVisible();
  await expect(page.getByLabel("Judgment ledger summary")).toHaveCount(0);
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
  await expect(page.getByRole("heading", { name: /Source coverage/ })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: /Edition cadence/ })).toHaveCount(0);
  await expect(page.locator(".expectation-signal-grid .signal-history-chart")).toHaveCount(2);
  await expect(page.locator(".expectation-signal-grid .signal-history-fallback")).toHaveCount(2);
  await expect(page.locator(".lead-region .probability-chart")).toBeVisible();
  await expect(page.locator(".lead-region .chart-value-current")).toContainText("now 85%");
  await expect(page.locator('[data-component-family="document-change"]')).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Archive" })).toHaveCount(0);

  await page.getByRole("link", { name: /Browse Editions/ }).click();
  await expect(page).toHaveURL(/\/editions$/);
  await expect(page.getByRole("heading", { name: "Edition timeline" })).toBeVisible();
  await page.locator(".edition-directory-row:not(.edition-directory-head) a").first().click();
  for (const family of families) {
    await expect(page.locator(`[data-component-family="${family}"]`).first()).toBeVisible();
  }
  await expect(page.getByRole("heading", { name: "Live signal feed" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Expectations in motion" })).toHaveCount(0);
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

test("uses the full canvas on destination pages and exposes a primary Topic signal", async ({ page }) => {
  await page.setViewportSize({ width: 2560, height: 1300 });
  for (const [path, selector, heading] of [
    ["/explore", ".directory-page", "Explore Signals and Topics"],
    ["/editions", ".directory-page", "Edition Archive"],
    ["/method", ".method-page", "How Open Signal makes a public claim"],
  ] as const) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
    const layout = await page.locator(selector).evaluate((element) => ({
      clientWidth: document.documentElement.clientWidth,
      documentWidth: document.documentElement.scrollWidth,
      pageWidth: element.getBoundingClientRect().width,
    }));
    expect(layout.pageWidth).toBeGreaterThanOrEqual(layout.clientWidth - 1);
    expect(layout.documentWidth).toBe(layout.clientWidth);
  }

  await page.goto("/explore");
  const firstTopicSignal = page.locator(".event-member-list li").first();
  await expect(firstTopicSignal.getByText("leader", { exact: true })).toBeVisible();
  await expect(firstTopicSignal.locator("strong")).toHaveText("74%");
  await expect(firstTopicSignal.locator(".trend-up")).toContainText("↗ +2pp");
});

test("keeps public information readable and encodes direction semantically", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Verified judgment ledger" })).toBeVisible();

  const signalHref = await page.locator(".claim-ledger-row:not(.claim-ledger-head) a").first().getAttribute("href");
  const topicHref = await page.getByRole("link", { name: "Track topic" }).getAttribute("href");
  const currentSizes = await page.evaluate(() => ({
    navigation: parseFloat(getComputedStyle(document.querySelector(".primary-link")!).fontSize),
    movementHeadline: parseFloat(getComputedStyle(document.querySelector(".expectation-signal-grid h3")!).fontSize),
    ledgerStatement: parseFloat(getComputedStyle(document.querySelector(".claim-ledger-row:not(.claim-ledger-head) strong")!).fontSize),
    watchHeadline: parseFloat(getComputedStyle(document.querySelector(".watch-list article > strong")!).fontSize),
    eventOption: parseFloat(getComputedStyle(document.querySelector(".event-comparison li strong")!).fontSize),
  }));
  expect(currentSizes.navigation).toBeGreaterThanOrEqual(11);
  expect(currentSizes.movementHeadline).toBeGreaterThanOrEqual(13);
  expect(currentSizes.ledgerStatement).toBeGreaterThanOrEqual(13);
  expect(currentSizes.watchHeadline).toBeGreaterThanOrEqual(12);
  expect(currentSizes.eventOption).toBeGreaterThanOrEqual(13);
  const ledgerFits = await page.locator(".claim-ledger-row:not(.claim-ledger-head)").first().evaluate((row) => {
    const cells = Array.from(row.children) as HTMLElement[];
    return cells.slice(0, 2).every((cell) => cell.scrollWidth <= cell.clientWidth + 1);
  });
  expect(ledgerFits).toBe(true);
  const ledgerColumnBudget = await page.locator(".claim-ledger-row:not(.claim-ledger-head)").first().evaluate((row) => {
    const desk = row.children.item(0)?.getBoundingClientRect().width ?? 0;
    const claim = row.children.item(1)?.getBoundingClientRect().width ?? 0;
    return { desk, claim };
  });
  expect(ledgerColumnBudget.desk).toBeLessThanOrEqual(130);
  expect(ledgerColumnBudget.claim).toBeGreaterThan(ledgerColumnBudget.desk * 2);

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
  const archiveClaimsFit = await page.locator(".edition-claims-cell").first().evaluate(
    (cell) => cell.scrollWidth <= cell.clientWidth + 1,
  );
  expect(archiveClaimsFit).toBe(true);
  const archiveColumnBudget = await page.locator(".edition-directory-row:not(.edition-directory-head)").first().evaluate((row) => {
    const cells = Array.from(row.children) as HTMLElement[];
    return {
      composed: cells[0]?.getBoundingClientRect().width ?? 0,
      coverage: cells[1]?.getBoundingClientRect().width ?? 0,
      claims: cells[2]?.getBoundingClientRect().width ?? 0,
      trigger: cells[3]?.getBoundingClientRect().width ?? 0,
    };
  });
  expect(archiveColumnBudget.composed).toBeLessThanOrEqual(240);
  expect(archiveColumnBudget.coverage).toBeGreaterThan(archiveColumnBudget.claims);
  expect(archiveColumnBudget.trigger).toBeGreaterThan(archiveColumnBudget.claims);
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
  await expect(page.getByRole("link", { name: /Open sealed evidence/ })).toHaveAttribute(
    "href",
    /^https:\/\/evidence\.open-signal\.test\/public\/evidence\/v1\//,
  );
  expect(await fontSize(page.locator(".claim-record-header dl > div").first())).toBeGreaterThanOrEqual(11);
  await expect(page.locator(".claim-record-header .statement-movement")).toHaveCount(1);
});

test("adapts typography and disclosure to collection size", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await request.post("http://127.0.0.1:8001/__control/front-mode?value=sparse-research");
  await revalidate(request, "e2e-sparse-research");
  await page.goto("/");

  const sparseResearch = page.locator(".research-watch-list");
  await expect(sparseResearch).toHaveAttribute("data-count", "2");
  await expect(sparseResearch).toHaveAttribute("data-density", "sparse");
  await expect(sparseResearch.locator(".research-context").first()).toBeVisible();
  await expect(sparseResearch.getByText(/not yet a Claim/).first()).toBeVisible();
  const sparseTitleSize = await fontSize(sparseResearch.locator("article > strong").first());

  await request.post("http://127.0.0.1:8001/__control/front-mode?value=full");
  await revalidate(request, "e2e-dense-research");
  await page.reload();

  const denseResearch = page.locator(".research-watch-list");
  await expect(denseResearch).toHaveAttribute("data-count", "6");
  await expect(denseResearch).toHaveAttribute("data-density", "dense");
  await expect(denseResearch.locator(".research-context").first()).toBeHidden();
  const denseTitleSize = await fontSize(denseResearch.locator("article > strong").first());
  expect(sparseTitleSize).toBeGreaterThanOrEqual(20);
  expect(denseTitleSize).toBeLessThanOrEqual(13);
  expect(sparseTitleSize).toBeGreaterThan(denseTitleSize);

  await page.goto("/explore");
  await expect(page.locator(".event-directory-grid")).toHaveAttribute("data-density", "dense");
  await expect(page.locator(".signal-directory-table")).toHaveAttribute("data-density", "dense");
  await expect(page.locator(".signal-directory-table small").first()).toBeVisible();

  await page.locator(".event-member-list a").first().click();
  await expect(page.locator(".topic-market-grid")).toHaveAttribute("data-density", "sparse");
  await expect(page.getByText("Binary prediction market.", { exact: true })).toBeVisible();
  await expect(page.locator(".topic-signal-table")).toHaveAttribute("data-density", "sparse");
});

test("keeps event content ahead of site telemetry when research is absent", async ({ page, request }) => {
  await request.post("http://127.0.0.1:8001/__control/front-mode?value=no-research");
  await revalidate(request, "e2e-no-research");
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "The event, not one market" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Signal pulse/ })).toHaveCount(0);
  await expect(page.getByText("24h breadth")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Live signal feed" })).toHaveCount(0);

  const comparison = await page.locator(".event-comparison").boundingBox();
  const side = await page.locator(".secondary-region").boundingBox();
  expect(comparison).not.toBeNull();
  expect(side).not.toBeNull();

  await page.setViewportSize({ width: 375, height: 812 });
  await page.reload();
  await expect(page.locator(".event-comparison")).toBeVisible();
  await expect(page.locator(".secondary-region")).toBeVisible();
  const mobileOrder = await Promise.all([
    page.locator(".coverage-strip").boundingBox(),
    page.locator(".lead-region").boundingBox(),
    page.locator(".event-comparison").boundingBox(),
    page.locator(".secondary-region").boundingBox(),
  ]);
  for (const box of mobileOrder) expect(box).not.toBeNull();
  expect(mobileOrder[0]!.y).toBeLessThan(mobileOrder[1]!.y);
  expect(mobileOrder[1]!.y).toBeLessThan(mobileOrder[2]!.y);
  expect(mobileOrder[2]!.y).toBeLessThan(mobileOrder[3]!.y);
});

test("keeps signal visuals directly below the hero when no event comparison is available", async ({ page, request }) => {
  await request.post("http://127.0.0.1:8001/__control/front-mode?value=no-featured-event");
  await revalidate(request, "e2e-no-featured-event");
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto("/");

  await expect(page.locator(".event-comparison")).toHaveCount(0);
  await expect(page.locator(".expectation-board")).toBeVisible();
  await expect(page.locator(".secondary-region")).toBeVisible();
  const [coverage, lead, secondary, movement] = await Promise.all([
    page.locator(".coverage-strip").boundingBox(),
    page.locator(".dashboard-lead-column").boundingBox(),
    page.locator(".secondary-region").boundingBox(),
    page.locator(".expectation-board").boundingBox(),
  ]);
  expect(coverage, "coverage box").not.toBeNull();
  expect(lead, "lead box").not.toBeNull();
  expect(secondary, "secondary box").not.toBeNull();
  expect(movement, "movement box").not.toBeNull();

  const firstRowBottom = Math.max(lead!.y + lead!.height, secondary!.y + secondary!.height);
  expect(Math.abs(movement!.y - firstRowBottom)).toBeLessThanOrEqual(2);
  expect(Math.abs(movement!.x - coverage!.x)).toBeLessThanOrEqual(2);
  expect(Math.abs(movement!.width - coverage!.width)).toBeLessThanOrEqual(2);
  await expect(page.locator(".expectation-signal-grid article")).toHaveCount(4);
});

test("places a featured event on its own full-width row", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto("/");
  await expect(page.locator(".event-comparison")).toBeVisible();

  const [coverage, lead, secondary, comparison, movement] = await Promise.all([
    page.locator(".coverage-strip").boundingBox(),
    page.locator(".dashboard-lead-column").boundingBox(),
    page.locator(".secondary-region").boundingBox(),
    page.locator(".event-comparison").boundingBox(),
    page.locator(".expectation-board").boundingBox(),
  ]);
  for (const box of [coverage, lead, secondary, comparison, movement]) expect(box).not.toBeNull();

  const firstRowBottom = Math.max(lead!.y + lead!.height, secondary!.y + secondary!.height);
  expect(Math.abs(comparison!.y - firstRowBottom)).toBeLessThanOrEqual(2);
  expect(Math.abs(comparison!.x - coverage!.x)).toBeLessThanOrEqual(2);
  expect(Math.abs(comparison!.width - coverage!.width)).toBeLessThanOrEqual(2);
  expect(Math.abs(movement!.y - (comparison!.y + comparison!.height))).toBeLessThanOrEqual(2);
});

test("labels an unchanged research item as a continuing watch", async ({ page, request }) => {
  await request.post("http://127.0.0.1:8001/__control/front-mode?value=continuing-research");
  await revalidate(request, "e2e-continuing-research");
  await page.goto("/");

  const research = page.locator(".research-watch-featured");
  await expect(research).toHaveAttribute("data-tenure", "continuing");
  await expect(research.getByText("1 continuing public watch · not Claims")).toBeVisible();
  await expect(research.getByText(/continuing watch/)).toBeVisible();
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
  const integrity = page.getByRole("region", { name: "Edition integrity and lifecycle" });
  await expect(integrity.getByText("Public Permanent")).toBeVisible();
  await expect(integrity.getByText("aaaaaaaaaaaaaaaa…")).toBeVisible();
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
  await expect(page.getByRole("heading", { name: "Selected Event Signals" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Recent Signals" })).toBeVisible();
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("link", { name: "Method" }).click();
  await expect(page).toHaveURL(/\/method$/);
  await expect(page.getByRole("heading", { name: "How Open Signal makes a public claim" })).toBeVisible();
});

test("Explore compresses multi-outcome events and paginates each collection independently", async ({ page }) => {
  await page.goto("/explore");

  const eventCard = page.locator(".event-signal-card").filter({
    has: page.getByRole("heading", { name: "2026 F1 Drivers' Champion" }),
  });
  await expect(eventCard).toBeVisible();
  await expect(eventCard.locator(".event-member-list li")).toHaveCount(3);
  await expect(eventCard.getByText("Kimi Antonelli", { exact: true })).toBeVisible();
  await expect(eventCard.getByText("Lewis Hamilton", { exact: true })).toBeVisible();
  await expect(eventCard.getByText("+17 source outcomes folded into this event")).toBeVisible();
  await expect(eventCard.getByText(/Longshot/)).toHaveCount(0);

  await page.getByRole("link", { name: "More events" }).click();
  await expect(page).toHaveURL(/topic_page=2/);
  await expect(page.getByRole("heading", { name: "Material event 12" })).toBeVisible();
  await expect(page.getByRole("link", { name: "More Signals" })).toBeVisible();

  await page.getByRole("link", { name: "More Signals" }).click();
  await expect(page).toHaveURL(/signal_page=2/);
  await expect(page.getByText("Verified source signal 25 changed materially.")).toBeVisible();
  await expect(page).toHaveURL(/topic_page=2/);
});

test("mobile order keeps the lead ahead of supporting research and navigation remains usable", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Research screening/ })).toBeVisible();
  const mobileOrder = await Promise.all([
    page.locator(".coverage-strip").boundingBox(),
    page.locator(".lead-region").boundingBox(),
    page.locator(".event-comparison").boundingBox(),
    page.locator(".secondary-region").boundingBox(),
    page.locator(".expectation-board").boundingBox(),
    page.locator(".research-watch-featured").boundingBox(),
  ]);
  for (const box of mobileOrder) expect(box).not.toBeNull();
  for (let index = 1; index < mobileOrder.length; index += 1) {
    expect(mobileOrder[index - 1]!.y).toBeLessThan(mobileOrder[index]!.y);
  }
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

test("redirects retired Chinese locale routes to the English publication", async ({ page }) => {
  await page.goto("/zh-TW/method");
  await expect(page).toHaveURL(/\/method$/);
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(
    page.getByRole("heading", { name: "How Open Signal makes a public claim" }),
  ).toBeVisible();
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
    "href",
    /\/method$/,
  );

  await page.goto("/zh-Hant/explore?topic_page=2");
  await expect(page).toHaveURL(/\/explore\?topic_page=2$/);
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByRole("navigation", { name: "Language" })).toHaveCount(0);
});

async function revalidate(
  request: APIRequestContext,
  editionId: string,
) {
  const response = await request.post("http://127.0.0.1:3000/api/revalidate", {
    headers: { Authorization: "Bearer e2e-revalidation-token" },
    data: { edition_id: editionId, locale: "en", claim_ids: [] },
  });
  expect(response.ok()).toBeTruthy();
}

async function fontSize(locator: import("@playwright/test").Locator): Promise<number> {
  return locator.evaluate((element) => parseFloat(getComputedStyle(element).fontSize));
}
