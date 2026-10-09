resource "azurerm_api_management" "main" {
  name                 = local.apim_name
  location             = var.location
  resource_group_name  = local.rg
  publisher_name       = "Singtel IDS"
  publisher_email      = var.publisher_email
  sku_name             = "PremiumV2_${var.apim_capacity}"
  min_api_version      = "2024-05-01"
  virtual_network_type = "Internal"
  tags                 = local.tags
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.identity["gateway"].id]
  }
  virtual_network_configuration {
    subnet_id = azurerm_subnet.main["apim"].id
  }
  depends_on = [azurerm_subnet_network_security_group_association.apim]
}

resource "azurerm_private_dns_zone" "apim" {
  name                = "${local.apim_name}.azure-api.net"
  resource_group_name = local.rg
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "apim" {
  name                 = "${local.prefix}-link"
  private_dns_zone_id  = azurerm_private_dns_zone.apim.id
  virtual_network_id   = azurerm_virtual_network.main.id
  registration_enabled = false
}

resource "azurerm_private_dns_a_record" "apim" {
  name                = "@"
  private_dns_zone_id = azurerm_private_dns_zone.apim.id
  ttl                 = 300
  records             = azurerm_api_management.main.private_ip_addresses
}

resource "azurerm_api_management_product" "main" {
  product_id            = "aiflux"
  api_management_name   = azurerm_api_management.main.name
  resource_group_name   = local.rg
  display_name          = "AIFLUX (native validation pending)"
  subscription_required = true
  approval_required     = true
  published             = false
}

resource "azurerm_api_management_api" "blocked" {
  name                  = "aiflux-native-validation-pending"
  resource_group_name   = local.rg
  api_management_name   = azurerm_api_management.main.name
  revision              = "1"
  display_name          = "AIFLUX - disabled"
  path                  = "v1"
  protocols             = ["https"]
  subscription_required = true
}

resource "azurerm_api_management_api_operation" "blocked" {
  for_each            = { models = { method = "GET", path = "/models" }, chat = { method = "POST", path = "/chat/completions" } }
  operation_id        = each.key
  api_name            = azurerm_api_management_api.blocked.name
  api_management_name = azurerm_api_management.main.name
  resource_group_name = local.rg
  display_name        = each.key
  method              = each.value.method
  url_template        = each.value.path
}

resource "azurerm_api_management_product_api" "blocked" {
  api_name            = azurerm_api_management_api.blocked.name
  product_id          = azurerm_api_management_product.main.product_id
  api_management_name = azurerm_api_management.main.name
  resource_group_name = local.rg
}

resource "azurerm_api_management_policy" "closed" {
  api_management_id = azurerm_api_management.main.id
  xml_content       = file("${path.module}/../../gateway/policies/disabled.xml")
}

resource "azurerm_api_management_api_policy" "closed" {
  api_name            = azurerm_api_management_api.blocked.name
  api_management_name = azurerm_api_management.main.name
  resource_group_name = local.rg
  xml_content         = file("${path.module}/../../gateway/policies/disabled.xml")
}

resource "azapi_resource" "monitor_logger" {
  type      = "Microsoft.ApiManagement/service/loggers@2024-05-01"
  parent_id = azurerm_api_management.main.id
  name      = "azuremonitor"
  body = {
    properties = {
      loggerType  = "azureMonitor"
      description = "Metadata only; no prompts, completions or sensitive headers."
      isBuffered  = false
    }
  }
}

resource "azapi_resource" "monitor_diagnostic" {
  type      = "Microsoft.ApiManagement/service/diagnostics@2025-09-01-preview"
  parent_id = azurerm_api_management.main.id
  name      = "azuremonitor"
  body = {
    properties = {
      loggerId            = azapi_resource.monitor_logger.id
      alwaysLog           = "allErrors"
      sampling            = { samplingType = "fixed", percentage = 100 }
      logClientIp         = false
      verbosity           = "error"
      operationNameFormat = "Name"
      frontend = {
        request = {
          headers = []
          body    = { bytes = 0 }
          dataMasking = {
            queryParams = [
              { mode = "Hide", value = "subscription-key" },
              { mode = "Hide", value = "api-key" },
              { mode = "Hide", value = "access_token" },
            ]
          }
        }
        response = { headers = ["x-aiflux-model", "x-aiflux-provider", "x-aiflux-region"], body = { bytes = 0 } }
      }
      backend = {
        request  = { headers = [], body = { bytes = 0 } }
        response = { headers = [], body = { bytes = 0 } }
      }
      largeLanguageModel = {
        logs = "enabled"
      }
    }
  }
}

resource "azurerm_monitor_diagnostic_setting" "apim" {
  name                           = "${local.prefix}-apim-metadata"
  target_resource_id             = azurerm_api_management.main.id
  log_analytics_workspace_id     = azurerm_log_analytics_workspace.main.id
  log_analytics_destination_type = "Dedicated"
  enabled_log {
    category = "GatewayLogs"
  }
  enabled_log {
    category = "GatewayLlmLogs"
  }
}
