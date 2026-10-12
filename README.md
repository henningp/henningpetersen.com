# henningpetersen.com — placeholder site

Minimal bilingual (EN/DE) placeholder page. The domain is currently dedicated
to email; the visible message links to <https://daenen4.de>.

- **Site:** [Astro](https://astro.build) + TypeScript, fully static → `dist/`
- **Infra (Terraform, `infra/`):**
   - S3 bucket in **eu-central-1 (Frankfurt)**, private, versioned, SSE
   - CloudFront distribution (global, Frankfurt edge for EU visitors) + ACM cert
- **Deploy:** `pnpm deploy` → build, `aws s3 sync`, CloudFront invalidation
- **Auth:** a scoped IAM user with a static access key (no SSO) — see below

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

This uses **one scoped IAM user** (`henning-deploy`) with a static access key.
It holds no `*` wildcards except where CloudFront requires it
(`Resource: "arn:aws:cloudfront::<account>:*"` — CloudFront does not permit
per-distribution ARN-based restrictions at apply time).

### 1. IAM user `henning-deploy`

Create the user, add a single access key, and copy both into
`~/.aws/credentials` (profile `default`):

```sh
aws iam create-user henning-deploy
aws iam create-access-key --user-name henning-deploy   # save the secret
```

~/.aws/credentials

```ini
[default]
aws_access_key_id = AKIA...
aws_secret_access_key = ...
```

~/.aws/config

```ini
[default]
region = eu-central-1
output = json
```

### 2. Scoped policy (single inline policy on `henning-deploy`)

| Statement   | Scope                                                        | Purpose                        |
|-------------|--------------------------------------------------------------|--------------------------------|
| `SiteBucket`| `arn:aws:s3:::henningpetersen-com(/*)` + `s3:ListAllMyBuckets` | S3 write + Terraform reads  |
| `SiteCloudFront`| `arn:aws:cloudfront::<account>:*`                      | Create/read/invalidate CDN     |
| `SiteAcm`   | `arn:aws:acm:us-east-1:<account>:certificate/*`           | Issue + validate cert          |

`SiteBucket` needs several S3 read actions that do **not** fall under the
`GetBucket*` / `PutBucket*` prefixes and were added one pair at a time as the
Terraform refresh path demanded them:

- `s3:Get/PutAccelerateConfiguration`
- `s3:Get/PutEncryptionConfiguration`
- `s3:Get/PutLifecycleConfiguration`
- `s3:Get/PutReplicationConfiguration`

Along with the standard set:
`CreateBucket, DeleteBucket, GetBucket*, PutBucket*, ListBucket,
GetObject, PutObject, DeleteObject, ListAllMyBuckets`.

`SiteCloudFront` also needs the tag action used by
`CreateDistributionWithTags`: `cloudfront:TagResource`.

### 3. Apply Terraform

```sh
cd infra
terraform init
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

### 4. DNS (at Host Europe, where the MX records already live)

Host Europe only allows CNAME on subdomains, so the apex is handled by a
provider-specific 301 redirect rather than a record:

- `www.henningpetersen.com` → **CNAME** → `<distribution_domain>`
- `henningpetersen.com` (apex) → **301 redirect** → `https://www.henningpetersen.com`
- **Do not touch** the existing MX / SPF / DMARC records.

If your zone is managed elsewhere, both apex and www can go straight to
`<distribution_domain>` as CNAMEs.

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
