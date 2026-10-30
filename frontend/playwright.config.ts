import { defineConfig } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// Dedicated ports so a developer's own servers (8000 / 5173) are never reused or disturbed.
const API_PORT = Number(process.env.E2E_API_PORT ?? 8200);
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 5273);

// One scratch directory per run. Env is inherited by workers, so they see the same value.
process.env.E2E_RUN ??= String(Date.now());
const scratch = path.join(os.tmpdir(), `querypilot-e2e-${process.env.E2E_RUN}`);
fs.mkdirSync(path.join(scratch, "uploads"), { recursive: true });
process.env.E2E_DB = path.join(scratch, "demo.db");
process.env.E2E_SCRATCH = scratch;

const backend = path.resolve(process.cwd(), "..", "backend");
const venvPy = path.join(backend, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const py = (fs.existsSync(venvPy) ? venvPy : "python").replace(/\\/g, "/");
const db = process.env.E2E_DB.replace(/\\/g, "/");

export default defineConfig({
  testDir: "./e2e",
  workers: 1, // the backend holds one shared "current database"; tests reset it in beforeEach
  fullyParallel: false,
  timeout: 90_000,
  retries: 1,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    channel: "msedge", // use "chrome" or drop the line to use Playwright's bundled Chromium
    launchOptions: { args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] },
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `"${py}" -m seed.generate --db "${db}" --customers 300 --orders 1000 --products 60 && "${py}" -m uvicorn app.main:app --port ${API_PORT}`,
      cwd: backend,
      url: `http://localhost:${API_PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        DATABASE_PATH: db,
        UPLOAD_DIR: path.join(scratch, "uploads"),
        HISTORY_PATH: path.join(scratch, "history.json"),
        RATE_LIMIT_PER_MIN: "0",
      },
    },
    {
      command: `npx vite --port ${WEB_PORT} --strictPort`,
      url: `http://localhost:${WEB_PORT}`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: { VITE_API_TARGET: `http://localhost:${API_PORT}` },
    },
  ],
});
