# Entirely mocked: no AWS credentials, API requests, or live state are used.
mock_provider "aws" {
  override_data {
    target = data.aws_iam_role.background_upload
    values = {
      arn = "arn:aws:iam::528099663248:role/henningpetersen-background-upload"
    }
  }
  override_data {
    target = data.aws_iam_role.background_lambda
    values = {
      arn = "arn:aws:iam::528099663248:role/henningpetersen-background-lambda"
    }
  }
  override_data {
    target = data.aws_iam_role.background_scheduler
    values = {
      arn = "arn:aws:iam::528099663248:role/henningpetersen-background-scheduler"
    }
  }
  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "528099663248"
    }
  }
  mock_resource "aws_acm_certificate" {
    defaults = {
      arn = "arn:aws:acm:us-east-1:528099663248:certificate/00000000-0000-0000-0000-000000000000"
    }
  }
}

mock_provider "aws" {
  alias = "eu"
  mock_resource "aws_lambda_function" {
    defaults = {
      arn        = "arn:aws:lambda:eu-central-1:528099663248:function:henningpetersen-background-sync"
      invoke_arn = "arn:aws:apigateway:eu-central-1:lambda:path/2015-03-31/functions/arn:aws:lambda:eu-central-1:528099663248:function:henningpetersen-background-sync/invocations"
    }
  }
  mock_resource "aws_apigatewayv2_api" {
    defaults = {
      execution_arn = "arn:aws:execute-api:eu-central-1:528099663248:testapi"
      api_endpoint  = "https://testapi.execute-api.eu-central-1.amazonaws.com"
    }
  }
}

override_resource {
  target = aws_s3_bucket.media
  values = {
    arn = "arn:aws:s3:::henningpetersen-com-media"
  }
}

override_resource {
  target = aws_cloudfront_distribution.site
  values = {
    arn = "arn:aws:cloudfront::528099663248:distribution/TEST"
  }
}

run "private_daily_backgrounds" {
  command = apply

  assert {
    condition     = aws_s3_bucket.media.bucket != aws_s3_bucket.site.bucket && !aws_s3_bucket.media.force_destroy
    error_message = "Media must use a separate bucket that is not automatically emptied on destroy."
  }

  assert {
    condition = (
      aws_s3_bucket_public_access_block.media.block_public_acls &&
      aws_s3_bucket_public_access_block.media.block_public_policy &&
      aws_s3_bucket_public_access_block.media.ignore_public_acls &&
      aws_s3_bucket_public_access_block.media.restrict_public_buckets
    )
    error_message = "The media bucket must block all public access."
  }

  assert {
    condition = (
      aws_lambda_function.background.runtime == "python3.13" &&
      aws_lambda_function.background.architectures == tolist(["x86_64"]) &&
      aws_lambda_function.background.reserved_concurrent_executions == -1 &&
      aws_lambda_function.background.role == data.aws_iam_role.background_lambda.arn
    )
    error_message = "Lambda must match the packaged runtime and use the existing role without reserving account concurrency."
  }

  assert {
    condition = (
      aws_scheduler_schedule.background.schedule_expression == "cron(0 3 * * ? *)" &&
      aws_scheduler_schedule.background.schedule_expression_timezone == "UTC" &&
      aws_scheduler_schedule.background.target[0].role_arn == data.aws_iam_role.background_scheduler.arn
    )
    error_message = "The daily schedule must use the existing Scheduler role and an explicit UTC cadence."
  }

  assert {
    condition = (
      length(aws_cloudfront_distribution.site.origin) == 2 &&
      aws_cloudfront_distribution.site.default_cache_behavior[0].target_origin_id == "s3-${var.bucket_name}" &&
      aws_cloudfront_distribution.site.ordered_cache_behavior[0].path_pattern == "background.json" &&
      aws_cloudfront_distribution.site.ordered_cache_behavior[0].max_ttl == 300 &&
      aws_cloudfront_distribution.site.ordered_cache_behavior[1].path_pattern == "photos/*" &&
      aws_cloudfront_distribution.site.ordered_cache_behavior[1].target_origin_id == "s3-${var.media_bucket_name}"
    )
    error_message = "Only the selection and published photos should use the media origin, with a short pointer TTL."
  }
}

run "published_objects_only" {
  command = apply

  assert {
    condition = (
      toset(jsondecode(aws_s3_bucket_policy.media.policy).Statement[0].Resource) == toset([
        "arn:aws:s3:::henningpetersen-com-media/photos/*",
        "arn:aws:s3:::henningpetersen-com-media/background.json"
      ]) &&
      jsondecode(aws_s3_bucket_policy.media.policy).Statement[0].Condition.StringEquals["AWS:SourceArn"] == "arn:aws:cloudfront::528099663248:distribution/TEST"
    )
    error_message = "CloudFront may read only published objects, never incoming uploads or private state."
  }
}
