# AWS access for Terraform and deployments

## Ownership

Use one scoped IAM user, **`henning-deploy`**, for both infrastructure maintenance
and content deployments. Manage the user, access keys, `SitePolicy`, and its
attachment manually in IAM using a separate administrative identity.

Terraform manages S3, CloudFront, ACM, and Route 53, including the S3 bucket policy
that lets CloudFront read the site. It does **not** manage the deployer's IAM
identity or permissions. The deployer does not need IAM administration, policy
read access, or permission to change its own access. The proposed background-sync
extension adds read/pass access to two specific execution roles, not IAM
administration; see [Background sync IAM bootstrap](background-iam/README.md).

`infra/iam.tf` was removed after checking that none of its three IAM resources
were in Terraform state. No live IAM objects were deleted or detached. Do not
reintroduce IAM resource declarations as documentation: Terraform executes them.

## Named local profile

Use **`henning-site`** rather than relying on the unrelated `default` profile:

```sh
aws configure --profile henning-site
# Existing henning-deploy access key; region eu-central-1; output json.
aws sts get-caller-identity --profile henning-site
```

If the existing key is only saved in `~/.aws/credentials`, copy its values locally
into the named profile; do not create an extra key just to rename a profile.
Expected identity: `arn:aws:iam::528099663248:user/henning-deploy`.
This repository does not create the local profile or edit `~/.aws/`.

Select it for a shell session:

```sh
export AWS_PROFILE=henning-site
terraform -chdir=infra plan
terraform -chdir=infra apply
pnpm deploy
```

Alternatively prefix each command with `AWS_PROFILE=henning-site`. Both Terraform
providers and the deploy script use the normal AWS credential chain; no profile
name is hardcoded in executable configuration. Environment credentials can take
precedence over a profile, so unset stale `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, and `AWS_SESSION_TOKEN` variables when switching identities.
Verify the identity before applying or deploying.

Leave the existing `default` profile alone until the named profile works. Protect
local credential files, never commit keys, rotate keys periodically, and disable
unused keys. IAM Identity Center with short-lived credentials is a future upgrade,
not a requirement for this small site. Protect the separate administrative login
with MFA; do not use root access keys.

## Reference policy (not applied by Terraform)

[`deployer-policy.json`](deployer-policy.json) is a **proposed reference policy**
for manual review and installation, not a verified export of the live policy.
The current deployer cannot read IAM policies, and the live policy has been edited
manually. Moving this JSON out of `infra/` does not update AWS permissions.

| Scope | Access |
|-------|--------|
| S3 bucket `henningpetersen-com` | Terraform bucket configuration and listing |
| Objects in that bucket | Upload, read, and delete site content |
| CloudFront distributions and OACs in account `528099663248` | Inspect, update, delete; tag distributions and invalidate caches |
| ACM certificates in `us-east-1` in that account | Inspect, tag, and delete |
| Hosted zone `Z0326591QB2H1WSRQHAY` | Inspect, tag, and change DNS records |
| Route 53 change IDs | Poll asynchronous DNS changes |
| APIs without resource-level scoping | Create/list CloudFront distributions and OACs; request/list ACM certificates |

This is a pragmatic infrastructure policy, not a content-upload-only policy:

- CloudFront resource-ID wildcards allow replacements without editing IAM for
  each new ID. They also allow maintenance of other distributions/OACs in this
  account. Tighten these to exact ARNs if the account hosts other projects.
- CloudFront create/list and ACM request/list actions require `Resource: "*"`.
  ACM request/list is restricted to `us-east-1`.
- S3 `GetBucket*`/`PutBucket*` are intentionally bucket-scoped action wildcards
  for Terraform maintenance. Object access is a separate statement. The CLI does
  not need `ListAllMyBuckets` to sync to this explicitly named bucket.
- DNS permissions cover **all records in this zone**, including mail records.
  Review every DNS plan carefully. Creating or deleting hosted zones is
  deliberately excluded; rebuilding the zone needs an administrator and a review
  of its ARN and registrar delegation.
- Create/delete permissions are real capabilities, not harmless just because
  Terraform normally leaves existing resources alone. Review replacement and
  destroy plans before approving them.

### Updating the live policy manually

1. Sign in with your administrative identity, not the deployer.
2. Save the current policy/version for rollback. Compare it with the reference;
   do not assume this file includes every manual change you have made.
3. Use IAM's policy editor/Access Analyzer validation to review the JSON. Apply
   the reviewed policy to `SitePolicy` and attach it to `henning-deploy`.
4. Verify the named profile's identity and run a **full** `terraform plan` (no
   `-target`). A plan checks refresh permissions, not every possible write action.
5. Test a normal content deployment when ready. If access is denied, investigate
   the exact action/resource rather than granting administrator access.
6. Keep the reference and this document in sync with your intended permissions.

The reference removes the invalid `acm:ListCertificateDomainValidations` action
(validation information comes from `DescribeCertificate`) and fixes global API
scopes in the previous JSON. It grants no `iam:*` actions.

## S3 background-sync extension

For the existing single managed policy named **`s3-deploy`**, use
[`s3-deploy-policy.json`](s3-deploy-policy.json). It is the exact union of the
hosting reference above and the background deployer reference below. Install it
as the default version of `s3-deploy`, retaining a previous version for rollback.
Do not replace the hosting permissions with the background-only file. This
combined policy is an alternative to attaching two separate deployer policies;
the Lambda and Scheduler runtime policies still belong on their respective roles,
not on the deployment user. When changing either source reference, update and
recheck the combined file against IAM's managed-policy size limit.

[Background sync IAM bootstrap](background-iam/README.md) contains a separate,
additive deployer policy and the trust/runtime policies for two administrator-
managed execution roles. No Flickr key or SSM parameter is needed. These are
reference files only: they do not alter AWS, replace `SitePolicy`, or add
executable IAM declarations to Terraform.

The extension grants `iam:GetRole` and service-restricted `iam:PassRole` on only
those two roles. The existing deployer policy above remains unchanged.
Terraform should manage the media bucket, Lambda, Scheduler group/schedule, and
log group, but not these roles or their policies. If the roles were created for
the previous Flickr design, update the Lambda inline policy using the bootstrap
instructions before deploying.
