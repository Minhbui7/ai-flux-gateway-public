resource "azurerm_virtual_network" "main" {
  name                = "${local.prefix}-vnet"
  location            = var.location
  resource_group_name = local.rg
  address_space       = [var.network.address_space]
  tags                = local.tags
  depends_on          = [terraform_data.approval]
}

locals {
  subnets = {
    appgw    = var.network.app_gateway_subnet
    link     = var.network.private_link_subnet
    apim     = var.network.apim_subnet
    apps     = var.network.apps_subnet
    endpoint = var.network.endpoints_subnet
  }
  delegations = {
    apim = "Microsoft.Web/hostingEnvironments"
    apps = "Microsoft.Web/serverFarms"
  }
}

resource "azurerm_subnet" "main" {
  for_each                                      = local.subnets
  name                                          = "${local.prefix}-${each.key}"
  resource_group_name                           = local.rg
  virtual_network_name                          = azurerm_virtual_network.main.name
  address_prefixes                              = [each.value]
  private_endpoint_network_policies             = "Disabled"
  private_link_service_network_policies_enabled = each.key != "link"
  dynamic "delegation" {
    for_each = contains(keys(local.delegations), each.key) ? [local.delegations[each.key]] : []
    content {
      name = "azure-service"
      service_delegation {
        name    = delegation.value
        actions = ["Microsoft.Network/virtualNetworks/subnets/action"]
      }
    }
  }
}

resource "azurerm_network_security_group" "apim" {
  name                = "${local.prefix}-apim-nsg"
  location            = var.location
  resource_group_name = local.rg
  tags                = local.tags
  security_rule {
    name                       = "PlatformHealth"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "AzureLoadBalancer"
    destination_address_prefix = "*"
  }
  security_rule {
    name                       = "AppGatewayHttps"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = var.network.app_gateway_subnet
    destination_address_prefix = "*"
  }
  security_rule {
    name                       = "DenyOtherGatewayClients"
    priority                   = 200
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
  security_rule {
    name                       = "KeyVaultDependency"
    priority                   = 100
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "VirtualNetwork"
    destination_address_prefix = "AzureKeyVault"
  }
}

resource "azurerm_subnet_network_security_group_association" "apim" {
  subnet_id                 = azurerm_subnet.main["apim"].id
  network_security_group_id = azurerm_network_security_group.apim.id
}

resource "azurerm_network_security_group" "appgw" {
  name                = "${local.prefix}-appgw-nsg"
  location            = var.location
  resource_group_name = local.rg
  tags                = local.tags
  security_rule {
    name                       = "PlatformHealth"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "AzureLoadBalancer"
    destination_address_prefix = "*"
  }
  security_rule {
    name                       = "PrivateLinkHttps"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = var.network.private_link_subnet
    destination_address_prefix = "*"
  }
  security_rule {
    name                       = "PlatformManagement"
    priority                   = 120
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "65200-65535"
    source_address_prefix      = "GatewayManager"
    destination_address_prefix = "*"
  }
  security_rule {
    name                       = "DenyDirectListeners"
    priority                   = 200
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "appgw" {
  subnet_id                 = azurerm_subnet.main["appgw"].id
  network_security_group_id = azurerm_network_security_group.appgw.id
}

locals {
  private_zones = toset([
    "privatelink.azurewebsites.net",
    "privatelink.database.windows.net",
    "privatelink.vaultcore.azure.net",
    "privatelink.cognitiveservices.azure.com",
    "privatelink.blob.core.windows.net",
    "privatelink.queue.core.windows.net",
    "privatelink.table.core.windows.net",
  ])
}

resource "azurerm_private_dns_zone" "main" {
  for_each            = local.private_zones
  name                = each.key
  resource_group_name = local.rg
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "main" {
  for_each             = local.private_zones
  name                 = "${local.prefix}-link"
  private_dns_zone_id  = azurerm_private_dns_zone.main[each.key].id
  virtual_network_id   = azurerm_virtual_network.main.id
  registration_enabled = false
}

locals {
  endpoint_targets = merge({
    vault     = { id = azurerm_key_vault.main.id, group = "vault", zone = "privatelink.vaultcore.azure.net" }
    sql       = { id = azurerm_mssql_server.main.id, group = "sqlServer", zone = "privatelink.database.windows.net" }
    language  = { id = azapi_resource.ai["language"].id, group = "account", zone = "privatelink.cognitiveservices.azure.com" }
    safety    = { id = azapi_resource.ai["safety"].id, group = "account", zone = "privatelink.cognitiveservices.azure.com" }
    ingestion = { id = azurerm_linux_function_app.ingestion.id, group = "sites", zone = "privatelink.azurewebsites.net" }
    }, { for k, app in azurerm_linux_web_app.main : k => {
      id = app.id, group = "sites", zone = "privatelink.azurewebsites.net"
      } }, { for k in ["blob", "queue", "table"] : "storage-${k}" => {
      id = azapi_resource.function_storage.id, group = k, zone = "privatelink.${k}.core.windows.net"
    } }
  )
}

resource "azurerm_private_endpoint" "main" {
  for_each            = local.endpoint_targets
  name                = "${local.prefix}-pe-${each.key}"
  location            = var.location
  resource_group_name = local.rg
  subnet_id           = azurerm_subnet.main["endpoint"].id
  tags                = local.tags
  private_service_connection {
    name                           = each.key
    private_connection_resource_id = each.value.id
    subresource_names              = [each.value.group]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = "private-dns"
    private_dns_zone_ids = [azurerm_private_dns_zone.main[each.value.zone].id]
  }
}
