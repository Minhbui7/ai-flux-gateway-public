mock_provider "azapi" {
  mock_data "azapi_resource" {
    defaults = {
      output = {
        location = "australiaeast"
        kind     = "AIServices"
        properties = {
          disableLocalAuth = true
        }
      }
    }
  }
}

variables {
  subscription_id      = "00000000-0000-0000-0000-000000000001"
  resource_group_name  = "rg-aiflux-test-aue"
  account_name         = "aiflux-test-aue-foundry"
  gateway_principal_id = "00000000-0000-0000-0000-000000000002"
}

run "luna_only" {
  command = plan
  assert {
    condition     = azapi_resource.luna.name == "gpt-5.6-luna" && azapi_resource.luna.body.sku.capacity == 120
    error_message = "Only the pinned Luna model at capacity 120 may be deployed."
  }
  assert {
    condition     = azapi_resource.luna.parent_id == local.account_id && length(output.deployments) == 1
    error_message = "Exactly one deployment in the supplied account is required."
  }
}

run "wrong_region_rejected" {
  command = plan
  override_data {
    target = data.azapi_resource.account
    values = {
      output = {
        location   = "eastus"
        kind       = "AIServices"
        properties = { disableLocalAuth = true }
      }
    }
  }
  expect_failures = [azapi_resource.luna]
}

run "key_auth_rejected" {
  command = plan
  override_data {
    target = data.azapi_resource.account
    values = {
      output = {
        location   = "australiaeast"
        kind       = "AIServices"
        properties = { disableLocalAuth = false }
      }
    }
  }
  expect_failures = [azapi_resource.luna]
}
