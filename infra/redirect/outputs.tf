output "name_servers" {
  description = "Assign these four nameservers to the .de domain at its registrar after DNS bootstrap"
  value       = aws_route53_zone.redirect.name_servers
}

output "hosted_zone_id" {
  description = "Attach this zone to the CloudFront Free plan to waive standard DNS charges"
  value       = aws_route53_zone.redirect.zone_id
}

output "distribution_id" {
  description = "Choose the Free plan for this distribution in the CloudFront console"
  value       = try(aws_cloudfront_distribution.redirect[0].id, null)
}

output "distribution_domain" {
  value = try(aws_cloudfront_distribution.redirect[0].domain_name, null)
}
