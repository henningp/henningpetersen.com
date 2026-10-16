# No AWS access or live state; this file exercises only mocked operations.
mock_provider "aws" {
  mock_data "aws_iam_role" {
    defaults = {
      arn = "arn:aws:iam::528099663248:role/henningpetersen-background-upload"
    }
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
      arn        = "arn:aws:lambda:eu-central-1:528099663248:function:henningpetersen-background-upload"
      invoke_arn = "arn:aws:apigateway:eu-central-1:lambda:path/2015-03-31/functions/arn:aws:lambda:eu-central-1:528099663248:function:henningpetersen-background-upload/invocations"
    }
  }
  mock_resource "aws_apigatewayv2_api" {
    defaults = {
      execution_arn = "arn:aws:execute-api:eu-central-1:528099663248:testapi"
      api_endpoint  = "https://testapi.execute-api.eu-central-1.amazonaws.com"
    }
  }
}

run "private_upload_endpoint" {
  command = apply

  assert {
    condition = (
      aws_apigatewayv2_api.background_upload.protocol_type == "HTTP" &&
      aws_apigatewayv2_route.background_upload.route_key == "POST /uploads" &&
      aws_apigatewayv2_stage.background_upload.auto_deploy &&
      length(coalesce(aws_apigatewayv2_stage.background_upload.tags, {})) == 0 &&
      aws_apigatewayv2_stage.background_upload.default_route_settings[0].throttling_rate_limit == 2 &&
      aws_apigatewayv2_stage.background_upload.default_route_settings[0].throttling_burst_limit == 5
    )
    error_message = "Only the throttled personal upload route should be exposed."
  }

  assert {
    condition = (
      aws_lambda_permission.background_upload.principal == "apigateway.amazonaws.com" &&
      aws_lambda_permission.background_upload.source_account == "528099663248" &&
      aws_lambda_permission.background_upload.source_arn == "arn:aws:execute-api:eu-central-1:528099663248:testapi/*/POST/uploads"
    )
    error_message = "API Gateway invocation must be scoped to this account, API, method, and path."
  }

  assert {
    condition = (
      aws_apigatewayv2_integration.background_upload.payload_format_version == "2.0" &&
      aws_lambda_function.background_upload.runtime == "python3.13" &&
      aws_lambda_function.background_upload.environment[0].variables == tomap({
        MEDIA_BUCKET         = "henningpetersen-com-media"
        TOKEN_HASH_PARAMETER = "/henningpetersen/backgrounds/upload-token-sha256"
      })
    )
    error_message = "Upload configuration must contain only a bucket and parameter name, never the personal token."
  }

  assert {
    condition = (
      length(aws_cloudfront_distribution.site.origin) == 2 &&
      aws_scheduler_schedule.background.schedule_expression == "cron(0 3 * * ? *)"
    )
    error_message = "Adding upload authorization must not change website origins or daily selection timing."
  }
}
