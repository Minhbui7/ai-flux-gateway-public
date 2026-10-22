export type Role = "customer" | "ids_admin";
export type SubscriptionState = "pending" | "active" | "suspended" | "failed";
export type KeyName = "primary" | "secondary";

export interface Me {
  organization_id: string;
  organization_name: string;
  tenant_id: string;
  object_id: string;
  role: Role;
}

export interface Paged<T> {
  items: T[];
  total: number;
}

export interface CatalogModel {
  id: string;
  provider: string;
  capabilities: string[];
  enabled: boolean;
  placeholder?: boolean;
  max_completion_tokens?: number | null;
}

export interface Subscription {
  id: string;
  name: string;
  team: string;
  state: SubscriptionState;
  created_at: string;
}

export interface AdminSubscription extends Subscription {
  organization_id: string;
  organization_name: string;
  team_id: string | null;
  gateway_access: "ready" | "pending" | "not_managed";
  gateway_message: string | null;
}

export interface UsageSummary {
  requests: number;
  input_tokens: number;
  output_tokens: number;
  known_cost: string | null;
  currency: string | null;
  incomplete_requests: number;
  failed_requests: number;
  throttled_requests: number;
  e2e_p95_ms: number | null;
  ttft_supported: boolean;
  cache_tokens_supported: boolean;
  last_ingested_at: string | null;
}

export interface UsageItem {
  id: string;
  subscription_id: string;
  model: string;
  provider: string;
  region: string;
  occurred_at: string;
  input_tokens: number | null;
  output_tokens: number | null;
  cached_input_tokens: number | null;
  cache_write_tokens: number | null;
  cost: string | null;
  currency: string | null;
  status_code: number;
  e2e_ms: number | null;
  ttft_ms: number | null;
  completeness: string;
}

export interface UsagePage extends Paged<UsageItem> {
  summary: UsageSummary;
}

export interface UsageMinute {
  minute: string;
  requests: number;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  avg_e2e_seconds: number | null;
  missing_token_requests: number;
  latency_samples: number;
}

export interface UsageSeries {
  items: UsageMinute[];
  start: string;
  end: string;
  interval_seconds: 60;
}

export interface ModelTokenBucket {
  start: string;
  end: string;
  model: string;
  requests: number;
  total_tokens: number | null;
  missing_token_requests: number;
}

export interface ModelTokenSeries {
  items: ModelTokenBucket[];
  start: string;
  end: string;
  interval_seconds: number;
}

export interface UsageFilters {
  days: number;
  subscription_id?: string;
  organization_id?: string;
  model?: string;
}

export interface UsageQuery extends UsageFilters {
  offset: number;
  limit: number;
}

export interface UsageSeriesQuery extends UsageFilters {
  start?: string;
  end?: string;
}

export interface Organization {
  id: string;
  name: string;
  tenant_id: string;
  enabled: boolean;
}

export interface Member {
  id: string;
  organization_id: string;
  object_id: string;
  role: Role;
  enabled: boolean;
}

export interface SafetyEvent {
  id: string;
  organization_id: string;
  subscription_id: string;
  occurred_at: string;
  category: string;
  action: string;
  correlation_id: string;
}

export interface Price {
  id: string;
  model: string;
  provider: string;
  region: string;
  effective_from: string;
  effective_to: string | null;
  currency: string;
  input_per_million: string;
  output_per_million: string;
  cached_input_per_million: string | null;
  cache_write_per_million: string | null;
  input_includes_cached: boolean;
}

export type PriceInput = Omit<Price, "id">;
export type GatewayScope = "dev-openai" | "dev-unified";
export type QuotaPeriod = "Hourly" | "Daily" | "Weekly" | "Monthly" | "Yearly";
export interface GatewayConfiguration {
  safety_threshold: number;
  rpm: number;
  tpm: number;
  token_quota: number;
  quota_period: QuotaPeriod;
}
export type Concurrency = 1 | 2 | 4 | 8 | 16;
export type RequestQuotaPeriod = "Daily" | "Monthly";
export interface GatewayLimits {
  rpm: number;
  tpm: number;
  token_quota: number;
  quota_period: QuotaPeriod;
  concurrency: Concurrency;
  request_quota: number | null;
  request_quota_period: RequestQuotaPeriod;
}
export interface TeamGatewayLimits { organization_id: string; team_id: string; limits: GatewayLimits }
export interface SubscriptionGatewayLimits { organization_id: string; subscription_id: string; limits: GatewayLimits }
export type SafetyProfile = "Standard" | "Strict" | "Custom";
export interface SafetyConfiguration {
  profile: SafetyProfile;
  hate: number;
  violence: number;
  sexual: number;
  self_harm: number;
  prompt_attack: boolean;
  protected_material: boolean;
  input_filtering: boolean;
  output_filtering: boolean;
}
export interface ManagedGatewayConfiguration {
  schema_version: 2;
  defaults: GatewayLimits;
  teams: TeamGatewayLimits[];
  subscriptions: SubscriptionGatewayLimits[];
  safety: SafetyConfiguration;
}
export type GatewayConfigurationUnion = GatewayConfiguration | ManagedGatewayConfiguration;
export interface GatewayCapabilities {
  managed_controls_enabled: boolean;
  concurrency_tiers: number[];
  protected_material_available: boolean;
  safety_relaxation_allowed: boolean;
  monthly_request_quota_available: boolean;
  enforcement_enabled: boolean;
  initial_safety_threshold?: number;
}
export interface GatewayTarget {
  organization_id: string;
  organization_name: string;
  team_id: string;
  team: string;
  subscription_id: string;
  name: string;
  state: SubscriptionState;
}export interface GatewayRevision {
  version: number;
  configuration: GatewayConfigurationUnion;
  reason: string;
  object_id: string;
  occurred_at: string;
  state: "pending" | "published" | "failed";
  error: string | null;
}
export interface GatewaySettings {
  scope: GatewayScope;
  max_rpm: number;
  max_tpm: number;
  version: number;
  published_version: number | null;
  desired: GatewayRevision | null;
  capabilities?: GatewayCapabilities;
}