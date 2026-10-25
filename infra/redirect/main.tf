locals {
  aliases = [var.domain, "www.${var.domain}"]
  dns_records = {
    apex_a    = { name = var.domain, type = "A" }
    apex_aaaa = { name = var.domain, type = "AAAA" }
    www_a     = { name = "www.${var.domain}", type = "A" }
    www_aaaa  = { name = "www.${var.domain}", type = "AAAA" }
  }
}

resource "aws_route53_zone" "redirect" {
  name = var.domain
  tags = var.tags
}

resource "aws_acm_certificate" "redirect" {
  domain_name               = var.domain
  subject_alternative_names = ["www.${var.domain}"]
  validation_method         = "DNS"
  tags                      = var.tags

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "validation" {
  for_each = {
    for domain in local.aliases : domain => one([
      for option in aws_acm_certificate.redirect.domain_validation_options : option
      if option.domain_name == domain
    ])
  }

  zone_id = aws_route53_zone.redirect.zone_id
  name    = each.value.resource_record_name
  type    = each.value.resource_record_type
  ttl     = 60
  records = [each.value.resource_record_value]
}

# Do not wait for issuance during bootstrap: delegation does not exist yet.
resource "aws_acm_certificate_validation" "redirect" {
  count = var.enable_redirect ? 1 : 0

  certificate_arn         = aws_acm_certificate.redirect.arn
  validation_record_fqdns = [for record in aws_route53_record.validation : record.fqdn]
}

resource "aws_cloudfront_function" "redirect" {
  count = var.enable_redirect ? 1 : 0

  name    = "${replace(var.domain, ".", "-")}-redirect"
  runtime = "cloudfront-js-2.0"
  comment = "Permanent redirect to https://${var.target_domain}"
  publish = true
  code = templatefile("${path.module}/redirect.js.tftpl", {
    target_origin = jsonencode("https://${var.target_domain}")
  })
}

resource "aws_cloudfront_distribution" "redirect" {
  count = var.enable_redirect ? 1 : 0

  enabled         = true
  is_ipv6_enabled = true
  aliases         = local.aliases
  comment         = "${var.domain} redirect to ${var.target_domain}"
  price_class     = "PriceClass_100"
  tags            = var.tags

  # CloudFront requires an origin even though the viewer-request function always
  # responds before an origin is contacted. No bucket or server is provisioned.
  origin {
    domain_name = var.target_domain
    origin_id   = "unused-redirect-origin"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id = "unused-redirect-origin"
    # Let the function redirect both HTTP and HTTPS directly to the final URL.
    viewer_protocol_policy = "allow-all"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    # AWS managed CachingOptimized policy, supported by the CloudFront Free plan.
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.redirect[0].arn
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.redirect[0].certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}

resource "aws_route53_record" "redirect" {
  for_each = var.enable_redirect ? local.dns_records : {}

  zone_id = aws_route53_zone.redirect.zone_id
  name    = each.value.name
  type    = each.value.type

  alias {
    name                   = aws_cloudfront_distribution.redirect[0].domain_name
    zone_id                = aws_cloudfront_distribution.redirect[0].hosted_zone_id
    evaluate_target_health = false
  }
}
