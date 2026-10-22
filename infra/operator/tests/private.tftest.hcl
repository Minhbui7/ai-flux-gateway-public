mock_provider "azurerm" {
  mock_data "azurerm_resource_group" {
    defaults = {
      id       = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-aiflux-example-dev"
      name     = "rg-aiflux-example-dev"
      location = "eastus"
    }
  }
  mock_data "azurerm_client_config" {
    defaults = {
      subscription_id = "00000000-0000-0000-0000-000000000000"
      tenant_id       = "00000000-0000-0000-0000-000000000001"
    }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-aiflux-example-dev/providers/Microsoft.ManagedIdentity/userAssignedIdentities/test"
    }
  }
}

variables {
  subscription_id                 = "00000000-0000-0000-0000-000000000000"
  resource_group_name             = "rg-aiflux-example-dev"
  location                        = "eastus"
  name_prefix                     = "aiflux-test"
  address_space                   = "10.240.0.0/16"
  vm_size                         = "Standard_B2s"
  admin_ssh_public_key            = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA test-only"
  deployment_approved             = true
  network_overlap_review_approved = true
  egress_approved                 = true
  deployment_identity_approved    = true
}

run "private_machine" {
  command = plan
  assert {
    condition     = azurerm_linux_virtual_machine.runner.resource_group_name == data.azurerm_resource_group.existing.name && azurerm_virtual_network.main.resource_group_name == data.azurerm_resource_group.existing.name
    error_message = "Bootstrap must consume the externally owned RG."
  }
  assert {
    condition     = azurerm_network_interface.runner.ip_configuration[0].public_ip_address_id == null && azurerm_linux_virtual_machine.runner.disable_password_authentication && azurerm_linux_virtual_machine.runner.provision_vm_agent
    error_message = "Runner must have no NIC public IP/password login and retain the agent for Run Command."
  }
  assert {
    condition     = azurerm_linux_virtual_machine.runner.identity[0].type == "SystemAssigned" && azurerm_linux_virtual_machine.runner.source_image_reference[0].offer == "ubuntu-24_04-lts" && !output.runner.github_registered
    error_message = "Create an Ubuntu LTS machine identity, not a registered GitHub runner."
  }
  assert {
    condition     = length([for rule in azurerm_network_security_group.runner.security_rule : rule if rule.direction == "Inbound" && rule.access == "Allow"]) == 0 && anytrue([for rule in azurerm_network_security_group.runner.security_rule : rule.name == "DenyAllInbound" && rule.priority == 100 && rule.access == "Deny"])
    error_message = "Override default VNet inbound allow and prohibit SSH/public inbound."
  }
  assert {
    condition     = azurerm_public_ip.egress.sku == "Standard" && azurerm_nat_gateway.runner.sku_name == "Standard" && alltrue([for subnet in azurerm_subnet.main : !subnet.default_outbound_access_enabled])
    error_message = "Use explicit billed NAT egress, never implicit default outbound access."
  }
  assert {
    condition     = anytrue([for rule in azurerm_network_security_group.runner.security_rule : rule.name == "AzureVmAgent" && rule.destination_address_prefix == "168.63.129.16" && rule.access == "Allow"]) && anytrue([for rule in azurerm_network_security_group.runner.security_rule : rule.name == "HttpsInternet" && rule.access == "Allow"]) && anytrue([for rule in azurerm_network_security_group.runner.security_rule : rule.name == "DenyOtherOutbound" && rule.access == "Deny"])
    error_message = "Run Command/agent and HTTPS egress must be explicit with an outbound deny fallback."
  }
  assert {
    condition     = azurerm_subnet.main["runner"].address_prefixes == tolist(["10.240.5.0/24"]) && azurerm_subnet.main["endpoint"].address_prefixes == tolist(["10.240.3.0/24"]) && azurerm_subnet.main["apim"].delegation[0].service_delegation[0].name == "Microsoft.Web/serverFarms" && azurerm_private_dns_zone.blob.name == "privatelink.blob.core.windows.net"
    error_message = "Use the reserved /24 scheme and shared state/private endpoint DNS."
  }
  assert {
    condition     = alltrue([for role in azurerm_role_assignment.deployment : role.scope == data.azurerm_resource_group.existing.id]) && toset(keys(azurerm_role_assignment.deployment)) == toset(["Contributor", "Role Based Access Control Administrator"]) && azurerm_federated_identity_credential.deployment.subject == "repo:REPLACE_WITH_GITHUB_OWNER/REPLACE_WITH_REPOSITORY:environment:aiflux-development"
    error_message = "Only the separate environment-federated identity may receive RG-scoped provisioning/RBAC roles."
  }
  assert {
    condition     = !yamldecode(file("${path.module}/cloud-init.yaml")).ssh_pwauth && strcontains(base64decode(azurerm_linux_virtual_machine.runner.custom_data), "machine-only") && !strcontains(base64decode(azurerm_linux_virtual_machine.runner.custom_data), "--token")
    error_message = "Cloud-init must remain no-secret, machine-only bootstrap."
  }
}

run "reject_unapproved" {
  command = plan
  variables {
    deployment_approved = false
  }
  expect_failures = [terraform_data.approval]
}

run "reject_unreviewed_overlap" {
  command = plan
  variables {
    network_overlap_review_approved = false
  }
  expect_failures = [terraform_data.approval]
}

run "reject_unapproved_egress" {
  command = plan
  variables {
    egress_approved = false
  }
  expect_failures = [terraform_data.approval]
}

run "reject_unapproved_identity" {
  command = plan
  variables {
    deployment_identity_approved = false
  }
  expect_failures = [terraform_data.approval]
}

run "reject_missing_machine_inputs" {
  command = plan
  variables {
    vm_size              = ""
    admin_ssh_public_key = ""
  }
  expect_failures = [terraform_data.approval]
}

run "reject_wrong_subscription" {
  command = plan
  variables {
    subscription_id = "00000000-0000-0000-0000-000000000099"
  }
  expect_failures = [terraform_data.approval]
}

run "reject_noncanonical_network" {
  command = plan
  variables {
    address_space = "10.240.1.0/16"
  }
  expect_failures = [var.address_space]
}
