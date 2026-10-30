import { expect } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";
import { DatabaseSync } from "node:sqlite";
import fs from "node:fs";
import path from "node:path";

export const API = `http://localhost:${process.env.E2E_API_PORT ?? 8200}`;

/** Point the shared backend back at the seeded demo database before each test. */
export async function resetDb(request: APIRequestContext) {
  const r = await request.post(`${API}/api/database/connect`, { data: { path: process.env.E2E_DB } });
  expect(r.ok(), await r.text()).toBeTruthy();
}

/** A small valid SQLite file with one table, `widgets`. */
export function makeWidgetsDb(): Buffer {
  const p = path.join(process.env.E2E_SCRATCH!, `widgets-${Date.now()}.db`);
  const db = new DatabaseSync(p);
  db.exec("CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT, qty INTEGER)");
  const ins = db.prepare("INSERT INTO widgets (name, qty) VALUES (?, ?)");
  for (let i = 0; i < 20; i++) ins.run(`w${i}`, i);
  db.close();
  return fs.readFileSync(p);
}

export async function tables(request: APIRequestContext): Promise<string[]> {
  return (await (await request.get(`${API}/api/health`)).json()).tables;
}

/** Client-side navigation via the tab nav, so the in-memory SQL / result survive. */
export const nav = (page: Page, label: string) => page.getByRole("link", { name: new RegExp(`^\\d\\d\\s*${label}$`, "i") }).click();

export async function openDbPopover(page: Page) {
  await page.getByTitle("Change database").click();
  await expect(page.getByRole("dialog", { name: "Database connection" })).toBeVisible();
}

/** Run the optimizer on the auto-loaded example and wait for the summary. */
export async function optimizeExample(page: Page) {
  await page.goto("/app");
  await expect(page.getByRole("button", { name: /^Optimize$/ })).toBeEnabled({ timeout: 90_000 });
  await page.getByRole("button", { name: /^Optimize$/ }).click();
  await expect(page.getByText("Why this plan won")).toBeVisible({ timeout: 60_000 });
}

export async function runLabComparison(page: Page) {
  await nav(page, "Lab");
  await expect(page.getByRole("heading", { name: "Benchmark Lab" })).toBeVisible();
  await expect(page.getByLabel("Baseline SQL")).not.toBeEmpty();
  await page.getByRole("button", { name: "Run comparison" }).click();
  await expect(page.getByText("Uncertainty and limitations")).toBeVisible({ timeout: 60_000 });
}
