import { defineConfig, devices } from "@playwright/test";

import { MOCK_API_PORT } from "./e2e/pages";

const port = 3100;
const apiPort = MOCK_API_PORT;
const configuredBaseUrl = process.env.PLAYWRIGHT_BASE_URL;
const executablePath = process.env.PLAYWRIGHT_EXECUTABLE_PATH;
const baseURL = configuredBaseUrl ?? `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  outputDir: "test-results",
  snapshotPathTemplate: "{testDir}/{testFilePath}-snapshots/{arg}{ext}",
  expect: {
    toHaveScreenshot: {
      animations: "disabled",
      caret: "hide",
      maxDiffPixelRatio: 0.01,
    },
  },
  use: {
    baseURL,
    launchOptions: executablePath ? { executablePath } : undefined,
    trace: "retain-on-failure",
  },
  webServer:
    configuredBaseUrl === undefined
      ? [
          {
            command: "node e2e/mock-api.mjs",
            url: `http://127.0.0.1:${apiPort}/health`,
            reuseExistingServer: false,
            timeout: 120_000,
          },
          {
            command: `COSTURA_API_URL=http://127.0.0.1:${apiPort} pnpm start --hostname 127.0.0.1 --port ${port}`,
            url: baseURL,
            reuseExistingServer: false,
            timeout: 120_000,
          },
        ]
      : undefined,
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
