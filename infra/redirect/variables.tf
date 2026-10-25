variable "domain" {
  description = "Registered domain to redirect (including its www subdomain)"
  type        = string
  default     = "henningpetersen.de"
}

variable "target_domain" {
  description = "Destination hostname; the redirect always uses HTTPS"
  type        = string
  default     = "henningpetersen.com"

  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$", var.target_domain))
    error_message = "Use a hostname only, without a scheme, path, query string, or port."
  }
}

variable "enable_redirect" {
  description = "Use false for DNS bootstrap; enable only after delegating the domain to this hosted zone"
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags applied to resources supporting tags"
  type        = map(string)
  default = {
    Name      = "henningpetersen.de redirect"
    ManagedBy = "terraform"
  }
}
