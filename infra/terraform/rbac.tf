# Elevated privileges required for role assignment
# These RBAC resources are deliberately inactive. An authorized RBAC administrator
# must create the scoped custom role and grants described in docs/deployment.md.
/*
resource "azurerm_role_definition" "subscription_manager" {
  for_each    = local.prerequisites_stage ? { platform = true } : {}
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
  for_each           = local.prerequisites_stage ? { platform = true } : {}
  scope              = azurerm_api_management.main.id
  role_definition_id = azurerm_role_definition.subscription_manager[each.key].role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.identity["api"].principal_id
}

resource "azurerm_role_assignment" "monitor_reader" {
  for_each             = local.prerequisites_stage ? toset(["api", "ingestion"]) : toset([])
  scope                = azurerm_log_analytics_workspace.main.id
  role_definition_name = "Log Analytics Reader"
  principal_id         = azurerm_user_assigned_identity.identity[each.key].principal_id
}

resource "azurerm_role_assignment" "monitor_publisher" {
  for_each             = toset(concat(["gateway"], local.prerequisites_stage ? ["api", "customer", "admin", "ingestion"] : []))
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
  for_each             = local.edge_tls_stage ? { edge = true } : {}
  scope                = trimsuffix(var.edge.certificate_vault_id, "/")
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.identity["edge"].principal_id
  lifecycle {
    create_before_destroy = true
    precondition {
      condition     = lower(trimsuffix(var.edge.certificate_vault_id, "/")) == lower(azurerm_key_vault.main.id)
      error_message = "Application Gateway read access must target the same managed Key Vault as the TLS certificate."
    }
  }
}

resource "azurerm_role_assignment" "acr_pull" {
  for_each             = local.prerequisites_stage ? toset(concat(["api", "customer", "admin"], var.ingestion_container_image != "" ? ["ingestion"] : [])) : toset([])
  scope                = local.registry_resource_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.identity[each.key].principal_id
}

resource "azurerm_role_assignment" "function_storage" {
  for_each = local.prerequisites_stage ? toset([
    "Storage Blob Data Owner",
    "Storage Queue Data Contributor",
    "Storage Table Data Contributor",
  ]) : toset([])
  scope                = azapi_resource.function_storage[0].id
  role_definition_name = each.key
  principal_id         = azurerm_user_assigned_identity.identity["ingestion"].principal_id
}
*/
