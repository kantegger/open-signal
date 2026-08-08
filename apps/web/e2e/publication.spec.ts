import { expect, test } from "@playwright/test";

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
});

test("hard retirement recompiles a complete page without empty modules", async ({ page, request }) => {
  await request.post("http://127.0.0.1:8001/__control/front-mode?value=empty");
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Current front page" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "No active signal is currently published." }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Archive" })).toBeVisible();
  await expect(page.locator("#method").getByText("Method", { exact: true })).toBeVisible();
  await expect(page.locator("#method").getByText("System state", { exact: true })).toBeVisible();
  await expect(page.locator("[data-component-family]")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Secondary signals" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Live signal feed" })).toHaveCount(0);
});

test("renders the complete rolling publication grammar", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/Open Signal/);
  await expect(page.getByRole("heading", { name: "Current front page" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "September rate cut became 21 points more likely." })).toBeVisible();
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

test("mobile order prioritizes the live feed and navigation remains usable", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  const liveFeed = page.getByRole("heading", { name: "Live signal feed" });
  const secondary = page.getByRole("heading", { name: "Secondary signals" });
  const [liveBox, secondaryBox] = await Promise.all([liveFeed.boundingBox(), secondary.boundingBox()]);
  expect(liveBox).not.toBeNull();
  expect(secondaryBox).not.toBeNull();
  expect(liveBox!.y).toBeLessThan(secondaryBox!.y);
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByRole("navigation").getByRole("link", { name: "Method" })).toBeVisible();
});

test("initial publication failure offers a working retry", async ({ page, request }) => {
  await request.post("http://127.0.0.1:8001/__control/front-fail?count=2");
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "The current verified snapshot could not be loaded." })).toBeVisible();
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Current front page" })).toBeVisible();
});
