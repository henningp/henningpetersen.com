"""Password-protected administration of private incoming background photos."""

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import unicodedata
from pathlib import Path, PurePosixPath

LOGGER = logging.getLogger(__name__)
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
PHOTO_KEY = re.compile(r"photos/[a-f0-9]{64}\.jpg\Z")
HASH = re.compile(r"[a-f0-9]{64}\Z")
MAX_BODY = 8192
PAGE = Path(__file__).with_name("index.html")


def response(status, body, content_type="application/json; charset=utf-8"):
    headers = {
        "Content-Type": content_type,
        "Cache-Control": "no-store, private",
        "X-Robots-Tag": "noindex, nofollow, noarchive",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' https://*.amazonaws.com; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
    }
    if status == 401:
        headers["WWW-Authenticate"] = 'Basic realm="Background admin", charset="UTF-8"'
    return {"statusCode": status, "headers": headers,
            "body": body if isinstance(body, str) else json.dumps(body)}


def caption(metadata):
    try:
        raw = metadata.get("caption", "")
        if not isinstance(raw, str) or len(raw) > 2000:
            return {}
        value = json.loads(base64.b64decode(raw, validate=True))
        if not isinstance(value, dict):
            return {}
        result = {}
        labels = value.get("label", {})
        if isinstance(labels, dict):
            clean = {lang: text.strip() for lang, text in labels.items()
                     if lang in ("en", "de") and valid_label(text) and text.strip()}
            if clean:
                result["label"] = clean
        year = value.get("year")
        if type(year) is int and 1000 <= year <= 9999:
            result["year"] = year
        return result
    except (ValueError, UnicodeError, RecursionError):
        return {}


def valid_label(text):
    return (isinstance(text, str) and len(text) <= 120
            and not any(unicodedata.category(char) in {"Cc", "Cs"} for char in text))


def valid_key(key):
    return (isinstance(key, str) and key.startswith("incoming/")
            and len(key.encode("utf-8")) <= 1024
            and PurePosixPath(key).suffix.lower() in EXTENSIONS)


def authorized(header, expected_username, expected_hash):
    if (not isinstance(expected_username, str) or not expected_username
            or len(expected_username) > 256 or ":" in expected_username
            or any(unicodedata.category(char) in {"Cc", "Cs"} for char in expected_username)
            or not isinstance(expected_hash, str) or not HASH.fullmatch(expected_hash)):
        raise ValueError("Invalid credential configuration")
    try:
        scheme, token = header.split(" ", 1)
        decoded = base64.b64decode(token, validate=True).decode("utf-8")
        username, password = decoded.split(":", 1)
        digest = hashlib.sha256(password.encode()).hexdigest()
        return (scheme.lower() == "basic" and hmac.compare_digest(username.encode(), expected_username.encode())
                and hmac.compare_digest(digest, expected_hash))
    except (ValueError, UnicodeError, AttributeError, TypeError):
        return False


class Store:
    def __init__(self, s3, bucket):
        self.s3 = s3
        self.bucket = bucket

    def head(self, key):
        return self.s3.head_object(Bucket=self.bucket, Key=key)

    def list_images(self):
        try:
            result = self.s3.get_object(Bucket=self.bucket, Key="state/inventory.json")
            with result["Body"] as body:
                state = json.load(body)
            sources = state.get("sources", {}) if isinstance(state, dict) else {}
            if not isinstance(sources, dict):
                sources = {}
        except Exception as error:
            if getattr(error, "response", {}).get("Error", {}).get("Code") not in {"NoSuchKey", "404", "NotFound"}:
                raise
            sources = {}
        images = []
        pages = self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix="incoming/")
        for page in pages:
            for item in page.get("Contents", []):
                key = item["Key"]
                if not valid_key(key):
                    continue
                head = self.head(key)
                record = sources.get(key, {})
                if not isinstance(record, dict):
                    record = {}
                photo = record.get("key", "")
                if (isinstance(photo, str) and PHOTO_KEY.fullmatch(photo)
                        and record.get("etag") == head.get("ETag")
                        and record.get("size") == head.get("ContentLength")
                        and record.get("modified") == str(head.get("LastModified", ""))):
                    image = "/" + photo
                else:
                    # Pending originals remain private; the short-lived URL is issued only after authentication.
                    image = self.s3.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=300)
                images.append({"key": key, "version": head.get("VersionId", ""),
                               "size": head["ContentLength"], "modified": head["LastModified"].isoformat(),
                               "image": image, **caption(head.get("Metadata", {}))})
        return images

    def checked_head(self, key, version):
        head = self.head(key)
        if not version or head.get("VersionId") != version:
            raise Conflict()
        return head

    def update(self, key, version, labels):
        head = self.checked_head(key, version)
        value = caption(head.get("Metadata", {}))
        clean = {lang: text.strip() for lang, text in labels.items() if text.strip()}
        value.pop("label", None)
        if clean:
            value["label"] = clean
        metadata = dict(head.get("Metadata", {}))
        metadata["caption"] = base64.b64encode(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()).decode("ascii")
        # REPLACE requires explicitly preserving the existing HTTP metadata.
        args = {field: head[field] for field in ("CacheControl", "ContentDisposition", "ContentEncoding", "ContentLanguage", "ContentType", "Expires") if field in head}
        self.s3.copy_object(Bucket=self.bucket, Key=key, CopySource={"Bucket": self.bucket, "Key": key},
                            CopySourceIfMatch=head["ETag"], MetadataDirective="REPLACE", Metadata=metadata, **args)

    def remove(self, key, version):
        head = self.checked_head(key, version)
        self.s3.delete_object(Bucket=self.bucket, Key=key, IfMatch=head["ETag"])


