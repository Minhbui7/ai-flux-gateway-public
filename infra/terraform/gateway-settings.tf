locals {
  gateway_settings_scopes = var.dev_admin_settings_enabled ? toset(concat(
    ["dev-openai"], var.dev_unified_inference_enabled ? ["dev-unified"] : []
  )) : toset([])
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
  count       = var.dev_admin_settings_enabled ? 1 : 0
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
