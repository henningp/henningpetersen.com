# Grants CloudFront (and only CloudFront, via OAC) read access to the bucket.
# origin_access_control_origin_type must be "s3" so it pairs with an S3-typed
# distribution origin — no custom_origin_config allowed on S3 origins.
resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${var.bucket_name}-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_origin_access_control" "media" {
  name                              = "${var.media_bucket_name}-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Wildcard-ish cert for apex + www. CloudFront mandates us-east-1.
# AWS provider v6 no longer waits for validation during apply — add the
# CNAMEs from `terraform output certificate_validation` at your DNS provider,
# then check with:
#   aws acm describe-certificate --certificate-arn <arn> --region us-east-1
resource "aws_acm_certificate" "site" {
  domain_name               = var.domain
  subject_alternative_names = ["www.${var.domain}"]
  validation_method         = "DNS"
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  is_ipv6_enabled     = true
  comment             = "${var.domain} placeholder site"
  default_root_object = "index.html"
  price_class         = "PriceClass_100"

  origin {
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_id                = "s3-${var.bucket_name}"
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  origin {
    domain_name              = aws_s3_bucket.media.bucket_regional_domain_name
    origin_id                = "s3-${var.media_bucket_name}"
    origin_access_control_id = aws_cloudfront_origin_access_control.media.id
  }

  ordered_cache_behavior {
    path_pattern           = "background.json"
    target_origin_id       = "s3-${var.media_bucket_name}"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    min_ttl                = 0
    default_ttl            = 300
    max_ttl                = 300
    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }
  }

  ordered_cache_behavior {
    path_pattern           = "photos/*"
    target_origin_id       = "s3-${var.media_bucket_name}"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = false
    min_ttl                = 0
    default_ttl            = 31536000
    max_ttl                = 31536000
    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }
  }

  default_cache_behavior {
    target_origin_id       = "s3-${var.bucket_name}"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    forwarded_values {
      query_string = false

      cookies {
        forward = "none"
      }
    }

    min_ttl     = 0
    default_ttl = 3600
    max_ttl     = 31536000
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  aliases = [
    var.domain,
    "www.${var.domain}",
  ]

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate.site.arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  tags = var.tags
}
