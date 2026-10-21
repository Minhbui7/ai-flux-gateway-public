terraform {
  required_version = "~> 1.16.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "= 5.9.0"
    }
    azapi = {
      source  = "Azure/azapi"
      version = "= 2.13.0"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id                 = var.subscription_id
  resource_provider_registrations = "none"
}

provider "azapi" {
  subscription_id = var.subscription_id
}

variable "subscription_id" {
  type = string
}

variable "resource_group_name" {
  description = "Existing state resource group. Not created/deleted by this stack."
  type        = string
}

variable "location" {
  type = string
}

variable "storage_account_name" {
  type = string
}

variable "private_endpoint_subnet_id" {
  description = "Existing operator-network subnet, reachable by deployment runners."
  type        = string
  validation {
    condition     = can(regex("^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft.Network/virtualNetworks/[^/]+/subnets/[^/]+$", var.private_endpoint_subnet_id))
    error_message = "Supply an existing operator-network subnet ARM resource ID."
  }
}

variable "private_dns_zone_id" {
  description = "Existing privatelink.blob.core.windows.net zone linked to runner VNet."
  type        = string
  validation {
    condition     = can(regex("^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft.Network/privateDnsZones/privatelink\\.blob\\.core\\.windows\\.net$", var.private_dns_zone_id))
    error_message = "Supply the existing private blob DNS zone ARM resource ID."
  }
}

variable "runner_principal_id" {
  description = "Existing federated deployment identity; no credential created."
  type        = string
  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.runner_principal_id))
    error_message = "Supply the existing federated deployment identity principal UUID, not a client ID or VM name."
  }
}

variable "deployment_approved" {
  type    = bool
  default = false
}

data "azurerm_resource_group" "existing" {
  name = var.resource_group_name
}

resource "azapi_resource" "state" {
  type      = "Microsoft.Storage/storageAccounts@2025-01-01"
  parent_id = data.azurerm_resource_group.existing.id
  name      = var.storage_account_name
  location  = var.location
  body = {
    kind = "StorageV2"
    sku  = { name = "Standard_ZRS" }
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
  lifecycle {
    prevent_destroy = true
    precondition {
      condition     = var.deployment_approved
      error_message = "Explicit state infrastructure approval is required."
    }
  }
}

resource "azapi_resource" "blob_service" {
  type      = "Microsoft.Storage/storageAccounts/blobServices@2025-01-01"
  parent_id = azapi_resource.state.id
  name      = "default"
  body = {
    properties = {
      deleteRetentionPolicy          = { enabled = true, days = 30 }
      containerDeleteRetentionPolicy = { enabled = true, days = 30 }
      isVersioningEnabled            = true
    }
  }
}

resource "azapi_resource" "container" {
  type      = "Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01"
  parent_id = azapi_resource.blob_service.id
  name      = "tfstate"
  body      = { properties = { publicAccess = "None" } }
}

resource "azurerm_private_endpoint" "state" {
  name                = "${var.storage_account_name}-pe"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.existing.name
  subnet_id           = var.private_endpoint_subnet_id
  private_service_connection {
    name                           = "state"
    private_connection_resource_id = azapi_resource.state.id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = "state"
    private_dns_zone_ids = [var.private_dns_zone_id]
  }
}

resource "azurerm_role_assignment" "state" {
  scope                = azapi_resource.container.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = var.runner_principal_id
}

output "backend" {
  value = {
    subscription_id      = var.subscription_id
    resource_group_name  = var.resource_group_name
    storage_account_name = azapi_resource.state.name
    container_name       = azapi_resource.container.name
    key                  = "aiflux.tfstate"
    use_azuread_auth     = true
    use_oidc             = true
  }
}
