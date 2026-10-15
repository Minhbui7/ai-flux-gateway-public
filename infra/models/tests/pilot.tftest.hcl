mock_provider "azapi" {
  override_during = plan
  mock_data "azapi_resource" {
    defaults = {
      output = { properties = { disableLocalAuth = true } }
    }
  }
}

variables {
  subscription_id      = "00000000-0000-0000-0000-000000000001"
  resource_group_name  = "rg-customer-pilot"
  eastus_account_name  = "customer-pilot-foundry"
  sweden_account_name  = "customer-pilot-foundry-swc"
  gateway_principal_id = "00000000-0000-0000-0000-000000000002"
}

run "customer_pilot_has_only_four_pinned_gpt_deployments" {
  command = plan
  variables {
    model_aliases = ["gpt-5.6-luna", "gpt-5.6-sol"]
  }
  assert {
    condition     = length(azapi_resource.openai) == 4 && length(azapi_resource.anthropic) == 0
    error_message = "Customer subset must not deploy the development expansion or manually owned Haiku."
  }
}

run "default_development_selection_is_unchanged" {
  command = plan
  assert {
    condition     = length(azapi_resource.openai) > 4 && length(azapi_resource.anthropic) == 2
    error_message = "Null model_aliases must preserve the existing development model selection."
  }
}

run "reject_unmanaged_or_unknown_alias" {
  command = plan
  variables {
    model_aliases = ["claude-haiku-5-5", "unknown"]
  }
  expect_failures = [var.model_aliases]
}
