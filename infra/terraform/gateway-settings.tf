locals {
  gateway_settings_active = var.dev_admin_settings_enabled || var.dev_admin_settings_provisioned
  gateway_settings_scopes = local.gateway_settings_active ? toset(concat(
    ["dev-openai"], var.dev_unified_inference_enabled ? ["dev-unified"] : []
  )) : toset([])
  # Managed v2 policy semantics need enforcement; v2 forward fragments only need provisioning.
  gateway_managed_v2_policy   = var.dev_gateway_controls_v2_enabled && var.dev_admin_settings_enabled
  gateway_forward_scopes      = var.dev_gateway_controls_v2_enabled ? local.gateway_settings_scopes : toset([])
  gateway_legacy_threshold    = var.dev_admin_settings_enabled ? "@((int)context.Variables[&quot;aiflux-safety-threshold&quot;])" : tostring(var.dev_openai_content_safety_threshold)
  gateway_category_thresholds = { for c in ["hate", "violence", "sexual", "self-harm"] : c => local.gateway_managed_v2_policy ? "@((int)(context.Variables.GetValueOrDefault&lt;bool&gt;(&quot;aiflux-managed-v2&quot;, false) ? context.Variables[&quot;aiflux-${c}-threshold&quot;] : context.Variables[&quot;aiflux-safety-threshold&quot;]))" : local.gateway_legacy_threshold }
  gateway_input_filter_expr   = local.gateway_managed_v2_policy ? "!context.Variables.GetValueOrDefault&lt;bool&gt;(&quot;aiflux-managed-v2&quot;, false) || context.Variables.GetValueOrDefault&lt;bool&gt;(&quot;aiflux-input-filtering&quot;, true)" : "true"
  gateway_output_filter_expr  = local.gateway_managed_v2_policy ? "!context.Variables.GetValueOrDefault&lt;bool&gt;(&quot;aiflux-managed-v2&quot;, false) || context.Variables.GetValueOrDefault&lt;bool&gt;(&quot;aiflux-output-filtering&quot;, true)" : "true"
  gateway_prompt_shield       = local.gateway_managed_v2_policy ? "!context.Variables.GetValueOrDefault&lt;bool&gt;(&quot;aiflux-managed-v2&quot;, false) || context.Variables.GetValueOrDefault&lt;bool&gt;(&quot;aiflux-prompt-attack&quot;, true)" : "true"
  gateway_protected_material  = var.dev_protected_material_available && local.gateway_managed_v2_policy
  gateway_policy_vars = {
    hate_threshold               = local.gateway_category_thresholds["hate"]
    violence_threshold           = local.gateway_category_thresholds["violence"]
    sexual_threshold             = local.gateway_category_thresholds["sexual"]
    selfharm_threshold           = local.gateway_category_thresholds["self-harm"]
    input_filter_expr            = local.gateway_input_filter_expr
    output_filter_expr           = local.gateway_output_filter_expr
    prompt_shield                = local.gateway_prompt_shield
    safety_relaxation_allowed    = var.dev_safety_relaxation_allowed
    managed_v2                   = local.gateway_managed_v2_policy
    protected_material_available = local.gateway_protected_material
    protected_material_url       = "${trimsuffix(azapi_resource.ai["safety"].output.properties.endpoint, "/")}/contentsafety/text:detectProtectedMaterial?api-version=2024-09-01"
  }
}

variable "dev_admin_settings_provisioned" {
  description = "Create runtime settings fragments, RBAC and scopes without turning on enforcement."
  type        = bool
  default     = false
}

variable "dev_gateway_controls_v2_enabled" {
  description = "Candidate gateway policy and API accept the v2 managed controls schema. Requires provisioned or enabled settings."
  type        = bool
  default     = false
  validation {
    condition     = !var.dev_gateway_controls_v2_enabled || var.dev_admin_settings_enabled || var.dev_admin_settings_provisioned
    error_message = "Gateway controls v2 require dev_admin_settings_provisioned or dev_admin_settings_enabled."
  }
}

