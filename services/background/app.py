"""Daily S3 photo processing and publication. No public endpoint or credentials."""

import hashlib
import io
import json
import logging
import os
import re
import secrets
import warnings
from datetime import datetime, timezone
from pathlib import PurePosixPath

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)
MAX_BYTES = 30 * 1024 * 1024
MAX_PIXELS = 40_000_000
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
PHOTO_KEY = re.compile(r"photos/[a-f0-9]{64}\.jpg\Z")
STATE_KEY = "state/inventory.json"
POINTER_KEY = "background.json"
PIPELINE_VERSION = 2


def missing_object(error):
    return getattr(error, "response", {}).get("Error", {}).get("Code") in {
        "NoSuchKey", "404", "NotFound"
    }


class S3Store:
    def __init__(self, client, bucket):
        self.client = client
        self.bucket = bucket

    def incoming(self):
        pages = self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix="incoming/"
        )
        # Complete every page before doing any publication.
        return [item for page in pages for item in page.get("Contents", [])]

    def read_json(self, key, with_etag=False):
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except Exception as error:
            if missing_object(error):
                return (None, None) if with_etag else None
            raise
        with response["Body"] as body:
            value = json.load(body)
        return (value, response["ETag"]) if with_etag else value

    def exists(self, key):
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception as error:
            if missing_object(error):
                return False
            raise
        return True

    def download(self, item):
        response = self.client.get_object(
            Bucket=self.bucket, Key=item["Key"], IfMatch=item["ETag"]
        )
        with response["Body"] as body:
            data = body.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("An incoming image exceeds the 30 MiB limit")
        return data

    def write(self, key, data, content_type, cache_control):
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=data,
            ContentType=content_type, CacheControl=cache_control,
        )

    def write_json(self, key, value, cache_control):
        self.write(
            key, json.dumps(value, sort_keys=True).encode(),
            "application/json", cache_control,
        )

    def publish(self, selection, expected_etag):
        condition = {"IfMatch": expected_etag} if expected_etag else {"IfNoneMatch": "*"}
        try:
            self.client.put_object(
                Bucket=self.bucket, Key=POINTER_KEY,
                Body=json.dumps(selection, sort_keys=True).encode(),
                ContentType="application/json",
                CacheControl="public, max-age=0, s-maxage=300, must-revalidate",
                **condition,
            )
        except Exception as error:
            if getattr(error, "response", {}).get("Error", {}).get("Code") in {
                "PreconditionFailed", "412"
            }:
                return False
            # Permissions, service failures, and 409 conflicts must remain retryable.
            raise
        return True


def render_photo(data):
    # Pillow is packaged for Lambda; core orchestration tests need no dependencies.
    from PIL import Image, ImageCms, ImageOps

    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as source:
            if source.width * source.height > MAX_PIXELS:
                raise ValueError("An incoming image exceeds the 40 megapixel limit")
            # HDR/spatial JPEGs may be MPO containers with auxiliary images (e.g.
            # a gain map). Publish only the primary still, never those extra frames.
            if getattr(source, "n_frames", 1) != 1 and source.format != "MPO":
                raise ValueError(
                    f"Upload still images, not animations or multi-page images ({source.format})"
                )
            source.seek(0)
            image = ImageOps.exif_transpose(source)
            image.thumbnail((2560, 2560), Image.Resampling.LANCZOS)
            if profile := image.info.get("icc_profile"):
                image = ImageCms.profileToProfile(
                    image, ImageCms.ImageCmsProfile(io.BytesIO(profile)),
                    ImageCms.createProfile("sRGB"),
                    outputMode="RGBA" if "A" in image.getbands() else "RGB",
                )
            image = image.convert("RGBA")
            # Fresh pixel-only image: no EXIF, GPS, IPTC, comments, or source profile.
            clean = Image.new("RGB", image.size, "white")
            clean.paste(image, mask=image.getchannel("A"))
            output = io.BytesIO()
            clean.save(output, "JPEG", quality=85, optimize=True, progressive=True)
            return output.getvalue(), clean.width, clean.height


def sync(store, now=None, render=render_photo, choose=secrets.choice):
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(timezone.utc).date().isoformat()
    items = sorted(
        (item for item in store.incoming()
         if PurePosixPath(item["Key"]).suffix.lower() in EXTENSIONS),
        key=lambda item: item["Key"],
    )
    if not items:
        LOGGER.warning("No supported incoming images; retaining the last published background")
        return {"status": "empty", "images": 0}

    previous_state = store.read_json(STATE_KEY)
    if previous_state is not None and (
        not isinstance(previous_state, dict)
        or not isinstance(previous_state.get("sources"), dict)
    ):
        raise ValueError("Invalid background inventory; publication stopped")
    cached = (previous_state or {}).get("sources", {})
    current, current_etag = store.read_json(POINTER_KEY, with_etag=True)
    if current is not None and not isinstance(current, dict):
        raise ValueError("Invalid background selection; publication stopped")

    sources = {}
    photos = {}
    for item in items:
        if item["Size"] > MAX_BYTES:
            raise ValueError("An incoming image exceeds the 30 MiB limit")
        old = cached.get(item["Key"], {})
        if (
            (previous_state or {}).get("version") == PIPELINE_VERSION
            and old.get("etag") == item["ETag"]
            and old.get("size") == item["Size"]
            and PHOTO_KEY.fullmatch(old.get("key", ""))
            and store.exists(old["key"])
        ):
            record = old
        else:
            data, width, height = render(store.download(item))
            key = f"photos/{hashlib.sha256(data).hexdigest()}.jpg"
            store.write(key, data, "image/jpeg", "public, max-age=31536000, immutable")
            record = {
                "etag": item["ETag"], "size": item["Size"],
                "key": key, "width": width, "height": height,
            }
        sources[item["Key"]] = record
        photos["/" + record["key"]] = record

    state = {"version": PIPELINE_VERSION, "sources": sources}
    if state != previous_state:
        store.write_json(STATE_KEY, state, "no-store")

    # Same-day retries/manual runs retain the published choice while it is eligible.
    if current and current.get("day") == day and current.get("src") in photos:
        return {"status": "unchanged", "images": len(photos)}

    candidates = sorted(photos)
    if len(candidates) > 1 and current and current.get("src") in candidates:
        candidates.remove(current["src"])
    src = choose(candidates)
    photo = photos[src]
    selection = {
        "src": src, "width": photo["width"], "height": photo["height"],
        "day": day, "updated": now.astimezone(timezone.utc).isoformat(),
    }
    # Last write: readers can never see a pointer to an image not yet uploaded.
    # Compare-and-swap: overlapping invocations cannot replace another run's choice.
    if not store.publish(selection, current_etag):
        LOGGER.info("Another invocation already published a selection")
        return {"status": "superseded", "images": len(photos)}
    LOGGER.info("Published background for %s from %d eligible images", day, len(photos))
    return {"status": "published", "images": len(photos), "day": day}


def handler(event, context):
    import boto3

    return sync(S3Store(boto3.client("s3"), os.environ["MEDIA_BUCKET"]))
