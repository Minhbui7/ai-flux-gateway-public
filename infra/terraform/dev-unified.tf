locals {
  dev_unified_aliases = concat(
    sort(tolist(local.dev_aliases)),
    local.dev_haiku_aliases,
    sort(tolist(local.dev_accepted_aliases))
  )
}

data "azapi_resource" "dev_haiku" {
  count                  = var.dev_unified_inference_enabled && !local.australian_pilot ? 1 : 0
  type                   = "Microsoft.CognitiveServices/accounts/deployments@2025-06-01"
  parent_id              = azapi_resource.ai["language"].id
  name                   = "claude-haiku-5-5"
  response_export_values = ["properties"]
}

resource "azurerm_api_management_api" "dev_unified" {
  count                 = var.dev_unified_inference_enabled ? 1 : 0
  name                  = "aiflux-dev-unified"
  resource_group_name   = local.rg
  api_management_name   = azurerm_api_management.main.name
  revision              = "1"
  display_name          = "AIFLUX guarded development adapter (not native unified API)"
  path                  = "dev/llm/v1"
  service_url           = "https://aiflux-disabled.invalid"
  protocols             = ["https"]
  subscription_required = true
  subscription_key_parameter_names {
    header = "Ocp-Apim-Subscription-Key"
    query  = "subscription-key"
  }
  import {
    content_format = "openapi+json"
    content_value  = file("${path.module}/../../gateway/openapi-dev-adapter.json")
  }
  lifecycle {
    precondition {
      condition     = var.dev_openai_inference_enabled && length(var.dev_portal_origins) == 2
      error_message = "The development adapter requires the verified OpenAI deployment gate and both exact portal origins."
    }
    precondition {
      condition     = length(local.dev_candidate_aliases) == 0 || var.dev_unified_inference_enabled
      error_message = "Temporary model candidates can only be routed through the guarded /dev/llm/v1 adapter, never /dev/v1."
    }
  }
}

# SQL-owned team subscriptions share APIM's ownerless per-user cap.
resource "azurerm_api_management_product" "dev_unified" {
  count                 = var.dev_unified_inference_enabled ? 1 : 0
  product_id            = "aiflux-dev-unified"
  api_management_name   = azurerm_api_management.main.name
  resource_group_name   = local.rg
  display_name          = "AIFLUX guarded development playground"
  subscription_required = true
  approval_required     = true
  subscriptions_limit   = 10
  published             = true
}

resource "azurerm_api_management_product_api" "dev_unified" {
  count               = var.dev_unified_inference_enabled ? 1 : 0
  api_name            = azurerm_api_management_api.dev_unified[0].name
  product_id          = azurerm_api_management_product.dev_unified[0].product_id
  api_management_name = azurerm_api_management.main.name
  resource_group_name = local.rg
}

resource "azapi_resource" "dev_anthropic_backend" {
  count     = var.dev_unified_inference_enabled && !local.australian_pilot ? 1 : 0
  type      = "Microsoft.ApiManagement/service/backends@2024-05-01"
  parent_id = azurerm_api_management.main.id
  name      = "dev-claude-haiku-5-5-eastus"
  body = {
    properties = {
      protocol    = "http"
      url         = "https://${local.prefix}-foundry.services.ai.azure.com/anthropic/v1"
      description = "Explicit text-only Anthropic Messages adapter; gateway UAMI authentication is applied by policy."
      tls         = { validateCertificateChain = true, validateCertificateName = true }
    }
  }
  lifecycle {
    precondition {
      condition     = data.azapi_resource.dev_haiku[0].output.properties.provisioningState == "Succeeded" && data.azapi_resource.dev_haiku[0].output.properties.model.name == "claude-haiku-5-5"
      error_message = "The guarded adapter requires the real succeeded Haiku 5.5 deployment in the primary Foundry account."
    }
  }
}

resource "azapi_resource" "dev_unified_policy" {
  count     = var.dev_unified_inference_enabled ? 1 : 0
  type      = "Microsoft.ApiManagement/service/apis/policies@2022-08-01"
  parent_id = replace(azurerm_api_management_api.dev_unified[0].id, ";rev=1", "")
  name      = "policy"
  body = {
    properties = {
      format = "rawxml"
      value = templatefile("${path.module}/../../gateway/policies/dev-openai.xml.tftpl", merge(local.gateway_policy_vars, {
        language_endpoint            = trimsuffix(azapi_resource.ai["language"].output.properties.endpoint, "/")
        gateway_identity_client      = azurerm_user_assigned_identity.identity["gateway"].client_id
        tpm_limit                    = var.dev_unified_tpm_limit
        rpm_limit                    = var.dev_openai_rpm_limit
        completion_token_limit       = var.dev_unified_max_completion_tokens
        safety_threshold             = local.gateway_legacy_threshold
        forward_tree                 = local.gateway_managed_v2_policy ? templatefile("${path.module}/../../gateway/policies/concurrency-tree.xml.tftpl", { fragment_id = azapi_resource.gateway_forward["dev-unified"].name }) : ""
        admin_settings_enabled       = var.dev_admin_settings_enabled
        settings_fragment_id         = var.dev_admin_settings_enabled ? azapi_resource.gateway_settings["dev-unified"].name : ""
        safety_backend_id            = azapi_resource.dev_content_safety_backend[0].name
        unified                      = true
        product_id                   = azurerm_api_management_product.dev_unified[0].product_id
        cors_origins                 = distinct(concat(var.dev_portal_origins, [for h in [var.gateway_origin_hostname] : "https://${h}" if h != ""]))
        model_list                   = jsonencode({ object = "list", data = [for alias in local.dev_unified_aliases : { id = alias, object = "model", owned_by = "aiflux" }] })
        model_alias_conditions       = local.dev_policy_model_alias_conditions
        model_completion_limits      = jsonencode(local.dev_completion_limits)
        anthropic_alias_conditions   = local.dev_policy_anthropic_conditions
        model_limit_rules            = local.dev_policy_model_limit_rules
        openai_aliases               = sort(tolist(local.dev_policy_openai_aliases))
        openai_pool_ids              = local.dev_policy_openai_pool_ids
        foundry_aliases              = sort(tolist(local.dev_policy_foundry_aliases))
        foundry_api_versions         = local.dev_policy_foundry_api_versions
        anthropic_aliases            = sort(tolist(local.dev_policy_anthropic_aliases))
        anthropic_context_conditions = local.dev_policy_anthropic_context_conditions
        anthropic_backend_ids        = local.dev_policy_anthropic_backend_ids
      }))
    }
  }
  depends_on = [
    azapi_resource.gateway_forward,
    azapi_resource.dev_anthropic_backend,
    azapi_resource.dev_anthropic_model_pool,
    azapi_resource.dev_model_pool,
    azapi_resource.dev_content_safety_backend
  ]
}
