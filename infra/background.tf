# IAM roles are administrator-managed; never create or modify them in this stack.
data "aws_iam_role" "background_lambda" {
  name = "henningpetersen-background-lambda"
}

data "aws_iam_role" "background_scheduler" {
  name = "henningpetersen-background-scheduler"
}

resource "aws_s3_bucket" "media" {
  provider      = aws.eu
  bucket        = var.media_bucket_name
  force_destroy = false
  tags          = var.tags
}

resource "aws_s3_bucket_versioning" "media" {
  provider = aws.eu
  bucket   = aws_s3_bucket.media.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "media" {
  provider = aws.eu
  bucket   = aws_s3_bucket.media.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "media" {
  provider                = aws.eu
  bucket                  = aws_s3_bucket.media.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "media" {
  provider = aws.eu
  bucket   = aws_s3_bucket.media.id
  rule {
    id     = "old-versions-and-incomplete-uploads"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
  depends_on = [aws_s3_bucket_versioning.media]
}

resource "aws_s3_bucket_policy" "media" {
  provider = aws.eu
  bucket   = aws_s3_bucket.media.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowCloudFrontPublishedPhotosOnly"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource = [
        "${aws_s3_bucket.media.arn}/photos/*",
        "${aws_s3_bucket.media.arn}/background.json"
      ]
      Condition = {
        StringEquals = {
          "AWS:SourceArn" = aws_cloudfront_distribution.site.arn
        }
      }
    }]
  })
}

resource "aws_cloudwatch_log_group" "background" {
  provider          = aws.eu
  name              = "/aws/lambda/henningpetersen-background-sync"
  retention_in_days = 14
  tags              = var.tags
}

resource "aws_lambda_function" "background" {
  provider         = aws.eu
  function_name    = "henningpetersen-background-sync"
  description      = "Process private S3 uploads and publish a shared daily background"
  role             = data.aws_iam_role.background_lambda.arn
  runtime          = "python3.13"
  architectures    = ["x86_64"]
  handler          = "app.handler"
  filename         = "${path.module}/../.artifacts/background-sync.zip"
  source_code_hash = filebase64sha256("${path.module}/../.artifacts/background-sync.zip")
  memory_size      = 1024
  timeout          = 300
  # Small accounts cannot reserve capacity without breaching AWS's unreserved
  # minimum. S3 conditional publication, not a concurrency quota, prevents races.
  reserved_concurrent_executions = -1
  environment {
    variables = {
      MEDIA_BUCKET = aws_s3_bucket.media.bucket
    }
  }
  tags = var.tags
  depends_on = [
    aws_cloudwatch_log_group.background,
    aws_s3_bucket_versioning.media,
    aws_s3_bucket_server_side_encryption_configuration.media,
    aws_s3_bucket_public_access_block.media
  ]
}

resource "aws_scheduler_schedule_group" "background" {
  provider = aws.eu
  name     = "henningpetersen-backgrounds"
  tags     = var.tags
}

resource "aws_scheduler_schedule" "background" {
  provider                     = aws.eu
  name                         = "daily-sync"
  group_name                   = aws_scheduler_schedule_group.background.name
  description                  = "Publish the daily website background at 03:00 UTC"
  schedule_expression          = "cron(0 3 * * ? *)"
  schedule_expression_timezone = "UTC"
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_lambda_function.background.arn
    role_arn = data.aws_iam_role.background_scheduler.arn
    input    = "{}"
    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 2
    }
  }
}
