mock_provider "aws" {
  mock_resource "aws_acm_certificate" {
    defaults = {
      arn = "arn:aws:acm:us-east-1:528099663248:certificate/00000000-0000-0000-0000-000000000000"
      domain_validation_options = [
        {
          domain_name           = "henningpetersen.de"
          resource_record_name  = "_apex.henningpetersen.de."
          resource_record_type  = "CNAME"
          resource_record_value = "_apex.acm-validations.aws."
        },
        {
          domain_name           = "www.henningpetersen.de"
          resource_record_name  = "_www.www.henningpetersen.de."
          resource_record_type  = "CNAME"
          resource_record_value = "_www.acm-validations.aws."
        }
      ]
    }
  }

  mock_resource "aws_acm_certificate_validation" {
    defaults = {
      certificate_arn = "arn:aws:acm:us-east-1:528099663248:certificate/00000000-0000-0000-0000-000000000000"
    }
  }

  mock_resource "aws_cloudfront_function" {
    defaults = {
      arn = "arn:aws:cloudfront::528099663248:function/henningpetersen-de-redirect"
    }
  }
}

run "bootstrap_without_waiting_for_delegation" {
  command = apply

  variables {
    enable_redirect = false
  }

  assert {
    condition = (
      aws_route53_zone.redirect.name == "henningpetersen.de" &&
      length(aws_route53_record.validation) == 2 &&
      length(aws_acm_certificate_validation.redirect) == 0 &&
      length(aws_cloudfront_function.redirect) == 0 &&
      length(aws_cloudfront_distribution.redirect) == 0 &&
      length(aws_route53_record.redirect) == 0
    )
    error_message = "Bootstrap must create only DNS and certificate validation records, without waiting for issuance."
  }
}

run "redirect_after_delegation" {
  command = apply

  assert {
    condition = (
      aws_acm_certificate.redirect.domain_name == "henningpetersen.de" &&
      aws_acm_certificate.redirect.subject_alternative_names == toset(["www.henningpetersen.de"]) &&
      aws_cloudfront_distribution.redirect[0].aliases == toset(["henningpetersen.de", "www.henningpetersen.de"]) &&
      aws_cloudfront_distribution.redirect[0].is_ipv6_enabled &&
      aws_cloudfront_distribution.redirect[0].viewer_certificate[0].ssl_support_method == "sni-only"
    )
    error_message = "Both .de hostnames must support HTTPS and IPv6 without dedicated-IP certificate charges."
  }

  assert {
    condition = (
      aws_cloudfront_function.redirect[0].publish &&
      aws_cloudfront_function.redirect[0].runtime == "cloudfront-js-2.0" &&
      aws_cloudfront_distribution.redirect[0].default_cache_behavior[0].viewer_protocol_policy == "allow-all" &&
      one(aws_cloudfront_distribution.redirect[0].default_cache_behavior[0].function_association).event_type == "viewer-request" &&
      one(aws_cloudfront_distribution.redirect[0].default_cache_behavior[0].function_association).function_arn == aws_cloudfront_function.redirect[0].arn &&
      strcontains(aws_cloudfront_function.redirect[0].code, "https://henningpetersen.com")
    )
    error_message = "A published viewer-request function must redirect both HTTP and HTTPS to the fixed destination."
  }

  assert {
    condition = (
      length(aws_route53_record.redirect) == 4 &&
      aws_route53_record.redirect["apex_a"].type == "A" &&
      aws_route53_record.redirect["apex_aaaa"].type == "AAAA" &&
      aws_route53_record.redirect["www_a"].type == "A" &&
      aws_route53_record.redirect["www_aaaa"].type == "AAAA" &&
      alltrue([for record in aws_route53_record.redirect :
        record.zone_id == aws_route53_zone.redirect.zone_id &&
        record.alias[0].name == aws_cloudfront_distribution.redirect[0].domain_name &&
        !record.alias[0].evaluate_target_health
      ])
    )
    error_message = "Apex and www must each have A/AAAA aliases in the .de zone pointing to the redirect distribution."
  }
}
