import type {
  CatalogModel, KeyName, Me, Member, Organization, Paged, Price, PriceInput, SafetyEvent,
  Subscription, SubscriptionState, UsagePage, UsageQuery,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
    this.name = "ApiError";
  }
}

export type TokenProvider = () => Promise<string>;
export type FetchLike = typeof fetch;

function detailOf(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      return d.map((e) => (e && typeof e === "object" && "msg" in e ? String((e as { msg: unknown }).msg) : "Invalid request")).join("; ");
    }
  }
  return fallback;
}

function qs(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") sp.set(k, String(v));
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export class ControlApi {
  constructor(
    private baseUrl: string,
    private getToken: TokenProvider,
    private fetchImpl: FetchLike = (...a) => fetch(...a),
  ) {}

  private async send(path: string, init: Omit<RequestInit, "headers"> & { json?: unknown; headers?: Record<string, string> } = {}): Promise<Response> {
    const token = await this.getToken();
    const headers: Record<string, string> = { Accept: "application/json", ...(init.headers ?? {}), Authorization: `Bearer ${token}` };
    let body = init.body;
    if (init.json !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(init.json);
    }
    let res: Response;
    try {
      res = await this.fetchImpl(`${this.baseUrl}${path}`, { ...init, headers, body, cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer" });
    } catch {
      throw new ApiError(0, "Could not reach the control plane. Check your connection and try again.");
    }
    if (!res.ok) {
      let detail = `Request failed (${res.status}).`;
      try {
        detail = detailOf(await res.json(), detail);
      } catch {
        /* non-JSON error body */
      }
      throw new ApiError(res.status, detail);
    }
    return res;
  }

  private async json<T>(path: string, init?: Parameters<ControlApi["send"]>[1]): Promise<T> {
    const res = await this.send(path, init);
    return (await res.json()) as T;
  }

  me = () => this.json<Me>("/me");
  models = () => this.json<Paged<CatalogModel>>("/models");
  subscriptions = (offset = 0, limit = 50) => this.json<Paged<Subscription>>(`/subscriptions${qs({ offset, limit })}`);
  createSubscription = (input: { name: string; team: string }, idempotencyKey: string) =>
    this.json<Subscription>("/subscriptions", { method: "POST", json: input, headers: { "Idempotency-Key": idempotencyKey } });
  revealKey = async (id: string, key: KeyName) =>
    (await this.json<{ key: string }>(`/subscriptions/${encodeURIComponent(id)}/reveal`, { method: "POST", json: { key } })).key;
  rotateKey = (id: string, key: KeyName) =>
    this.json<{ state: SubscriptionState }>(`/subscriptions/${encodeURIComponent(id)}/rotate`, { method: "POST", json: { key } });
  setState = (id: string, state: "active" | "suspended") =>
    this.json<Subscription>(`/subscriptions/${encodeURIComponent(id)}/state`, { method: "PUT", json: { state } });
  reconcile = (id: string) => this.json<Subscription>(`/subscriptions/${encodeURIComponent(id)}/reconcile`, { method: "POST" });

  usage = (q: UsageQuery) => this.json<UsagePage>(`/usage${qs({ days: q.days, subscription_id: q.subscription_id, offset: q.offset, limit: q.limit })}`);
  adminUsage = (q: UsageQuery) =>
    this.json<UsagePage>(`/admin/usage${qs({ days: q.days, subscription_id: q.subscription_id, organization_id: q.organization_id, offset: q.offset, limit: q.limit })}`);

  /** Authenticated CSV export; the token travels only in the Authorization header. */
  async exportCsv(admin: boolean, days: number, organizationId?: string): Promise<Blob> {
    const path = admin ? `/admin/usage/export${qs({ days, organization_id: organizationId })}` : `/usage/export${qs({ days })}`;
    const res = await this.send(path, { headers: { Accept: "text/csv" } });
    return res.blob();
  }

  organizations = () => this.json<Paged<Organization>>("/admin/organizations");
  createOrganization = (input: { name: string; tenant_id: string }) => this.json<Organization>("/admin/organizations", { method: "POST", json: input });
  setOrganizationEnabled = (id: string, enabled: boolean) =>
    this.json<Organization>(`/admin/organizations/${encodeURIComponent(id)}`, { method: "PUT", json: { enabled } });

  members = (organizationId: string) => this.json<Paged<Member>>(`/admin/members${qs({ organization_id: organizationId })}`);
  createMember = (input: { organization_id: string; object_id: string; role: Member["role"] }) =>
    this.json<Member>("/admin/members", { method: "POST", json: input });
  setMemberEnabled = (id: string, enabled: boolean) =>
    this.json<Member>(`/admin/members/${encodeURIComponent(id)}`, { method: "PUT", json: { enabled } });

  safety = (days: number, organizationId: string | undefined, offset: number, limit: number) =>
    this.json<Paged<SafetyEvent>>(`/admin/safety${qs({ days, organization_id: organizationId, offset, limit })}`);

  prices = () => this.json<Paged<Price>>("/admin/prices");
  endPrice = (id: string, effectiveTo: string) =>
    this.json<Price>(`/admin/prices/${encodeURIComponent(id)}/end`, { method: "PUT", json: { effective_to: effectiveTo } });
  createPrice = (input: PriceInput) => this.json<Price>("/admin/prices", { method: "POST", json: input });
}