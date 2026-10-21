data "azurerm_resource_group" "existing" {
  name = var.resource_group_name
}

data "azurerm_client_config" "current" {}

locals {
  rg                  = data.azurerm_resource_group.existing.name
  rg_id               = data.azurerm_resource_group.existing.id
  prefix              = var.name_prefix
  compact             = replace(var.name_prefix, "-", "")
  tags                = merge(var.tags, { service = "aiflux", inference = "disabled" })
  apim_name           = "${local.prefix}-apim"
  sql_location        = coalesce(var.sql_location, var.location)
  platform_stage      = contains(["platform", "edge-bootstrap", "edge-candidate", "public-edge"], var.deployment_stage)
  prerequisites_stage = contains(["prerequisites", "platform", "edge-bootstrap", "edge-candidate", "public-edge"], var.deployment_stage)
  sql_stage           = local.prerequisites_stage && var.sql_enabled
  public_edge_stage   = var.deployment_stage == "public-edge"
  edge_stage          = contains(["edge-bootstrap", "edge-candidate", "public-edge"], var.deployment_stage)
  edge_tls_stage      = contains(["edge-candidate", "public-edge"], var.deployment_stage)
  hybrid_data_stage   = local.prerequisites_stage && var.hybrid_private_data_enabled
  identity_names = toset(concat(
    ["gateway"],
    local.prerequisites_stage ? ["api", "customer", "admin", "ingestion"] : [],
    local.edge_stage ? ["edge"] : [],
  ))
}

resource "terraform_data" "approval" {
  input = var.deployment_approved
  lifecycle {
    precondition {
      condition     = var.deployment_approved
      error_message = "Cost/config approval is required before planning infrastructure. Inference remains blocked independently."
    }
    precondition {
      condition     = (!local.platform_stage && !var.dev_openai_inference_enabled && !var.dev_unified_inference_enabled) || var.manual_rbac_verified
      error_message = "Elevated privileges required for role assignment: an authorized administrator must provision and verify the documented manual RBAC grants before runtime or inference rollout."
    }
    precondition {
      condition     = data.azurerm_client_config.current.subscription_id == var.subscription_id
      error_message = "Provider subscription must match the explicitly supplied subscription."
    }
    precondition {
      condition     = var.deployment_stage != "public-edge" || var.public_edge_live_gates_approved
      error_message = "Public Application Gateway routes require explicit approval after live application, authorization, DNS, TLS, WAF and backend acceptance."
    }
    precondition {
      condition     = var.deployment_stage != "public-edge" || var.protection_language_enabled
      error_message = "Deferred Language/PII provisioning blocks public-edge release; provisioning other components does not attest protection readiness."
    }
    precondition {
      condition     = !local.public_edge_stage || !var.hybrid_private_data_enabled || var.private_sql_connectivity_accepted
      error_message = "Hybrid public-edge release requires live private SQL identity/connectivity and migration acceptance, not public firewall IP capture."
    }
    precondition {
      condition     = !local.public_edge_stage || var.sql_public_network_access_enabled || var.hybrid_private_data_enabled
      error_message = "Public-edge release requires either reviewed public SQL firewall rules or the hybrid private data path."
    }
  }
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "${local.prefix}-logs"
  location            = var.location
  resource_group_name = local.rg
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_days
  tags                = local.tags
  depends_on          = [terraform_data.approval]
}

resource "azurerm_application_insights" "main" {
  name                         = "${local.prefix}-insights"
  location                     = var.location
  resource_group_name          = local.rg
  workspace_id                 = azurerm_log_analytics_workspace.main.id
  application_type             = "web"
  local_authentication_enabled = false
  tags                         = local.tags
}

resource "azurerm_user_assigned_identity" "identity" {
  for_each            = local.identity_names
  name                = "${local.prefix}-${each.key}-identity"
  location            = var.location
  resource_group_name = local.rg
  tags                = local.tags
  depends_on          = [terraform_data.approval]
}

resource "azurerm_key_vault" "main" {
  name                          = "${local.compact}kv"
  location                      = var.location
  resource_group_name           = local.rg
  tenant_id                     = data.azurerm_client_config.current.tenant_id
  sku_name                      = "standard"
  rbac_authorization_enabled    = true
  purge_protection_enabled      = true
  soft_delete_retention_days    = 90
  public_network_access_enabled = var.key_vault_public_network_access_enabled
  tags                          = local.tags
  network_acls {
    bypass         = "AzureServices"
    default_action = "Allow"
  }
  depends_on = [terraform_data.approval]
}

resource "azapi_resource" "ai" {
  for_each  = merge({ safety = "ContentSafety" }, var.protection_language_enabled ? { language = "AIServices" } : {})
  type      = "Microsoft.CognitiveServices/accounts@2024-10-01"
  parent_id = local.rg_id
  name      = each.key == "language" ? "${local.prefix}-foundry" : "${local.prefix}-${each.key}"
  location  = each.key == "language" ? coalesce(var.model_location, var.location) : var.location
  tags      = local.tags
  identity {
    type = "SystemAssigned"
  }
  body = {
    kind = each.value
    sku  = { name = "S0" }
    properties = {
      customSubDomainName = each.key == "language" ? "${local.prefix}-foundry" : "${local.prefix}-${each.key}"
      publicNetworkAccess = "Enabled"
      disableLocalAuth    = true
      networkAcls         = { defaultAction = "Allow", ipRules = [], virtualNetworkRules = [] }
    }
  }
  response_export_values = ["properties.endpoint"]
  depends_on             = [terraform_data.approval]
}
