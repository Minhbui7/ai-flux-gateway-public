mock_provider "azurerm" {
  mock_data "azurerm_resource_group" {
    defaults = {
      id       = "/subscriptions/4d75ed7f-75ab-4db6-b1f3-263f240d1450/resourceGroups/rg-aiflux-fdpo-dev"
      location = "eastus"
    }
  }
  mock_data "azurerm_client_config" {
    defaults = {
      subscription_id = "4d75ed7f-75ab-4db6-b1f3-263f240d1450"
      tenant_id       = "00000000-0000-0000-0000-000000000001"
    }
  }
  mock_resource "azurerm_api_management" {
    defaults = {
      id                   = "/subscriptions/4d75ed7f-75ab-4db6-b1f3-263f240d1450/resourceGroups/rg-aiflux-fdpo-dev/providers/Microsoft.ApiManagement/service/aiflux-test-apim"
      private_ip_addresses = ["10.50.2.4"]
    }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/4d75ed7f-75ab-4db6-b1f3-263f240d1450/resourceGroups/rg-aiflux-fdpo-dev/providers/Microsoft.ManagedIdentity/userAssignedIdentities/test"
      client_id    = "00000000-0000-0000-0000-000000000002"
      principal_id = "00000000-0000-0000-0000-000000000003"
    }
  }
  mock_resource "azurerm_application_insights" {
    defaults = {
      id                = "/subscriptions/4d75ed7f-75ab-4db6-b1f3-263f240d1450/resourceGroups/rg-aiflux-fdpo-dev/providers/Microsoft.Insights/components/test"
      connection_string = "InstrumentationKey=00000000-0000-0000-0000-000000000004"
    }
  }
}

mock_provider "azapi" {}

variables {
  subscription_id      = "4d75ed7f-75ab-4db6-b1f3-263f240d1450"
  resource_group_name  = "rg-aiflux-fdpo-dev"
  location             = "eastus"
  name_prefix          = "aiflux-test"
  deployment_approved  = true
  publisher_email      = "test@example.invalid"
  apim_capacity        = 1
  app_service_sku      = "P1v3"
  sql_sku              = "S0"
  log_retention_days   = 30
  registry_resource_id = "/subscriptions/4d75ed7f-75ab-4db6-b1f3-263f240d1450/resourceGroups/rg-aiflux-fdpo-dev/providers/Microsoft.ContainerRegistry/registries/test"
  entra = {
    audience            = "api://test"
    client_id           = "00000000-0000-0000-0000-000000000005"
    home_tenant_id      = "00000000-0000-0000-0000-000000000001"
    bootstrap_object_id = "00000000-0000-0000-0000-000000000006"
  }
  sql_admin = {
    login     = "test-admin"
    object_id = "00000000-0000-0000-0000-000000000007"
    tenant_id = "00000000-0000-0000-0000-000000000001"
  }
  network = {
    address_space       = "10.50.0.0/16"
    app_gateway_subnet  = "10.50.0.0/24"
    app_gateway_ip      = "10.50.0.10"
    private_link_subnet = "10.50.1.0/24"
    apim_subnet         = "10.50.2.0/24"
    apps_subnet         = "10.50.3.0/24"
    endpoints_subnet    = "10.50.4.0/24"
  }
  edge = {
    origin_hostname             = "origin.example.invalid"
    certificate_secret_id       = "https://test.vault.azure.net/secrets/test"
    certificate_vault_id        = "/subscriptions/4d75ed7f-75ab-4db6-b1f3-263f240d1450/resourceGroups/rg-aiflux-fdpo-dev/providers/Microsoft.KeyVault/vaults/test"
    private_link_location       = "eastus"
    request_timeout_seconds     = 120
    app_gateway_timeout_seconds = 120
    waf_body_limit_kb           = 128
    waf_inspection_limit_kb     = 128
    zones                       = ["1", "2", "3"]
  }
  apps = {
    api      = { image = "test/api@sha256:0000", registry_url = "https://test.azurecr.io", port = 8000, health_path = "/health" }
    customer = { image = "test/customer@sha256:0000", registry_url = "https://test.azurecr.io", port = 8080, health_path = "/" }
    admin    = { image = "test/admin@sha256:0000", registry_url = "https://test.azurecr.io", port = 8080, health_path = "/admin/" }
  }
}

run "disabled_posture" {
  command = plan
  assert {
    condition     = azurerm_api_management.main.sku_name == "PremiumV2_1" && azurerm_api_management.main.virtual_network_type == "Internal"
    error_message = "Gateway must be the private v2 candidate, not a classic/public substitute."
  }
  assert {
    condition     = !azurerm_api_management_product.main.published && azurerm_api_management_api.blocked.subscription_required
    error_message = "The product must remain unpublished and native subscriptions required."
  }
  assert {
    condition     = !azurerm_cdn_frontdoor_route.main.enabled && !azurerm_linux_function_app.ingestion.enabled
    error_message = "Edge/ingestion must remain disabled until reviewed operational configuration."
  }
  assert {
    condition     = !output.inference_enabled && local.control_settings.AIFLUX_CATALOG_CONFIGURED == "false"
    error_message = "No success-shaped inference/catalog defaults."
  }
  assert {
    condition     = alltrue([for app in azurerm_linux_web_app.main : !app.public_network_access_enabled]) && !azurerm_mssql_server.main.public_network_access_enabled
    error_message = "No public application/SQL origins."
  }
  assert {
    condition     = azapi_resource.monitor_diagnostic.body.properties.largeLanguageModel == { logs = "enabled" }
    error_message = "LLM message capture must be omitted."
  }
}

run "reject_unapproved_cost" {
  command = plan
  variables {
    deployment_approved = false
  }
  expect_failures = [terraform_data.approval]
}
