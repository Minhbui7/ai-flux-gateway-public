locals {
  database_url = "mssql+pyodbc://@${azurerm_mssql_server.main.fully_qualified_domain_name}:1433/${azurerm_mssql_database.main.name}?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no"
  control_settings = {
    AIFLUX_ENVIRONMENT         = "production"
    AIFLUX_DATABASE_URL        = local.database_url
    AIFLUX_ENTRA_AUDIENCE      = var.entra.audience
    AIFLUX_ENTRA_CLIENT_ID     = var.entra.client_id
    AIFLUX_HOME_TENANT_ID      = var.entra.home_tenant_id
    AIFLUX_BOOTSTRAP_OBJECT_ID = var.entra.bootstrap_object_id
    AIFLUX_GATEWAY_URL         = "https://${azurerm_cdn_frontdoor_endpoint.main.host_name}/v1"
    AIFLUX_APIM_RESOURCE_ID    = azurerm_api_management.main.id
    AIFLUX_APIM_PRODUCT_ID     = azurerm_api_management_product.main.product_id
    AIFLUX_LOG_WORKSPACE_ID    = azurerm_log_analytics_workspace.main.workspace_id
    AIFLUX_CATALOG_PATH        = var.catalog_container_path
    AIFLUX_CATALOG_CONFIGURED  = "false"
  }
}

resource "azurerm_service_plan" "apps" {
  name                = "${local.prefix}-apps-plan"
  resource_group_name = local.rg
  location            = var.location
  os_type             = "Linux"
  sku_name            = var.app_service_sku
  tags                = local.tags
  depends_on          = [terraform_data.approval]
}

resource "azurerm_linux_web_app" "main" {
  for_each                                       = var.apps
  name                                           = "${local.prefix}-${each.key}"
  resource_group_name                            = local.rg
  location                                       = var.location
  service_plan_id                                = azurerm_service_plan.apps.id
  https_only                                     = true
  public_network_access_enabled                  = false
  ftp_publish_basic_authentication_enabled       = false
  webdeploy_publish_basic_authentication_enabled = false
  virtual_network_subnet_id                      = azurerm_subnet.main["apps"].id
  key_vault_reference_identity_id                = azurerm_user_assigned_identity.identity[each.key].id
  tags                                           = local.tags
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.identity[each.key].id]
  }
  app_settings = merge(each.key == "api" ? local.control_settings : {}, {
    AZURE_CLIENT_ID                           = azurerm_user_assigned_identity.identity[each.key].client_id
    WEBSITES_PORT                             = tostring(each.value.port)
    APPLICATIONINSIGHTS_CONNECTION_STRING     = azurerm_application_insights.main.connection_string
    APPLICATIONINSIGHTS_AUTHENTICATION_STRING = "Authorization=AAD;ClientId=${azurerm_user_assigned_identity.identity[each.key].client_id}"
  })
  site_config {
    always_on                                     = true
    minimum_tls_version                           = "1.2"
    scm_minimum_tls_version                       = "1.2"
    ftps_state                                    = "Disabled"
    health_check_path                             = each.value.health_path
    detailed_error_logging_enabled                = false
    container_registry_use_managed_identity       = true
    container_registry_managed_identity_client_id = azurerm_user_assigned_identity.identity[each.key].client_id
    application_stack {
      docker_image_name   = each.value.image
      docker_registry_url = each.value.registry_url
    }
  }
  depends_on = [azurerm_role_assignment.acr_pull]
}

resource "azurerm_linux_function_app" "ingestion" {
  name                                           = "${local.prefix}-ingestion"
  resource_group_name                            = local.rg
  location                                       = var.location
  service_plan_id                                = azurerm_service_plan.apps.id
  storage_account_name                           = azapi_resource.function_storage.name
  storage_uses_managed_identity                  = true
  content_share_force_disabled                   = true
  enabled                                        = false
  https_only                                     = true
  public_network_access_enabled                  = false
  builtin_logging_enabled                        = false
  ftp_publish_basic_authentication_enabled       = false
  webdeploy_publish_basic_authentication_enabled = false
  virtual_network_subnet_id                      = azurerm_subnet.main["apps"].id
  tags                                           = local.tags
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.identity["ingestion"].id]
  }
  app_settings = merge(local.control_settings, {
    AIFLUX_CATALOG_PATH                       = "/home/site/wwwroot/gateway/catalog/models.json"
    AZURE_CLIENT_ID                           = azurerm_user_assigned_identity.identity["ingestion"].client_id
    FUNCTIONS_WORKER_RUNTIME                  = "python"
    AzureWebJobsStorage__credential           = "managedidentity"
    AzureWebJobsStorage__clientId             = azurerm_user_assigned_identity.identity["ingestion"].client_id
    AzureWebJobsStorage__blobServiceUri       = "https://${azapi_resource.function_storage.name}.blob.core.windows.net"
    AzureWebJobsStorage__queueServiceUri      = "https://${azapi_resource.function_storage.name}.queue.core.windows.net"
    AzureWebJobsStorage__tableServiceUri      = "https://${azapi_resource.function_storage.name}.table.core.windows.net"
    APPLICATIONINSIGHTS_AUTHENTICATION_STRING = "Authorization=AAD;ClientId=${azurerm_user_assigned_identity.identity["ingestion"].client_id}"
  })
  site_config {
    always_on                              = true
    minimum_tls_version                    = "1.2"
    scm_minimum_tls_version                = "1.2"
    ftps_state                             = "Disabled"
    detailed_error_logging_enabled         = false
    application_insights_connection_string = azurerm_application_insights.main.connection_string
    application_stack {
      python_version = "3.11"
    }
  }
  depends_on = [azurerm_role_assignment.function_storage]
}
