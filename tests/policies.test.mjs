import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const policy = (path) => JSON.parse(readFileSync(new URL(`../docs/${path}`, import.meta.url), "utf8"));

test("combined deployer reference is the hosting/background union and fits the IAM limit", () => {
  const hosting = policy("deployer-policy.json");
  const background = policy("background-iam/deployer-policy.json");
  const combined = policy("s3-deploy-policy.json");
  assert.deepEqual(combined.Statement, [...hosting.Statement, ...background.Statement]);
  assert.ok(JSON.stringify(combined).length <= 6144);
});

test("direct media-object access is limited to reading/writing the public pointer", () => {
  for (const path of ["background-iam/deployer-policy.json", "s3-deploy-policy.json"]) {
    const statements = policy(path).Statement.filter((statement) => {
      const actions = Array.isArray(statement.Action) ? statement.Action : [statement.Action];
      const resources = Array.isArray(statement.Resource) ? statement.Resource : [statement.Resource];
      return actions.some((action) => /^s3:(GetObject|PutObject|DeleteObject|\*)/.test(action))
        && resources.some((resource) => resource.startsWith("arn:aws:s3:::henningpetersen-com-media/"));
    });
    assert.deepEqual(statements, [{
      Sid: "ManageBackgroundPointer",
      Effect: "Allow",
      Action: ["s3:GetObject", "s3:PutObject"],
      Resource: "arn:aws:s3:::henningpetersen-com-media/background.json",
    }]);
  }
});
