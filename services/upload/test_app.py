import base64
import hashlib
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from app import EXPIRY_SECONDS, MAX_BYTES, MAX_REQUEST_BYTES, handle, handler, signed_upload

# Test-only fake token, never a usable credential.
TOKEN = "test_only_" + "x" * 40
DIGEST = hashlib.sha256(TOKEN.encode()).hexdigest()


def request(body=None, token=TOKEN):
    return {
        "version": "2.0", "rawPath": "/uploads",
        "requestContext": {"http": {"method": "POST"}},
        "headers": {"authorization": f"Bearer {token}", "content-type": "application/json"},
        "body": json.dumps({"content_type": "image/jpeg"}) if body is None else body,
        "isBase64Encoded": False,
    }


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.signs = 0
        self.lookups = 0

    def token_hash(self):
        self.lookups += 1
        return DIGEST

    def sign(self):
        self.signs += 1
        return {"url": "https://bucket.s3.eu-central-1.amazonaws.com/", "fields": {"key": "incoming/shortcut/test.jpg"}}

    def run_request(self, event=None):
        return handle(request() if event is None else event, self.token_hash, self.sign)

    def test_valid_request_returns_a_noncacheable_upload_form(self):
        response = self.run_request()
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["headers"]["Cache-Control"], "no-store")
        body = json.loads(response["body"])
        self.assertEqual(body["expires_in"], 300)
        self.assertEqual(body["max_bytes"], MAX_BYTES)
        self.assertEqual(body["fields"]["key"], "incoming/shortcut/test.jpg")
        self.assertEqual(self.signs, 1)
        self.assertNotIn(TOKEN, response["body"])

    def test_invalid_auth_never_signs(self):
        for token in ("", "short", TOKEN + "different", "x" * 129, "é" * 50):
            with self.subTest(token_length=len(token)):
                response = self.run_request(request(token=token))
                self.assertEqual(response["statusCode"], 401)
                self.assertEqual(response["headers"]["WWW-Authenticate"], "Bearer")
        self.assertEqual(self.signs, 0)

    def test_absent_or_malformed_auth_does_not_query_ssm(self):
        for authorization in (None, "Basic abc", "", f"Bearer {TOKEN}\n"):
            event = request()
            event["headers"]["authorization"] = authorization
            self.assertEqual(self.run_request(event)["statusCode"], 401)
        self.assertEqual(self.lookups, 0)

    def test_header_names_and_auth_scheme_are_case_insensitive(self):
        event = request()
        event["headers"] = {"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json; charset=utf-8"}
        self.assertEqual(self.run_request(event)["statusCode"], 200)

    def test_token_rotation_is_effective_on_the_next_request(self):
        self.assertEqual(self.run_request()["statusCode"], 200)
        self.token_hash = lambda: hashlib.sha256((TOKEN + "new").encode()).hexdigest()
        self.assertEqual(self.run_request()["statusCode"], 401)
        self.assertEqual(self.signs, 1)

    def test_bad_hash_or_missing_parameter_fails_closed_without_leaking_details(self):
        for value in (None, "", "not-a-hash", "A" * 64):
            response = handle(request(), lambda: value, self.sign)
            self.assertEqual(response["statusCode"], 503)
        def unavailable():
            raise RuntimeError("sensitive configuration detail")
        response = handle(request(), unavailable, self.sign)
        self.assertEqual(response["statusCode"], 503)
        self.assertNotIn("sensitive", response["body"])
        self.assertEqual(self.signs, 0)

    def test_invalid_body_is_rejected(self):
        for body in ("", "not json", "[]", "null", '{"content_type":"image/png"}',
                     '{"content_type":"image/jpeg","key":"photos/overwrite.jpg"}',
                     '{"content_type":"image/jpeg","filename":"../overwrite.jpg"}'):
            self.assertEqual(self.run_request(request(body=body))["statusCode"], 400)
        self.assertEqual(self.signs, 0)

    def test_request_body_limit(self):
        self.assertEqual(self.run_request(request(body=" " * (MAX_REQUEST_BYTES + 1)))["statusCode"], 413)
        self.assertEqual(self.run_request(request(body=" " * (MAX_REQUEST_BYTES * 3)))["statusCode"], 413)
        self.assertEqual(self.signs, 0)

    def test_base64_requests_and_invalid_base64(self):
        event = request()
        event["body"] = base64.b64encode(event["body"].encode()).decode()
        event["isBase64Encoded"] = True
        self.assertEqual(self.run_request(event)["statusCode"], 200)
        event["body"] = "not valid base64!"
        self.assertEqual(self.run_request(event)["statusCode"], 400)

    def test_wrong_method_path_or_content_type_never_signs(self):
        event = request()
        event["requestContext"]["http"]["method"] = "GET"
        self.assertEqual(self.run_request(event)["statusCode"], 405)
        event = request()
        event["rawPath"] = "/other"
        self.assertEqual(self.run_request(event)["statusCode"], 405)
        event = request()
        event["headers"]["content-type"] = "multipart/form-data"
        self.assertEqual(self.run_request(event)["statusCode"], 415)
        self.assertEqual(self.signs, 0)

    def test_signer_errors_do_not_expose_credentials(self):
        def failed():
            raise RuntimeError(TOKEN)
        response = handle(request(), self.token_hash, failed)
        self.assertEqual(response["statusCode"], 503)
        self.assertNotIn(TOKEN, response["body"])

    def test_sensitive_details_are_not_logged(self):
        def failed():
            raise RuntimeError("private-token-and-signed-url")
        with self.assertLogs("app", level="ERROR") as logs:
            handle(request(), self.token_hash, failed)
        self.assertNotIn(TOKEN, str(logs.output))
        self.assertNotIn("private-token", str(logs.output))


