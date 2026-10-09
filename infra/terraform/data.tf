resource "azurerm_mssql_server" "main" {
  name                          = "${local.prefix}-sql"
  resource_group_name           = local.rg
  location                      = var.location
  version                       = "12.0"
  minimum_tls_version           = "1.2"
  public_network_access_enabled = false
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
  name      = "aiflux"
  server_id = azurerm_mssql_server.main.id
  sku_name  = var.sql_sku
  tags      = local.tags
  lifecycle {
    prevent_destroy = true
  }
}

resource "azapi_resource" "function_storage" {
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
      publicNetworkAccess          = "Disabled"
      defaultToOAuthAuthentication = true
      networkAcls = {
        defaultAction       = "Deny"
        bypass              = "None"
        ipRules             = []
        virtualNetworkRules = []
      }
    }
  }
  depends_on = [terraform_data.approval]
}
