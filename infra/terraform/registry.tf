resource "azurerm_container_registry" "main" {
  count                         = var.create_container_registry ? 1 : 0
  name                          = "${local.compact}acr"
  resource_group_name           = local.rg
  location                      = var.location
  sku                           = "Basic"
  admin_enabled                 = false
  public_network_access_enabled = true
  anonymous_pull_enabled        = false
  tags                          = local.tags
  depends_on                    = [terraform_data.approval]
}

locals {
  registry_resource_id = var.create_container_registry ? azurerm_container_registry.main[0].id : var.registry_resource_id
}
