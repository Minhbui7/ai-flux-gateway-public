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

variable "model_aliases" {
  description = "Null preserves the existing development selection. Customer pilots may select a reviewed subset."
  type        = set(string)
  default     = null
  validation {
    condition     = var.model_aliases == null ? true : length(setsubtract(var.model_aliases, toset([for model in jsondecode(file("${path.module}/model-spec.json")).models : model.id if model.terraform_managed]))) == 0
    error_message = "Only Terraform-managed aliases in the pinned model specification may be selected."
  }
}

variable "openai_capacity" {
  type    = number
  default = 120
  validation {
    condition     = var.openai_capacity == 120
    error_message = "The existing GPT-5.6 deployment capacity is fixed at 120 units in each region."
  }
}

locals {
  model_spec = jsondecode(file("${path.module}/model-spec.json"))
  group_id   = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}"
  eastus_id  = "${local.group_id}/providers/Microsoft.CognitiveServices/accounts/${var.eastus_account_name}"
  accounts = {
    eastus        = local.eastus_id
    swedencentral = azapi_resource.sweden.id
  }
  deployment_models = {
    for model in local.model_spec.models : model.id => model
    if model.terraform_managed && (var.model_aliases == null ? true : contains(var.model_aliases, model.id))
  }
  openai_deployments = {
    for deployment in flatten([
      for model in values(local.deployment_models) : [
        for region in lookup(model, "regions", local.model_spec.regions) : {
          key      = "${region}-${model.id}"
          region   = region
          name     = model.id
          format   = model.arm_format
          version  = model.version
          capacity = model.capacity == 120 ? var.openai_capacity : model.capacity
        }
      ] if model.arm_format != "Anthropic"
    ]) : deployment.key => deployment
  }
  anthropic_deployments = {
    for deployment in flatten([
      for model in values(local.deployment_models) : [
        for region in lookup(model, "regions", local.model_spec.regions) : {
          key      = "${region}-${model.id}"
          region   = region
          name     = model.id
          format   = model.arm_format
          version  = model.version
          capacity = try(model.region_capacities[region], model.capacity)
        }
      ] if model.arm_format == "Anthropic"
    ]) : deployment.key => deployment
  }
  shared_quota_preflight = alltrue([
    for model in values(local.deployment_models) :
    !contains(keys(model), "shared_quota_limit_units") ||
    model.capacity * length(lookup(model, "regions", local.model_spec.regions)) <= model.shared_quota_limit_units
  ])
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
  for_each  = local.openai_deployments
  type      = "Microsoft.CognitiveServices/accounts/deployments@2025-06-01"
  name      = each.value.name
  parent_id = local.accounts[each.value.region]
  body = {
    sku = { name = "GlobalStandard", capacity = each.value.capacity }
    properties = {
      model                = { format = each.value.format, name = each.value.name, version = each.value.version }
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
    precondition {
      condition     = local.shared_quota_preflight
      error_message = "The combined East US and Sweden Central GlobalStandard capacity exceeds an explicit shared per-model quota budget."
    }
  }
}

resource "azapi_resource" "anthropic" {
  for_each  = local.anthropic_deployments
  type      = "Microsoft.CognitiveServices/accounts/deployments@2025-06-01"
  name      = each.value.name
  parent_id = local.accounts[each.value.region]
  body = {
    sku = { name = "GlobalStandard", capacity = each.value.capacity }
    properties = {
      model                = { format = each.value.format, name = each.value.name, version = each.value.version }
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
    precondition {
      condition     = local.shared_quota_preflight
      error_message = "The combined East US and Sweden Central GlobalStandard capacity exceeds an explicit shared per-model quota budget."
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
  value = merge(
    { for key, deployment in azapi_resource.openai : key => deployment.output },
    { for key, deployment in azapi_resource.anthropic : key => deployment.output }
  )
}
