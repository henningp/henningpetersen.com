import base64
import copy
import hashlib
import io
import json
import unittest
from datetime import datetime, timedelta, timezone

from app import MAX_BYTES, POINTER_KEY, STATE_KEY, S3Store, read_caption, render_photo, sync

NOW = datetime(2026, 10, 16, 3, tzinfo=timezone.utc)


class MemoryStore:
    def __init__(self):
        self.uploads = {"incoming/one.jpg": b"first", "incoming/two.png": b"second"}
        self.objects = {}
        self.writes = []
        self.downloads = []
        self.captions = {}
        self.modified = {}
        self.fail_key = None

    def incoming(self):
        return [{"Key": key, "ETag": hashlib.sha256(data).hexdigest(), "Size": len(data),
                 "LastModified": self.modified.get(key, "initial")}
                for key, data in self.uploads.items()]

    def read_json(self, key, with_etag=False):
        value = copy.deepcopy(self.objects.get(key))
        etag = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest() if value else None
        return (value, etag) if with_etag else value

    def exists(self, key):
        return key in self.objects

    def download(self, item):
        self.downloads.append(item["Key"])
        return self.uploads[item["Key"]], self.captions.get(item["Key"], {})

    def write(self, key, data, content_type, cache_control):
        if key == self.fail_key:
            raise RuntimeError("upload failed")
        self.writes.append((key, content_type, cache_control))
        self.objects[key] = data

    def write_json(self, key, value, cache_control):
        self.write(key, copy.deepcopy(value), "application/json", cache_control)

    def publish(self, selection, expected_etag):
        _, actual_etag = self.read_json(POINTER_KEY, with_etag=True)
        if actual_etag != expected_etag:
            return False
        self.write_json(POINTER_KEY, selection, "public, max-age=0, s-maxage=300, must-revalidate")
        return True


