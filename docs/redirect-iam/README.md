# Domain redirect: additional deployer permissions

The updated [`s3-deploy` reference](../s3-deploy-policy.json) includes the redirect
permissions. It is for **administrator review**, not a live IAM export or a policy
installed by Terraform. The local AWS profile `henning-site`
authenticates as `arn:aws:iam::528099663248:user/henning-deploy`; IAM policies attach
to that user, not to the local profile.

## Update the existing policy

Using an administrator login in account **528099663248**:

1. Open **IAM → Policies → s3-deploy → Edit → JSON**.
2. Save the current version for rollback and compare it with the reference so
   any manually added permissions are retained.
3. Paste [`../s3-deploy-policy.json`](../s3-deploy-policy.json), validate, and save
   it as the default policy version. It is **6,000/6,144 non-whitespace characters**;
   compaction merges duplicate statements without broadening their permissions.

No new policy attachment is needed. Keep `BackgroundUploadInfrastructurePolicy`
and other existing attachments unchanged. [`deployer-policy.json`](deployer-policy.json)
in this directory is only the redirect permission source used by the combined
reference and tests; **do not replace `s3-deploy` with that redirect-only file**.

The combined reference retains hosting/background access and adds no IAM
administration, registrar, or pricing-plan permissions. Updating, publishing,
reading, and deleting Functions is restricted to `henningpetersen-de-redirect`.
Function creation requires an unscoped grant, described below.

### Temporary bootstrap scope

The hosted-zone ID does not exist yet. Consequently the redirect extension initially:

- Allows hosted-zone creation (the API requires `Resource: "*"` and this grant
  is not restricted to the `.de` domain name).
- Allows zone discovery, inspection, and tagging across the account. **Tagging
  is write access**, not just discovery. It is needed to apply Terraform's tags
  to the newly created zone before its ID can be scoped in IAM.
- Allows A/AAAA/CNAME record changes only for `henningpetersen.de`, its `www`
  name, and underscore-prefixed names below it used by ACM validation. The
  resource ARN is initially all hosted zones, but the record-name/type conditions
  still apply. It does not add MX, TXT, NS, SOA, or `.com` record-write access.
- Does **not** allow hosted-zone deletion. Terraform destroy/replacement of the
  zone needs a separate administrator review and an exact-zone deletion grant.
- Allows CloudFront Function creation across the account: AWS does not support
  resource-level scoping for `cloudfront:CreateFunction`. Remove the
  `cloudfront:CreateFunction` grant after the first full redirect apply if you
  do not need automatic Function replacement. Existing hosting permissions
  already supply distribution creation and tagging; there is no separate IAM
  action named `cloudfront:CreateDistributionWithTags`.

After the [DNS bootstrap](../domain-redirect.md#1-bootstrap-dns) succeeds:

1. Get the zone ID with `terraform -chdir=infra/redirect output -raw hosted_zone_id`.
2. In `s3-deploy` and the reference JSON, replace `hostedzone/*` in the three
   redirect zone-scoped statements with `hostedzone/ZONE_ID_FROM_OUTPUT`.
3. Remove `route53:CreateHostedZone` from the bootstrap actions; keep the two
   discovery actions if you want the duplicate-zone check to keep working.
4. Keep the record-name/type conditions. If you later authorize teardown, add
   `route53:DeleteHostedZone` only for that exact zone, not all hosted zones.

Keep the source references and combined file synchronized when narrowing access.
Existing hosting/background grants are retained; other attached policies can
also grant access independently.

## Validation and verification

Optionally validate with an explicitly selected administrator CLI profile:

```sh
aws accessanalyzer validate-policy \
  --profile YOUR_ADMIN_PROFILE \
  --region us-east-1 \
  --policy-type IDENTITY_POLICY \
  --policy-document file://docs/s3-deploy-policy.json
```

No administrator CLI profile is configured by this repository. Do not assume the
unrelated `default` profile is an administrator. Local JSON/tests are not a
substitute for live IAM Access Analyzer validation.

After saving the policy and allowing for IAM propagation:

```sh
aws sts get-caller-identity --profile henning-site
aws route53 list-hosted-zones-by-name \
  --dns-name henningpetersen.de --max-items 1 --profile henning-site
AWS_PROFILE=henning-site terraform -chdir=infra/redirect plan -var='enable_redirect=false'
```

Inspect the returned zone name: the list is lexicographic and can return a
different domain if `.de` has no zone yet. If a matching zone exists, import it
instead of creating a duplicate. A successful plan does not prove create/write
permissions; review and apply the bootstrap separately using the main guide.