class SigningTests(unittest.TestCase):
    def test_form_is_fixed_to_jpeg_size_expiry_and_unique_private_key(self):
        class S3:
            def generate_presigned_post(self, **kwargs):
                self.arguments = kwargs
                return {"url": "https://example.invalid", "fields": {"key": kwargs["Key"]}}
        s3 = S3()
        first = signed_upload(s3, "bucket")
        args = s3.arguments
        self.assertRegex(args["Key"], r"^incoming/shortcut/[a-f0-9]{32}\.jpg$")
        self.assertEqual(args["Bucket"], "bucket")
        self.assertEqual(args["ExpiresIn"], EXPIRY_SECONDS)
        self.assertIn(["content-length-range", 1, MAX_BYTES], args["Conditions"])
        self.assertIn({"Content-Type": "image/jpeg"}, args["Conditions"])
        self.assertIn({"success_action_status": "201"}, args["Conditions"])
        self.assertEqual(args["Fields"], {"Content-Type": "image/jpeg", "success_action_status": "201"})
        second = signed_upload(s3, "bucket")
        self.assertNotEqual(first["fields"]["key"], second["fields"]["key"])


try:
    import boto3
    from botocore.config import Config
except ImportError:
    boto3 = None


@unittest.skipIf(boto3 is None, "Install boto3 locally to verify actual SDK policy generation (no AWS calls)")
class SdkTests(unittest.TestCase):
    def test_actual_handler_uses_ssm_sigv4_and_s3_form_signing_without_network_calls(self):
        from botocore.stub import Stubber

        make_client = boto3.client
        clients = {}
        stubs = []
        parameter = "/henningpetersen/backgrounds/upload-token-sha256"
        def client(service, **kwargs):
            result = make_client(
                service, aws_access_key_id="test-only", aws_secret_access_key="test-only",
                aws_session_token="test-session-only", **kwargs,
            )
            clients[service] = result
            if service == "ssm":
                stub = Stubber(result)
                stub.add_response("get_parameter", {"Parameter": {"Value": DIGEST}}, {"Name": parameter})
                stub.activate()
                stubs.append(stub)
            return result
        try:
            with patch.dict(os.environ, {"AWS_REGION": "eu-central-1", "MEDIA_BUCKET": "test-background-bucket", "TOKEN_HASH_PARAMETER": parameter}), patch.object(boto3, "client", client):
                response = handler(request(), None)
            self.assertEqual(response["statusCode"], 200)
            self.assertEqual(clients["ssm"].meta.config.signature_version, "v4")
            self.assertEqual(clients["s3"].meta.config.signature_version, "s3v4")
            body = json.loads(response["body"])
            self.assertEqual(body["expires_in"], EXPIRY_SECONDS)
            self.assertIn("x-amz-security-token", body["fields"])
            for stub in stubs:
                stub.assert_no_pending_responses()
        finally:
            for stub in stubs:
                stub.deactivate()
            for item in clients.values():
                item.close()

    def test_real_sdk_policy_has_exact_key_bucket_content_type_size_and_session_token(self):
        s3 = boto3.client(
            "s3", region_name="eu-central-1", endpoint_url="https://s3.eu-central-1.amazonaws.com",
            aws_access_key_id="test-only", aws_secret_access_key="test-only",
            aws_session_token="test-session-only",
            config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
        )
        result = signed_upload(s3, "test-background-bucket")
        fields = result["fields"]
        policy = json.loads(base64.b64decode(fields["policy"]))
        self.assertEqual(result["url"], "https://test-background-bucket.s3.eu-central-1.amazonaws.com/")
        self.assertIn({"bucket": "test-background-bucket"}, policy["conditions"])
        self.assertIn({"key": fields["key"]}, policy["conditions"])
        self.assertIn(["content-length-range", 1, MAX_BYTES], policy["conditions"])
        self.assertIn({"Content-Type": "image/jpeg"}, policy["conditions"])
        self.assertEqual(fields["x-amz-security-token"], "test-session-only")
        self.assertEqual(fields["x-amz-algorithm"], "AWS4-HMAC-SHA256")
        self.assertEqual(set(fields), {
            "key", "Content-Type", "success_action_status", "policy", "x-amz-algorithm",
            "x-amz-credential", "x-amz-date", "x-amz-security-token", "x-amz-signature",
        })


