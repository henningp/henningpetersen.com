import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const policy = (path) => JSON.parse(readFileSync(new URL(`../docs/${path}`, import.meta.url), "utf8"));

// Expand statements to individual grants so merging identical action sets across
// resources is checked for exact equivalence, including every condition.
const grants = (statements) => [...new Set(statements.flatMap((statement) =>
  [statement.Action].flat().flatMap((action) => [statement.Resource].flat().map((resource) =>
    JSON.stringify([statement.Effect, action, resource, statement.Condition ?? null])))))].sort();

test("combined deployer reference is exactly the hosting/background/redirect union and fits the IAM limit", () => {
  const hosting = policy("deployer-policy.json");
  const background = policy("background-iam/deployer-policy.json");
  const redirect = policy("redirect-iam/deployer-policy.json");
  const combined = policy("s3-deploy-policy.json");
  assert.deepEqual(grants(combined.Statement), grants([...hosting.Statement, ...background.Statement, ...redirect.Statement]));
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
    assert.deepEqual(statements.map(({ Sid, ...statement }) => statement), [{
      Effect: "Allow",
      Action: ["s3:GetObject", "s3:PutObject"],
      Resource: "arn:aws:s3:::henningpetersen-com-media/background.json",
    }]);
  }
});

test("redirect permissions are additive and contain no IAM, registrar, storage, or pricing-plan administration", () => {
  const redirect = policy("redirect-iam/deployer-policy.json");
  assert.ok(JSON.stringify(redirect).length <= 6144);
  for (const statement of redirect.Statement) {
    assert.equal(statement.Effect, "Allow");
    const actions = Array.isArray(statement.Action) ? statement.Action : [statement.Action];
    for (const action of actions) {
      assert.match(action, /^(route53|cloudfront):[A-Za-z]+$/);
      assert.notEqual(action, "route53:DeleteHostedZone");
    }
  }
  assert.deepEqual(redirect.Statement.filter((statement) => statement.Resource === "*").map((statement) => statement.Sid),
    ["BootstrapRedirectZone", "CreateRedirectFunction"]);
});

test("redirect DNS writes are limited to .de web/validation names and record types", () => {
  const redirect = policy("redirect-iam/deployer-policy.json");
  const writes = redirect.Statement.filter((statement) =>
    [statement.Action].flat().includes("route53:ChangeResourceRecordSets"));
  assert.equal(writes.length, 1);
  assert.deepEqual(writes[0].Condition, {
    "ForAllValues:StringLike": {
      "route53:ChangeResourceRecordSetsNormalizedRecordNames": [
        "henningpetersen.de", "www.henningpetersen.de", "_*.henningpetersen.de",
      ],
    },
    "ForAllValues:StringEquals": {
      "route53:ChangeResourceRecordSetsRecordTypes": ["A", "AAAA", "CNAME"],
    },
    Null: {
      "route53:ChangeResourceRecordSetsNormalizedRecordNames": "false",
      "route53:ChangeResourceRecordSetsRecordTypes": "false",
    },
  });
});

test("redirect function management targets only the named function", () => {
  const redirect = policy("redirect-iam/deployer-policy.json");
  const functions = redirect.Statement.find((statement) => statement.Sid === "ManageRedirectFunction");
  assert.equal(functions.Resource,
    "arn:aws:cloudfront::528099663248:function/henningpetersen-de-redirect");
  assert.ok(!functions.Action.includes("cloudfront:CreateFunction"));
  assert.ok(functions.Action.includes("cloudfront:PublishFunction"));
  assert.deepEqual(redirect.Statement.find((statement) => statement.Sid === "CreateRedirectFunction"), {
    Sid: "CreateRedirectFunction",
    Effect: "Allow",
    Action: "cloudfront:CreateFunction",
    Resource: "*",
  });
});
