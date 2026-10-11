terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

# Default provider: us-east-1 — CloudFront is global, but its resources and
# (mandatory) ACM certificate live here.
provider "aws" {
  region = "us-east-1"
}

# EU provider: the S3 origin lives in Frankfurt (eu-central-1).
provider "aws" {
  alias  = "eu"
  region = "eu-central-1"
}

data "aws_caller_identity" "current" {}
