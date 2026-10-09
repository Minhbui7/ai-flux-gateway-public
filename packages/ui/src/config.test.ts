import { describe, expect, it } from "vitest";
import { loadConfig } from "./config";

const good = {
  VITE_ENTRA_CLIENT_ID: "11111111-2222-3333-4444-555555555555",
  VITE_ENTRA_AUTHORITY: "https://login.microsoftonline.com/organizations",
  VITE_API_SCOPE: "api://x/access_as_user",
  VITE_GATEWAY_URL: "https://aiflux.example.com/v1/",
};

describe("loadConfig", () => {
  it("denies when empty", () => {
    const r = loadConfig({});
    expect(r.ok).toBe(false);
  });
  it("accepts valid config and defaults control URL to /api", () => {
    const r = loadConfig(good);
    expect(r).toMatchObject({ ok: true, config: { controlApiUrl: "/api", gatewayUrl: "https://aiflux.example.com/v1" } });
  });
  it("rejects non-organizations authority and insecure gateway", () => {
    expect(loadConfig({ ...good, VITE_ENTRA_AUTHORITY: "https://login.microsoftonline.com/common" }).ok).toBe(false);
    expect(loadConfig({ ...good, VITE_GATEWAY_URL: "http://example.com/v1" }).ok).toBe(false);
  });
});