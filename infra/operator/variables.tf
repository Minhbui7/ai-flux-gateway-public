variable "subscription_id" {
  type = string
}

variable "resource_group_name" {
  description = "Existing externally owned RG; never created or imported by this root."
  type        = string
}

variable "location" {
  type = string
}

variable "name_prefix" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,18}$", var.name_prefix))
    error_message = "Use a 3-19 character lowercase resource prefix."
  }
}

variable "address_space" {
  description = "Reviewed /16. Dedicated /24s reserve .1 AppGW, .2 APIM, .3 endpoints, .4 apps, .5 runner."
  type        = string
  validation {
    condition     = can(cidrsubnet(var.address_space, 8, 5)) && can(regex("^([0-9]{1,3}\\.){3}[0-9]{1,3}/16$", var.address_space)) && try(cidrhost(var.address_space, 0) == split("/", var.address_space)[0], false)
    error_message = "Supply an IPv4 /16 for the five dedicated /24 subnets."
  }
}

variable "vm_size" {
  description = "Explicitly priced/approved x64 SKU. Standard_B2s is only a comparison candidate."
  type        = string
  default     = ""
}

variable "os_disk" {
  description = "Explicit disk comparison candidate; not an approval."
  type = object({
    size_gb      = number
    storage_type = string
  })
  default = {
    size_gb      = 32
    storage_type = "StandardSSD_LRS"
  }
  validation {
    condition     = var.os_disk.size_gb >= 32 && floor(var.os_disk.size_gb) == var.os_disk.size_gb && contains(["StandardSSD_LRS", "Premium_LRS"], var.os_disk.storage_type)
    error_message = "Select an integer disk size >=32 GiB and StandardSSD_LRS or Premium_LRS."
  }
}

variable "admin_ssh_public_key" {
  description = "Existing operator public key required by the Linux VM API. No key is generated; SSH is disabled and inbound denied."
  type        = string
  default     = ""
}

variable "deployment_approved" {
  type    = bool
  default = false
}

variable "network_overlap_review_approved" {
  description = "Attest corporate/peering/VPN overlap review, not merely an empty subscription VNet list."
  type        = bool
  default     = false
}

variable "egress_approved" {
  description = "Approve billed Standard NAT gateway + egress-only Standard public IP and outbound HTTPS policy."
  type        = bool
  default     = false
}

variable "deployment_identity_approved" {
  description = "Approve separate environment-federated deployment identity and RG-scoped Contributor/RBAC Administrator."
  type        = bool
  default     = false
}
