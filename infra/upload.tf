# Manually bootstrap this role and the token-hash parameter (docs/upload-iam/).
# Neither the raw token nor its hash is read into Terraform state.
data "aws_iam_role" "background_upload" {
  name = "henningpetersen-background-upload"
}

resource "aws_cloudwatch_log_group" "background_upload" {
  provider          = aws.eu
  name              = "/aws/lambda/henningpetersen-background-upload"
  retention_in_days = 14
  tags              = var.tags
}

resource "aws_lambda_function" "background_upload" {
  provider         = aws.eu
  function_name    = "henningpetersen-background-upload"
  description      = "Authorize private S3 uploads from a personal Apple Shortcut"
  role             = data.aws_iam_role.background_upload.arn
  runtime          = "python3.13"
  architectures    = ["x86_64"]
  handler          = "app.handler"
  filename         = "${path.module}/../.artifacts/background-upload.zip"
  source_code_hash = filebase64sha256("${path.module}/../.artifacts/background-upload.zip")
  memory_size      = 128
  timeout          = 15
  environment {
    variables = {
      MEDIA_BUCKET         = aws_s3_bucket.media.bucket
      TOKEN_HASH_PARAMETER = "/henningpetersen/backgrounds/upload-token-sha256"
    }
  }
  tags = var.tags
  depends_on = [
    aws_cloudwatch_log_group.background_upload,
    aws_s3_bucket_public_access_block.media,
    aws_s3_bucket_server_side_encryption_configuration.media
  ]
}

resource "aws_apigatewayv2_api" "background_upload" {
  provider      = aws.eu
  name          = "henningpetersen-background-upload"
  protocol_type = "HTTP"
  # Deliberately no CORS, access logging, public website route, or default route.
  tags = var.tags
}

resource "aws_apigatewayv2_integration" "background_upload" {
  provider               = aws.eu
  api_id                 = aws_apigatewayv2_api.background_upload.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.background_upload.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 16000
}

resource "aws_apigatewayv2_route" "background_upload" {
  provider           = aws.eu
  api_id             = aws_apigatewayv2_api.background_upload.id
  route_key          = "POST /uploads"
  authorization_type = "NONE" # Personal bearer token is checked inside Lambda.
  target             = "integrations/${aws_apigatewayv2_integration.background_upload.id}"
}

resource "aws_apigatewayv2_stage" "background_upload" {
  provider    = aws.eu
  api_id      = aws_apigatewayv2_api.background_upload.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit   = 5
    throttling_rate_limit    = 2
    detailed_metrics_enabled = false
  }
  # Tagged CreateStage was rejected under an unsupported IAM action name.
  # Stage tags are optional; keep the parent API tagged without broadening IAM.
  depends_on = [aws_lambda_permission.background_upload]
}

resource "aws_lambda_permission" "background_upload" {
  provider       = aws.eu
  statement_id   = "AllowBackgroundUploadApi"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.background_upload.function_name
  principal      = "apigateway.amazonaws.com"
  source_account = data.aws_caller_identity.current.account_id
  source_arn     = "${aws_apigatewayv2_api.background_upload.execution_arn}/*/POST/uploads"
}
