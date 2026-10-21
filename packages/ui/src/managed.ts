import type {
  Concurrency, GatewayCapabilities, GatewayConfiguration, GatewayConfigurationUnion, GatewayLimits, ManagedGatewayConfiguration,
  QuotaPeriod, RequestQuotaPeriod, SafetyConfiguration,
} from "./types";

export const QUOTA_PERIODS: QuotaPeriod[] = ["Hourly", "Daily", "Weekly", "Monthly", "Yearly"];
export const CONCURRENCY_TIERS: Concurrency[] = [1, 2, 4, 8, 16];
export const INT_MAX = 2147483647;

export const isManaged = (c: GatewayConfigurationUnion | null | undefined): c is ManagedGatewayConfiguration =>
  c != null && (c as ManagedGatewayConfiguration).schema_version === 2;

/** Legacy-shaped view used by the legacy form, even when the latest snapshot is managed. */
export function legacyOf(c: GatewayConfigurationUnion | null | undefined): GatewayConfiguration | undefined {
  if (!c) return undefined;
  if (!isManaged(c)) return c;
  const { rpm, tpm, token_quota, quota_period } = c.defaults;
  return { safety_threshold: c.safety.hate, rpm, tpm, token_quota, quota_period };
}

export const STANDARD_SAFETY: SafetyConfiguration = {
  profile: "Standard", hate: 4, violence: 4, sexual: 4, self_harm: 4,
  prompt_attack: true, protected_material: true, input_filtering: true, output_filtering: true,
};
export const STRICT_SAFETY: SafetyConfiguration = { ...STANDARD_SAFETY, profile: "Strict", hate: 1, violence: 1, sexual: 1, self_harm: 1 };

/** Custom safety equivalent to the single legacy threshold; protected material was never enabled. */
export const migrateLegacySafety = (threshold: number): SafetyConfiguration => ({
  profile: "Custom", hate: threshold, violence: threshold, sexual: threshold, self_harm: threshold,
  prompt_attack: true, protected_material: false, input_filtering: true, output_filtering: true,
});

export const currentSafety = (c: GatewayConfigurationUnion | null | undefined, initialThreshold?: number): SafetyConfiguration | undefined =>
  isManaged(c) ? c.safety : migrateLegacySafety(c ? c.safety_threshold : initialThreshold ?? 1);

export const SAFETY_CATEGORIES = ["hate", "violence", "sexual", "self_harm"] as const;
export const SAFETY_TOGGLES = ["prompt_attack", "protected_material", "input_filtering", "output_filtering"] as const;
export const safetyLabel: Record<(typeof SAFETY_CATEGORIES)[number] | (typeof SAFETY_TOGGLES)[number], string> = {
  hate: "Hate", violence: "Violence", sexual: "Sexual", self_harm: "Self-harm",
  prompt_attack: "Prompt attack detection", protected_material: "Protected material detection",
  input_filtering: "Input filtering", output_filtering: "Output filtering",
};

export function presetFor(profile: SafetyConfiguration["profile"], from: SafetyConfiguration): SafetyConfiguration {
  if (profile === "Standard") return STANDARD_SAFETY;
  if (profile === "Strict") return STRICT_SAFETY;
  return { ...from, profile: "Custom" };
}

/** Absolute operator floor (independent of stored settings): without relaxation, prompt/input/output scanning must be on. Protected material is not part of it. */
export const isFloorToggle = (k: (typeof SAFETY_TOGGLES)[number], caps: GatewayCapabilities | undefined): boolean =>
  !caps?.safety_relaxation_allowed && k !== "protected_material";

export function applyFloor(s: SafetyConfiguration, caps: GatewayCapabilities | undefined): SafetyConfiguration {
  const next = { ...s };
  for (const k of SAFETY_TOGGLES) if (isFloorToggle(k, caps)) next[k] = true;
  return next;
}

export function isRelaxation(next: SafetyConfiguration, current: SafetyConfiguration | undefined): boolean {
  if (!current) return false;
  return SAFETY_CATEGORIES.some((k) => next[k] > current[k]) || SAFETY_TOGGLES.some((k) => current[k] && !next[k]);
}

export function validateSafety(s: SafetyConfiguration, caps: GatewayCapabilities | undefined): string | null {
  for (const k of SAFETY_CATEGORIES) if (!Number.isInteger(s[k]) || s[k] < 0 || s[k] > 7) return `${safetyLabel[k]} threshold must be a whole number from 0 to 7.`;
  if (s.protected_material && !caps?.protected_material_available) return "Protected material detection is not available in this environment, so this configuration cannot be published.";
  for (const k of SAFETY_TOGGLES) if (!s[k] && isFloorToggle(k, caps)) return `${safetyLabel[k]} must be enabled by the operator floor.`;
  return null;
}

