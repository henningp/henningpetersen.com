# Personal photo upload with Apple Shortcuts

Create one private Shortcut on the Mac and sync it to your own iPhone/iPad with
iCloud. No publishing, signed `.shortcut` download, AWS keys on devices, gallery,
or deletion interface is needed. The Shortcut contains a **personal upload token**;
don't export/share the configured Shortcut with others.

## How it works

```text
Shortcut ── HTTPS + bearer token ──▶ API Gateway → signing Lambda
         ◀── five-minute S3 form ──
Shortcut ── multipart JPEG upload ─▶ S3 incoming/shortcut/<random-id>.jpg
                                      ↓ next 03:00 UTC processing run
                                  public background pool
```

The signing endpoint is `POST /uploads`. The original JSON request remains valid:

```json
{"content_type":"image/jpeg"}
```

Caption-aware clients may additionally send optional `label` and `year` fields:

```json
{"content_type":"image/jpeg","label":{"en":"Lake Constance","de":"Bodensee"},"year":2012}
```

Only `en` and `de` labels are accepted. Each is single-line text of at most 120
Unicode characters; surrounding whitespace is trimmed and blank labels omitted.
Either language may be missing. `year`, if supplied, must be a JSON integer from
1000 to 9999; omit it when the capture date is unknown. No other request fields
are accepted. The JSON request limit is 4 KiB.

It returns `url`, `fields`, `expires_in`, and `max_bytes`. The second request is
**POST multipart/form-data**, not PUT or JSON. Using S3's signed form policy lets
S3 enforce the **1 byte–30 MiB** range without relying on Shortcuts' file-size
formatting. It also requires the exact private key, `image/jpeg` form field, and
success status `201`. Image bytes never pass through API Gateway or Lambda.

Requests containing `label` or `year` also receive an `x-amz-meta-caption` form
field—even if the caption is empty. This is an opaque, signed, ASCII-safe encoding
of the approved labels/year. Copy it verbatim into the S3 form; do not decode,
rebuild, translate, or edit it. S3 rejects missing or changed signed metadata.
Legacy requests receive exactly the original form fields, with no metadata field.
The metadata is stored privately on the uploaded object, not embedded in the JPEG.

An upload is queued, **not immediately processed or published**. The existing
daily job and same-day selection behavior are unchanged. MIME declarations are
not image validation: the existing processing Lambda still decodes and validates
uploads before publication. The signer has no access to originals, published
photos, deletion, or background selection.

## Deploy the endpoint

First complete [upload IAM setup](upload-iam/README.md): a new execution role,
an additional managed policy on `henning-deploy`, and the token-hash parameter.
Keep the existing `s3-deploy` and background execution roles unchanged.

From the repository root:

```sh
pnpm build:background
pnpm build:upload
pnpm test
terraform -chdir=infra validate
terraform -chdir=infra test
AWS_PROFILE=henning-site aws sts get-caller-identity
AWS_PROFILE=henning-site terraform -chdir=infra plan
```

Review the full plan. Expected new resources: one log group, one signing Lambda,
one Lambda invocation permission, and the HTTP API/integration/route/stage. No
DNS, CloudFront, public page, existing bucket/policy, or daily schedule changes
are needed for uploads. The token value and hash must not appear in the plan.

When approved:

```sh
AWS_PROFILE=henning-site terraform -chdir=infra apply
terraform -chdir=infra output -raw background_upload_url
```

The output is the HTTPS URL to put in the Shortcut. It is configuration, not a
secret. No static website deployment is needed for this feature.

API Gateway allows approximately two authorization requests per second, with a
burst of five. Throttling is best-effort, not an absolute spending cap. The route
checks a bearer token inside Lambda; it does not use an API Gateway API key or
Cognito login. API access logging is not enabled. The Lambda logs only generic
configuration/signing errors, not tokens, requests, forms, URLs, or photos. Logs
retain 14 days; this feature does not add visitor logging to the public site.

## Build the private Shortcut on your Mac

