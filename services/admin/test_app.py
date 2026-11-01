import base64
import hashlib
import io
import json
import unittest
from datetime import datetime, timezone

import app


PASSWORD = "a-secure-random-password"
PASSWORD_HASH = hashlib.sha256(PASSWORD.encode()).hexdigest()
USERNAME = "custom-user"
AUTH = "Basic " + base64.b64encode((USERNAME + ":" + PASSWORD).encode()).decode()
ORIGIN = "https://www.henningpetersen.com"


def event(method, path, body=None, **headers):
    result = {"requestContext": {"http": {"method": method}}, "rawPath": path,
              "headers": {"authorization": AUTH, **headers}}
    if body is not None:
        result["body"] = json.dumps(body)
    return result


class FakeStore:
    def __init__(self):
        self.calls = []

    def list_images(self):
        self.calls.append(("list",))
        return [{"key": "incoming/a.jpg"}]

    def update(self, *args):
        self.calls.append(("update", *args))

    def remove(self, *args):
        self.calls.append(("remove", *args))


class HandleTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()

    def handle(self, request, get_credentials=lambda: (USERNAME, PASSWORD_HASH)):
        return app.handle(request, get_credentials, self.store, {ORIGIN})

    def mutation(self, path, body, **overrides):
        headers = {"origin": ORIGIN, "x-admin-request": "1", "content-type": "application/json"}
        headers.update(overrides)
        return self.handle(event("POST", path, body, **headers))

    def test_authentication_on_all_routes_and_no_store(self):
        for path in ("/admin", "/admin/images", "/admin/labels", "/admin/remove"):
            result = self.handle(event("GET", path, authorization="Basic YmFkOmJhZA=="))
            self.assertEqual(result["statusCode"], 401)
            self.assertIn("Basic", result["headers"]["WWW-Authenticate"])
            self.assertIn("no-store", result["headers"]["Cache-Control"])
            self.assertIn("noindex", result["headers"]["X-Robots-Tag"])
        self.assertEqual(self.store.calls, [])
        self.assertEqual(self.handle(event("GET", "/admin"))["statusCode"], 200)
        self.assertEqual(self.handle(event("GET", "/admin/images"))["statusCode"], 200)

    def test_invalid_auth_and_missing_credentials_fail_closed(self):
        for value in ("", "Bearer abc", "Basic !!!!", "Basic " + base64.b64encode("ä:x".encode()).decode()):
            self.assertEqual(self.handle(event("GET", "/admin", authorization=value))["statusCode"], 401)
        self.assertEqual(self.handle(event("GET", "/admin"), lambda: (USERNAME, "weak"))["statusCode"], 503)
        self.assertEqual(self.handle(event("GET", "/admin"), lambda: 1 / 0)["statusCode"], 503)
        for invalid in ("", "bad:name", "bad\nname", "a" * 257, None):
            self.assertEqual(self.handle(event("GET", "/admin"), lambda: (invalid, PASSWORD_HASH))["statusCode"], 503)

    def test_username_is_configurable_and_rotation_takes_effect(self):
        request = event("GET", "/admin")
        self.assertEqual(self.handle(request)["statusCode"], 200)
        self.assertEqual(self.handle(request, lambda: ("other-user", PASSWORD_HASH))["statusCode"], 401)
        old_admin = "Basic " + base64.b64encode(("admin:" + PASSWORD).encode()).decode()
        self.assertEqual(self.handle(event("GET", "/admin", authorization=old_admin))["statusCode"], 401)
        unicode_user = "Björk"
        unicode_auth = "Basic " + base64.b64encode((unicode_user + ":" + PASSWORD).encode()).decode()
        self.assertEqual(self.handle(event("GET", "/admin", authorization=unicode_auth),
                                     lambda: (unicode_user, PASSWORD_HASH))["statusCode"], 200)

    def test_csrf_origin_header_and_content_type(self):
        body = {"key": "incoming/a.jpg", "version": "v1"}
        for override in ({"origin": "https://evil.example"}, {"origin": "null"},
                         {"x-admin-request": ""}, {"content-type": "text/plain"}):
            self.assertEqual(self.mutation("/admin/remove", body, **override)["statusCode"], 403)
        self.assertEqual(self.store.calls, [])

    def test_valid_mutations_and_reject_invalid_fields(self):
        body = {"key": "incoming/a.jpg", "version": "v1", "labels": {"en": "Coast", "de": "Küste"}}
        self.assertEqual(self.mutation("/admin/labels", body)["statusCode"], 200)
        self.assertEqual(self.store.calls[-1], ("update", body["key"], body["version"], body["labels"]))
        for change in ({"key": "photos/a.jpg"}, {"key": "incoming/a.txt"}, {"version": ""},
                       {"labels": {"en": "x\ny", "de": ""}}, {"labels": {"en": "x"}},
                       {"labels": {"en": "a" * 121, "de": ""}}, {"extra": "x"}):
            self.assertEqual(self.mutation("/admin/labels", {**body, **change})["statusCode"], 400)
        self.assertEqual(self.mutation("/admin/remove", {"key": body["key"], "version": "v1"})["statusCode"], 200)
        self.assertEqual(self.store.calls[-1], ("remove", "incoming/a.jpg", "v1"))

    def test_conflict_and_unexpected_exception_do_not_leak(self):
        def fail(*args):
            raise app.Conflict()
        self.store.remove = fail
        result = self.mutation("/admin/remove", {"key": "incoming/a.jpg", "version": "v1"})
        self.assertEqual(result["statusCode"], 409)