def render(data):
    return b"jpeg:" + data, 1920, 1080


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()

    def run_sync(self, now=NOW, **kwargs):
        return sync(self.store, now, render=render, choose=lambda values: values[0], **kwargs)

    def test_uploads_before_publishing_and_keeps_original_names_private(self):
        result = self.run_sync()
        self.assertEqual(result["status"], "published")
        self.assertEqual(self.store.writes[-1][0], POINTER_KEY)
        pointer = self.store.objects[POINTER_KEY]
        self.assertRegex(pointer["src"], r"^/photos/[a-f0-9]{64}\.jpg$")
        self.assertIn(pointer["src"][1:], self.store.objects)
        self.assertNotIn("incoming", json.dumps(pointer))
        self.assertIn("s-maxage=300", self.store.writes[-1][2])

    def test_same_day_retry_is_idempotent_and_incremental(self):
        self.run_sync()
        pointer = copy.deepcopy(self.store.objects[POINTER_KEY])
        self.store.writes.clear()
        self.store.downloads.clear()
        self.assertEqual(self.run_sync()["status"], "unchanged")
        self.assertEqual(self.store.objects[POINTER_KEY], pointer)
        self.assertEqual(self.store.writes, [])
        self.assertEqual(self.store.downloads, [])

    def test_bilingual_caption_is_published_and_cached_without_other_metadata(self):
        self.store.uploads.pop("incoming/two.png")
        caption = {"label": {"en": "Lake Constance", "de": "Bodensee"}, "year": 2012}
        self.store.captions["incoming/one.jpg"] = caption
        self.run_sync()
        pointer = self.store.objects[POINTER_KEY]
        self.assertEqual(pointer["label"], caption["label"])
        self.assertEqual(pointer["year"], 2012)
        self.store.downloads.clear()
        self.assertEqual(self.run_sync()["status"], "unchanged")
        self.assertEqual(self.store.downloads, [])

    def test_labelled_duplicate_updates_caption_but_not_todays_photo(self):
        self.store.uploads.pop("incoming/two.png")
        self.run_sync()
        before = copy.deepcopy(self.store.objects[POINTER_KEY])
        self.store.uploads["incoming/reupload.jpg"] = self.store.uploads["incoming/one.jpg"]
        self.store.captions["incoming/reupload.jpg"] = {"label": {"en": "Crater Lake"}, "year": 2012}
        self.assertEqual(self.run_sync(), {"status": "published", "images": 1, "day": "2026-10-16"})
        pointer = self.store.objects[POINTER_KEY]
        self.assertEqual(pointer["src"], before["src"])
        self.assertEqual(pointer["label"], {"en": "Crater Lake"})
        self.assertEqual(self.run_sync()["status"], "unchanged")

    def test_duplicate_caption_preference_and_ties_are_deterministic(self):
        self.store.uploads = {key: b"same" for key in (
            "incoming/z.jpg", "incoming/d.jpg", "incoming/c.jpg", "incoming/b.jpg", "incoming/a.jpg")}
        self.store.captions = {
            "incoming/b.jpg": {"year": 2012},
            "incoming/c.jpg": {"label": {"en": "One language"}, "year": 2012},
            "incoming/d.jpg": {"label": {"en": "Winner", "de": "Gewinner"}, "year": 2012},
            "incoming/z.jpg": {"label": {"en": "Other", "de": "Andere"}, "year": 2020},
        }
        self.assertEqual(self.run_sync()["images"], 1)
        self.assertEqual(self.store.objects[POINTER_KEY]["label"]["en"], "Winner")
        self.assertEqual(self.store.objects[POINTER_KEY]["year"], 2012)

    def test_metadata_only_source_replacement_refreshes_and_can_clear_caption(self):
        self.store.uploads.pop("incoming/two.png")
        self.store.captions["incoming/one.jpg"] = {"year": 2012}
        self.run_sync()
        before = self.store.objects[POINTER_KEY]["src"]
        self.store.captions.clear()
        self.store.modified["incoming/one.jpg"] = "replaced"
        self.store.downloads.clear()
        self.run_sync()
        self.assertEqual(self.store.downloads, ["incoming/one.jpg"])
        self.assertEqual(self.store.objects[POINTER_KEY]["src"], before)
        self.assertNotIn("year", self.store.objects[POINTER_KEY])

    def test_old_inventory_is_reprocessed_for_caption_support(self):
        self.run_sync()
        self.store.objects[STATE_KEY]["version"] = 2
        self.store.downloads.clear()
        self.run_sync()
        self.assertEqual(len(self.store.downloads), 2)

    def test_next_day_avoids_previous_image(self):
        self.run_sync()
        before = self.store.objects[POINTER_KEY]["src"]
        self.run_sync(NOW + timedelta(days=1))
        self.assertNotEqual(self.store.objects[POINTER_KEY]["src"], before)

    def test_single_image_remains_valid_on_next_day(self):
        self.store.uploads.pop("incoming/two.png")
        self.run_sync()
        before = self.store.objects[POINTER_KEY]["src"]
        self.run_sync(NOW + timedelta(days=1))
        self.assertEqual(self.store.objects[POINTER_KEY]["src"], before)
        self.assertEqual(self.store.objects[POINTER_KEY]["day"], "2026-10-17")

    def test_adding_an_image_does_not_change_todays_choice(self):
        self.run_sync()
        before = copy.deepcopy(self.store.objects[POINTER_KEY])
        self.store.uploads["incoming/three.jpg"] = b"third"
        self.run_sync()
        self.assertEqual(self.store.objects[POINTER_KEY], before)
        self.assertEqual(len(self.store.objects[STATE_KEY]["sources"]), 3)

    def test_removed_source_is_no_longer_eligible(self):
        self.run_sync()
        before = self.store.objects[POINTER_KEY]["src"]
        state = self.store.objects[STATE_KEY]["sources"]
        removed = next(key for key, value in state.items() if "/" + value["key"] == before)
        del self.store.uploads[removed]
        self.run_sync()
        self.assertNotEqual(self.store.objects[POINTER_KEY]["src"], before)
        # Cached URLs still work; cleanup is deliberately not destructive.
        self.assertIn(before[1:], self.store.objects)

    def test_source_edit_reprocesses_only_changed_image(self):
        self.run_sync()
        self.store.downloads.clear()
        self.store.uploads["incoming/one.jpg"] = b"edited"
        self.run_sync()
        self.assertEqual(self.store.downloads, ["incoming/one.jpg"])

    def test_deleted_generated_image_is_rebuilt(self):
        self.run_sync()
        key = self.store.objects[POINTER_KEY]["src"][1:]
        del self.store.objects[key]
        self.run_sync()
        self.assertIn(key, self.store.objects)

    def test_empty_inventory_preserves_last_good_selection(self):
        self.run_sync()
        before = copy.deepcopy(self.store.objects)
        self.store.uploads.clear()
        self.assertEqual(self.run_sync()["status"], "empty")
        self.assertEqual(self.store.objects, before)

    def test_unsupported_files_are_not_processed(self):
        self.store.uploads = {"incoming/photo.heic": b"heic", "incoming/": b""}
        self.assertEqual(self.run_sync()["status"], "empty")
        self.assertEqual(self.store.writes, [])

    def test_processing_failure_preserves_selection_and_inventory(self):
        self.run_sync()
        before = copy.deepcopy(self.store.objects)
        self.store.uploads["incoming/broken.jpg"] = b"broken"
        def broken(data):
            raise ValueError("invalid photo")
        with self.assertRaises(ValueError):
            sync(self.store, NOW + timedelta(days=1), render=broken)
        self.assertEqual(self.store.objects, before)

    def test_incomplete_listing_does_not_publish(self):
        self.run_sync()
        before = copy.deepcopy(self.store.objects)
        def failed_listing():
            raise RuntimeError("listing failed")
        self.store.incoming = failed_listing
        with self.assertRaises(RuntimeError):
            self.run_sync()
        self.assertEqual(self.store.objects, before)

    def test_failed_publication_can_be_retried(self):
        self.store.fail_key = POINTER_KEY
        with self.assertRaises(RuntimeError):
            self.run_sync()
        self.assertNotIn(POINTER_KEY, self.store.objects)
        self.store.fail_key = None
        self.assertEqual(self.run_sync()["status"], "published")

    def test_oversized_image_is_rejected_before_download(self):
        self.store.incoming = lambda: [{"Key": "incoming/large.jpg", "ETag": "x", "Size": MAX_BYTES + 1}]
        with self.assertRaises(ValueError):
            self.run_sync()
        self.assertEqual(self.store.downloads, [])

    def test_invalid_inventory_fails_closed(self):
        self.store.objects[STATE_KEY] = {"sources": []}
        with self.assertRaises(ValueError):
            self.run_sync()
        self.assertEqual(self.store.writes, [])

    def test_overlapping_invocations_preserve_the_first_published_selection(self):
        for existing_selection in (False, True):
            with self.subTest(existing_selection=existing_selection):
                self.store = MemoryStore()
                if existing_selection:
                    self.run_sync(NOW - timedelta(days=1))
                winner = {}
                def choose_after_competing_run(candidates):
                    result = sync(self.store, NOW, render=render, choose=lambda values: values[-1])
                    self.assertEqual(result["status"], "published")
                    winner.update(copy.deepcopy(self.store.objects[POINTER_KEY]))
                    return candidates[0]
                result = sync(self.store, NOW, render=render, choose=choose_after_competing_run)
                self.assertEqual(result["status"], "superseded")
                self.assertEqual(self.store.objects[POINTER_KEY], winner)
                self.assertEqual(self.run_sync()["status"], "unchanged")


