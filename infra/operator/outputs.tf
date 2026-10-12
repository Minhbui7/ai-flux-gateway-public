output "operator_network" {
  description = "Explicit nonsecret main-root inputs; operator root retains sole ownership."
  value = {
    virtual_network_id = azurerm_virtual_network.main.id
    subnet_ids         = { for key, subnet in azurerm_subnet.main : key => subnet.id }
    blob_dns_zone_id   = azurerm_private_dns_zone.blob.id
  }
}

output "state_inputs" {
  description = "Pass these explicit IDs to infra/state. runner_principal_id is the federated deployment identity, NOT the VM identity."
  value = {
    private_endpoint_subnet_id = azurerm_subnet.main["endpoint"].id
    private_dns_zone_id        = azurerm_private_dns_zone.blob.id
    runner_principal_id        = azurerm_user_assigned_identity.deployment.principal_id
  }
}

output "deployment_identity" {
  value = {
    client_id    = azurerm_user_assigned_identity.deployment.client_id
    principal_id = azurerm_user_assigned_identity.deployment.principal_id
    tenant_id    = data.azurerm_client_config.current.tenant_id
    subject      = azurerm_federated_identity_credential.deployment.subject
  }
}

output "runner" {
  description = "Machine only; this output does not attest successful cloud-init, tools or GitHub registration."
  value = {
    resource_id       = azurerm_linux_virtual_machine.runner.id
    name              = azurerm_linux_virtual_machine.runner.name
    private_ip        = azurerm_network_interface.runner.private_ip_address
    vm_principal_id   = azurerm_linux_virtual_machine.runner.identity[0].principal_id
    egress_public_ip  = azurerm_public_ip.egress.ip_address
    github_registered = false
  }
}
