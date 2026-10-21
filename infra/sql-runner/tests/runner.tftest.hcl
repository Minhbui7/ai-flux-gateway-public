mock_provider "azurerm" {}

override_data {
  target = data.azurerm_virtual_network.existing
  values = {
    name     = "aiflux-test-vnet"
    location = "australiaeast"
  }
}

variables {
  subscription_id     = "10000000-0000-0000-0000-000000000001"
  resource_group_name = "rg-aiflux-test"
  name_prefix         = "aiflux-test"
  network_profile     = "10.240"
  registry_id         = "/subscriptions/10000000-0000-0000-0000-000000000001/resourceGroups/rg-aiflux-test/providers/Microsoft.ContainerRegistry/registries/aifluxtestacr"
  ssh_public_key      = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCcok+olRWFYjlDcRYna3YsaZnbbzz5xWkPTkFrsabnTP9TIAdUV8D6eolxRShOkzgsGsdC+H5wsaqQSBdHPq/222V73CSUDFljpP/M9495gW1GwWyj0p6C6UWd2WBfi430l923mbk1MoaUM5KH3Bmc4OUOtT1kU4W4nu1rGHaAvwB4TSb0oY+R2Cx8JSYNv1s/wjpTXl+CX6gihLlrMEJ16GYOAEGMA9Rbm50x5lxQ9g5lVf/PwkfqSsE1HhMSe1ATSWaOWfSt0AJ/qSg6/VBLt0P0xnD1K6rIY5t9oq9QV1lwZGNkIAFotL0oqOxvORxsbIW0HCRxN2M0rkdARV+h"
  image_version       = "24.04.202610160"
}

run "private_runner_contract" {
  command = plan
  assert {
    condition     = azurerm_network_interface.runner.ip_configuration[0].public_ip_address_id == null
    error_message = "Migration VM must not have a public IP."
  }
  assert {
    condition     = azurerm_subnet.runner.address_prefixes == tolist(["10.240.5.0/24"]) && !azurerm_subnet.runner.default_outbound_access_enabled
    error_message = "Use a separate explicitly routed runner subnet."
  }
  assert {
    condition     = azurerm_linux_virtual_machine.runner.identity[0].type == "UserAssigned" && azurerm_linux_virtual_machine.runner.disable_password_authentication
    error_message = "Use only the separate runner identity and disable passwords."
  }
  assert {
    condition     = azurerm_role_assignment.pull.role_definition_name == "AcrPull" && azurerm_role_assignment.pull.scope == var.registry_id
    error_message = "Only registry-scoped image pull is granted to the runner."
  }
  assert {
    condition     = alltrue([for rule in azurerm_network_security_group.runner.security_rule : rule.destination_address_prefix != "AzurePlatformDNS" || rule.access == "Deny"])
    error_message = "AzurePlatformDNS only accepts Deny rules; use the platform IP for explicit DNS allowance."
  }
}
