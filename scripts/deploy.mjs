#!/usr/bin/env node
/**
 * Deployment pipeline:
 *   1. Build the site        (pnpm exec astro build)
 *   2. Upload to S3          (aws s3 sync --delete, versioned)
 *   3. Invalidate CloudFront (aws cloudfront create-invalidation)
 *
 * Credentials use the standard AWS CLI credential chain. Select the site's
 * named profile with AWS_PROFILE=henning-site (see docs/deployer-access.md).
 * Bucket + distribution are read from the Terraform outputs in infra/
 * (keys `bucket_name` / `distribution_id`), unless overridden by env vars
 * BUCKET / DISTRIBUTION_ID — handy before the first `terraform apply`.
 *
 * Usage: AWS_PROFILE=henning-site pnpm deploy
 */
import { execFileSync } from "node:child_process";
import { join } from "node:path";

const projectRoot = new URL("..", import.meta.url).pathname;
const infraDir = join(projectRoot, "infra");

function run(cmd, args, opts = {}) {
  const out = execFileSync(cmd, args, {
    encoding: "utf8",
    stdio: opts.quiet ? ["pipe", "pipe", "inherit"] : "inherit",
     ...opts,
  });
  return out?.trim() ?? "";
}

function fail(msg) {
  console.error(`\n✗ ${msg}`);
  process.exit(1);
}

// 1. Build -------------------------------------------------------------------
console.log("▸ Building site…");
run("pnpm", ["exec", "astro", "build"], { cwd: projectRoot });

// 2. Resolve bucket + distribution -------------------------------------------
// Env vars win; otherwise read the Terraform outputs (bucket_name /
// distribution_id). If there is no state yet, fall back to nothing and let the
// per-value check below explain what to set.
let outputs = {};
try {
  outputs = JSON.parse(
    run("terraform", ["output", "-json"], { cwd: infraDir, quiet: true }),
  );
} catch {
  outputs = {};
}

const value = (envName, outputKey) =>
  process.env[envName] ?? outputs[outputKey]?.value;

const bucket = value("BUCKET", "bucket_name");
const distributionId = value("DISTRIBUTION_ID", "distribution_id");

if (!bucket) {
  fail(
    "BUCKET not found. Set it as an env var, or run the Terraform apply first " +
      "(cd infra && terraform init && terraform apply).",
  );
}
if (!distributionId) {
  fail(
    "DISTRIBUTION_ID not found. Set it as an env var, or run the Terraform apply first " +
      "(cd infra && terraform init && terraform apply).",
  );
}

console.log(
  `\n▸ Uploading dist/ → s3://${bucket} (distribution ${distributionId})`,
);

// 3. Upload ------------------------------------------------------------------
run("aws", ["s3", "sync", "--delete", "--only-show-errors", "dist", `s3://${bucket}`], {
  cwd: projectRoot,
});

// 4. Invalidate CloudFront cache ---------------------------------------------
console.log("▸ Invalidating CloudFront cache (/*)…");
run("aws", [
  "cloudfront",
  "create-invalidation",
  "--distribution-id",
  distributionId,
  "--paths",
  "/*",
]);

console.log("\n✓ Deployed. The fresh content should be live within ~1–2 minutes.");