class PermissionTests(unittest.TestCase):
    def test_apigateway_permissions_use_supported_http_verb_actions(self):
        root = Path(__file__).resolve().parents[2]
        policy = json.loads((root / "docs/upload-iam/deployer-policy.json").read_text())
        allowed = {"apigateway:GET", "apigateway:POST", "apigateway:PUT", "apigateway:PATCH", "apigateway:DELETE"}
        for statement in policy["Statement"]:
            actions = statement["Action"]
            actions = [actions] if isinstance(actions, str) else actions
            self.assertTrue({action for action in actions if action.startswith("apigateway:")} <= allowed)

    def test_runtime_can_only_upload_candidates_read_one_hash_and_write_logs(self):
        root = Path(__file__).resolve().parents[2]
        policy = json.loads((root / "docs/upload-iam/lambda-policy.json").read_text())
        statements = {statement["Sid"]: statement for statement in policy["Statement"]}
        upload = statements["UploadCandidatesOnly"]
        self.assertEqual(upload["Action"], "s3:PutObject")
        self.assertEqual(upload["Resource"], "arn:aws:s3:::henningpetersen-com-media/incoming/shortcut/*")
        token_hash = statements["ReadPersonalUploadTokenHash"]
        self.assertEqual(token_hash["Action"], "ssm:GetParameter")
        self.assertEqual(token_hash["Resource"], "arn:aws:ssm:eu-central-1:528099663248:parameter/henningpetersen/backgrounds/upload-token-sha256")
        self.assertEqual(set(statements), {"UploadCandidatesOnly", "ReadPersonalUploadTokenHash", "WriteUploadLogs"})

    def test_deployer_policy_fits_and_only_passes_the_upload_role_to_lambda(self):
        root = Path(__file__).resolve().parents[2]
        policy = json.loads((root / "docs/upload-iam/deployer-policy.json").read_text())
        self.assertLessEqual(len(json.dumps(policy, separators=(",", ":"))), 6144)
        for statement in policy["Statement"]:
            actions = statement["Action"]
            actions = [actions] if isinstance(actions, str) else actions
            self.assertFalse(any(action.startswith("ssm:") for action in actions))
            iam_actions = [action for action in actions if action.startswith("iam:")]
            self.assertTrue(set(iam_actions) <= {"iam:GetRole", "iam:PassRole"})
            if "iam:PassRole" in actions:
                self.assertEqual(statement["Resource"], "arn:aws:iam::528099663248:role/henningpetersen-background-upload")
                self.assertEqual(statement["Condition"]["StringEquals"]["iam:PassedToService"], "lambda.amazonaws.com")


if __name__ == "__main__":
    unittest.main()
