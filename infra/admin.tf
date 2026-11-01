# IAM role and credential parameters are provisioned separately by an administrator.
data "aws_iam_role" "background_admin" {
  count = var.enable_background_admin ? 1 : 0
  name  = "henningpetersen-background-admin"
}

resource "aws_cloudwatch_log_group" "background_admin" {
  count             = var.enable_background_admin ? 1 : 0
  provider          = aws.eu
  name              = "/aws/lambda/henningpetersen-background-admin"
  retention_in_days = 14
  tags              = var.tags
}

resource "aws_lambda_function" "background_admin" {
  count            = var.enable_background_admin ? 1 : 0
  provider         = aws.eu
  function_name    = "henningpetersen-background-admin"
  role             = data.aws_iam_role.background_admin[0].arn
  runtime          = "python3.13"
  architectures    = ["x86_64"]
  handler          = "app.handler"
  filename         = "${path.module}/../.artifacts/background-admin.zip"
  source_code_hash = filebase64sha256("${path.module}/../.artifacts/background-admin.zip")
  memory_size      = 256
  timeout          = 30
  environment {
    variables = {
      MEDIA_BUCKET            = aws_s3_bucket.media.bucket
      USERNAME_PARAMETER      = "/henningpetersen/backgrounds/admin-user"
      PASSWORD_HASH_PARAMETER = "/henningpetersen/backgrounds/admin-password-sha256"
      ADMIN_ORIGINS           = "https://${var.domain},https://www.${var.domain}"
    }
  }
  tags       = var.tags
  depends_on = [aws_cloudwatch_log_group.background_admin]
}

resource "aws_apigatewayv2_api" "background_admin" {
  count         = var.enable_background_admin ? 1 : 0
  provider      = aws.eu
  name          = "henningpetersen-background-admin"
  protocol_type = "HTTP"
  # No CORS and no access logging: requests may contain credentials or private keys.
  tags = var.tags
}

resource "aws_apigatewayv2_integration" "background_admin" {
  count                  = var.enable_background_admin ? 1 : 0
  provider               = aws.eu
  api_id                 = aws_apigatewayv2_api.background_admin[0].id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.background_admin[0].invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 30000
}

resource "aws_apigatewayv2_route" "background_admin" {
  for_each           = var.enable_background_admin ? toset(["ANY /admin", "ANY /admin/{proxy+}"]) : toset([])
  provider           = aws.eu
  api_id             = aws_apigatewayv2_api.background_admin[0].id
  route_key          = each.value
  authorization_type = "NONE" # The Lambda checks Basic auth on every route.
  target             = "integrations/${aws_apigatewayv2_integration.background_admin[0].id}"
}

resource "aws_apigatewayv2_stage" "background_admin" {
  count       = var.enable_background_admin ? 1 : 0
  provider    = aws.eu
  api_id      = aws_apigatewayv2_api.background_admin[0].id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = 5
    throttling_rate_limit  = 2
  }
  depends_on = [aws_lambda_permission.background_admin]
}

resource "aws_lambda_permission" "background_admin" {
  for_each       = var.enable_background_admin ? toset(["admin", "admin/*"]) : toset([])
  provider       = aws.eu
  statement_id   = each.value == "admin" ? "AllowAdminPage" : "AllowAdminRoutes"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.background_admin[0].function_name
  principal      = "apigateway.amazonaws.com"
  source_account = data.aws_caller_identity.current.account_id
  source_arn     = "${aws_apigatewayv2_api.background_admin[0].execution_arn}/*/*/${each.value}"
}
