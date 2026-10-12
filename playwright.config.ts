import { defineConfig } from "@playwright/test";

// The dev servers run WITHOUT VITE_* values on purpose: e2e verifies deny-by-default.
export default defineConfig({
  testDir: "tests/e2e",
  use: { browserName: "chromium" },
  webServer: [
    { command: "npm run dev -w @aiflux/customer-portal", url: "http://localhost:5173", reuseExistingServer: !process.env.CI, timeout: 60_000 },
    { command: "npm run dev -w @aiflux/admin-portal", url: "http://localhost:5174/admin/", reuseExistingServer: !process.env.CI, timeout: 60_000 },
  ],
});