variable "dev_protected_material_available" {
  description = "Operator-verified capability flag for Content Safety protected text detection; no protected-code guarantee."
  type        = bool
  default     = false
}

variable "dev_monthly_request_quota_available" {
  description = "Operator-verified capability flag for monthly request quotas."
  type        = bool
  default     = false
}

variable "dev_safety_relaxation_allowed" {
  description = "Allow admin settings to relax safety thresholds and disable harm scans or prompt shielding. Revoking this flag restores mandatory scans and shielding in the invariant policy."
  type        = bool
  default     = false
}

variable "dev_gateway_max_rpm" {
  description = "Maximum requests per minute a managed control may configure."
  type        = number
  default     = 2
}

variable "dev_admin_settings_enabled" {
  description = "Opt in to IDS-admin settings fragments. Initially denies inference until an admin explicitly publishes safety, RPM/TPM and token quota settings. Activation changes counter namespaces."
  type        = bool
  default     = false
  validation {
    condition     = !var.dev_admin_settings_enabled || var.dev_openai_inference_enabled
    error_message = "Admin settings require the existing guarded OpenAI inference gate; this does not enable inference or production."
  }
}

resource "azapi_resource" "gateway_settings" {
  for_each  = local.gateway_settings_scopes
  type      = "Microsoft.ApiManagement/service/policyFragments@2024-05-01"
  parent_id = azurerm_api_management.main.id
  name      = "aiflux-${each.key}-settings"
  body = {
    properties = {
      description = "Runtime-owned bounded settings; invariant inspection and routing remain Terraform-owned."
      format      = "rawxml"
      value       = file("${path.module}/../../gateway/policies/settings-unconfigured.xml")
    }
  }
  lifecycle {
    # Only the settings fragment's content is runtime-owned, never API policies/backends.
    ignore_changes = [body.properties.value]
    precondition {
      condition     = local.platform_stage
      error_message = "Admin settings require the platform API identity and SQL deployment."
    }
  }
}

resource "azurerm_role_definition" "gateway_settings" {
  count       = local.gateway_settings_active ? 1 : 0
  name        = "${local.prefix}-gateway-settings"
  scope       = local.rg_id
  description = "Read/write approved settings fragments only; no API policy, backend, role or service writes."
  permissions {
    actions = [
      "Microsoft.ApiManagement/service/policyFragments/read",
      "Microsoft.ApiManagement/service/policyFragments/write",
    ]
  }
  assignable_scopes = [local.rg_id]
}

resource "azurerm_role_assignment" "gateway_settings" {
  for_each           = local.gateway_settings_scopes
  scope              = azapi_resource.gateway_settings[each.key].id
  role_definition_id = azurerm_role_definition.gateway_settings[0].role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.identity["api"].principal_id
}

# Terraform owns forwarding/routing. Fragments cannot nest, so this fragment holds the retry+forward
# block only; concurrency wrappers are generated in the API policy around the literal include.
resource "azapi_resource" "gateway_forward" {
  for_each  = local.gateway_forward_scopes
  type      = "Microsoft.ApiManagement/service/policyFragments@2024-05-01"
  parent_id = azurerm_api_management.main.id
  name      = "aiflux-${each.key}-forward"
  body = {
    properties = {
      description = "Terraform-owned backend retry and forwarding."
      format      = "rawxml"
      value = templatefile("${path.module}/../../gateway/policies/forward-fragment.xml.tftpl", {
        unified               = each.key == "dev-unified"
        openai_aliases        = sort(tolist(local.dev_policy_openai_aliases))
        openai_pool_ids       = local.dev_policy_openai_pool_ids
        anthropic_aliases     = sort(tolist(local.dev_policy_anthropic_aliases))
        anthropic_backend_ids = local.dev_policy_anthropic_backend_ids
      })
    }
  }
  depends_on = [
    azapi_resource.dev_model_pool,
    azapi_resource.dev_anthropic_backend,
    azapi_resource.dev_anthropic_model_pool,
  ]
}
