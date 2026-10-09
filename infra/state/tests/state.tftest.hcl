mock_provider "azurerm" {
  mock_data "azurerm_resource_group" {
    defaults = {
      id = "/subscriptions/4d75ed7f-75ab-4db6-b1f3-263f240d1450/resourceGroups/rg-state-test"
    }
  }
}
mock_provider "azapi" {}

variables {
  subscription_id            = "4d75ed7f-75ab-4db6-b1f3-263f240d1450"
  resource_group_name        = "rg-state-test"
  location                   = "eastus"
  storage_account_name       = "aifluxteststate"
  private_endpoint_subnet_id = "/subscriptions/4d75ed7f-75ab-4db6-b1f3-263f240d1450/resourceGroups/rg-state-test/providers/Microsoft.Network/virtualNetworks/operator/subnets/state"
  private_dns_zone_id        = "/subscriptions/4d75ed7f-75ab-4db6-b1f3-263f240d1450/resourceGroups/rg-state-test/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net"
  runner_principal_id        = "00000000-0000-0000-0000-000000000001"
  deployment_approved        = true
}

run "private_keyless_state" {
  command = plan
  assert {
    condition     = azapi_resource.state.body.properties.publicNetworkAccess == "Disabled" && !azapi_resource.state.body.properties.allowSharedKeyAccess
    error_message = "State must be private and Azure AD-only."
  }
  assert {
    condition     = azapi_resource.blob_service.body.properties.isVersioningEnabled && azapi_resource.container.body.properties.publicAccess == "None"
    error_message = "State must preserve versions and disallow anonymous blob access."
  }
}

run "reject_unapproved_state" {
  command = plan
  variables {
    deployment_approved = false
  }
  expect_failures = [azapi_resource.state]
}
