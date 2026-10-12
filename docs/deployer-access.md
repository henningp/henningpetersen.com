# `henning-deploy` — AWS access for terraforming & deploying

## Where this lives

The IAM **user `henning-deploy`** and its **`SitePolicy`** are created and kept in
the **AWS Console** (attached in IAM, not applied by Terraform). This repo holds an
**exact, durable copy** of the active policy at
[`infra/deployer-policy.json`](/infra/deployer-policy.json), and `infra/iam.tf`
references that file so the module mirrors the live policy.

> Why not apply it? IAM was provisioned by hand in the console and is *not* in the
> Terraform state. Applying the `aws_iam_policy`/`aws_iam_user` resources here would
> try to create a **second** policy of the same name. Treat `iam.tf` as documentation
> of intent until/unless the resources are `terraform import`-ed.

## What the policy grants

Seven statements, scoped narrowly to this account (`528099663248`):

| # | Service | Scope | Grants |
|---|---------|-------|--------|
| 0 | **ACM** | `arn:aws:acm:us-east-1:…:certificate/*` | Read/inspect/tag the CloudFront TLS cert (`Describe`/`Get`/`List*`/`Renew`/`Tag*`) |
| 1 | **CloudFront** | `arn:aws:cloudfront::528099663248:*` | `Get*`/`Update*`/`Delete*` for the distribution + OAC, plus `CreateInvalidation` (used by `pnpm deploy`) |
| 2 | **Route 53** | `*` | Manage the hosted zone & record sets (created for the NS cutover); includes `GetChange` to poll async changes |
| 3 | **S3** | `arn:aws:s3:::henningpetersen-com[/*]` | Read/write the content bucket: `PutObject`, `ListBucket`, `GetBucket*`, encryption/lifecycle config, `DeleteObject`/`DeleteBucket` |
| 4 | **S3** | `*` | `ListAllMyBuckets` (needed so the CLI can resolve the bucket name) |
| 5 | **CloudFront** | `…:528099663248:*` | *Create*/`List* for distributions & OACs (first-time provisioning only) |
| 6 | **ACM** | `…:certificate/*` | `RequestCertificate` / `ListCertificates` (first-time provisioning only) |

### Least-privilege notes
- **S3** statement 3 is bucket-scoped; statement 4 (`ListAllMyBuckets`) is unavoidable
  for an S3 CLI key that only knows the bucket *name*.
- **Route 53** uses `"Resource": "*"` — Route 53 does not support per-record resource
  granularity, so account scope is expected here. It can be tightened to a zone
  ARN later if needed.
- `Create*` / `RequestCertificate` / `Delete*` are *first-time provisioning* scopes:
  they exist so the stack can be built, and are harmless once the resources exist
  (idempotent Terraform won't call them unless the resource is missing).

## Reconciling with Terraform (optional, later)

If you ever want Terraform to *own* IAM, import the live identities first so it
adopts them instead of colliding:

```bash
cd infra
terraform import aws_iam_user.henning_deploy henning-deploy
terraform import aws_iam_policy.SitePolicy SitePolicy
terraform import 'aws_iam_user_policy_attachment.henning_deploy_policy[*]' SitePolicy
terraform apply
```

Until then, keep any **policy changes in the console** and paste the updated JSON
back into `infra/deployer-policy.json` to keep the record in sync.

## Identity
- **User:** `henning-deploy` — `arn:aws:iam::528099663248:user/henning-deploy`
- **Access key:** `REDACTED_AWS_ACCESS_KEY_ID`
- **Region:** `eu-central-1` (profile `[default]` in `~/.aws/` — not committed)
