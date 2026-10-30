import { expect, test } from "@playwright/test";
import { API, makeWidgetsDb, nav, openDbPopover, optimizeExample, resetDb, runLabComparison, tables } from "./helpers";

test.beforeEach(async ({ request }) => { await resetDb(request); });

const scroller = (page: import("@playwright/test").Page) => page.locator("main").locator("xpath=..");

test.describe("landing", () => {
  test("loads, renders the 3D canvas, and scrolls through all chapters to the CTAs", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Every query has a cost." })).toBeVisible();
    await expect(page.locator("canvas")).toBeVisible();
    await scroller(page).evaluate((el) => el.scrollTo(0, el.scrollHeight));
    await expect(page.getByRole("heading", { name: "The evidence." })).toBeInViewport();
    await expect(page.getByRole("link", { name: "Open Query Workbench" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Explore the optimizer" })).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("CTA opens the workbench", async ({ page }) => {
    await page.goto("/");
    await scroller(page).evaluate((el) => el.scrollTo(0, el.scrollHeight));
    await page.getByRole("link", { name: "Open Query Workbench" }).click();
    await expect(page).toHaveURL(/\/app$/);
    await expect(page.getByText("Get to your first optimization")).toBeVisible();
  });

  test.describe("reduced motion", () => {
    test.use({ reducedMotion: "reduce" });
    test("falls back to the static page with no canvas", async ({ page }) => {
      await page.goto("/");
      await expect(page.getByRole("heading", { name: "Every query has a cost." })).toBeVisible();
      await expect(page.locator("canvas")).toHaveCount(0);
      await scroller(page).evaluate((el) => el.scrollTo(0, el.scrollHeight));
      await expect(page.getByRole("link", { name: "Open Query Workbench" })).toBeVisible();
    });
  });
});

test.describe("database upload", () => {
  test("a valid SQLite upload switches the schema", async ({ page, request }) => {
    await page.goto("/app");
    await openDbPopover(page);
    await page.locator("#db-upload").setInputFiles({ name: "widgets.db", mimeType: "application/octet-stream", buffer: makeWidgetsDb() });
    await expect.poll(() => tables(request)).toEqual(["widgets"]);
    // the upload triggers a page reload; retry the navigation if it races with it
    await expect(async () => { await page.goto("/app/schema"); }).toPass();
    await expect(page.locator(".react-flow__node")).toHaveCount(1);
    await expect(page.locator(".react-flow__node").first()).toContainText("widgets");
  });

  test("an invalid upload shows an error and keeps the previous database", async ({ page, request }) => {
    const before = await tables(request);
    await page.goto("/app");
    await openDbPopover(page);
    await page.locator("#db-upload").setInputFiles({ name: "bad.db", mimeType: "application/octet-stream", buffer: Buffer.from("this is not sqlite ".repeat(40)) });
    await expect(page.getByText(/This is not a SQLite( or DuckDB)? database file\./)).toBeVisible();
    expect(await tables(request)).toEqual(before);
    expect(before).toContain("customers");
    await expect(page.getByRole("dialog", { name: "Database connection" })).toBeVisible(); // app still usable
  });
});

test.describe("workbench", () => {
  test("optimizing an example shows the summary with estimated and measured blocks", async ({ page }) => {
    await optimizeExample(page);
    await expect(page.getByText(/Estimated/).first()).toBeVisible();
    await expect(page.getByText(/Measured/).first()).toBeVisible();
  });

  test("schema graph renders the discovered tables", async ({ page, request }) => {
    const names = await tables(request);
    await page.goto("/app/schema");
    await expect(page.getByLabel("Schema relationship graph")).toBeVisible();
    await expect(page.locator(".react-flow__node")).toHaveCount(names.length);
    await expect(page.locator(".react-flow__edge").first()).toBeAttached();
  });

  test("workload CSV is grouped and ranked by recorded time", async ({ page }) => {
    const csv = [
      "query,calls,total_ms",
      "SELECT * FROM customers WHERE id = 1,10,50",
      "SELECT * FROM customers WHERE id = 2,5,25",
      "SELECT * FROM orders,2,900",
    ].join("\n");
    await page.goto("/app/workload");
    await page.locator("#wl-file").setInputFiles({ name: "slow.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
    await expect(page.getByText(/Map columns/)).toBeVisible();
    await page.getByRole("button", { name: "Analyze workload" }).click();
    await expect(page.getByText("Source: slow.csv")).toBeVisible();
    const rows = page.locator("table.data tbody tr").filter({ has: page.getByRole("button", { name: "Open in SQL Lab" }) });
    await expect(rows).toHaveCount(2); // the two `customers` literals collapse into one pattern
    await expect(rows.first()).toContainText("orders");
    await expect(rows.nth(1)).toContainText("75"); // 50 + 25 ms
  });

  test("lab compare runs and reports uncertainty", async ({ page }) => {
    await optimizeExample(page);
    await runLabComparison(page);
    await expect(page.getByText(/No measurable difference|faster|slower|No verdict/).first()).toBeVisible();
  });

  test("an investigation can be saved, reopened, and flags that it is historical", async ({ page, request }) => {
    await optimizeExample(page);
    await runLabComparison(page);
    const title = `e2e-${Date.now()}`;
    await page.getByLabel("Title").fill(title);
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText(/Saved\. Find it in History/)).toBeVisible();

    await nav(page, "History");
    await page.getByRole("button", { name: "Investigations" }).click();
    await page.getByLabel(`Select ${title}`).check();
    await page.getByRole("button", { name: "Open selected" }).click();
    await expect(page.getByText("It is not a guarantee of current performance.")).toBeVisible();

    // cleanup: the investigations store is a fixed file in backend/data, so remove what we created
    const list = await (await request.get(`${API}/api/investigations`)).json();
    for (const it of list.items ?? list) if (it.title === title) await request.delete(`${API}/api/investigations/${it.id}`);
  });

  test("index lab shows DDL and does not create anything", async ({ page, request }) => {
    const idx = async () => JSON.stringify((await (await request.get(`${API}/api/schema`)).json()).tables.map((t: any) => [t.name, t.indexes]));
    const before = await idx();
    await optimizeExample(page);
    await nav(page, "Index Lab");
    await page.getByRole("button", { name: "Analyze indexes" }).click();
    await expect(page.getByRole("button", { name: "Copy DDL" }).first()).toBeVisible({ timeout: 30_000 });
    await expect(page.locator("pre").filter({ hasText: /CREATE INDEX/ }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Create index…" }).first()).toBeDisabled(); // read-only server
    expect(await idx()).toEqual(before);
  });
});

test.describe("responsive 390px", () => {
  test.use({ viewport: { width: 390, height: 800 }, hasTouch: true });

  test("landing has no horizontal overflow", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Every query has a cost." })).toBeVisible();
    const o = await scroller(page).evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(o).toBeLessThanOrEqual(0);
  });

  test("workbench has no horizontal page overflow", async ({ page }) => {
    await page.goto("/app");
    await expect(page.getByText("Get to your first optimization")).toBeVisible();
    const o = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(o).toBeLessThanOrEqual(0);
  });
});
