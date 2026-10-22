terraform {
  required_version = "~> 1.16.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "= 5.9.0"
    }
  }
  backend "local" {}
}

provider "azurerm" {
  features {}
  subscription_id                 = var.subscription_id
  resource_provider_registrations = "none"
}

variable "subscription_id" {
  type = string
}
variable "resource_group_name" {
  type = string
}
variable "name_prefix" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,18}$", var.name_prefix))
    error_message = "Use the deployment's validated prefix."
  }
}
variable "network_profile" {
  type = string
  validation {
    condition     = contains(["10.240", "10.241"], var.network_profile)
    error_message = "Use an existing deployment network profile."
  }
}
variable "registry_id" {
  type = string
}
variable "ssh_public_key" {
  type = string
}
variable "image_version" {
  type = string
}

locals {
  name = "${var.name_prefix}-sql-init"
  tags = { environment = "dev", workload = "aiflux", purpose = "temporary-sql-initialization" }
}

data "azurerm_virtual_network" "existing" {
  name                = "${var.name_prefix}-vnet"
  resource_group_name = var.resource_group_name
}

resource "azurerm_subnet" "runner" {
  name                            = local.name
  resource_group_name             = var.resource_group_name
  virtual_network_name            = data.azurerm_virtual_network.existing.name
  address_prefixes                = ["${var.network_profile}.5.0/24"]
  default_outbound_access_enabled = false
}

resource "azurerm_network_security_group" "runner" {
  name                = local.name
  location            = data.azurerm_virtual_network.existing.location
  resource_group_name = var.resource_group_name
  tags                = local.tags
  security_rule {
    name                       = "DenyInbound"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
  security_rule {
    name                       = "PrivateSql"
    priority                   = 100
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "1433"
    source_address_prefix      = "*"
    destination_address_prefix = "${var.network_profile}.3.0/24"
  }
  security_rule {
    name                         = "PlatformAgentAndIdentity"
    priority                     = 110
    direction                    = "Outbound"
    access                       = "Allow"
    protocol                     = "Tcp"
    source_port_range            = "*"
    destination_port_ranges      = ["80", "32526"]
    source_address_prefix        = "*"
    destination_address_prefixes = ["168.63.129.16", "169.254.169.254"]
  }
  security_rule {
    name                       = "PlatformDns"
    priority                   = 120
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "53"
    source_address_prefix      = "*"
    destination_address_prefix = "168.63.129.16"
  }
  security_rule {
    name                       = "PackageAndIdentityHttps"
    priority                   = 130
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["80", "443"]
    source_address_prefix      = "*"
    destination_address_prefix = "Internet"
  }
  security_rule {
    name                       = "DenyOtherOutbound"
    priority                   = 4000
    direction                  = "Outbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "runner" {
  subnet_id                 = azurerm_subnet.runner.id
  network_security_group_id = azurerm_network_security_group.runner.id
}
resource "azurerm_public_ip" "outbound" {
  name                = "${local.name}-outbound"
  location            = data.azurerm_virtual_network.existing.location
  resource_group_name = var.resource_group_name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.tags
  lifecycle {
    # Azure stamps immutable FirstPartyUsage ip_tags; preserve them as in edge.tf.
    ignore_changes = [ip_tags]
  }
}
resource "azurerm_nat_gateway" "runner" {
  name                = local.name
  location            = data.azurerm_virtual_network.existing.location
  resource_group_name = var.resource_group_name
  sku_name            = "Standard"
  tags                = local.tags
}
resource "azurerm_nat_gateway_public_ip_association" "runner" {
  nat_gateway_id       = azurerm_nat_gateway.runner.id
  public_ip_address_id = azurerm_public_ip.outbound.id
}
resource "azurerm_subnet_nat_gateway_association" "runner" {
  subnet_id      = azurerm_subnet.runner.id
  nat_gateway_id = azurerm_nat_gateway.runner.id
}
resource "azurerm_user_assigned_identity" "runner" {
  name                = "${local.name}-identity"
  location            = data.azurerm_virtual_network.existing.location
  resource_group_name = var.resource_group_name
  tags                = local.tags
}
resource "azurerm_role_assignment" "pull" {
  scope                            = var.registry_id
  role_definition_name             = "AcrPull"
  principal_id                     = azurerm_user_assigned_identity.runner.principal_id
  skip_service_principal_aad_check = true
}
resource "azurerm_network_interface" "runner" {
  name                = local.name
  location            = data.azurerm_virtual_network.existing.location
  resource_group_name = var.resource_group_name
  tags                = local.tags
  ip_configuration {
    name                          = "private"
    subnet_id                     = azurerm_subnet.runner.id
    private_ip_address_allocation = "Dynamic"
  }
}
resource "azurerm_linux_virtual_machine" "runner" {
  name                            = local.name
  location                        = data.azurerm_virtual_network.existing.location
  resource_group_name             = var.resource_group_name
  size                            = "Standard_D2s_v5"
  admin_username                  = "migration"
  disable_password_authentication = true
  network_interface_ids           = [azurerm_network_interface.runner.id]
  secure_boot_enabled             = true
  vtpm_enabled                    = true
  tags                            = local.tags
  admin_ssh_key {
    username   = "migration"
    public_key = var.ssh_public_key
  }
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.runner.id]
  }
  os_disk {
    name                 = "${local.name}-os"
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
    disk_size_gb         = 32
  }
  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = var.image_version
  }
  boot_diagnostics {}
  depends_on = [
    azurerm_subnet_network_security_group_association.runner,
    azurerm_subnet_nat_gateway_association.runner,
    azurerm_nat_gateway_public_ip_association.runner,
    azurerm_role_assignment.pull
  ]
  lifecycle {
    precondition {
      condition     = data.azurerm_virtual_network.existing.location == "australiaeast"
      error_message = "This private runner is bounded to Australia East."
    }
  }
}

output "runner" {
  value = {
    vm_id        = azurerm_linux_virtual_machine.runner.id
    client_id    = azurerm_user_assigned_identity.runner.client_id
    principal_id = azurerm_user_assigned_identity.runner.principal_id
    identity_id  = azurerm_user_assigned_identity.runner.id
  }
}
