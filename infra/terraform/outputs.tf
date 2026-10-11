output "resource_group_name" {
  value = local.rg
}

output "gateway_url" {
  description = "Public HTTPS gateway base after the public-edge stage; inference remains disabled."
  value       = local.public_edge_stage ? local.gateway_url : null
}

output "inference_enabled" {
  value = false
}

output "deferred_protection_dependencies" {
  description = "Explicit missing provisioned dependencies, not runtime protection acceptance. Inference stays disabled even when empty."
  value       = var.protection_language_enabled ? [] : ["language-pii"]
}

output "deferred_platform_dependencies" {
  description = "Explicit deferred platform provisioning dependencies; does not attest application readiness."
  value = concat(
    var.sql_enabled ? [] : ["azure-sql"],
    var.sql_enabled && !var.sql_public_network_access_enabled && !var.hybrid_private_data_enabled ? ["sql-public-endpoint"] : [],
    var.hybrid_private_data_enabled && !var.private_sql_connectivity_accepted ? ["private-sql-runtime-acceptance"] : [],
  )
}

output "container_registry" {
  value = var.create_container_registry ? {
    id           = azurerm_container_registry.main[0].id
    name         = azurerm_container_registry.main[0].name
    login_server = azurerm_container_registry.main[0].login_server
  } : null
}

output "control_plane_settings" {
  description = "Nonsecret runtime configuration; catalog explicitly unconfigured."
  value       = local.platform_stage ? local.control_settings : null
}

output "apim_resource_id" {
  value = azurerm_api_management.main.id
}

output "identity_principal_ids" {
  value = { for k, v in azurerm_user_assigned_identity.identity : k => v.principal_id }
}

output "public_gateway" {
  description = "Public Application Gateway endpoint; only present in the public-edge stage."
  value = local.public_edge_stage ? {
    application_gateway_id = azurerm_application_gateway.main["public"].id
    public_ip_id           = azurerm_public_ip.appgw["public"].id
    hostname               = var.edge.origin_hostname
    url                    = "https://${var.edge.origin_hostname}"
  } : null
}

output "edge_preparation" {
  description = "Provisioning inventory only, not DNS/TLS/backend/live acceptance; public routes remain gated."
  value = local.edge_stage ? {
    stage                  = var.deployment_stage
    hostname               = var.edge.origin_hostname
    public_ip_id           = azurerm_public_ip.appgw["public"].id
    application_gateway_id = azurerm_application_gateway.main["public"].id
    tls_configured         = local.edge_tls_stage
    public_routes_released = local.public_edge_stage
    inference_enabled      = false
  } : null
}

output "sql_connection_url" {
  value = local.database_url
}

output "sql_required_outbound_ipv4s" {
  description = "Empty in hybrid mode. Legacy public-data mode requires reviewing platform outbound addresses and configuring exact sql_firewall_ipv4s; refresh after plan/scale changes."
  value       = var.hybrid_private_data_enabled ? toset([]) : local.app_sql_outbound_ipv4s
}

output "private_data_endpoints" {
  description = "Management-plane endpoint/DNS inventory only; not evidence of runtime SQL authorization or migrations."
  value = { for name, endpoint in azurerm_private_endpoint.data : name => {
    id      = endpoint.id
    address = endpoint.private_service_connection[0].private_ip_address
    zone    = azurerm_private_dns_zone.data[name].name
  } }
}
