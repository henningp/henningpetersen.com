resource "aws_s3_bucket" "site" {
  provider = aws.eu
  bucket   = var.bucket_name
  tags     = var.tags
}

resource "aws_s3_bucket_versioning" "site" {
  provider = aws.eu
  bucket   = aws_s3_bucket.site.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  provider = aws.eu
  bucket   = aws_s3_bucket.site.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Explicitly keep all public access blocked.
# Readers go through CloudFront + Origin Access Control, never directly at S3.
resource "aws_s3_bucket_public_access_block" "site" {
  provider                = aws.eu
  bucket                  = aws_s3_bucket.site.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

// Reader grant for CloudFront via OAC.
//
// For OAC the bucket policy does NOT reference the OAC ID as a principal --
// S3's principal directory has no such entry, so that ARN is rejected with
// "MalformedPolicy: Invalid principal in policy". Instead grant the CloudFront
// service principal and scope it to THIS distribution with an AWS:SourceArn
// condition. The OAC only SIGNS the request (attached to the origin in
// cloudfront.tf); this policy authorizes the signing service. Because the grant
// is conditioned on a single distribution ARN it is not public, so PAB's
// BlockPublicPolicy accepts it.
resource "aws_s3_bucket_policy" "site" {
  provider = aws.eu
  bucket   = aws_s3_bucket.site.id

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Sid    = "AllowCloudFrontOACRead",
        Effect = "Allow",
        Principal = {
          Service = "cloudfront.amazonaws.com"
        },
        Action   = "s3:GetObject",
        Resource = "${aws_s3_bucket.site.arn}/*",
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = "arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/${aws_cloudfront_distribution.site.id}"
          },
        },
      },
    ],
  })
}
