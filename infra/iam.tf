# IAM resources are MAINTAINED IN THE AWS CONSOLE for henning-deploy, NOT applied
# by Terraform (they are not in the state). This file + infra/deployer-policy.json
# exist as a durable, exact RECORD of the access the deployer/terraforming identity
# needs. Do NOT add `aws_iam_policy`/`aws_iam_user` to `terraform apply` without
# first `terraform import`-ing them, or Terraform will attempt to create a second
# policy of the same name. See docs/deployer-access.md.

resource "aws_iam_user" "henning_deploy" {
  name = "henning-deploy"
}

# The user and policy are console-managed. Policy content is referenced from the
# exact active JSON so the module mirrors the repo-of-record.
resource "aws_iam_policy" "SitePolicy" {
  name        = "SitePolicy"
  description = "Read/write access for henningpetersen.com infrastructure (S3/CloudFront/ACM/Route53). Maintained in the console; this JSON is the documented reference."
  path        = "/"

  policy = file("${path.module}/deployer-policy.json")
}

resource "aws_iam_user_policy_attachment" "henning_deploy_policy" {
  user       = aws_iam_user.henning_deploy.name
  policy_arn = aws_iam_policy.SitePolicy.arn
}
