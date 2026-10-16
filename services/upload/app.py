"""Authorize private JPEG uploads; image bytes go directly from Shortcuts to S3."""

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import uuid

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)
MAX_BYTES = 30 * 1024 * 1024
MAX_REQUEST_BYTES = 1024
EXPIRY_SECONDS = 300
TOKEN = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")
TOKEN_HASH = re.compile(r"[a-f0-9]{64}\Z")


def reply(status, value):
    headers = {"Content-Type": "application/json", "Cache-Control": "no-store"}
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return {"statusCode": status, "headers": headers, "body": json.dumps(value)}


def handle(event, get_token_hash, create_upload):
    http = event.get("requestContext", {}).get("http", {})
    if http.get("method") != "POST" or event.get("rawPath") != "/uploads":
        return reply(405, {"error": "Use POST /uploads"})
    headers = {key.lower(): value for key, value in (event.get("headers") or {}).items()}
    authorization = headers.get("authorization", "")
    if not isinstance(authorization, str):
        return reply(401, {"error": "Unauthorized"})
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not TOKEN.fullmatch(token):
        return reply(401, {"error": "Unauthorized"})

    try:
        expected = get_token_hash()
        if not isinstance(expected, str) or not TOKEN_HASH.fullmatch(expected):
            raise ValueError("Invalid token hash configuration")
    except Exception:
        # Do not log requests, tokens, signed form fields, or SDK exception details.
        LOGGER.error("Upload authentication configuration unavailable")
        return reply(503, {"error": "Upload service temporarily unavailable"})
    actual = hashlib.sha256(token.encode()).hexdigest()
    if not hmac.compare_digest(actual, expected):
        return reply(401, {"error": "Unauthorized"})

    content_type = headers.get("content-type", "")
    if not isinstance(content_type, str) or content_type.split(";", 1)[0].lower().strip() != "application/json":
        return reply(415, {"error": "Use application/json"})
    body = event.get("body", "")
    if not isinstance(body, str):
        return reply(400, {"error": "Invalid JSON request"})
    if len(body) > MAX_REQUEST_BYTES * 2:
        return reply(413, {"error": "Request too large"})
    try:
        data = base64.b64decode(body, validate=True) if event.get("isBase64Encoded") else body.encode()
        if len(data) > MAX_REQUEST_BYTES:
            return reply(413, {"error": "Request too large"})
        value = json.loads(data)
    except (ValueError, UnicodeError):
        return reply(400, {"error": "Invalid JSON request"})
    if not isinstance(value, dict) or value != {"content_type": "image/jpeg"}:
        return reply(400, {"error": "Only content_type=image/jpeg is accepted"})

    try:
        upload = create_upload()
    except Exception:
        LOGGER.error("Could not authorize an upload")
        return reply(503, {"error": "Upload service temporarily unavailable"})
    return reply(200, {**upload, "expires_in": EXPIRY_SECONDS, "max_bytes": MAX_BYTES})


def signed_upload(s3, bucket):
    # No client-controlled paths or filenames. This role cannot overwrite published
    # photos, list/read originals, delete objects, or trigger background selection.
    key = f"incoming/shortcut/{uuid.uuid4().hex}.jpg"
    return s3.generate_presigned_post(
        Bucket=bucket,
        Key=key,
        Fields={"Content-Type": "image/jpeg", "success_action_status": "201"},
        Conditions=[
            {"Content-Type": "image/jpeg"},
            {"success_action_status": "201"},
            ["content-length-range", 1, MAX_BYTES],
        ],
        ExpiresIn=EXPIRY_SECONDS,
    )


def handler(event, context):
    import boto3
    from botocore.config import Config

    region = os.environ["AWS_REGION"]
    config = Config(
        connect_timeout=2, read_timeout=3, retries={"max_attempts": 1},
    )
    ssm = boto3.client("ssm", region_name=region, config=config)
    s3 = boto3.client(
        "s3", region_name=region, endpoint_url=f"https://s3.{region}.amazonaws.com",
        config=config.merge(Config(signature_version="s3v4", s3={"addressing_style": "virtual"})),
    )
    return handle(
        event,
        # Read on every request: changing the hash revokes the personal token
        # without redeployment or a warm-container credential cache.
        lambda: ssm.get_parameter(Name=os.environ["TOKEN_HASH_PARAMETER"])["Parameter"]["Value"],
        lambda: signed_upload(s3, os.environ["MEDIA_BUCKET"]),
    )
