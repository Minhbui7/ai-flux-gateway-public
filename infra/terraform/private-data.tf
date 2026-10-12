locals {
  private_data_services = local.hybrid_data_stage ? {
    sql   = { resource_id = azurerm_mssql_server.main[0].id, group = "sqlServer", zone = "privatelink.database.windows.net" }
    vault = { resource_id = azurerm_key_vault.main.id, group = "vault", zone = "privatelink.vaultcore.azure.net" }
    blob  = { resource_id = azapi_resource.function_storage[0].id, group = "blob", zone = "privatelink.blob.core.windows.net" }
    queue = { resource_id = azapi_resource.function_storage[0].id, group = "queue", zone = "privatelink.queue.core.windows.net" }
    table = { resource_id = azapi_resource.function_storage[0].id, group = "table", zone = "privatelink.table.core.windows.net" }
  } : {}
}

resource "azurerm_subnet" "private_endpoints" {
  count                = local.hybrid_data_stage ? 1 : 0
  name                 = "${local.prefix}-private-endpoints"
  resource_group_name  = local.rg
  virtual_network_name = azurerm_virtual_network.main[0].name
  address_prefixes     = [var.network.private_endpoint_subnet]
}

resource "azurerm_subnet" "app_service_integration" {
  count                = local.hybrid_data_stage ? 1 : 0
  name                 = "${local.prefix}-app-service-integration"
  resource_group_name  = local.rg
  virtual_network_name = azurerm_virtual_network.main[0].name
  address_prefixes     = [var.network.app_service_integration_subnet]
  delegation {
    name = "app-service"
    service_delegation {
      name    = "Microsoft.Web/serverFarms"
      actions = ["Microsoft.Network/virtualNetworks/subnets/action"]
    }
  }
}

resource "azurerm_network_security_group" "app_service_integration" {
  count               = local.hybrid_data_stage ? 1 : 0
  name                = "${local.prefix}-app-service-integration-nsg"
  location            = var.location
  resource_group_name = local.rg
  tags                = local.tags
  security_rule {
    name                       = "PrivateSqlProxyAndHttps"
    priority                   = 100
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["1433", "443"]
    source_address_prefix      = var.network.app_service_integration_subnet
    destination_address_prefix = var.network.private_endpoint_subnet
  }
  security_rule {
    name                       = "DenyOtherPrivateDataPorts"
    priority                   = 110
    direction                  = "Outbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = var.network.app_service_integration_subnet
    destination_address_prefix = var.network.private_endpoint_subnet
  }
}

resource "azurerm_subnet_network_security_group_association" "app_service_integration" {
  count                     = local.hybrid_data_stage ? 1 : 0
  subnet_id                 = azurerm_subnet.app_service_integration[0].id
  network_security_group_id = azurerm_network_security_group.app_service_integration[0].id
}

resource "azurerm_private_dns_zone" "data" {
  for_each            = local.private_data_services
  name                = each.value.zone
  resource_group_name = local.rg
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "data" {
  for_each             = local.private_data_services
  name                 = "${local.prefix}-${each.key}"
  private_dns_zone_id  = azurerm_private_dns_zone.data[each.key].id
  virtual_network_id   = azurerm_virtual_network.main[0].id
  registration_enabled = false
  tags                 = local.tags
}

resource "azurerm_private_endpoint" "data" {
  for_each            = local.private_data_services
  name                = "${local.prefix}-${each.key}-pe"
  location            = var.location
  resource_group_name = local.rg
  subnet_id           = azurerm_subnet.private_endpoints[0].id
  tags                = local.tags
  private_service_connection {
    name                           = "${local.prefix}-${each.key}"
    private_connection_resource_id = each.value.resource_id
    subresource_names              = [each.value.group]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = "data"
    private_dns_zone_ids = [azurerm_private_dns_zone.data[each.key].id]
  }
  depends_on = [azurerm_private_dns_zone_virtual_network_link.data]
}
