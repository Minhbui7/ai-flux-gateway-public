locals {
  dev_unified_aliases = concat(sort(tolist(local.dev_aliases)), ["claude-haiku-5-5"])
}

data "azapi_resource" "dev_haiku" {
  count                  = var.dev_unified_inference_enabled ? 1 : 0
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
  count     = var.dev_unified_inference_enabled ? 1 : 0
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
      value = templatefile("${path.module}/../../gateway/policies/dev-openai.xml.tftpl", {
        language_endpoint       = trimsuffix(azapi_resource.ai["language"].output.properties.endpoint, "/")
        gateway_identity_client = azurerm_user_assigned_identity.identity["gateway"].client_id
        tpm_limit               = var.dev_unified_tpm_limit
        rpm_limit               = var.dev_openai_rpm_limit
        completion_token_limit  = var.dev_unified_max_completion_tokens
        safety_threshold        = var.dev_openai_content_safety_threshold
        safety_backend_id       = azapi_resource.dev_content_safety_backend[0].name
        unified                 = true
        product_id              = azurerm_api_management_product.dev_unified[0].product_id
        cors_origins            = distinct(concat(var.dev_portal_origins, [for h in [var.gateway_origin_hostname] : "https://${h}" if h != ""]))
        model_list              = jsonencode({ object = "list", data = [for alias in local.dev_unified_aliases : { id = alias, object = "model", owned_by = "aiflux" }] })
      })
    }
  }
  depends_on = [azapi_resource.dev_anthropic_backend, azapi_resource.dev_model_pool, azapi_resource.dev_content_safety_backend]
}
