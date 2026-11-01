# Background administration: IAM and deployment

The admin endpoint is opt-in; `pnpm deploy` only deploys the static site. The IAM
policies here are references for review, not live exports. The deployer policy
also relies on the existing upload policy for API Gateway and log discovery.

## Bootstrap in AWS

1. In Frankfurt, create the Lambda execution role
   `henningpetersen-background-admin` with the existing
   [Lambda trust policy](../upload-iam/lambda-trust-policy.json). Attach the reviewed
   [admin runtime policy](lambda-policy.json) as an inline policy. It can manage
   incoming sources, but not the public pointer or published derivatives.
2. Attach a separate reviewed managed policy based on
   [deployer-policy.json](deployer-policy.json) to `henning-deploy`. Keep the
   existing hosting and upload policies attached. Review both with IAM Access
   Analyzer. The deployer does not need source-photo or credential access.
3. Generate a **random**, high-entropy password locally and save it in a password
   manager. Never put it in chat, arguments, Terraform, Git, or logs:

   ```sh
   python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
   ```

   Compute its SHA-256 hash using a hidden prompt:

   ```sh
   python3 -c 'import getpass, hashlib; print(hashlib.sha256(getpass.getpass("Admin password: ").encode()).hexdigest())'
   ```

   Create a **Standard String** in Systems Manager Parameter Store (Frankfurt):
   `/henningpetersen/backgrounds/admin-password-sha256`, containing the lowercase
   64-character hash, not the password. SHA-256 is appropriate here **only for a
   randomly generated password**, not a human-chosen one. Terraform never reads it.
4. Create another **Standard String** in Frankfurt named
   `/henningpetersen/backgrounds/admin-user` containing the chosen username. Use
   1–256 characters, without colons or control characters. A `SecureString` can
   also be read, but may require `kms:Decrypt` and key-policy changes.

   Both parameters are read on every request; changing or removing either revokes
   access immediately. Existing signed image URLs work until expiry. Update the
   manually managed runtime policy before deploying, or authentication fails closed.

## Deploy

1. Build all Lambda packages: `pnpm build:background`, `pnpm build:upload`,
   and `pnpm build:admin`.
2. Add `enable_background_admin = true` to a local `infra/terraform.tfvars`
   (ignored by Git). **Keep it for future plans and applies**: removing it plans
   deletion of the admin resources. Preserve any other existing variables.
3. Run tests, then `AWS_PROFILE=henning-site terraform -chdir=infra plan` and
   review the complete plan before applying. No DNS or mail changes are expected.
4. Visit `https://www.henningpetersen.com/admin`. Check that unauthenticated
   requests return 401 and test edits/removals on a disposable image.

Basic auth is sent on every request over HTTPS. Browsers may retain credentials
until closed; there is no logout button. CloudFront caching is disabled, and the
direct API URL uses the same authentication. Stage throttling is shared, not a
per-user lockout. No CORS is enabled; mutations require an allowed Origin, JSON,
and a custom header. Responses are `no-store` and `noindex`. Do not enable access
logging that could record credentials, image names or signed URLs.

## Behavior and limitations

- Each row is a source: remove every duplicate to exclude the image from future
  rotation. Changes apply after the next successful run. Published URLs remain
  accessible, and an empty pool retains the last background. S3 retains older
  versions according to its lifecycle policy.
- Labels preserve the year and other metadata. Avoid simultaneous edits/deletes:
  version and ETag checks cannot detect every metadata-only race. A concurrent
  processor may publish an older snapshot until the next successful run.
- Each save or removal refreshes the table, discarding other unsaved edits. Pending
  images use five-minute signed URLs for private originals, including embedded
  metadata; don't share those URLs. Refresh expired previews. Some original formats
  may not display. Click a thumbnail to enlarge it; click again or press Escape to
  close it. The list is intended for a small photo pool.