class S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}


class AdapterTests(unittest.TestCase):
    def test_publication_requires_matching_or_missing_pointer(self):
        class Client:
            def put_object(self, **kwargs):
                self.arguments = kwargs
        client = Client()
        store = S3Store(client, "bucket")
        self.assertTrue(store.publish({"src": "test"}, None))
        self.assertEqual(client.arguments["IfNoneMatch"], "*")
        self.assertNotIn("IfMatch", client.arguments)
        self.assertTrue(store.publish({"src": "test"}, '"etag"'))
        self.assertEqual(client.arguments["IfMatch"], '"etag"')
        self.assertNotIn("IfNoneMatch", client.arguments)

    def test_publication_only_suppresses_a_lost_compare_and_swap(self):
        class Client:
            code = "PreconditionFailed"
            def put_object(self, **kwargs):
                raise S3Error(self.code)
        client = Client()
        store = S3Store(client, "bucket")
        self.assertFalse(store.publish({}, None))
        for code in ("AccessDenied", "ConditionalRequestConflict", "ServiceUnavailable"):
            client.code = code
            with self.assertRaises(S3Error):
                store.publish({}, None)

    def test_pointer_read_returns_its_etag(self):
        class Client:
            def get_object(self, **kwargs):
                return {"Body": io.BytesIO(b'{"src":"test"}'), "ETag": '"etag"'}
        self.assertEqual(S3Store(Client(), "bucket").read_json(POINTER_KEY, with_etag=True),
                         ({"src": "test"}, '"etag"'))

    def test_missing_object_is_distinguished_from_permission_failure(self):
        class Client:
            code = "NoSuchKey"
            def get_object(self, **kwargs):
                raise S3Error(self.code)
        client = Client()
        store = S3Store(client, "bucket")
        self.assertIsNone(store.read_json(POINTER_KEY))
        self.assertEqual(store.read_json(POINTER_KEY, with_etag=True), (None, None))
        client.code = "AccessDenied"
        with self.assertRaises(S3Error):
            store.read_json(POINTER_KEY)

    def test_download_uses_etag_and_closes_stream(self):
        class Client:
            def get_object(self, **kwargs):
                self.arguments = kwargs
                self.body = io.BytesIO(b"photo")
                return {"Body": self.body, "Metadata": {
                    "caption": base64.b64encode(b'{"label":{"de":"Bodensee"},"year":2012}').decode(),
                    "private": "must not leak",
                }}
        client = Client()
        store = S3Store(client, "bucket")
        self.assertEqual(store.download({"Key": "incoming/a.jpg", "ETag": '"etag"'}),
                         (b"photo", {"label": {"de": "Bodensee"}, "year": 2012}))
        self.assertEqual(client.arguments["IfMatch"], '"etag"')
        self.assertTrue(client.body.closed)

    def test_lists_all_pages(self):
        class Client:
            def get_paginator(self, operation):
                self.operation = operation
                return self
            def paginate(self, **kwargs):
                self.arguments = kwargs
                return [{"Contents": [{"Key": "incoming/a.jpg"}]}, {},
                        {"Contents": [{"Key": "incoming/b.jpg"}]}]
        client = Client()
        items = S3Store(client, "bucket").incoming()
        self.assertEqual(len(items), 2)
        self.assertEqual(client.arguments["Prefix"], "incoming/")


