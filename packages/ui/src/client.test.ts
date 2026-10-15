import { describe, expect, it } from "vitest";
import { ApiError, ControlApi } from "./client";

function api(handler: (url: string, init: RequestInit) => Response) {
  const calls: { url: string; init: RequestInit }[] = [];
  const f = (async (url: string, init: RequestInit) => { calls.push({ url, init }); return handler(url, init); }) as unknown as typeof fetch;
  return { client: new ControlApi("/api", async () => "tok", f), calls };
}

describe("ControlApi", () => {
  it("sends bearer token with no-store and idempotency key", async () => {
    const { client, calls } = api(() => new Response(JSON.stringify({ id: "1", name: "n", team: "t", state: "pending", created_at: "x" }), { status: 201 }));
    const s = await client.createSubscription({ name: "n", team: "t" }, "key-1");
    expect(s.state).toBe("pending");
    const c = calls[0]!;
    expect(c.url).toBe("/api/subscriptions");
    expect(c.init.cache).toBe("no-store");
    expect((c.init.headers as Record<string, string>)["Idempotency-Key"]).toBe("key-1");
    expect((c.init.headers as Record<string, string>).Authorization).toBe("Bearer tok");
    expect(JSON.parse(c.init.body as string)).toEqual({ name: "n", team: "t" });
  });
  it("surfaces FastAPI detail errors", async () => {
    const { client } = api(() => new Response(JSON.stringify({ detail: "Not approved" }), { status: 403 }));
    await expect(client.me()).rejects.toMatchObject({ status: 403, detail: "Not approved" });
  });
  it("keeps the token out of export URLs", async () => {
    const { client, calls } = api(() => new Response("a,b\n1,2\n"));
    await client.exportCsv(true, 30, "org-1");
    expect(calls[0]!.url).toBe("/api/admin/usage/export?days=30&organization_id=org-1");
    expect(calls[0]!.url).not.toContain("tok");
  });
  it("builds reveal and usage requests", async () => {
    const { client, calls } = api((u) => new Response(JSON.stringify(u.includes("reveal") ? { key: "k" } : { items: [], total: 0 })));
    expect(await client.revealKey("a b", "primary")).toBe("k");
    await client.subscriptions(50, 25);
    expect(calls[0]!.url).toBe("/api/subscriptions/a%20b/reveal");
    expect(calls[1]!.url).toBe("/api/subscriptions?offset=50&limit=25");
  });
  it("builds customer and admin minute-series requests with UTC viewport filters", async () => {
    const { client, calls } = api(() => new Response(JSON.stringify({ items: [], start: "2026-01-01T00:00:00Z", end: "2026-01-02T00:00:00Z", interval_seconds: 60 })));
    const viewport = { days: 7, subscription_id: "sub 1", organization_id: "org/1", start: "2026-01-01T00:00:00.000Z", end: "2026-01-02T00:00:00.000Z" };
    await client.usageSeries(viewport);
    await client.adminUsageSeries(viewport);
    expect(calls[0]!.url).toBe("/api/usage/timeseries?days=7&subscription_id=sub+1&start=2026-01-01T00%3A00%3A00.000Z&end=2026-01-02T00%3A00%3A00.000Z");
    expect(calls[1]!.url).toBe("/api/admin/usage/timeseries?days=7&subscription_id=sub+1&organization_id=org%2F1&start=2026-01-01T00%3A00%3A00.000Z&end=2026-01-02T00%3A00%3A00.000Z");
  });
  it("closes a price period with a timezone-aware timestamp", async () => {
    const { client, calls } = api(() => new Response("{}"));
    await client.endPrice("p/1", "2025-02-01T00:00:00.000Z");
    expect(calls[0]!.url).toBe("/api/admin/prices/p%2F1/end");
    expect(calls[0]!.init.method).toBe("PUT");
    expect(JSON.parse(calls[0]!.init.body as string)).toEqual({ effective_to: "2025-02-01T00:00:00.000Z" });
  });
  it("maps network failure to ApiError", async () => {
    const c = new ControlApi("/api", async () => "t", (async () => { throw new TypeError("x"); }) as unknown as typeof fetch);
    await expect(c.models()).rejects.toBeInstanceOf(ApiError);
  });
});