Open Apple's **Shortcuts** app and create **Add website backgrounds**. Action
labels vary with macOS/iOS version and language; names below use English.

### A. Configuration and input

1. Add a **Text** action with the endpoint URL. **Set Variable** → `Upload Endpoint`.
2. Add another **Text** action containing your original token (not its SHA-256
   hash), without spaces or line breaks. **Set Variable** → `Upload Token`.
3. Add **If → Shortcut Input has any value**. In that branch, run **Get Images
   from Input** explicitly on `Shortcut Input`, then **Set Variable → Photos**
   to the extracted Images. Normalizing shared input here is necessary: using
   the raw share input can leave the loop with zero photos. In **Otherwise**, use
   **Select Photos**, with **Select Multiple** enabled, then explicitly set
   `Photos` to the selected photos. Continue after **End If**.
   If Photos access is unavailable in the Mac picker, test from a Finder Quick
   Action using exported images; the iPhone/iPad share-sheet path is the primary
   workflow and does not require a separate export.
4. Set a **Number** `0` as variable `Uploaded Count`.
5. Add **Repeat with Each** item in `Photos`. All of B–D below go inside this loop.

The action list is a recipe, not an automatically installed Shortcut. No native
Share Extension is created. On the Mac you can enable **Use as Quick Action**
(Finder/Services) in Details, depending on your preferred input workflow.

### B. Convert the repeat item to JPEG

1. Use **Get Images from Input** on `Repeat Item` to obtain the still photo.
2. **Convert Image** → convert the image from step 1 to **JPEG**. Expand its options:
   turn **Preserve Metadata off**, and choose a good quality setting (about 85%
   if a numeric value is available).
3. **Set Variable** → `JPEG` to the converted output.

Resizing is intentionally left to the existing processing Lambda to keep the
Shortcut simple. Uploads still have a 30 MiB limit, and processing rejects images
above 40 megapixels; high-resolution originals may need resizing before upload.
Live Photos should become their still image, not a video; verify this during the
device test below. The Lambda independently normalizes images and strips metadata
before they become public.

### C. Request an upload form

Add **Get Contents of URL**:

- URL: variable `Upload Endpoint`
- Method: **POST**
- Header `Authorization`: `Bearer ` followed by variable `Upload Token`
- Header `Content-Type`: `application/json`
- Request Body: **JSON**
- JSON field `content_type` (Text): `image/jpeg`

The space after `Bearer` is required. **Set Variable** on the output →
`Authorization Response`. Use **Get Dictionary Value** to read:

- `url` → variable `Upload URL`
- `fields` → variable `Form Fields`

If either value is missing, show an error alert including `Uploaded Count` and
stop the Shortcut. Do not show or log the complete authorization response; it
contains signed credentials for the five-minute upload.

### D. Upload directly to S3

First add **Get Dictionary Value** actions for each of the nine Text fields in
the table below, always reading from `Form Fields`. Name their Magic Variables
so you can distinguish them. These extraction actions must execute **before**
the upload request.

Then add a second **Get Contents of URL**:

- URL: `Upload URL`
- Method: **POST**
- Request Body: **Form**
- **Do not** manually add an HTTP `Content-Type` header: Shortcuts must generate
  the multipart boundary. The `Content-Type` *form field* below is different.

Add these form rows in this order, using the already-extracted Magic Variables
for the Text values. Don't type the literal variable names, and don't hard-code
signed values—they change on every upload.

| Form key (exact spelling/case) | Type | Value |
|-------------------------------|------|-------|
| `key` | Text | `Form Fields` → `key` |
| `Content-Type` | Text | `Form Fields` → `Content-Type` |
| `success_action_status` | Text | `Form Fields` → `success_action_status` |
| `policy` | Text | `Form Fields` → `policy` |
| `x-amz-algorithm` | Text | `Form Fields` → `x-amz-algorithm` |
| `x-amz-credential` | Text | `Form Fields` → `x-amz-credential` |
| `x-amz-date` | Text | `Form Fields` → `x-amz-date` |
| `x-amz-security-token` | Text | `Form Fields` → `x-amz-security-token` |
| `x-amz-signature` | Text | `Form Fields` → `x-amz-signature` |
| `file` | **File** | variable `JPEG` |

