mock_provider "aws" {
  mock_data "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::528099663248:role/henningpetersen-background-admin" }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "528099663248" }
  }
  mock_resource "aws_acm_certificate" {
    defaults = { arn = "arn:aws:acm:us-east-1:528099663248:certificate/00000000-0000-0000-0000-000000000000" }
  }
}

mock_provider "aws" {
  alias = "eu"
  mock_resource "aws_lambda_function" {
    defaults = {
      arn        = "arn:aws:lambda:eu-central-1:528099663248:function:henningpetersen-background-admin"
      invoke_arn = "arn:aws:apigateway:eu-central-1:lambda:path/2015-03-31/functions/arn:aws:lambda:eu-central-1:528099663248:function:henningpetersen-background-admin/invocations"
    }
  }
  mock_resource "aws_apigatewayv2_api" {
    defaults = {
      execution_arn = "arn:aws:execute-api:eu-central-1:528099663248:testapi"
      api_endpoint  = "https://testapi.execute-api.eu-central-1.amazonaws.com"
    }
  }
}

run "admin_opt_in" {
  command = apply
  variables { enable_background_admin = true }

  assert {
    condition = (
      length(aws_cloudfront_distribution.site.origin) == 3 &&
      aws_cloudfront_distribution.site.ordered_cache_behavior[2].path_pattern == "admin" &&
      aws_cloudfront_distribution.site.ordered_cache_behavior[3].path_pattern == "admin/*" &&
      alltrue([for b in slice(aws_cloudfront_distribution.site.ordered_cache_behavior, 2, 4) :
        b.target_origin_id == "background-admin" && b.viewer_protocol_policy == "https-only" &&
        b.min_ttl == 0 && b.default_ttl == 0 && b.max_ttl == 0 &&
        contains(b.forwarded_values[0].headers, "Authorization") &&
        contains(b.forwarded_values[0].headers, "Origin") &&
      contains(b.forwarded_values[0].headers, "X-Admin-Request")])
    )
    error_message = "Admin paths must forward authentication and CSRF headers over HTTPS without caching."
  }
  assert {
    condition = (
      toset(keys(aws_apigatewayv2_route.background_admin)) == toset(["ANY /admin", "ANY /admin/{proxy+}"]) &&
      aws_apigatewayv2_stage.background_admin[0].default_route_settings[0].throttling_rate_limit == 2 &&
      aws_lambda_function.background_admin[0].environment[0].variables.USERNAME_PARAMETER == "/henningpetersen/backgrounds/admin-user" &&
      aws_lambda_function.background_admin[0].environment[0].variables.PASSWORD_HASH_PARAMETER == "/henningpetersen/backgrounds/admin-password-sha256" &&
      aws_lambda_permission.background_admin["admin"].source_arn == "arn:aws:execute-api:eu-central-1:528099663248:testapi/*/*/admin" &&
      aws_lambda_permission.background_admin["admin/*"].source_arn == "arn:aws:execute-api:eu-central-1:528099663248:testapi/*/*/admin/*"
    )
    error_message = "The admin API must be separately throttled, scoped, and contain no password."
  }
}
