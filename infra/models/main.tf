terraform {
  required_version = "~> 1.16.0"
  required_providers {
    azapi = {
      source  = "Azure/azapi"
      version = "= 2.13.0"
    }
  }
  backend "local" {}
}

provider "azapi" {
  subscription_id = var.subscription_id
}

variable "subscription_id" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "eastus_account_name" {
  type = string
}

variable "sweden_account_name" {
  type = string
}

variable "gateway_principal_id" {
  type = string
}

variable "openai_capacity" {
  type    = number
  default = 1
  validation {
    condition     = var.openai_capacity >= 1 && floor(var.openai_capacity) == var.openai_capacity
    error_message = "Capacity must be a positive integer; validate live regional quota before increasing."
  }
}

locals {
  group_id  = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}"
  eastus_id = "${local.group_id}/providers/Microsoft.CognitiveServices/accounts/${var.eastus_account_name}"
  accounts = {
    eastus        = local.eastus_id
    swedencentral = azapi_resource.sweden.id
  }
  deployments = {
    for pair in setproduct(["eastus", "swedencentral"], ["gpt-5.6-luna", "gpt-5.6-sol"]) :
    "${pair[0]}-${pair[1]}" => { region = pair[0], name = pair[1] }
  }
}

data "azapi_resource" "eastus" {
  type                   = "Microsoft.CognitiveServices/accounts@2025-06-01"
  resource_id            = local.eastus_id
  response_export_values = ["id", "location", "kind", "properties.endpoint", "properties.disableLocalAuth"]
}

resource "azapi_resource" "sweden" {
  type      = "Microsoft.CognitiveServices/accounts@2025-06-01"
  name      = var.sweden_account_name
  parent_id = local.group_id
  location  = "swedencentral"
  body = {
    kind     = "AIServices"
    sku      = { name = "S0" }
    identity = { type = "SystemAssigned" }
    properties = {
      customSubDomainName = var.sweden_account_name
      disableLocalAuth    = true
      publicNetworkAccess = "Enabled"
      networkAcls         = { defaultAction = "Allow" }
    }
  }
  response_export_values = ["id", "properties.endpoint", "properties.endpoints", "properties.provisioningState"]
  lifecycle {
    prevent_destroy = true
  }
}

resource "azapi_resource" "openai" {
  for_each  = local.deployments
  type      = "Microsoft.CognitiveServices/accounts/deployments@2025-06-01"
  name      = each.value.name
  parent_id = local.accounts[each.value.region]
  body = {
    sku = { name = "GlobalStandard", capacity = var.openai_capacity }
    properties = {
      model                = { format = "OpenAI", name = each.value.name, version = "2026-07-09" }
      raiPolicyName        = "Microsoft.DefaultV2"
      versionUpgradeOption = "NoAutoUpgrade"
    }
  }
  response_export_values = ["id", "sku", "properties.model", "properties.provisioningState"]
  lifecycle {
    prevent_destroy = true
    precondition {
      condition     = data.azapi_resource.eastus.output.properties.disableLocalAuth == true
      error_message = "Existing Foundry must retain disabled local/key authentication."
    }
  }
}

resource "azapi_resource" "gateway_openai_user" {
  for_each  = local.accounts
  type      = "Microsoft.Authorization/roleAssignments@2022-04-01"
  name      = uuidv5("url", "${each.value}/${var.gateway_principal_id}/CognitiveServicesOpenAIUser")
  parent_id = each.value
  body = {
    properties = {
      roleDefinitionId = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"
      principalId      = var.gateway_principal_id
      principalType    = "ServicePrincipal"
    }
  }
  response_export_values = ["id"]
}

resource "azapi_resource" "gateway_anthropic_user_sweden" {
  type      = "Microsoft.Authorization/roleAssignments@2022-04-01"
  name      = uuidv5("url", "${azapi_resource.sweden.id}/${var.gateway_principal_id}/CognitiveServicesUser")
  parent_id = azapi_resource.sweden.id
  body = {
    properties = {
      roleDefinitionId = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/a97b65f3-24c7-4388-baec-2e87135dc908"
      principalId      = var.gateway_principal_id
      principalType    = "ServicePrincipal"
    }
  }
  response_export_values = ["id"]
}

output "deployments" {
  value = { for key, deployment in azapi_resource.openai : key => deployment.output }
}
