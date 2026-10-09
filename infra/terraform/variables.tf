variable "subscription_id" {
  type = string
}

variable "resource_group_name" {
  description = "Existing resource group; ownership stays outside this stack."
  type        = string
}

variable "location" {
  description = "Gateway region, not inferred from resource group metadata."
  type        = string
}

variable "name_prefix" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,18}$", var.name_prefix))
    error_message = "Use 3-19 lowercase letters/digits/hyphens starting with a letter."
  }
}

variable "deployment_approved" {
  description = "Explicit cost/config approval. Does NOT enable inference."
  type        = bool
  default     = false
}

variable "publisher_email" {
  type = string
}

variable "entra" {
  description = "Existing registrations only; no Entra tenant/application is created."
  type = object({
    audience            = string
    client_id           = string
    home_tenant_id      = string
    bootstrap_object_id = string
  })
}

variable "sql_admin" {
  description = "Existing Entra SQL administrator group/service principal."
  type = object({
    login     = string
    object_id = string
    tenant_id = string
  })
}

variable "network" {
  description = "Reviewed nonoverlapping ranges; AppGW private IP must be in its subnet."
  type = object({
    address_space       = string
    app_gateway_subnet  = string
    app_gateway_ip      = string
    private_link_subnet = string
    apim_subnet         = string
    apps_subnet         = string
    endpoints_subnet    = string
  })
}

variable "edge" {
  description = "Operator-owned DNS/cert. Certificate contents are never read by Terraform."
  type = object({
    origin_hostname             = string
    certificate_secret_id       = string
    certificate_vault_id        = string
    private_link_location       = string
    request_timeout_seconds     = number
    app_gateway_timeout_seconds = number
    waf_body_limit_kb           = number
    waf_inspection_limit_kb     = number
    zones                       = list(string)
  })
  validation {
    condition = (
      var.edge.request_timeout_seconds >= 16 && var.edge.request_timeout_seconds <= 240 &&
      var.edge.app_gateway_timeout_seconds >= 1 && var.edge.app_gateway_timeout_seconds <= 86400 &&
      length(var.edge.zones) >= 2
    )
    error_message = "Set documented timeout ranges and at least two supported AppGW zones."
  }
}

variable "apps" {
  description = "Reviewed immutable container references, no registry passwords."
  type = map(object({
    image        = string
    registry_url = string
    port         = number
    health_path  = string
  }))
  validation {
    condition     = toset(keys(var.apps)) == toset(["api", "customer", "admin"])
    error_message = "Exactly api/customer/admin hosts are required."
  }
}

variable "registry_resource_id" {
  description = "Existing ACR; app identities get AcrPull. Configure private routing separately if required."
  type        = string
}

variable "app_service_sku" {
  type = string
}

variable "sql_sku" {
  type = string
}

variable "log_retention_days" {
  type = number
}

variable "apim_capacity" {
  type = number
  validation {
    condition     = var.apim_capacity >= 1 && var.apim_capacity <= 30 && floor(var.apim_capacity) == var.apim_capacity
    error_message = "Premium v2 capacity must be an integer from 1 to 30; quota/region still need validation."
  }
}

variable "catalog_container_path" {
  description = "Read-only catalog bundled in API/Function artifacts."
  type        = string
  default     = "/app/gateway/catalog/models.json"
}

variable "tags" {
  type    = map(string)
  default = {}
}
