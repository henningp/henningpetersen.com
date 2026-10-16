variable "domain" {
  description = "Apex domain to serve"
  type        = string
  default     = "henningpetersen.com"
}

variable "bucket_name" {
  description = "S3 bucket holding the static site"
  type        = string
  default     = "henningpetersen-com"
}

variable "tags" {
  description = "Tags applied to all resources"
  type        = map(string)
  default = {
    Name      = "henningpetersen.com"
    ManagedBy = "terraform"
  }
}

variable "media_bucket_name" {
  description = "Separate S3 bucket for private uploads and published backgrounds (also update manual IAM policies if changed)"
  type        = string
  default     = "henningpetersen-com-media"
}
