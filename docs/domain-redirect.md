# henningpetersen.de redirect

`infra/redirect/` is a **separate Terraform root and local state**, not a module
of the website stack. It manages only `.de`: a public zone, DNS-validated ACM
certificate in us-east-1, CloudFront Function/distribution, and apex/www A/AAAA
aliases. It does not manage registrations, `.com`, mail, IAM, or pricing plans.

Both HTTP and HTTPS redirect permanently (301) to `https://henningpetersen.com`,
preserving the path and query parameters, including repeated query parameters.
There is no new S3 bucket, Lambda, or server. CloudFront requires an origin in its
configuration, but the function responds before any request reaches it.

## Prerequisites

- Finish the `.de` registration transfer before changing its nameservers in AWS.
- Check whether a public `.de` zone already exists. If so, review its records and
  import it into `aws_route53_zone.redirect` rather than creating a duplicate.
  Import any existing records you intend this stack to manage too.
- Use a deliberately authorized AWS profile. Have an administrator update the
  existing `s3-deploy` policy using the [redirect IAM instructions](redirect-iam/README.md).
  No additional policy attachment is needed. Narrow the temporary zone bootstrap
  scope after zone creation; do not grant the deployer IAM administration.
- Registrar nameserver changes and the Free-plan subscription below are manual
  administrator actions, not permissions this Terraform stack needs.

## 1. Bootstrap DNS

Select the intended profile and verify the AWS account first:

```sh
export AWS_PROFILE=henning-site
aws sts get-caller-identity
terraform -chdir=infra/redirect init
terraform -chdir=infra/redirect plan -var='enable_redirect=false'
terraform -chdir=infra/redirect apply -var='enable_redirect=false'
terraform -chdir=infra/redirect output name_servers
```

This creates the zone, certificate request, and validation CNAMEs without waiting
for a certificate that cannot validate until delegation exists. Assign the four
output nameservers under **Route 53 → Registered domains → henningpetersen.de**.
Do not copy the `.com` nameservers: each zone has its own set. If DNSSEC DS records
exist at the registrar, remove the old delegation's DS records before switching
to this unsigned zone. This stack does not configure DNSSEC.

## 2. Create the redirect

After public DNS reflects the new delegation:

```sh
dig NS henningpetersen.de
terraform -chdir=infra/redirect plan
terraform -chdir=infra/redirect apply
```

`enable_redirect` defaults to true. Terraform now waits for certificate issuance,
creates the distribution and function, and adds the four alias records.
Allow time for DNS propagation and CloudFront deployment. If certificate
validation times out, verify delegation and rerun the apply; do not create a new
zone. After setup, omit the bootstrap flag: setting it false again would remove
the distribution and website aliases.

## 3. Attach the Free plan (manual)

The installed HashiCorp AWS provider (6.68.0) does not expose PricingPlanManager
subscriptions or hosted-zone attachments. Terraform therefore initially creates
a **pay-as-you-go** distribution; it does not guarantee zero-cost operation.

In the CloudFront console, select the distribution from `distribution_id`, choose
the **Free ($0/month)** pricing plan, then attach `hosted_zone_id` under **Manage
Plan**. Merely pointing DNS at CloudFront does not attach the zone to the plan.
Review subsequent Terraform plans for any console-created settings (for example
a WAF association) before applying; reconcile intentional settings in code rather
than blindly reverting them. This stack does not manage the subscription's
lifecycle; review/cancel it in the console before destroying the distribution.

For normal redirect traffic, the Free plan covers CloudFront, Functions, TLS,
and the attached zone: approximately **$0/year extra**, excluding registration
renewal and taxes. Its monthly allowance is 1 million requests / 100 GB. Until the
zone is attached, standard Route 53 pricing is $0.50/month ($6/year, with creation
month not prorated); pay-as-you-go CloudFront/Function usage can also be billed.
See [CloudFront pricing](https://aws.amazon.com/cloudfront/pricing/) and
[DNS plan coverage](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/flat-rate-pricing-plan.html#route-53-dns-coverage).

## Verify

```sh
curl -I 'http://henningpetersen.de/example?tag=one&tag=two'
curl -I 'https://henningpetersen.de/example?tag=one&tag=two'
curl -I 'https://www.henningpetersen.de/'
```

Expect `301` and `Location: https://henningpetersen.com/...`, retaining the path
and query parameters. These redirects do not forward email.

## Local tests (no AWS calls)

```sh
terraform -chdir=infra/redirect init
terraform -chdir=infra/redirect validate
terraform -chdir=infra/redirect test
node --test tests/redirect.test.mjs
```
