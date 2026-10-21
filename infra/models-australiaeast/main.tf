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

variable "account_name" {
  type = string
}

variable "gateway_principal_id" {
  type = string
}

locals {
  specification = jsondecode(file("${path.module}/../models/model-spec.json"))
  luna          = one([for model in local.specification.models : model if model.id == "gpt-5.6-luna"])
  account_id    = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}/providers/Microsoft.CognitiveServices/accounts/${var.account_name}"
}

data "azapi_resource" "account" {
  type                   = "Microsoft.CognitiveServices/accounts@2025-06-01"
  resource_id            = local.account_id
  response_export_values = ["location", "kind", "properties.disableLocalAuth"]
}

resource "azapi_resource" "luna" {
  type      = "Microsoft.CognitiveServices/accounts/deployments@2025-06-01"
  name      = local.luna.id
  parent_id = local.account_id
  body = {
    sku = { name = "GlobalStandard", capacity = local.luna.capacity }
    properties = {
      model                = { format = local.luna.arm_format, name = local.luna.id, version = local.luna.version }
      raiPolicyName        = "Microsoft.DefaultV2"
      versionUpgradeOption = "NoAutoUpgrade"
    }
  }
  response_export_values = ["id", "sku", "properties.model", "properties.provisioningState"]
  lifecycle {
    prevent_destroy = true
    precondition {
      condition = (
        data.azapi_resource.account.output.location == "australiaeast" &&
        data.azapi_resource.account.output.kind == "AIServices" &&
        data.azapi_resource.account.output.properties.disableLocalAuth == true &&
        local.luna.capacity == 120
      )
      error_message = "The Luna-only profile requires an Australia East AIServices account with key auth disabled and pinned capacity 120."
    }
  }
}

resource "azapi_resource" "gateway_openai_user" {
  type      = "Microsoft.Authorization/roleAssignments@2022-04-01"
  name      = uuidv5("url", "${local.account_id}/${var.gateway_principal_id}/CognitiveServicesOpenAIUser")
  parent_id = local.account_id
  body = {
    properties = {
      roleDefinitionId = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/${local.luna.gateway_role_definition_id}"
      principalId      = var.gateway_principal_id
      principalType    = "ServicePrincipal"
    }
  }
  response_export_values = ["id"]
}

output "deployments" {
  value = { "australiaeast-gpt-5.6-luna" = azapi_resource.luna.output }
}
