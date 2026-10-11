#!/usr/bin/env node
/**
 * Deployment pipeline:
 *   1. Build the site            (pnpm exec astro build)
 *   2. Upload to S3              (aws s3 sync --delete)
 *   3. Invalidate CloudFront     (aws cloudfront create-invalidation)
 *
 * Credentials come from the AWS CLI profile, e.g. via `aws configure sso`.
 * Bucket / distribution are read from Terraform outputs (infra/), unless
 * BUCKET / DISTRIBUTION_ID env vars are set (useful before `terraform apply`).
 *
 * Usage: pnpm deploy
 */
import { execFileSync } from "node:child_process";

const projectRoot = new URL("..", import.meta.url).pathname;
const infraDir = new URL("./infra", import.meta.url).pathname;

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

function requireEnvOrOutput(name, outputs) {
  const value = process.env[name] ?? outputs?.[name]?.value;
  if (!value) {
    fail(
      `${name} not found. Set it as an env var, or run the Terraform apply first ` +
        `(cd infra && terraform init && terraform apply).`,
    );
  }
  return value;
}

// 1. Build -------------------------------------------------------------------
console.log("▸ Building site…");
run("pnpm", ["exec", "astro", "build"], { cwd: projectRoot });

// 2. Resolve bucket + distribution -------------------------------------------
let outputs = {};
try {
  outputs = JSON.parse(
    run("terraform", ["output", "-json", "-chdir", infraDir], { quiet: true }),
  );
} catch {
  // No Terraform state yet — fall back to env vars only.
}

const bucket = requireEnvOrOutput("BUCKET", outputs);
const distributionId = requireEnvOrOutput("DISTRIBUTION_ID", outputs);

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
