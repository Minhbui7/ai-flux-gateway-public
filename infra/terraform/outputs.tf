output "resource_group_name" {
  value = local.rg
}

output "gateway_url" {
  description = "Planned public base URL; route disabled and inference blocked."
  value       = "https://${azurerm_cdn_frontdoor_endpoint.main.host_name}/v1"
}

output "inference_enabled" {
  value = false
}

output "control_plane_settings" {
  description = "Nonsecret runtime configuration; catalog explicitly unconfigured."
  value       = local.control_settings
}

output "apim_resource_id" {
  value = azurerm_api_management.main.id
}

output "identity_principal_ids" {
  value = { for k, v in azurerm_user_assigned_identity.identity : k => v.principal_id }
}

output "private_frontend" {
  value = {
    application_gateway_id = azurerm_application_gateway.main.id
    group_id               = "private"
    origin_hostname        = var.edge.origin_hostname
  }
}

output "sql_connection_url" {
  value = local.database_url
}
