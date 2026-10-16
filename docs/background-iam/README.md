# Background sync: IAM bootstrap

These are **reference policies for administrator review**, not exports of live
AWS configuration. Nothing here is applied by Terraform. Backgrounds now come
directly from private S3 uploads; no Flickr account, API key, or SSM parameter is
needed. See [background operation](../backgrounds.md).

The infrastructure and frontend are implemented in the repository, but applying
these IAM policies and deploying the infrastructure are separate steps.

## Resource contract

The Terraform implementation uses these exact names. Review and update the
policies before changing them. All regional resources are in Frankfurt
(`eu-central-1`), in account `528099663248`.

| Resource | Name |
|----------|------|
| Media bucket | `henningpetersen-com-media` |
| Lambda function | `henningpetersen-background-sync` |
| Lambda log group | `/aws/lambda/henningpetersen-background-sync` |
| Lambda execution role (no IAM path) | `henningpetersen-background-lambda` |
| Scheduler execution role (no IAM path) | `henningpetersen-background-scheduler` |
| Scheduler group | `henningpetersen-backgrounds` |
| Schedule in that group | `daily-sync` |
| Additional deployer managed policy | `BackgroundInfrastructurePolicy` |

The S3 bucket name is globally unique; availability has not been checked. A
different bucket name requires changing the bucket ARNs in both permission files.

## Ownership and permissions

**Existing `s3-deploy` policy:** if the deployment user uses a single policy with
this name, update it using [the combined policy](../s3-deploy-policy.json) instead
of the separate-policy attachment workflow below. It contains both hosting and
background infrastructure permissions. Do not replace it with this directory's
background-only `deployer-policy.json`. Runtime policies go on the two execution
roles, not on the user.

- **Administrator:** manages these two roles, their trust/inline policies, and the
  additional deployer policy. Keep them outside
  Terraform, just like the existing deployer identity. Save any existing role or
  policy configuration before updating it; do not overwrite unfamiliar resources.
- **`henning-deploy`:** keeps its existing `SitePolicy`, including CloudFront/OAC
  permissions. Attach `deployer-policy.json` as a separate managed policy; do not
  replace `SitePolicy`. The additional policy allows management of the named
  bucket, function, schedule/group, and logs. It allows `GetRole` and service-
  restricted `PassRole` on just the two execution roles, but no IAM writes or
  direct SSM access. `DescribeLogGroups` requires `Resource: "*"`; it exposes log
  group metadata across Frankfurt, not other groups' log contents.
- **Lambda:** can list this media bucket, read `incoming/*`, read/write generated
  photos, `background.json`, and private `state/` objects, and write streams in its
  pre-created log group. Bucket-wide listing also lets S3 distinguish missing
  objects from access-denied errors on the first run. It cannot write/delete
  originals, delete generated photos, administer buckets, read the site bucket,
  access SSM, create log groups, or invalidate CloudFront.
- **Scheduler:** can invoke only the named, unqualified Lambda function. Its trust
  is restricted to this account and **schedule group**, not a schedule ARN, as
  required by EventBridge Scheduler.

The deployer is still trusted: changing Lambda code lets it exercise the Lambda
role's access, including reading private originals and changing published photos.
Limiting direct object access is not a security boundary against someone who can
deploy arbitrary Lambda code.
Likewise, bucket-policy management permits changing who can read the media.

The media bucket uses SSE-S3; no customer-managed KMS key or key permissions are
needed. Human uploads use an administrator or separately authorized uploader, not
the Lambda role. The deployer policy intentionally grants no direct media-object
access and does not provide an S3 console upload workflow.

## Administrator setup

Run commands from the repository root with AWS CLI v2. Substitute your separate
administrative profile for `YOUR_ADMIN_PROFILE`; **do not use `henning-site`** for
these steps. Never configure root access keys. Verify that STS returns the intended
administrator in account `528099663248`:

```sh
export AWS_PROFILE=YOUR_ADMIN_PROFILE
aws sts get-caller-identity
```

First validate each permission policy in IAM Access Analyzer (trust policies are
reviewed separately in the IAM role editor). For example:

```sh
aws accessanalyzer validate-policy \
  --policy-document file://docs/background-iam/deployer-policy.json \
  --policy-type IDENTITY_POLICY \
  --region eu-central-1
```

Repeat for `lambda-policy.json` and `scheduler-policy.json`. Resolve errors and
review warnings before installation. AWS validation and live permission tests
have **not** been performed as part of preparing these files.

### 1. Create the execution roles

