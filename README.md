# henningpetersen.com — placeholder site

Minimal bilingual (EN/DE) placeholder page. The domain is currently dedicated
to email; the visible message links to <https://daenen4.de>.

- **Site:** [Astro](https://astro.build) + TypeScript, fully static → `dist/`
- **Infra (Terraform, `infra/`):**
  - S3 bucket in **eu-central-1 (Frankfurt)**, private, versioned, SSE
  - CloudFront distribution (global, Frankfurt edge for EU visitors) + ACM cert
- **Deploy:** `pnpm deploy` → build, `aws s3 sync`, CloudFront invalidation
- **Auth:** AWS CLI with IAM Identity Center (SSO) — no long-lived keys

## Local development

```sh
pnpm install
pnpm dev          # http://localhost:4321
pnpm build        # outputs to dist/
```

Language: auto-detected from the browser locale on first visit, switchable in
the top-right corner, choice remembered via `localStorage`. To change copy or
the email/company links, edit `src/config.ts` and `src/pages/index.astro`.


## One-time AWS setup

### 1. IAM Identity Center (SSO)

1. Enable **IAM Identity Center** (https://docs.aws.amazon.com/singlesignon/latest/userguide/what-is.html).
   Free for a personal account; requires your AWS account as a trusted entity
   and an active MFA device on your root user.
2. Create a **Permission set** (e.g. `henningpetersen.s3-deploy`), 30 days,
   MFA optional, and attach a policy scoped to this bucket only:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Sid": "S3Deploy",
         "Effect": "Allow",
         "Action": [
           "s3:PutObject",
           "s3:DeleteObject",
           "s3:ListBucket",
           "s3:GetBucketLocation"
         ],
         "Resource": [
           "arn:aws:s3:::henningpetersen-com",
           "arn:aws:s3:::henningpetersen-com/*"
         ]
       },
       {
         "Sid": "CloudFrontInvalidate",
         "Effect": "Allow",
         "Action": [
           "cloudfront:CreateInvalidation",
           "cloudfront:GetDistribution",
           "cloudfront:ListInvalidations"
         ],
         "Resource": "*"
       }
     ]
   }
   ```
3. Assign your root/primary account user (or a dedicated SSO user) to the
   permission set for this AWS account.

### 2. Configure the AWS CLI

```sh
aws configure sso          # follow the prompts (SSO URL from your IIC config)
aws sso login              # opens the browser OAuth loop; tokens refresh automatically
```

### 3. Apply Terraform

```sh
cd infra
terraform init
terraform apply
```

Outputs you need at your DNS provider:

- `certificate_validation` — CNAME records (type **CNAME**, TTL 60) until the
  ACM certificate is issued. Check with
  `aws acm describe-certificate --certificate-arn <arn> --region us-east-1`
  until it says `ISSUED`.
- `distribution_domain` — the CloudFront domain, e.g.
  `d12ab3c4d5e6f7.cloudfront.net`.

### 4. DNS (at your zone provider, where the MX records already live)

- `henningpetersen.com` → CNAME → `<distribution_domain>`
- `www.henningpetersen.com` → CNAME → `<distribution_domain>` (optional)
- **Do not touch** the existing MX / SPF / DMARC records.

## Deploy

```sh
pnpm deploy
```

That builds the site, syncs `dist/` to S3 (`--delete`, versioned), and
invalidates the CloudFront cache. Fresh content is usually live within ~2
minutes. Repeat any time — no other moving parts.

## Cost (at near-zero traffic)

Effectively **$0 / month**: S3 storage + requests are inside the free tier,
CloudFront's first 1M requests and 100 GB transfer per month are free, and the
ACM certificate is free. Expect a few cents once traffic becomes noticeable.
