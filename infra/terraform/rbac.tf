resource "azurerm_role_definition" "subscription_manager" {
  name        = "${local.prefix}-subscription-manager"
  scope       = local.rg_id
  description = "Runtime APIM team subscription operations; no policy/backend/service write."
  permissions {
    actions = [
      "Microsoft.ApiManagement/service/read",
      "Microsoft.ApiManagement/service/products/read",
      "Microsoft.ApiManagement/service/subscriptions/read",
      "Microsoft.ApiManagement/service/subscriptions/write",
      "Microsoft.ApiManagement/service/subscriptions/listSecrets/action",
      "Microsoft.ApiManagement/service/subscriptions/regeneratePrimaryKey/action",
      "Microsoft.ApiManagement/service/subscriptions/regenerateSecondaryKey/action",
    ]
  }
  assignable_scopes = [local.rg_id]
}

resource "azurerm_role_assignment" "subscription_manager" {
  scope              = azurerm_api_management.main.id
  role_definition_id = azurerm_role_definition.subscription_manager.role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.identity["api"].principal_id
}

resource "azurerm_role_assignment" "monitor_reader" {
  for_each             = toset(["api", "ingestion"])
  scope                = azurerm_log_analytics_workspace.main.id
  role_definition_name = "Log Analytics Reader"
  principal_id         = azurerm_user_assigned_identity.identity[each.key].principal_id
}

resource "azurerm_role_assignment" "monitor_publisher" {
  for_each             = toset(["api", "customer", "admin", "ingestion", "gateway"])
  scope                = azurerm_application_insights.main.id
  role_definition_name = "Monitoring Metrics Publisher"
  principal_id         = azurerm_user_assigned_identity.identity[each.key].principal_id
}

resource "azurerm_role_assignment" "ai_user" {
  for_each             = azapi_resource.ai
  scope                = each.value.id
  role_definition_name = "Cognitive Services User"
  principal_id         = azurerm_user_assigned_identity.identity["gateway"].principal_id
}

resource "azurerm_role_assignment" "gateway_secrets" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.identity["gateway"].principal_id
}

resource "azurerm_role_assignment" "edge_certificate" {
  scope                = var.edge.certificate_vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.identity["edge"].principal_id
}

resource "azurerm_role_assignment" "acr_pull" {
  for_each             = toset(["api", "customer", "admin"])
  scope                = var.registry_resource_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.identity[each.key].principal_id
}

resource "azurerm_role_assignment" "function_storage" {
  for_each = toset([
    "Storage Blob Data Owner",
    "Storage Queue Data Contributor",
    "Storage Table Data Contributor",
  ])
  scope                = azapi_resource.function_storage.id
  role_definition_name = each.key
  principal_id         = azurerm_user_assigned_identity.identity["ingestion"].principal_id
}
