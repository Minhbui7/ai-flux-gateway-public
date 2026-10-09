data "azurerm_resource_group" "existing" {
  name = var.resource_group_name
}

data "azurerm_client_config" "current" {}

locals {
  rg        = data.azurerm_resource_group.existing.name
  rg_id     = data.azurerm_resource_group.existing.id
  prefix    = var.name_prefix
  compact   = replace(var.name_prefix, "-", "")
  tags      = merge(var.tags, { service = "aiflux", inference = "disabled" })
  apim_name = "${local.prefix}-apim"
}

resource "terraform_data" "approval" {
  input = var.deployment_approved
  lifecycle {
    precondition {
      condition     = var.deployment_approved
      error_message = "Cost/config approval is required before planning infrastructure. Inference remains blocked independently."
    }
    precondition {
      condition     = data.azurerm_client_config.current.subscription_id == var.subscription_id
      error_message = "Provider subscription must match the explicitly supplied subscription."
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
  for_each            = toset(["gateway", "edge", "api", "customer", "admin", "ingestion"])
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
  public_network_access_enabled = false
  tags                          = local.tags
  network_acls {
    bypass         = "None"
    default_action = "Deny"
  }
  depends_on = [terraform_data.approval]
}

resource "azapi_resource" "ai" {
  for_each  = { language = "TextAnalytics", safety = "ContentSafety" }
  type      = "Microsoft.CognitiveServices/accounts@2024-10-01"
  parent_id = local.rg_id
  name      = "${local.prefix}-${each.key}"
  location  = var.location
  tags      = local.tags
  identity {
    type = "SystemAssigned"
  }
  body = {
    kind = each.value
    sku  = { name = "S0" }
    properties = {
      customSubDomainName = "${local.prefix}-${each.key}"
      publicNetworkAccess = "Disabled"
      disableLocalAuth    = true
      networkAcls         = { defaultAction = "Deny", ipRules = [], virtualNetworkRules = [] }
    }
  }
  response_export_values = ["properties.endpoint"]
  depends_on             = [terraform_data.approval]
}
