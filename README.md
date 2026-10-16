# henningpetersen.com — placeholder site

Minimal bilingual (EN/DE) placeholder page. The domain is currently dedicated
to email; the visible message links to <https://daenen4.de>.

- **Site:** [Astro](https://astro.build) + TypeScript, fully static → `dist/`
- **Infra (Terraform, `infra/`):**
  - S3 bucket in **eu-central-1 (Frankfurt)**, private, versioned, SSE
  - CloudFront distribution (global, Frankfurt edge for EU visitors) + ACM cert
  - Route 53 public zone, website records, and Google mail DNS
  - Separate media bucket + daily Lambda/Scheduler for shared background photos
- **Deploy:** `AWS_PROFILE=henning-site pnpm deploy` → build, S3 sync, CDN invalidation
- **Auth:** a manually managed scoped IAM user; named profile `henning-site`

## Local development

```sh
pnpm install
pnpm dev           # http://localhost:4321
pnpm build         # outputs to dist/
```

Language: auto-detected from the browser locale on first visit, switchable in
the top-right corner, choice remembered via `localStorage`. To change copy or
the email/company links, edit `src/config.ts` and `src/pages/index.astro`.


## One-time AWS setup

### 1. Manually managed IAM access

Use one scoped IAM user (`henning-deploy`) for Terraform and content deployment.
Manage its access keys, `SitePolicy`, and policy attachment manually in IAM with
an administrative login. **This Terraform stack does not manage deployer IAM.**
It still manages the application bucket policy granting CloudFront read access.

See [AWS access](docs/deployer-access.md) for setup, scope, and maintenance.
[The reference policy](docs/deployer-policy.json) is for manual review; Terraform
does not apply it, and it is not a verified snapshot of live permissions.

### 2. Named AWS profile

Configure the existing deployer credentials locally (never commit them):

```sh
aws configure --profile henning-site  # region eu-central-1; output json
export AWS_PROFILE=henning-site
aws sts get-caller-identity
```

The expected user is `arn:aws:iam::528099663248:user/henning-deploy`. Profile
selection stays outside the Terraform providers and deployment script. The
existing `default` profile is not changed by this repository.

### 3. Apply Terraform

First complete the [background IAM setup](docs/background-iam/README.md), including
updating the Lambda role if it was originally created for Flickr. Build its Linux
deployment ZIP before planning:

```sh
pnpm build:background
export AWS_PROFILE=henning-site
cd infra
terraform init
terraform plan
terraform apply
```

Outputs you need at your DNS provider:

- `certificate_validation` — CNAME records (type **CNAME**, TTL 60) until the
  ACM certificate is issued. AWS provider v6 does **not** wait for this during
  apply — add the CNAMEs yourself, then check with
  `aws acm get-certificate --certificate-arn <arn> --region us-east-1`
  (it errors precisely while validation is still pending, so success = issued).
- `distribution_domain` — the CloudFront domain, e.g.
  `d12ab3c4d5e6f7.cloudfront.net`.

### 4. DNS (Route 53)

`infra/route53.tf` manages the public zone: apex A/AAAA aliases to CloudFront,
the `www` CNAME, and Google mail records. Host Europe is the previous DNS host,
not the place to edit the current records. The registrar's NS delegation must
match `terraform output route53_name_servers`.

**Do not change MX / SPF / DMARC records as part of website or IAM maintenance.**
Review DNS changes carefully because this domain is used for email.

## Deploy

```sh
AWS_PROFILE=henning-site pnpm deploy
```

That builds the site, syncs `dist/` to S3 (`--delete`, versioned), and
invalidates the CloudFront cache. Fresh content is usually live within ~2
minutes. Repeat any time. This deploy only changes the static site, not the
separate photo pool or Lambda code.

## Daily background photos

Upload JPEG/PNG/WebP/TIFF candidates into `incoming/` in the private media bucket.
The daily Lambda processes them and publishes one shared background at 03:00 UTC.
Photos are shown in both light and dark themes, with a solid-color fallback.

See [background setup and operation](docs/backgrounds.md) for deployment, supported
formats and limits, manual invocation, tests, and removal/failure behavior. A
friendlier uploader is intentionally deferred; for now use the S3 console with an
administrator or separately authorized upload identity.

## Cost (at near-zero traffic)

Expected to be small: S3, CloudFront, Lambda, Scheduler, and processing logs are
usage-based. Free-tier eligibility depends on the account and current AWS plans;
no zero-cost guarantee is assumed. The ACM certificate has no additional charge
when used with CloudFront.
