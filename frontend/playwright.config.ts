import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 45_000 },
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://localhost:5173",
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
      url: "http://localhost:8000/healthz",
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      env: {
        SPRITE_APP_ENV: "simulation",
        SPRITE_AUTH_MODE: "dev",
        SPRITE_DATABASE_URL: "sqlite+aiosqlite:///./.runtime/playwright-v3.db",
        SPRITE_DATA_ROOT: ".runtime/playwright-v3-data",
        SPRITE_EMBEDDED_WORKERS: "true",
        SPRITE_SIMULATION_ROWS: "96",
        SPRITE_SIMULATION_COLUMNS: "128",
        SPRITE_SIMULATION_EXPOSURE_SCALE: "0.001",
      },
    },
    {
      command: "pnpm dev --host 0.0.0.0",
      url: "http://localhost:5173",
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
    },
  ],
});