class FakeS3:
    def __init__(self):
        self.head = {"VersionId": "v1", "ETag": '"etag"', "ContentLength": 10,
                     "LastModified": datetime(2026, 1, 1, tzinfo=timezone.utc),
                     "ContentType": "image/jpeg", "Metadata": {"other": "kept", "caption": base64.b64encode(json.dumps({"label": {"en": "Old"}, "year": 2024}).encode()).decode()}}
        self.calls = []
        self.inventory = {}

    def head_object(self, **kwargs):
        self.calls.append(("head", kwargs))
        return self.head

    def copy_object(self, **kwargs):
        self.calls.append(("copy", kwargs))

    def delete_object(self, **kwargs):
        self.calls.append(("delete", kwargs))

    def get_object(self, **kwargs):
        return {"Body": io.BytesIO(json.dumps(self.inventory).encode())}

    def get_paginator(self, name):
        self.assert_name = name
        return self

    def paginate(self, **kwargs):
        return [{"Contents": [{"Key": "incoming/a.jpg"}, {"Key": "incoming/ignore.txt"}]}]

    def generate_presigned_url(self, *args, **kwargs):
        self.calls.append(("sign", kwargs))
        return "https://s3.amazonaws.com/signed"


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.s3 = FakeS3()
        self.store = app.Store(self.s3, "media")

    def test_updates_preserve_year_metadata_and_conditional_source(self):
        self.store.update("incoming/a.jpg", "v1", {"en": " New ", "de": "Küste"})
        args = self.s3.calls[-1][1]
        self.assertEqual(args["CopySourceIfMatch"], '"etag"')
        self.assertEqual(args["ContentType"], "image/jpeg")
        self.assertEqual(args["Metadata"]["other"], "kept")
        self.assertEqual(app.caption(args["Metadata"]), {"label": {"en": "New", "de": "Küste"}, "year": 2024})

    def test_delete_is_conditional_and_rejects_stale_version(self):
        with self.assertRaises(app.Conflict):
            self.store.remove("incoming/a.jpg", "stale")
        self.assertNotEqual(self.s3.calls[-1][0], "delete")
        self.store.remove("incoming/a.jpg", "v1")
        self.assertEqual(self.s3.calls[-1][1]["IfMatch"], '"etag"')

    def test_list_signed_pending_and_processed_preview(self):
        result = self.store.list_images()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["image"], "https://s3.amazonaws.com/signed")
        self.assertEqual(result[0]["year"], 2024)
        self.assertEqual(self.s3.calls[-1][1]["ExpiresIn"], 300)
        key = "photos/" + "a" * 64 + ".jpg"
        self.s3.inventory = {"sources": {"incoming/a.jpg": {"key": key, "etag": '"etag"', "size": 10,
                              "modified": str(self.s3.head["LastModified"])}}}
        self.assertEqual(self.store.list_images()[0]["image"], "/" + key)

    def test_caption_invalid_and_preserve_year_with_empty_labels(self):
        self.assertEqual(app.caption({"caption": "!"}), {})
        self.store.update("incoming/a.jpg", "v1", {"en": "", "de": ""})
        self.assertEqual(app.caption(self.s3.calls[-1][1]["Metadata"]), {"year": 2024})


if __name__ == "__main__":
    unittest.main()
