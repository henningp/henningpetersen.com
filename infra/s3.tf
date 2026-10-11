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
  provider              = aws.eu
  bucket                = aws_s3_bucket.site.id
  block_public_acls     = true
  block_public_policy   = true
  ignore_public_acls    = true
  restrict_public_buckets = true
}
