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

export interface UsageQuery {
  days: number;
  subscription_id?: string;
  organization_id?: string;
  offset: number;
  limit: number;
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