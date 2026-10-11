resource "azurerm_mssql_server" "main" {
  count                         = local.sql_stage ? 1 : 0
  name                          = "${local.prefix}-sql"
  resource_group_name           = local.rg
  location                      = local.sql_location
  version                       = "12.0"
  minimum_tls_version           = "1.2"
  public_network_access_enabled = var.sql_public_network_access_enabled
  connection_policy             = var.hybrid_private_data_enabled ? "Proxy" : "Default"
  tags                          = local.tags
  identity {
    type = "SystemAssigned"
  }
  azuread_administrator {
    login_username              = var.sql_admin.login
    object_id                   = var.sql_admin.object_id
    tenant_id                   = var.sql_admin.tenant_id
    azuread_authentication_only = true
  }
  depends_on = [terraform_data.approval]
}

resource "azurerm_mssql_database" "main" {
  count     = local.sql_stage ? 1 : 0
  name      = "aiflux"
  server_id = azurerm_mssql_server.main[0].id
  sku_name  = var.sql_sku
  tags      = local.tags
  lifecycle {
    prevent_destroy = true
  }
}

resource "azapi_resource" "function_storage" {
  count     = local.prerequisites_stage ? 1 : 0
  type      = "Microsoft.Storage/storageAccounts@2025-01-01"
  parent_id = local.rg_id
  name      = "${local.compact}func"
  location  = var.location
  tags      = local.tags
  body = {
    kind = "StorageV2"
    sku  = { name = "Standard_LRS" }
    properties = {
      minimumTlsVersion            = "TLS1_2"
      supportsHttpsTrafficOnly     = true
      allowBlobPublicAccess        = false
      allowSharedKeyAccess         = false
      publicNetworkAccess          = var.function_storage_public_network_access_enabled ? "Enabled" : "Disabled"
      defaultToOAuthAuthentication = true
      networkAcls = {
        defaultAction       = "Allow"
        bypass              = "None"
        ipRules             = []
        virtualNetworkRules = []
      }
    }
  }
  depends_on = [terraform_data.approval]
}

resource "azurerm_mssql_firewall_rule" "operator" {
  count            = local.sql_stage && var.sql_public_network_access_enabled ? 1 : 0
  name             = "reviewed-operator"
  server_id        = azurerm_mssql_server.main[0].id
  start_ip_address = var.operator_ip
  end_ip_address   = var.operator_ip
}

resource "azurerm_mssql_firewall_rule" "apps" {
  for_each         = local.platform_stage && var.sql_public_network_access_enabled ? var.sql_firewall_ipv4s : {}
  name             = "app-${each.key}"
  server_id        = azurerm_mssql_server.main[0].id
  start_ip_address = each.value
  end_ip_address   = each.value
}

locals {
  app_sql_outbound_ipv4s = local.platform_stage ? toset(concat(
    flatten([for app in values(azurerm_linux_web_app.main) : app.possible_outbound_ip_address_list]),
    azurerm_linux_function_app.ingestion[0].possible_outbound_ip_address_list,
  )) : toset([])
}

resource "terraform_data" "sql_firewall_gate" {
  count = local.public_edge_stage && !var.hybrid_private_data_enabled ? 1 : 0
  lifecycle {
    precondition {
      condition     = length(local.app_sql_outbound_ipv4s) > 0 && length(setsubtract(local.app_sql_outbound_ipv4s, toset(values(var.sql_firewall_ipv4s)))) == 0
      error_message = "Before public edge approval, capture all platform possible outbound IPv4 addresses and add reviewed exact-address SQL firewall rules in a second platform plan."
    }
  }
  depends_on = [azurerm_mssql_firewall_rule.apps]
}
