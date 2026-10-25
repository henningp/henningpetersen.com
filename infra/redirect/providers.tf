terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

# CloudFront certificates must be in us-east-1. Credentials stay outside Terraform.
provider "aws" {
  region = "us-east-1"
}