**The `file` row must be last, with type File—not Text.** Do not base64-encode the
photo or place it in a JSON body. Get a fresh form for each image and upload it
immediately, not after authorizing a whole batch.

Use **Get Text from Input** on the S3 result. A successful upload returns XML
containing `<PostResponse`. If that text is absent, show an error with
`Uploaded Count` and stop. Only after success, calculate `Uploaded Count + 1` and
**Set Variable** → `Uploaded Count`. Add **Wait → 1 second** before the next loop
iteration, so fast uploads don't exhaust the endpoint's request throttle.

After **End Repeat**, show a notification:

> Uploaded [Uploaded Count] photos. They will join the next daily processing run.

Native network errors can stop Get Contents of URL before your error branch.
In that case no final success summary should run. Photos uploaded before the
failure remain in S3. Retry the missing photos; retrying the entire batch can
create duplicate originals (the processor deduplicates identical derivatives).
This first version does not promise automatic continue-on-error batch retries.

### Optional extension: preview and review bilingual captions

Deploy the caption-capable Lambdas and website **before changing your working
Shortcut**; see [the rollout sequence](backgrounds.md#caption-rollout). The original
recipe above continues to work unchanged. These additions remain inside the
existing **Repeat with Each** loop, so a batch is reviewed one image at a time.

#### Before B: read details, preview, and edit

1. Initialize `Suggested Location` and `Capture Year` to empty Text **on every
   iteration**, so a photo cannot inherit the previous photo's metadata.
2. **Get Details of Images → Location**, explicitly from the original `Repeat
   Item`, not the converted `JPEG`. If Location has a value, use **Get Details of
   Locations → City** as the suggestion; if City is empty, try **Name**. Set
   `Suggested Location` to that text. A lookup may need network access; its result
   is only a suggestion, not necessarily the landmark's name. Never use **Get
   Current Location** as a fallback.
3. **Get Details of Images → Date Taken**, again from the original `Repeat Item`.
   If it has a value, use **Format Date → Custom → `yyyy`**, then **Get Numbers
   from Input → Get Item from List → First Item** to obtain a Number and set
   `Capture Year` to it. Use Date Taken, not the file's creation date or today's
   date. Leave missing dates blank; optionally add an edit prompt for the year.
4. **Quick Look** the original `Repeat Item`. Dismiss the preview to continue.
   Native Shortcuts does not provide a combined image-and-text-edit form here:
   preview and editing are sequential.
5. **Ask for Input → Text**, prompt `English location — photo [Repeat Index]`
   (optionally include `Capture Year`), **Default Answer** `Suggested Location`.
   Save as `Label EN`. Leave it blank if you want no location label.
6. **Ask for Input → Text**, prompt `German location — photo [Repeat Index]`,
   **Default Answer** `Label EN`. Save as `Label DE`. Most proper names can simply
   be confirmed unchanged. There is no automatic translation service.

Then run B's normal JPEG conversion with **Preserve Metadata off**. Metadata only
supplies defaults locally; only approved labels/year are sent separately. Photos'
sharing options/permissions can remove location before Shortcuts receives it;
in that case you can still type the label. Verify Location and Date Taken on the
actual share-sheet input rather than assuming every photo has them.

#### Extend C's JSON body and D's form

- In C, retain `content_type` and add a **Dictionary** JSON field `label`, with
  nested **Text** fields `en` → `Label EN` and `de` → `Label DE`. Always include
  this dictionary, even when both strings are blank.
- When `Capture Year` has a value, add JSON field `year` with type **Number** and
  value `Capture Year`. Otherwise omit the key entirely—not empty Text or `null`.
  For editors that cannot conditionally omit JSON fields, put **Get Contents of
  URL** in an **If Capture Year has any value / Otherwise** pair: both branches
  send `content_type` and the nested `label`, but only the first adds `year`.
  In each branch, set `Authorization Response` to that request's output, then
  continue with C's existing response extraction after **End If**.
- In D, extract a **tenth Text value**, `x-amz-meta-caption`, from `Form Fields`
  before the upload request. Stop with an error if it is absent: this workflow
  requires the updated endpoint.
- Add form row **`x-amz-meta-caption` | Text | extracted value** before `file`.
  Keep all nine original fields and keep **`file` last, type File**. Do not try to
  create the metadata value yourself. Even an entirely empty caption receives
  this field because the signing request explicitly includes `label`.
- Obtain the signed form **after** preview/editing, as in this sequence, so the
  five-minute expiry does not run down while you review captions.

The website uses its existing EN/DE selection. It falls back to the other label
when a translation is missing, then to year alone, and hides an empty caption.
Captions are plain text, not HTML. Labelled re-uploads of identical processed
images take precedence over old unlabelled copies without increasing their
selection probability. Existing originals are not automatically deleted.

## Sync privately to iPhone/iPad

1. Enable **Shortcuts in iCloud** on the Mac and each iPhone/iPad, using your own
   Apple Account. Wait for **Add website backgrounds** to appear in Shortcuts.
2. On the iPhone/iPad, open that Shortcut's **Details** and enable **Show in Share
   Sheet**, accepting **Images**. Set no-input behavior to the photo picker if
   offered. iOS/iPadOS options may not all be exposed in the Mac editor.
3. In Photos, select an image → **Share → Add website backgrounds**. Use
   **Edit Actions** to enable/favorite it if necessary.
4. Approve network access to the API's `execute-api.eu-central-1.amazonaws.com`
   host and the S3 bucket's `s3.eu-central-1.amazonaws.com` host when prompted.
   Approve access to selected photos as requested by the picker/workflow.

No publishing or developer account is required. Keep the configured Shortcut and
its token private; anyone with a copy can upload until the token is revoked.

## Verification and limitations

Automated tests cover authentication, malformed requests, revocation, scoped
presigned form parameters, actual SDK policy generation when boto3 is installed,
and mocked Terraform routing/permissions. They cannot exercise Apple's native
Shortcuts actions; **Mac/iPhone/iPad testing remains a manual acceptance step**.

After deployment, test:

- An unauthenticated request: `401`, no signed upload authorization.
- One landscape JPEG, one portrait/HEIC photo, a Live Photo, and a multi-selection
  from the iPhone/iPad share sheet. Check orientation and still-image conversion.
- Confirm the form's binary File row works, without base64/text conversion, and
  that a successful S3 response is actually exposed as XML by your OS version.
- Check objects under `incoming/shortcut/` as an administrator; originals remain
  private, and the public site still shows today's existing selection.
- Bad token: `401`; unavailable/invalid hash: `503`; non-JPEG request: `400`;
  expired/tampered S3 form or file above 30 MiB: rejected by S3.
- Interrupt a batch; verify there is no false whole-batch success notification.
- After the daily job, verify the processed images join the eligible pool. No
  upload completion callback or immediate processor invocation is implemented.
- With captions: test a photo with known location/date, one without either, and a
  two-photo batch. Check that defaults reset, preview and edit refer to the current
  photo, both prompts are editable, accented names survive, and Preserve Metadata
  remains off. Check both EN/DE labels on the site after processing. A labelled
  re-upload of today's image should update its caption without changing its image.
  Cancel review and verify there is no false success notification.

To run SDK-only tests locally without contacting AWS, install `boto3` in your
isolated test environment and run:

```sh
.artifacts/background-test-venv/bin/python -m pip install boto3
.artifacts/background-test-venv/bin/python -m unittest discover -s services/upload -p 'test_*.py'
```

There is no upload UI, delete endpoint, gallery, S3 event trigger, or CORS/browser
support in this version. Disabling CORS is not an authentication boundary.