These are first-install commands, not an idempotent installer. If a role already
exists, inspect and back it up rather than deleting/recreating it. No broad AWS
managed execution policy is needed in addition to the inline policies below.

```sh
aws iam create-role \
  --role-name henningpetersen-background-lambda \
  --assume-role-policy-document file://docs/background-iam/lambda-trust-policy.json

aws iam put-role-policy \
  --role-name henningpetersen-background-lambda \
  --policy-name BackgroundSyncRuntime \
  --policy-document file://docs/background-iam/lambda-policy.json

aws iam create-role \
  --role-name henningpetersen-background-scheduler \
  --assume-role-policy-document file://docs/background-iam/scheduler-trust-policy.json

aws iam put-role-policy \
  --role-name henningpetersen-background-scheduler \
  --policy-name InvokeBackgroundSync \
  --policy-document file://docs/background-iam/scheduler-policy.json
```

The referenced bucket, Lambda, log group, and schedule group need not exist yet.
IAM propagation may take a short time after creation.

### 2. Attach the additional deployer policy

```sh
aws iam create-policy \
  --policy-name BackgroundInfrastructurePolicy \
  --description 'Manage the named website background resources and pass their execution roles' \
  --policy-document file://docs/background-iam/deployer-policy.json

aws iam attach-user-policy \
  --user-name henning-deploy \
  --policy-arn arn:aws:iam::528099663248:policy/BackgroundInfrastructurePolicy
```

If this managed policy already exists, review its current version and attachments
before making a new version default. Leave `SitePolicy` and unrelated attachments
unchanged. An SCP, permissions boundary, or explicit deny can still restrict these
permissions.

### 3. Update an already-created Lambda role

If you followed the earlier Flickr-based instructions, replace just the
`BackgroundSyncRuntime` inline policy with the current file (as administrator):

```sh
aws iam put-role-policy \
  --role-name henningpetersen-background-lambda \
  --policy-name BackgroundSyncRuntime \
  --policy-document file://docs/background-iam/lambda-policy.json
```

This removes SSM access, adds private incoming-photo reads, and adjusts bucket
listing for initial/missing-object reads. The Scheduler role and deployer policy
are unchanged. Remove any separate, now-unused Flickr permissions only after
review; no credentials are required for this implementation.

### 4. Verify the deployer, then deploy the infrastructure

```sh
export AWS_PROFILE=henning-site
aws sts get-caller-identity
aws iam get-role --role-name henningpetersen-background-lambda
aws iam get-role --role-name henningpetersen-background-scheduler
```

Expected identity: `arn:aws:iam::528099663248:user/henning-deploy`. The role reads
test only `GetRole`; there is no standalone `PassRole` API to test.

Build the Lambda ZIP as described in [background operation](../backgrounds.md),
run a full Terraform plan (no `-target`), inspect it, then apply only with approval.
A plan checks reads, not every creation/update permission. Test both a manual
Lambda invocation and an actual scheduled run,
inspect logs, and verify same-origin delivery through CloudFront. Diagnose exact
action/resource denials rather than granting administrator access.

## Constraints for the implementation

- Reuse the existing CloudFront distribution and OAC permissions from `SitePolicy`;
  add a media origin and path behaviors. Do not touch DNS or site deployment sync.
- Permit CloudFront to read only `photos/*` and `background.json` in the media
  bucket. Keep `state/` private, including inventories and bookkeeping.
- Terraform creates the log group with finite retention **before** Lambda runs.
  Package image-processing dependencies with the function (no layer permissions
  are included), use an unqualified function ARN, and avoid a VPC/NAT gateway.
- Use SSE-S3 for the media bucket; no SSM, KMS, or Secrets Manager permissions
  are included. Store no credentials in Terraform state or logs.
- Use the exact schedule name/group and a daily schedule with an explicit time
  zone. Use conditional S3 publication and idempotent retries, not reserved Lambda
  concurrency (small accounts must leave their limited concurrency unreserved).
- Reconcile only from a successfully fetched complete S3 inventory. Failed
  listing/export/upload must not erase the published selection or retire photos.
- Cache the selection briefly; version image keys by content hash. Choose only
  current eligible images. Keep bookkeeping in `state/` and publish the pointer
  last. S3 versioning/lifecycle and browser caches affect how removal works.
- Alarm notifications, SNS subscriptions, and a dead-letter queue are **not**
  covered by this bootstrap. Add and review their permissions when choosing the
  monitoring design; logs alone do not satisfy the planned failure notification.

References: [Scheduler trust conditions](https://docs.aws.amazon.com/scheduler/latest/UserGuide/cross-service-confused-deputy-prevention.html),
[PassRole](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_passrole.html).
