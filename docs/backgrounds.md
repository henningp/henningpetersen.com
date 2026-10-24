# Daily backgrounds from S3

Background candidates live in a separate private S3 bucket,
`henningpetersen-com-media`, in Frankfurt. No Flickr/API key, Mac job, or
public-page request-time backend is involved. The site bucket and its `sync --delete`
deployment stay unchanged.

## Flow

1. Upload photos manually to `incoming/` (originals stay private).
2. EventBridge Scheduler invokes Lambda daily at **03:00 UTC** (04:00/05:00 in
   Berlin, depending on daylight saving time).
3. Lambda lists the complete incoming inventory, processes new/changed supported
   images, and generates content-hashed JPEGs under `photos/`. It applies EXIF
   orientation, converts embedded color profiles to sRGB, fits the image within
   2560 × 2560 without upscaling, flattens transparency on white, and strips source
   metadata. It skips reprocessing unchanged sources using private `state/` data.
   Optional reviewed EN/DE labels and a capture year are read from private S3 object
   metadata, not EXIF; only those approved caption fields are published.
4. Lambda chooses one image for the UTC calendar day, avoiding the previous
   selection when alternatives exist. It uploads images before publishing the
   small `background.json` pointer. Same-day retries/manual runs keep today's
   image choice unless its source was removed or changed; caption updates can be
   published without changing the image.
5. The existing CloudFront distribution serves `/photos/*` and `/background.json`
   through the same website domain. Its bucket permission excludes originals and
   state. Photos cache for one year; the pointer caches at the CDN for at most
   five minutes and browsers revalidate it.
6. Browsers load the background in both themes, with a theme-aware overlay for
   readability. Visible tabs check every five minutes and when brought into focus.
   Open tabs can therefore take up to roughly ten minutes to converge after a
   change (CDN cache plus polling). No-JS/network failures keep the solid fallback
   or last successfully loaded photo; no visitor identifier or extra localStorage
   entry is used.
7. A discreet caption follows the existing EN/DE language selection. Missing
   translations fall back to the other language, then to year alone; absent
   caption data hides the label. The caption changes only once its image loads.

## Caption rollout

This is backwards-compatible with existing uploads, old `background.json`
documents, and the original Shortcut:

1. Build and deploy the upload signer and background processor with the usual
   reviewed Terraform plan. No new infrastructure or IAM permissions are needed:
   `s3:GetObject` already returns object metadata, and `s3:PutObject` covers storing
   signed metadata. Legacy upload requests still return the original form fields.
