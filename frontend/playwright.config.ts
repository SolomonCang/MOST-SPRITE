import { defineConfig, devices } from "@playwright/test";

const apiPort = Number(process.env.SPRITE_E2E_API_PORT ?? 8010);
const webPort = Number(process.env.SPRITE_E2E_WEB_PORT ?? 5174);
const apiUrl = `http://localhost:${apiPort}`;
const webUrl = `http://localhost:${webPort}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 45_000 },
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: webUrl,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: "uv run sprite-api",
      cwd: "..",
      url: `${apiUrl}/healthz`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: {
        SPRITE_APP_ENV: "simulation",
        SPRITE_AUTH_MODE: "dev",
        SPRITE_LOCAL_AUTH_SECRET: "playwright-local-auth-key-2026-change-me",
        SPRITE_DATABASE_URL: "sqlite+aiosqlite:///./.runtime/playwright-v3.db",
        SPRITE_DATA_ROOT: ".runtime/playwright-v3-data",
        SPRITE_EMBEDDED_WORKERS: "true",
        SPRITE_API_PORT: String(apiPort),
        SPRITE_CORS_ORIGINS: JSON.stringify([webUrl]),
        SPRITE_SIMULATION_ROWS: "96",
        SPRITE_SIMULATION_COLUMNS: "128",
        SPRITE_SIMULATION_EXPOSURE_SCALE: "0.001",
      },
    },
    {
      command: `pnpm dev --host 0.0.0.0 --port ${webPort}`,
      url: webUrl,
      timeout: 120_000,
      reuseExistingServer: false,
      env: {
        VITE_API_URL: apiUrl,
        VITE_WS_URL: `ws://localhost:${apiPort}`,
      },
    },
  ],
});
