resource "azurerm_api_management" "main" {
  name                          = local.apim_name
  location                      = var.location
  resource_group_name           = local.rg
  publisher_name                = var.publisher_name
  publisher_email               = var.publisher_email
  sku_name                      = "BasicV2_${var.apim_capacity}"
  virtual_network_type          = "None"
  public_network_access_enabled = true
  tags                          = local.tags
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.identity["gateway"].id]
  }
  depends_on = [terraform_data.approval]
}

resource "azurerm_api_management_product" "main" {
  product_id            = "aiflux"
  api_management_name   = azurerm_api_management.main.name
  resource_group_name   = local.rg
  display_name          = "AIFLUX (native validation pending)"
  subscription_required = true
  approval_required     = true
  subscriptions_limit   = 1000
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

locals {
  model_backends_path = var.model_backends_file != null ? var.model_backends_file : "${path.module}/../models/model-backends.json"
  model_descriptor = jsondecode(
    fileexists(local.model_backends_path) ?
    file(local.model_backends_path) :
    jsonencode({ subscription_id = var.subscription_id, backends = [] })
  )
  deployment_specs = jsondecode(file("${path.module}/../models/model-spec.json"))
  deployment_spec_by_alias = {
    for model in local.deployment_specs.models : model.id => model
  }
  deployment_target_regions = {
    for model in local.deployment_specs.models :
    model.id => lookup(model, "regions", local.deployment_specs.regions)
  }
  dev_aliases = toset(["gpt-5.6-luna", "gpt-5.6-sol"])
  dev_new_aliases = toset([
    for alias, model in local.deployment_spec_by_alias : alias
    if model.terraform_managed && !contains(local.dev_aliases, alias)
  ])
  dev_candidate_aliases = toset(var.dev_unified_candidate_model_aliases)
  dev_accepted_aliases  = toset(var.dev_unified_accepted_model_aliases)
  dev_selected_new_aliases = var.dev_unified_inference_enabled ? setunion(
    local.dev_candidate_aliases,
    local.dev_accepted_aliases
  ) : toset([])
  dev_unified_routed_aliases = setunion(local.dev_aliases, local.dev_selected_new_aliases)
  dev_openai_routed_aliases = setunion(
    local.dev_aliases,
    toset([for alias in local.dev_selected_new_aliases : alias
    if local.deployment_spec_by_alias[alias].arm_format != "Anthropic"])
  )
  dev_model_backends = {
    for backend in local.model_descriptor.backends :
    "${backend.alias}-${backend.region}" => backend
    if backend.ready == true &&
    try(backend.operator_smoke.http_status, 0) == 200 &&
    try(backend.operator_smoke.choices_schema_present, false) == true &&
    contains(local.dev_openai_routed_aliases, backend.alias)
  }
  dev_model_pools = {
    for alias in local.dev_openai_routed_aliases : alias => {
      backends = {
        for key, backend in local.dev_model_backends : key => backend
        if backend.alias == alias
      }
    }
  }
  dev_model_pooled_aliases = toset([
    for alias, pool in local.dev_model_pools : alias
    if length(pool.backends) > 1
  ])
  dev_anthropic_backends = {
    for backend in try(local.model_descriptor.anthropic_backends, []) :
    "${try(backend.alias, backend.model)}-${backend.region}" => merge(backend, {
      alias = try(backend.alias, backend.model)
    })
    if try(backend.alias, backend.model) != "claude-haiku-5-5" &&
    contains(local.dev_selected_new_aliases, try(backend.alias, backend.model)) &&
    backend.ready == true &&
    try(backend.operator_smoke.http_status, 0) == 200 &&
    try(backend.operator_smoke.content_schema_present, false) == true
  }
  dev_anthropic_pools = {
    for alias in [
      for selected in local.dev_selected_new_aliases : selected
      if local.deployment_spec_by_alias[selected].arm_format == "Anthropic"
      ] : alias => {
      backends = {
        for key, backend in local.dev_anthropic_backends : key => backend
        if backend.alias == alias
      }
    }
  }
  dev_anthropic_pooled_aliases = toset([
    for alias, pool in local.dev_anthropic_pools : alias
    if length(pool.backends) > 1
  ])
  dev_completion_limits = merge(
    { for alias in local.dev_unified_routed_aliases :
    alias => local.deployment_spec_by_alias[alias].max_completion_tokens },
    { "claude-haiku-5-5" = local.deployment_spec_by_alias["claude-haiku-5-5"].max_completion_tokens }
  )
  dev_policy_aliases = var.dev_unified_inference_enabled ? setunion(
    local.dev_unified_routed_aliases,
    toset(["claude-haiku-5-5"])
  ) : local.dev_aliases
  dev_policy_openai_aliases = var.dev_unified_inference_enabled ? local.dev_openai_routed_aliases : local.dev_aliases
  dev_policy_anthropic_aliases = var.dev_unified_inference_enabled ? toset(concat(["claude-haiku-5-5"], [
    for alias in local.dev_selected_new_aliases : alias
    if local.deployment_spec_by_alias[alias].arm_format == "Anthropic"
  ])) : toset([])
  dev_policy_foundry_aliases = var.dev_unified_inference_enabled ? toset([
    for alias in local.dev_selected_new_aliases : alias
    if local.deployment_spec_by_alias[alias].wire_api == "foundry-model-inference"
  ]) : toset([])
  dev_policy_completion_limits = var.dev_unified_inference_enabled ? local.dev_completion_limits : {
    for alias in local.dev_aliases : alias => var.dev_openai_max_completion_tokens
  }
  dev_policy_openai_pool_ids = {
    for alias in local.dev_policy_openai_aliases :
    alias => contains(local.dev_model_pooled_aliases, alias)
    ? "dev-${lower(replace(alias, ".", "-"))}-pool"
    : "dev-${lower(replace("${alias}-${lookup(local.deployment_spec_by_alias[alias], "regions", local.deployment_specs.regions)[0]}", ".", "-"))}"
  }
  dev_policy_anthropic_backend_ids = {
    for alias in local.dev_policy_anthropic_aliases :
    alias => alias == "claude-haiku-5-5"
    ? "dev-claude-haiku-5-5-eastus"
    : contains(local.dev_anthropic_pooled_aliases, alias)
    ? "dev-${lower(replace(alias, ".", "-"))}-pool"
    : "dev-${lower(replace("${alias}-${local.deployment_target_regions[alias][0]}", ".", "-"))}"
  }
  dev_policy_model_alias_conditions = join(
    " || ",
    [for alias in sort(tolist(local.dev_policy_aliases)) : "(string)model == \"${alias}\""]
  )
  dev_policy_anthropic_conditions = length(local.dev_policy_anthropic_aliases) == 0 ? "false" : join(
    " || ",
    [for alias in sort(tolist(local.dev_policy_anthropic_aliases)) : "(string)model == \"${alias}\""]
  )
  dev_policy_anthropic_context_conditions = length(local.dev_policy_anthropic_aliases) == 0 ? "false" : join(
    " || ",
    [for alias in sort(tolist(local.dev_policy_anthropic_aliases)) : "(string)context.Variables[\"aiflux-model\"] == \"${alias}\""]
  )
  dev_policy_foundry_api_versions = {
    for alias in local.dev_policy_foundry_aliases :
    alias => local.deployment_spec_by_alias[alias].api_version
  }
  dev_policy_model_limit_rules = join("\n", [
    for alias in sort(keys(local.dev_policy_completion_limits)) :
    "if ((string)model == \"${alias}\") { modelMaximum = ${local.dev_policy_completion_limits[alias]}; }"
  ])
}

resource "terraform_data" "dev_openai_gate" {
  count = var.dev_openai_inference_enabled ? 1 : 0

  input = {
    aliases       = sort(tolist(local.dev_aliases))
    backend_count = length(local.dev_model_backends)
  }

  lifecycle {
    precondition {
      condition = (
        local.model_descriptor.subscription_id == var.subscription_id &&
        length([
          for backend in values(local.dev_model_backends) : backend
          if contains(local.dev_aliases, backend.alias)
        ]) == 4 &&
        alltrue([
          for backend in values(local.dev_model_backends) :
          backend.provider == "OpenAI" &&
          backend.account_resource_id == "/subscriptions/${var.subscription_id}/resourceGroups/${local.rg}/providers/Microsoft.CognitiveServices/accounts/${backend.account_name}" &&
          backend.deployment_resource_id == "${backend.account_resource_id}/deployments/${backend.deployment_name}" &&
          backend.endpoint == "https://${backend.account_name}.openai.azure.com" &&
          backend.deployment_name == backend.alias &&
          backend.model_name == backend.alias &&
          backend.wire_api == "azure-openai-v1" &&
          backend.operation == "/openai/v1/chat/completions" &&
          backend.model_version == local.deployment_spec_by_alias[backend.alias].version &&
          backend.sku == "GlobalStandard" &&
          backend.capacity == 120 &&
          backend.provisioning_state == "Succeeded" &&
          backend.ready == true &&
          backend.auth.type == "Entra bearer token" &&
          backend.auth.audience == "https://cognitiveservices.azure.com/" &&
          backend.auth.gateway_role == "Cognitive Services OpenAI User" &&
          backend.auth.gateway_role_definition_id == local.deployment_spec_by_alias[backend.alias].gateway_role_definition_id &&
          backend.auth.gateway_role_assigned == true &&
          backend.operator_smoke.passed == true &&
          backend.operator_smoke.http_status == 200 &&
          backend.operator_smoke.choices_schema_present == true
          if contains(local.dev_aliases, backend.alias)
        ]) &&
        alltrue([
          for alias in local.dev_aliases :
          length(local.dev_model_pools[alias].backends) == 2 &&
          toset([for backend in values(local.dev_model_pools[alias].backends) : backend.region]) ==
          toset(["eastus", "swedencentral"])
        ]) &&
        length(local.dev_selected_new_aliases) <= length(local.dev_new_aliases) &&
        length(setsubtract(local.dev_selected_new_aliases, local.dev_new_aliases)) == 0 &&
        length(setsubtract(local.dev_candidate_aliases, local.dev_new_aliases)) == 0 &&
        length(setsubtract(local.dev_accepted_aliases, local.dev_new_aliases)) == 0 &&
        alltrue([
          for alias in local.dev_selected_new_aliases :
          local.deployment_spec_by_alias[alias].arm_format == "Anthropic"
          ? (
            length([
              for backend in values(local.dev_anthropic_backends) : backend
              if backend.alias == alias
            ]) == length(local.deployment_target_regions[alias]) &&
            toset([
              for backend in values(local.dev_anthropic_backends) : backend.region
              if backend.alias == alias
            ]) == toset(local.deployment_target_regions[alias]) &&
            alltrue([
              for backend in values(local.dev_anthropic_backends) : backend.alias != alias || (
                backend.provider == "Anthropic" &&
                backend.version == local.deployment_spec_by_alias[alias].version &&
                backend.wire_api == local.deployment_spec_by_alias[alias].wire_api &&
                backend.operation == local.deployment_spec_by_alias[alias].operation &&
                backend.request_contract.token_parameter == local.deployment_spec_by_alias[alias].request_token_parameter &&
                backend.request_contract.max_completion_tokens == local.deployment_spec_by_alias[alias].max_completion_tokens &&
                backend.endpoint == "https://${backend.account_name}.services.ai.azure.com" &&
                backend.endpoint_verified == true &&
                backend.capacity == local.deployment_spec_by_alias[alias].capacity &&
                backend.required_tpm >= local.deployment_spec_by_alias[alias].capacity * 1000 &&
                backend.ready == true &&
                backend.auth.audience == "https://cognitiveservices.azure.com/" &&
                backend.auth.gateway_role == "Cognitive Services User" &&
                backend.auth.gateway_role_definition_id == local.deployment_spec_by_alias[alias].gateway_role_definition_id &&
                backend.auth.gateway_role_assigned == true &&
                backend.operator_smoke.passed == true &&
                backend.operator_smoke.http_status == 200 &&
                backend.operator_smoke.content_schema_present == true
              )
            ])
          )
          : (
            length([
              for backend in values(local.dev_model_backends) : backend
              if backend.alias == alias
            ]) == length(local.deployment_target_regions[alias]) &&
            toset([
              for backend in values(local.dev_model_backends) : backend.region
              if backend.alias == alias
            ]) == toset(local.deployment_target_regions[alias]) &&
            alltrue([
              for backend in values(local.dev_model_backends) : backend.alias != alias || (
                backend.provider == local.deployment_spec_by_alias[alias].arm_format &&
                backend.model_version == local.deployment_spec_by_alias[alias].version &&
                backend.wire_api == local.deployment_spec_by_alias[alias].wire_api &&
                backend.operation == local.deployment_spec_by_alias[alias].operation &&
                backend.api_version == local.deployment_spec_by_alias[alias].api_version &&
                backend.request_contract.token_parameter == local.deployment_spec_by_alias[alias].request_token_parameter &&
                backend.request_contract.max_completion_tokens == local.deployment_spec_by_alias[alias].max_completion_tokens &&
                backend.endpoint_verified == true &&
                (
                  local.deployment_spec_by_alias[alias].endpoint_source == "model_inference_endpoint"
                  ? backend.endpoint == "https://${backend.account_name}.services.ai.azure.com/models"
                  : backend.endpoint == "https://${backend.account_name}.openai.azure.com"
                ) &&
                backend.capacity == local.deployment_spec_by_alias[alias].capacity &&
                backend.required_tpm >= 100000 &&
                backend.ready == true &&
                backend.auth.audience == "https://cognitiveservices.azure.com/" &&
                backend.auth.gateway_role == local.deployment_spec_by_alias[alias].gateway_role &&
                backend.auth.gateway_role_definition_id == local.deployment_spec_by_alias[alias].gateway_role_definition_id &&
                backend.auth.gateway_role_assigned == true &&
                backend.operator_smoke.passed == true &&
                backend.operator_smoke.http_status == 200 &&
                backend.operator_smoke.choices_schema_present == true
              )
            ])
          )
        ]) &&
        var.dev_openai_content_safety_threshold != null
      )
      error_message = "The guarded APIs require direct-smoked deployments in both approved regions, exact ARM model/version/capacity, the expected endpoint/auth role, and explicit safety configuration. Newly requested aliases route only when listed in the explicit candidate or accepted inputs; candidates stay hidden from /models."
    }
  }
}

resource "azurerm_api_management_api" "dev_openai" {
  name                  = "aiflux-dev-openai"
  resource_group_name   = local.rg
  api_management_name   = azurerm_api_management.main.name
  revision              = "1"
  display_name          = "AIFLUX guarded development OpenAI API"
  description           = "Subscriber-required text-only development API. Production catalog and product remain disabled."
  path                  = "dev/v1"
  service_url           = "https://aiflux-disabled.invalid"
  protocols             = ["https"]
  subscription_required = true
  subscription_key_parameter_names {
    header = "Ocp-Apim-Subscription-Key"
    query  = "subscription-key"
  }
  import {
    content_format = "openapi+json"
    content_value  = file("${path.module}/../../gateway/openapi-dev.json")
  }
}

resource "azapi_resource" "dev_openai_policy" {
  type      = "Microsoft.ApiManagement/service/apis/policies@2022-08-01"
  parent_id = replace(azurerm_api_management_api.dev_openai.id, ";rev=1", "")
  name      = "policy"
  body = {
    properties = {
      format = "rawxml"
      value = var.dev_openai_inference_enabled ? templatefile("${path.module}/../../gateway/policies/dev-openai.xml.tftpl", {
        language_endpoint            = trimsuffix(azapi_resource.ai["language"].output.properties.endpoint, "/")
        gateway_identity_client      = azurerm_user_assigned_identity.identity["gateway"].client_id
        tpm_limit                    = var.dev_openai_tpm_limit
        rpm_limit                    = var.dev_openai_rpm_limit
        completion_token_limit       = var.dev_openai_max_completion_tokens
        safety_threshold             = var.dev_admin_settings_enabled ? "@((int)context.Variables[&quot;aiflux-safety-threshold&quot;])" : tostring(var.dev_openai_content_safety_threshold)
        admin_settings_enabled       = var.dev_admin_settings_enabled
        settings_fragment_id         = var.dev_admin_settings_enabled ? azapi_resource.gateway_settings["dev-openai"].name : ""
        safety_backend_id            = azapi_resource.dev_content_safety_backend[0].name
        unified                      = false
        product_id                   = azurerm_api_management_product.dev_openai[0].product_id
        cors_origins                 = []
        model_list                   = jsonencode({ object = "list", data = [for alias in sort(tolist(local.dev_aliases)) : { id = alias, object = "model", owned_by = "aiflux" }] })
        model_alias_conditions       = local.dev_policy_model_alias_conditions
        anthropic_alias_conditions   = local.dev_policy_anthropic_conditions
        model_limit_rules            = local.dev_policy_model_limit_rules
        openai_aliases               = sort(tolist(local.dev_policy_openai_aliases))
        openai_pool_ids              = local.dev_policy_openai_pool_ids
        foundry_aliases              = sort(tolist(local.dev_policy_foundry_aliases))
        foundry_api_versions         = local.dev_policy_foundry_api_versions
        anthropic_aliases            = sort(tolist(local.dev_policy_anthropic_aliases))
        anthropic_context_conditions = local.dev_policy_anthropic_context_conditions
        anthropic_backend_ids        = local.dev_policy_anthropic_backend_ids
      }) : file("${path.module}/../../gateway/policies/disabled.xml")
    }
  }
  depends_on = [
    terraform_data.dev_openai_gate,
    azapi_resource.dev_model_pool,
    azapi_resource.dev_content_safety_backend,
    azurerm_role_assignment.ai_user
  ]
}

resource "azapi_resource" "closed_policy" {
  type      = "Microsoft.ApiManagement/service/policies@2022-08-01"
  parent_id = azurerm_api_management.main.id
  name      = "policy"
  body = {
    properties = {
      format = "rawxml"
      value = templatefile("${path.module}/../../gateway/policies/global-dev-gate.xml.tftpl", {
        dev_api_id      = azurerm_api_management_api.dev_openai.name
        enabled         = var.dev_openai_inference_enabled
        unified_enabled = var.dev_unified_inference_enabled
      })
    }
  }
  depends_on = [azapi_resource.dev_openai_policy, azapi_resource.dev_unified_policy]
}

resource "azapi_resource" "blocked_api_policy" {
  type      = "Microsoft.ApiManagement/service/apis/policies@2022-08-01"
  parent_id = replace(azurerm_api_management_api.blocked.id, ";rev=1", "")
  name      = "policy"
  body = {
    properties = {
      format = "rawxml"
      value  = file("${path.module}/../../gateway/policies/disabled.xml")
    }
  }
}

resource "azurerm_api_management_product" "dev_openai" {
  count                 = var.dev_openai_inference_enabled ? 1 : 0
  product_id            = "aiflux-dev-openai"
  api_management_name   = azurerm_api_management.main.name
  resource_group_name   = local.rg
  display_name          = "AIFLUX single-subscriber development text API"
  description           = "Approved subscriptions only; text-only OpenAI chat; strict request, token, and content-safety gates."
  subscription_required = true
  approval_required     = true
  subscriptions_limit   = 1
  published             = true
  depends_on            = [terraform_data.dev_openai_gate]
}

resource "azurerm_api_management_product_api" "dev_openai" {
  count               = var.dev_openai_inference_enabled ? 1 : 0
  api_name            = azurerm_api_management_api.dev_openai.name
  product_id          = azurerm_api_management_product.dev_openai[0].product_id
  api_management_name = azurerm_api_management.main.name
  resource_group_name = local.rg
}

resource "azapi_resource" "dev_model_backend" {
  for_each  = var.dev_openai_inference_enabled ? local.dev_model_backends : {}
  type      = "Microsoft.ApiManagement/service/backends@2024-05-01"
  parent_id = azurerm_api_management.main.id
  name      = "dev-${lower(replace(each.key, ".", "-"))}"
  body = {
    properties = {
      protocol    = "http"
      url         = each.value.wire_api == "foundry-model-inference" ? trimsuffix(each.value.endpoint, "/") : "${trimsuffix(each.value.endpoint, "/")}/openai/v1"
      description = "Verified ${each.value.alias} ${each.value.region} ${each.value.wire_api} endpoint."
      tls = {
        validateCertificateChain = true
        validateCertificateName  = true
      }
      circuitBreaker = {
        rules = [{
          name = "server-errors"
          failureCondition = {
            count    = 3
            interval = "PT1M"
            statusCodeRanges = [{
              min = 500
              max = 599
            }]
          }
          tripDuration     = "PT1M"
          acceptRetryAfter = true
        }]
      }
    }
  }
  depends_on = [terraform_data.dev_openai_gate]
}

resource "azapi_resource" "dev_model_pool" {
  for_each = var.dev_openai_inference_enabled ? {
    for alias, pool in local.dev_model_pools : alias => pool if length(pool.backends) > 1
  } : {}
  type      = "Microsoft.ApiManagement/service/backends@2024-05-01"
  parent_id = azurerm_api_management.main.id
  name      = "dev-${lower(replace(each.key, ".", "-"))}-pool"
  body = {
    properties = {
      type = "Pool"
      pool = {
        services = [
          for backend_key in sort(keys(each.value.backends)) : {
            id       = azapi_resource.dev_model_backend[backend_key].id
            priority = 1
            weight   = 1
          }
        ]
      }
    }
  }
  depends_on = [azapi_resource.dev_model_backend]
}

resource "azapi_resource" "dev_anthropic_model_backend" {
  for_each  = var.dev_openai_inference_enabled ? local.dev_anthropic_backends : {}
  type      = "Microsoft.ApiManagement/service/backends@2024-05-01"
  parent_id = azurerm_api_management.main.id
  name      = "dev-${lower(replace(each.key, ".", "-"))}"
  body = {
    properties = {
      protocol    = "http"
      url         = "${trimsuffix(each.value.endpoint, "/")}/anthropic/v1"
      description = "Verified ${each.value.alias} ${each.value.region} Foundry Anthropic Messages endpoint."
      tls = {
        validateCertificateChain = true
        validateCertificateName  = true
      }
    }
  }
  depends_on = [terraform_data.dev_openai_gate]
}

resource "azapi_resource" "dev_anthropic_model_pool" {
  for_each = var.dev_openai_inference_enabled ? {
    for alias, pool in local.dev_anthropic_pools : alias => pool if length(pool.backends) > 1
  } : {}
  type      = "Microsoft.ApiManagement/service/backends@2024-05-01"
  parent_id = azurerm_api_management.main.id
  name      = "dev-${lower(replace(each.key, ".", "-"))}-pool"
  body = {
    properties = {
      type = "Pool"
      pool = {
        services = [
          for backend_key in sort(keys(each.value.backends)) : {
            id       = azapi_resource.dev_anthropic_model_backend[backend_key].id
            priority = 1
            weight   = 1
          }
        ]
      }
    }
  }
  depends_on = [azapi_resource.dev_anthropic_model_backend]
}

resource "azapi_resource" "dev_content_safety_backend" {
  count                     = var.dev_openai_inference_enabled ? 1 : 0
  type                      = "Microsoft.ApiManagement/service/backends@2024-06-01-preview"
  parent_id                 = azurerm_api_management.main.id
  name                      = "aiflux-dev-content-safety"
  schema_validation_enabled = false
  body = {
    properties = {
      protocol    = "http"
      url         = trimsuffix(azapi_resource.ai["safety"].output.properties.endpoint, "/")
      description = "Azure AI Content Safety backend for original, redacted, and completion policy checks."
      tls = {
        validateCertificateChain = true
        validateCertificateName  = true
      }
      credentials = {
        managedIdentity = {
          resource = "https://cognitiveservices.azure.com"
          clientId = azurerm_user_assigned_identity.identity["gateway"].client_id
        }
      }
    }
  }
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
      loggerId           = azapi_resource.monitor_logger.id
      alwaysLog          = "allErrors"
      sampling           = { samplingType = "fixed", percentage = 100 }
      logClientIp        = false
      verbosity          = "information"
      largeLanguageModel = { logs = "enabled" }
      frontend = {
        request = {
          headers = []
          body    = { bytes = 0 }
          dataMasking = {
            queryParams = [
              { mode = "Hide", value = "*" },
            ]
          }
        }
        response = { headers = ["x-aiflux-model", "x-aiflux-provider", "x-aiflux-region"], body = { bytes = 0 } }
      }
      backend = {
        request = {
          headers = []
          body    = { bytes = 0 }
          dataMasking = {
            queryParams = [{ mode = "Hide", value = "*" }]
          }
        }
        response = { headers = [], body = { bytes = 0 } }
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
