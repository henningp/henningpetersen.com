output "bucket_name" {
  description = "S3 bucket with the site assets"
  value       = aws_s3_bucket.site.bucket
}

output "bucket_arn" {
  value = aws_s3_bucket.site.arn
}

output "distribution_id" {
  description = "CloudFront distribution ID (needed for invalidations)"
  value       = aws_cloudfront_distribution.site.id
}

output "distribution_domain" {
  description = "CloudFront domain, to point your DNS CNAME at"
  value       = aws_cloudfront_distribution.site.domain_name
}

output "certificate_arn" {
  value = aws_acm_certificate.site.arn
}

output "route53_name_servers" {
  description = "The 4 nameservers to point your registrar / Host Europe 'NS Delegate' at, AFTER `terraform apply` has created every record. Only then does Route 53 become authoritative."
  value       = aws_route53_zone.site.name_servers
}

output "certificate_validation" {
  description = "CNAME records to add at your DNS provider until the certificate is issued: type CNAME, TTL 60, value = the string shown here"
  value = {
    for r in aws_acm_certificate.site.validation_option : r.domain_name => r.validation_domain
  }
}
