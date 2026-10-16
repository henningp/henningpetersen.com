# Personal Shortcut upload: IAM setup

These are reference files for **manual administrator review**, not a snapshot of
live permissions. Nothing here changes AWS automatically. Do not alter the
existing background processing/Scheduler roles or replace the user's `s3-deploy`
policy. The Shortcut upload endpoint is separate from the public website.

## Resources

All regional resources are in Frankfurt (`eu-central-1`), account `528099663248`.

| Resource | Name |
|----------|------|
| New Lambda execution role | `henningpetersen-background-upload` |
| Lambda / HTTP API | `henningpetersen-background-upload` |
| Lambda log group | `/aws/lambda/henningpetersen-background-upload` |
| SSM Standard String parameter | `/henningpetersen/backgrounds/upload-token-sha256` |
| Additional deployer managed policy | `BackgroundUploadInfrastructurePolicy` |
| Authorized upload prefix | `henningpetersen-com-media/incoming/shortcut/*` |

## 1. Add the execution role

Using an administrative identity in account `528099663248`:

1. Open **IAM → Roles → Create role → Custom trust policy**.
2. Paste [`lambda-trust-policy.json`](lambda-trust-policy.json).
3. Do not attach broad AWS managed policies. Name the **role** exactly
   `henningpetersen-background-upload` and create it.
4. Open that role → **Permissions → Add permissions → Create inline policy → JSON**.
5. Paste [`lambda-policy.json`](lambda-policy.json), review validation, and name
   the inline permission policy `BackgroundUploadRuntime`.

If either object already exists, inspect/back it up before editing; don't delete
or replace unrelated permissions. The role needs only S3 `PutObject` under the
new upload prefix, one SSM parameter read, and writes to its pre-created log
group. It cannot list/read/delete images, change daily selection, or read the
website bucket. An S3 signed form exposes temporary signing information but not
the role's secret key; its policy restricts uploads to one randomly generated key.

## 2. Add a separate deployer policy

1. Open **IAM → Policies → Create policy → JSON**.
2. Paste [`deployer-policy.json`](deployer-policy.json) and review validation.
3. Name it `BackgroundUploadInfrastructurePolicy`.
4. Open **IAM → Users → henning-deploy → Permissions → Add permissions → Attach
   policies directly**, and attach this new policy.

Keep **`s3-deploy` attached and unchanged**. Its combined hosting/background
reference is already close to IAM's 6,144-character managed-policy limit, so don't
append the upload permissions to it. The new runtime policy belongs on the
execution role, not the user.

The additional deployer policy manages just the named Lambda/log group and can
read/pass only the new role to Lambda. It also manages HTTP/WebSocket APIs and
API Gateway tags in Frankfurt: API IDs aren't known before creation, so these
API permissions are region-wide, not confined to this application's API. Tighten
them after creation if this account contains other APIs. Log-group discovery
exposes Frankfurt group metadata. No IAM administration, SSM read/write, S3
object access, or direct function invocation is added to the deployer.

The API stage deliberately has no tags. Tagged `CreateStage` returned an error
naming `apigateway:TagResource`, but IAM rejected that as an invalid action.
Do not add it or grant wildcard API actions as a workaround. Omitting the
optional stage tags avoids this failure; the parent API, Lambda, and logs remain
tagged. The deployer policy uses supported HTTP-verb API Gateway actions only.

Review the permission documents with IAM Access Analyzer; fix errors and review
warnings. A CLI equivalent, from the repository root using an administrator
profile, is:

```sh
aws accessanalyzer validate-policy \
  --profile YOUR_ADMIN_PROFILE \
  --region eu-central-1 \
  --policy-type IDENTITY_POLICY \
  --policy-document file://docs/upload-iam/deployer-policy.json
```

Repeat for `lambda-policy.json`. Trust policy review is separate. No live
Access Analyzer validation is claimed by these reference files.

## 3. Generate your personal token and store its hash

Do this **locally**, not in chat, shell command arguments, Terraform variables,
source files, or Git. One token can be shared by your own devices through iCloud
Shortcuts; it has upload-only authority, not deployment or deletion authority.

Generate a random token in your own Terminal:

```sh
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Save it in your password manager. This prints a real credential in your local
terminal, so don't share its output or screenshots. Then compute its hash using
a hidden prompt:

```sh
python3 -c 'import getpass, hashlib; print(hashlib.sha256(getpass.getpass("Upload token: ").encode()).hexdigest())'
```

In **Systems Manager → Parameter Store**, select Frankfurt and create:

- Name: `/henningpetersen/backgrounds/upload-token-sha256`
- Tier: **Standard**
- Type: **String** (the high-entropy token's hash, not the secret token)
- Value: the **64-character lowercase SHA-256 hash** from the second command

Only the **original token** goes into the private Shortcut. The server keeps
only the hash. No SSM data source reads the hash into Terraform state, and no KMS
permission is needed. The API reads the hash on each request, so rotating it
revokes the old token immediately for new authorizations. Already-issued S3 forms
can still be used until their five-minute expiration (or signing credentials
expire). Forms are reusable until expiry, not one-time tickets.

To revoke without replacing it yet, an administrator can remove the parameter;
the endpoint then fails closed with a generic 503 response. Do not set a weak
human password in place of the generated token. Store a replacement token's hash
and update the synced Shortcut to restore access.

## 4. Deploy and configure the Shortcut

Follow [Shortcut upload setup](../shortcut-upload.md). Build **both** Lambda ZIPs
before planning the full stack. Check the `henning-site` profile identity first;
the deployer does not create this role, parameter, or its own permissions.

The native Shortcut must still be created/tested in Apple's app. No public
sharing link, downloadable Shortcut, app signing, or separate mobile app is used.