2. Build and deploy the website. Existing unlabelled photos simply have no caption.
3. Add the [optional Shortcut caption extension](shortcut-upload.md#optional-extension-preview-and-review-bilingual-captions)
   and manually test it on the iPhone/iPad before re-uploading the library.

The new processing-cache version reprocesses existing sources once to discover
caption metadata. Later runs also detect metadata-only source replacements using
S3 LastModified, even when the image ETag is unchanged. Caption metadata must be
base64-encoded UTF-8 JSON under the private object's `caption` metadata key; the
signing endpoint generates it automatically. Invalid metadata is ignored rather
than blocking the image. Raw GPS coordinates and unrelated metadata are never
copied into the public pointer.

For identical generated images, the processor prefers a source with more
nonempty language labels, then one with a known year. Ties use the lexicographically
first incoming key; labels from different sources are not combined. If you need
to correct conflicting captions, remove/replace the obsolete incoming copy with
an authorized identity. Re-uploading all photos does not delete old originals or
guarantee deduplication when JPEG export settings or pixels have changed.

## First deployment

Prerequisites: Node.js 22.18+ (for TypeScript test execution), pnpm, Python 3.10+
for packaging/tests, Terraform, AWS CLI v2, and the administrator-created roles
and policy from [IAM bootstrap](background-iam/README.md), plus the additional
[upload prerequisites](upload-iam/README.md) for the full stack. The image-processing
package targets **Python 3.13, Linux x86-64** regardless of the build computer's
platform.

**If the Lambda role was created for Flickr, update its inline policy first**
using step 3 of the bootstrap instructions. The new code needs `incoming/*` reads
and bucket listing; it does not need SSM access.

From the repository root:

```sh
pnpm install
pnpm test
pnpm build:background
pnpm build:upload
pnpm build
AWS_PROFILE=henning-site terraform -chdir=infra validate
AWS_PROFILE=henning-site terraform -chdir=infra plan
```

`build:background` downloads a pinned, SHA-256-verified Pillow Linux wheel from
PyPI and assembles `.artifacts/background-sync.zip`; no Docker, global Python
packages, or extra Terraform provider is needed. Rebuild it whenever the Lambda
code changes. Build output is ignored by Git. The requirements file pins the
corresponding native package for local image tests.

Review the full plan: new media resources, logs, Lambda, schedule/group, and an
in-place CloudFront origin/behavior update are expected. **No DNS, mail, site
bucket replacement, or IAM role/policy changes should be needed.** Existing
infrastructure drift may still appear; investigate rather than accepting it
blindly. The media bucket name must be globally available. If changed, update
the corresponding manual IAM policies too.

When approved:

```sh
AWS_PROFILE=henning-site terraform -chdir=infra apply
AWS_PROFILE=henning-site pnpm deploy
```

The first empty run is harmless: the page uses its solid background until you
upload images and the first selection is published. Terraform does not create
or overwrite `background.json`, inventories, or images.

## Uploading photos

[Apple Shortcut upload](shortcut-upload.md) adds personal, token-authenticated
uploads from the iPhone/iPad sharing dialog, synced privately from the Mac via
iCloud. It needs its own [IAM bootstrap](upload-iam/README.md) and endpoint
deployment. Share one photo at a time, or launch the Shortcut directly and use its
photo picker for batches. Multi-photo share-sheet input showed preview/location
mismatches during manual testing; see [supported selection paths](shortcut-upload.md#supported-photo-selection-paths).
The manual alternative below remains available.

Use an administrator or an identity separately authorized to upload media. The
`henning-site` deployer's direct media-object permissions cover only read/write
on `background.json`; they do not allow uploading, reading, or deleting photos.

1. Export selected photos from Apple Photos as **JPEG** (not unmodified HEIC).
   Multi-picture JPEGs (MPO, including some HDR/spatial exports) are supported:
   only the primary still is published, without auxiliary images or metadata.
   PNG, WebP, and single-image TIFF are also supported. Live Photos must be
   exported as still images. HEIC/RAW/video/GIF files are ignored.
2. In the S3 console (Frankfurt), open the media bucket and upload into
   **`incoming/`**, e.g. `incoming/coast.jpg`. Do not enable public access or public
   ACLs. Keep files below **30 MiB** and **40 megapixels** each. Animations,
   multi-page TIFFs, or corrupt supported files fail the run rather than being
   published.
3. Wait until the next daily run, or invoke the function manually using the
   deployer profile. From the repository root:

```sh
AWS_PROFILE=henning-site aws lambda invoke \
  --region eu-central-1 \
  --function-name henningpetersen-background-sync \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  .artifacts/background-result.json
```

Check both the CLI's `FunctionError` field (HTTP 200 alone is not success) and
`.artifacts/background-result.json`. Result statuses are `published`, `unchanged`,
`empty`, or `superseded` (another invocation published first). A new upload joins
the pool immediately on processing but does not
replace an already eligible same-day choice. View
`https://www.henningpetersen.com/background.json` after the short cache expires.
If the initial missing pointer was cached as a 403, CloudFront's default error
cache can briefly delay the first publication too.

No gallery or deletion UI is included yet. Only upload photos you are comfortable
making public: generated copies are public even though originals remain private.

## Manual caption tests

The deployer has permanent `s3:GetObject` / `s3:PutObject` permission on exactly
`background.json`. This allows a one-off caption test without changing the image,
source uploads, or private inventory. It is **not** a persistent per-photo edit:
the next successful processor run restores captions from source metadata (or
removes the test caption if the source has none). Use the labelled upload workflow
for permanent captions.

1. Verify `AWS_PROFILE=henning-site aws sts get-caller-identity`. From the repository
   root, download a backup and note the **ETag** in the command's JSON response:

   ```sh
   AWS_PROFILE=henning-site aws s3api get-object \
     --region eu-central-1 \
     --bucket henningpetersen-com-media --key background.json \
     .artifacts/caption-before.json
   ```

2. Make `.artifacts/caption-test.json` from that backup. Keep `src`, `width`,
   `height`, and `day` unchanged. Set only the approved caption fields and update
   `updated` to the current UTC ISO timestamp. For example:

   ```json
   {"label":{"en":"Snow Mountain","de":"Schneekoppe"},"year":2024}
   ```

   These fields are added to the existing pointer, **not** a replacement document
   on their own. Check that `day` and `src` still identify the intended photo.

3. Write conditionally, replacing `ETAG_FROM_GET_OBJECT` with the response's ETag
   (retain its double quotes inside the shell's single quotes):

   ```sh
   AWS_PROFILE=henning-site aws s3api put-object \
     --region eu-central-1 \
     --bucket henningpetersen-com-media --key background.json \
     --body .artifacts/caption-test.json \
     --content-type application/json \
     --cache-control 'public, max-age=0, s-maxage=300, must-revalidate' \
     --if-match 'ETAG_FROM_GET_OBJECT'
   ```

   A precondition failure means another publisher won: reread and review the
   current pointer instead of retrying without the condition. Do not alter private
   state or grant broader S3 access to work around an access denial.

4. Invalidate `/background.json` using the deployer's existing CloudFront access:

   ```sh
   AWS_PROFILE=henning-site aws cloudfront create-invalidation \
     --distribution-id E2IQ8JIGOJ2KUB --paths /background.json
   ```

   Check the public JSON and reload the website to test both EN/DE labels. Existing
   open tabs may still wait until their next five-minute refresh. To restore the
   backup manually, first read the current ETag and verify the image/day are still
   the intended ones, then use another conditional write; do not blindly overwrite
   a newer daily selection.

## Edits, removals, and failure behavior

- Replacing an incoming object causes reprocessing; content hashes ensure an
  existing public URL never changes its contents. Duplicate generated images
  count as one candidate.
- Delete a candidate from `incoming/` using an authorized identity to remove it
  from future selection on the next successful run. If today's photo was removed,
  another eligible photo replaces it. **An empty pool preserves the last photo**
  as a safety measure; do not use an empty upload folder to disable publication.
- Generated images are deliberately **not automatically deleted**: they may
  still be referenced by browser/CDN caches. Removing a source does not revoke an
  already published URL. Urgent takedown needs an administrator to remove the
  generated objects/update the pointer and invalidate their CloudFront paths;
  copies already cached in browsers cannot be recalled. No automatic photo purge
  or disable switch is included.
- A listing, image-processing, or upload failure leaves the last selection intact.
  Fix/remove a problematic upload and invoke again. Previously uploaded derivatives
  may remain, but are not selected until the run successfully completes. Missing
  generated files are rebuilt from their originals on the next run.
- Publication uses S3 conditional writes (`If-Match` / `If-None-Match`), so
  overlapping invocations cannot overwrite each other's selection. Lambda uses
  the account's unreserved concurrency; no concurrency quota increase is needed.
  Inventory updates are only a processing cache, not the publication lock.
  Scheduler retries delivery
  failures; Lambda's asynchronous invocation handling retries execution errors.
  Same-day publication is idempotent. CloudWatch logs retain 14 days of processing
  logs; no website request logging or analytics is enabled by this feature.
- This implementation has **logs but no email alerts or dead-letter queue**.
  Add notification infrastructure/permissions separately if desired. To inspect
  processing logs as the deployer:

```sh
AWS_PROFILE=henning-site aws logs filter-log-events \
  --region eu-central-1 \
  --log-group-name /aws/lambda/henningpetersen-background-sync \
  --limit 20
```

Current originals and derivatives are retained; noncurrent S3 object versions
expire after 30 days and abandoned multipart uploads after seven days. This is
not a backup of the Photos library. Storage, CloudFront traffic, Lambda, logs,
and Scheduler have usage-based costs; at a handful of images and low traffic they
should be small, but no free-tier eligibility is assumed.

## Tests

`pnpm test` runs frontend behavior and Python orchestration/adapter tests without
AWS access. Image-processing tests run when Pillow is installed; otherwise they
are explicitly skipped. To exercise the actual processing code in an isolated
environment (choose a local Python version supported by the pinned Pillow):

```sh
python3 -m venv .artifacts/background-test-venv
.artifacts/background-test-venv/bin/python -m pip install -r services/background/requirements.txt
.artifacts/background-test-venv/bin/python -m unittest discover -s services/background -p 'test_*.py'
```

After building the Lambda ZIP, Terraform 1.7+ can exercise the infrastructure
configuration using mocked providers:

```sh
terraform -chdir=infra test
```

These tests use isolated test state and fake provider operations, not AWS or the
live Terraform state. They check separate/private storage, the packaged runtime,
daily scheduling, cache routing/TTLs, and CloudFront's restricted object access.
They do not prove that live IAM permissions are sufficient.

The fixture images are generated by tests; no personal photos are committed.