class Conflict(Exception):
    pass


def handle(event, get_credentials, store, origins):
    headers = {str(key).lower(): value for key, value in (event.get("headers") or {}).items()}
    try:
        username, password_hash = get_credentials()
        if not authorized(headers.get("authorization", ""), username, password_hash):
            return response(401, {"error": "Unauthorized"})
    except Exception:
        LOGGER.error("Admin authentication configuration unavailable")
        return response(503, {"error": "Admin service temporarily unavailable"})
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("rawPath", "")
    try:
        if method == "GET" and path in ("/admin", "/admin/"):
            return response(200, PAGE.read_text(encoding="utf-8"), "text/html; charset=utf-8")
        if method == "GET" and path == "/admin/images":
            return response(200, {"images": store.list_images()})
        if method != "POST" or path not in ("/admin/labels", "/admin/remove"):
            return response(404, {"error": "Not found"})
        # Browsers cannot set this custom header cross-origin without a CORS preflight.
        if (headers.get("origin") not in origins or headers.get("x-admin-request") != "1"
                or headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json"):
            return response(403, {"error": "Invalid request origin"})
        body = event.get("body", "")
        if not isinstance(body, str) or len(body) > MAX_BODY * 2:
            return response(400, {"error": "Invalid request"})
        data = base64.b64decode(body, validate=True) if event.get("isBase64Encoded") else body.encode()
        if len(data) > MAX_BODY:
            return response(400, {"error": "Invalid request"})
        value = json.loads(data)
        expected_fields = {"key", "version", "labels"} if path.endswith("labels") else {"key", "version"}
        if (not isinstance(value, dict) or set(value) != expected_fields or not valid_key(value["key"])
                or not isinstance(value["version"], str) or not value["version"]):
            return response(400, {"error": "Invalid request"})
        if path.endswith("labels"):
            labels = value["labels"]
            if not isinstance(labels, dict) or set(labels) != {"en", "de"} or not all(valid_label(x) for x in labels.values()):
                return response(400, {"error": "Labels must be single-line text of at most 120 characters"})
            store.update(value["key"], value["version"], labels)
        else:
            store.remove(value["key"], value["version"])
        return response(200, {"ok": True})
    except (ValueError, UnicodeError, RecursionError):
        return response(400, {"error": "Invalid request"})
    except Conflict:
        return response(409, {"error": "Image changed; reload the list and try again"})
    except Exception as error:
        code = getattr(error, "response", {}).get("Error", {}).get("Code")
        if code in {"PreconditionFailed", "412", "NoSuchKey", "404", "NotFound", "ConditionalRequestConflict", "409"}:
            return response(409, {"error": "Image changed; reload the list and try again"})
        LOGGER.error("Admin operation failed")
        return response(503, {"error": "Admin service temporarily unavailable"})


def handler(event, context):
    import boto3
    from botocore.config import Config
    ssm = boto3.client("ssm")
    s3 = boto3.client("s3", config=Config(signature_version="s3v4"))
    def credentials():
        username = ssm.get_parameter(Name=os.environ["USERNAME_PARAMETER"], WithDecryption=True)["Parameter"]["Value"]
        password_hash = ssm.get_parameter(Name=os.environ["PASSWORD_HASH_PARAMETER"])["Parameter"]["Value"]
        return username, password_hash

    return handle(event, credentials,
                  Store(s3, os.environ["MEDIA_BUCKET"]), set(os.environ["ADMIN_ORIGINS"].split(",")))