class CaptionTests(unittest.TestCase):
    def test_missing_or_malformed_metadata_is_ignored(self):
        for encoded in (None, "", "!invalid", "x" * 2001,
                        base64.b64encode(b"not json").decode(),
                        base64.b64encode(b"[" * 1100).decode(),
                        base64.b64encode(b"\xff").decode()):
            self.assertEqual(read_caption({"caption": encoded}), {})
        self.assertEqual(read_caption({}), {})

    def test_only_valid_approved_fields_survive(self):
        for value, expected in [
            ([], {}), ({"label": "bad"}, {}),
            ({"label": {"en": " Lake ", "de": "See", "fr": "Lac"}, "year": 2012, "gps": "private"},
             {"label": {"en": "Lake", "de": "See"}, "year": 2012}),
            ({"label": {"en": "x" * 121, "de": "bad\nlabel"}, "year": True}, {}),
            ({"label": {"en": 42}, "year": "2012"}, {}),
            ({"label": {"en": ""}, "year": 2012}, {"year": 2012}),
        ]:
            with self.subTest(value=value):
                encoded = base64.b64encode(json.dumps(value).encode()).decode()
                self.assertEqual(read_caption({"caption": encoded}), expected)


try:
    from PIL import Image
except ImportError:
    Image = None


@unittest.skipIf(Image is None, "Install services/background/requirements.txt for image-processing tests")
class ImageTests(unittest.TestCase):
    def test_multi_picture_jpeg_uses_only_the_primary_still(self):
        primary = Image.new("RGB", (80, 40), "red")
        auxiliary = Image.new("RGB", (80, 40), "blue")
        data = io.BytesIO()
        primary.save(data, "MPO", save_all=True, append_images=[auxiliary])
        with Image.open(io.BytesIO(data.getvalue())) as source:
            self.assertEqual(source.format, "MPO")
            self.assertEqual(source.n_frames, 2)
        output, width, height = render_photo(data.getvalue())
        self.assertEqual((width, height), (80, 40))
        with Image.open(io.BytesIO(output)) as result:
            self.assertEqual(result.format, "JPEG")
            self.assertEqual(getattr(result, "n_frames", 1), 1)
            red, green, blue = result.getpixel((40, 20))
            self.assertGreater(red, 240)
            self.assertLess(blue, 10)
            self.assertFalse(result.getexif())

    def test_multi_page_tiff_is_still_rejected(self):
        data = io.BytesIO()
        image = Image.new("RGB", (10, 10), "red")
        image.save(data, "TIFF", save_all=True, append_images=[image])
        with self.assertRaisesRegex(ValueError, "multi-page images.*TIFF"):
            render_photo(data.getvalue())

    def test_animated_webp_is_still_rejected(self):
        data = io.BytesIO()
        first = Image.new("RGB", (10, 10), "red")
        second = Image.new("RGB", (10, 10), "blue")
        first.save(data, "WEBP", save_all=True, append_images=[second], duration=100)
        with self.assertRaisesRegex(ValueError, "animations.*WEBP"):
            render_photo(data.getvalue())

    def test_resizes_strips_metadata_and_normalizes_orientation(self):
        image = Image.new("RGB", (3000, 1500), "red")
        exif = Image.Exif()
        exif[274] = 6
        exif[270] = "private description"
        data = io.BytesIO()
        image.save(data, "JPEG", exif=exif)
        output, width, height = render_photo(data.getvalue())
        self.assertEqual((width, height), (1280, 2560))
        with Image.open(io.BytesIO(output)) as result:
            self.assertEqual(result.format, "JPEG")
            self.assertFalse(result.getexif())
            self.assertNotIn("icc_profile", result.info)

    def test_transparency_is_flattened_without_upscaling(self):
        image = Image.new("RGBA", (10, 20), (0, 0, 0, 0))
        data = io.BytesIO()
        image.save(data, "PNG")
        output, width, height = render_photo(data.getvalue())
        self.assertEqual((width, height), (10, 20))
        with Image.open(io.BytesIO(output)) as result:
            self.assertEqual(result.getpixel((0, 0)), (255, 255, 255))

    def test_corrupt_image_is_rejected(self):
        with self.assertRaises(Exception):
            render_photo(b"not an image")


if __name__ == "__main__":
    unittest.main()