export type LimitsDraft = { rpm: string; tpm: string; token_quota: string; quota_period: string; concurrency: string; request_quota: string; request_quota_period: string };
export const emptyLimitsDraft = (): LimitsDraft => ({ rpm: "", tpm: "", token_quota: "", quota_period: "", concurrency: "", request_quota: "", request_quota_period: "Daily" });
export const limitsDraftOf = (l: GatewayLimits): LimitsDraft => ({
  rpm: String(l.rpm), tpm: String(l.tpm), token_quota: String(l.token_quota), quota_period: l.quota_period,
  concurrency: String(l.concurrency), request_quota: l.request_quota === null ? "" : String(l.request_quota), request_quota_period: l.request_quota_period,
});
export const limitsDraftOfLegacy = (c: GatewayConfiguration): LimitsDraft => ({
  ...emptyLimitsDraft(), rpm: String(c.rpm), tpm: String(c.tpm), token_quota: String(c.token_quota), quota_period: c.quota_period,
});

const whole = (s: string, lo: number, hi: number) => {
  const v = Number(s);
  return /^\d+$/.test(s) && Number.isSafeInteger(v) && v >= lo && v <= hi ? v : null;
};

export function validateLimits(d: LimitsDraft, max: { rpm: number; tpm: number }, caps: GatewayCapabilities | undefined): GatewayLimits | null {
  const rpm = whole(d.rpm, 1, max.rpm);
  const tpm = whole(d.tpm, 1, max.tpm);
  const token_quota = whole(d.token_quota, 1, INT_MAX);
  const concurrency = whole(d.concurrency, 1, 16);
  const quota_period = QUOTA_PERIODS.find((p) => p === d.quota_period);
  const rqp = (["Daily", "Monthly"] as RequestQuotaPeriod[]).find((p) => p === d.request_quota_period);
  const request_quota = d.request_quota === "" ? null : whole(d.request_quota, 1, INT_MAX);
  if (rpm === null || tpm === null || token_quota === null || concurrency === null || !quota_period || !rqp) return null;
  if (d.request_quota !== "" && request_quota === null) return null;
  const tiers = caps?.concurrency_tiers ?? CONCURRENCY_TIERS;
  if (!CONCURRENCY_TIERS.includes(concurrency as Concurrency) || !tiers.includes(concurrency)) return null;
  if (request_quota !== null && rqp === "Monthly" && !caps?.monthly_request_quota_available) return null;
  return { rpm, tpm, token_quota, quota_period, concurrency: concurrency as Concurrency, request_quota, request_quota_period: rqp };
}

export type ManagedDraft = {
  defaults: LimitsDraft;
  teams: Record<string, LimitsDraft>;
  subscriptions: Record<string, LimitsDraft>;
};
export const teamKey = (org: string, team: string) => `${org}/${team}`;
export const subKey = (org: string, sub: string) => `${org}/${sub}`;

export function managedDraftOf(c: GatewayConfigurationUnion | null | undefined): ManagedDraft {
  if (!c) return { defaults: emptyLimitsDraft(), teams: {}, subscriptions: {} };
  if (!isManaged(c)) return { defaults: limitsDraftOfLegacy(c), teams: {}, subscriptions: {} };
  return {
    defaults: limitsDraftOf(c.defaults),
    teams: Object.fromEntries(c.teams.map((t) => [teamKey(t.organization_id, t.team_id), limitsDraftOf(t.limits)])),
    subscriptions: Object.fromEntries(c.subscriptions.map((s) => [subKey(s.organization_id, s.subscription_id), limitsDraftOf(s.limits)])),
  };
}

export function buildManaged(d: ManagedDraft, safety: SafetyConfiguration, max: { rpm: number; tpm: number }, caps: GatewayCapabilities | undefined): ManagedGatewayConfiguration | null {
  const defaults = validateLimits(d.defaults, max, caps);
  if (!defaults) return null;
  const teams: ManagedGatewayConfiguration["teams"] = [];
  for (const [k, v] of Object.entries(d.teams)) {
    const limits = validateLimits(v, max, caps);
    if (!limits) return null;
    const [organization_id, team_id] = k.split("/");
    teams.push({ organization_id: organization_id!, team_id: team_id!, limits });
  }
  const subscriptions: ManagedGatewayConfiguration["subscriptions"] = [];
  for (const [k, v] of Object.entries(d.subscriptions)) {
    const limits = validateLimits(v, max, caps);
    if (!limits) return null;
    const [organization_id, subscription_id] = k.split("/");
    subscriptions.push({ organization_id: organization_id!, subscription_id: subscription_id!, limits });
  }
  return { schema_version: 2, defaults, teams, subscriptions, safety };
}

export const describeLimits = (l: GatewayLimits) =>
  `${l.rpm} RPM, ${l.tpm} TPM, ${l.token_quota} tokens per ${l.quota_period.toLowerCase()} window, concurrency ${l.concurrency}, ` +
  (l.request_quota === null ? "no request quota" : `${l.request_quota} requests ${l.request_quota_period.toLowerCase()}`);
