import assert from "node:assert/strict";
import test from "node:test";
import { backgroundCaption, backgroundPath, createBackgroundUpdater } from "../src/background.ts";

const first = `/photos/${"a".repeat(64)}.jpg`;
const second = `/photos/${"b".repeat(64)}.jpg`;
const response = (src) => Response.json({ src });
const image = () => ({ src: "", classList: { add() {} } });

test("only generated relative paths are accepted", () => {
  assert.equal(backgroundPath({ src: first }), first);
  for (const src of ["https://example.com/photo.jpg", "//example.com/photo.jpg", "/incoming/private.jpg", "/photos/../state/inventory.json", `${first}?x=1`, `${first}\n`, "/photos/short.jpg"]) {
    assert.equal(backgroundPath({ src }), null);
  }
  for (const value of [null, false, {}, { src: 42 }]) {
    assert.equal(backgroundPath(value), null);
  }
});

test("captions support both languages, partial metadata, and empty fallback", () => {
  const selection = { label: { en: "Lake Constance", de: "Bodensee" }, year: 2012 };
  assert.deepEqual(backgroundCaption(selection, "en"), { text: "Lake Constance, 2012", lang: "en" });
  assert.deepEqual(backgroundCaption(selection, "de"), { text: "Bodensee, 2012", lang: "de" });
  assert.deepEqual(backgroundCaption({ label: { en: "Crater Lake" } }, "de"), { text: "Crater Lake", lang: "en" });
  assert.equal(backgroundCaption({ year: 2012 }, "en").text, "2012");
  for (const value of [null, {}, { src: first }, { label: null }, { label: "bad" },
    { label: { en: 42, de: " " }, year: "2012" }, { year: true }, { year: 2012.5 },
    { year: 999 }, { year: 10000 }, { label: { en: "line\nbreak" } },
    { label: { en: "x".repeat(121) } }, { label: { en: "\ud800" } }]) {
    assert.equal(backgroundCaption(value, "en").text, "");
  }
});

test("publishes caption data only after the photo succeeds, including same-photo metadata updates", async () => {
  const target = image();
  const published = [];
  let selection = { src: first, label: { en: "First" } };
  let broken = false;
  let loads = 0;
  const update = createBackgroundUpdater(target, async () => Response.json(selection), async () => {
    loads++;
    if (broken) throw new Error("offline");
    assert.deepEqual(published, []);
  }, (photo) => published.push({ src: target.src, photo }));
  await update();
  assert.deepEqual(published, [{ src: first, photo: selection }]);
  selection = { src: second, label: { en: "Second" } };
  broken = true;
  assert.equal(await update(), false);
  assert.equal(target.src, first);
  assert.equal(published.length, 1);
  selection = { src: first, label: { en: "Updated" } };
  await update();
  assert.deepEqual(published.at(-1), { src: first, photo: selection });
  assert.equal(loads, 2);
  selection = { src: first };
  await update();
  assert.deepEqual(published.at(-1), { src: first, photo: selection });
  selection = { src: "/incoming/unsafe.jpg", label: { en: "Must not appear" } };
  assert.equal(await update(), false);
  assert.equal(published.length, 3);
});

test("loads before displaying and does not reload an unchanged selection", async () => {
  const target = image();
  const loaded = [];
  const update = createBackgroundUpdater(target, async (url, options) => {
    assert.equal(url, "/background.json");
    assert.equal(options.credentials, "omit");
    assert.equal(options.cache, "no-cache");
    return response(first);
  }, async (src) => {
    assert.equal(target.src, "");
    loaded.push(src);
  });
  assert.equal(await update(), true);
  assert.equal(target.src, first);
  assert.equal(await update(), true);
  assert.deepEqual(loaded, [first]);
});

test("failed refresh retains the last working image and can recover", async () => {
  const target = image();
  let selected = first;
  let broken = false;
  const update = createBackgroundUpdater(target, async () => response(selected), async () => {
    if (broken) throw new Error("offline");
  });
  await update();
  selected = second;
  broken = true;
  assert.equal(await update(), false);
  assert.equal(target.src, first);
  broken = false;
  assert.equal(await update(), true);
  assert.equal(target.src, second);
});

test("missing selection, invalid JSON, network errors, and unsafe paths use fallback", async () => {
  for (const fetcher of [
    async () => new Response("", { status: 403 }),
    async () => new Response("not json"),
    async () => { throw new Error("offline"); },
    async () => response("https://external.example/photo.jpg"),
  ]) {
    const target = image();
    assert.equal(await createBackgroundUpdater(target, fetcher)(), false);
    assert.equal(target.src, "");
  }
});

test("overlapping refreshes do not race", async () => {
  let resolve;
  const loading = new Promise((done) => { resolve = done; });
  const target = image();
  const update = createBackgroundUpdater(target, async () => response(first), () => loading);
  const firstUpdate = update();
  assert.equal(await update(), false);
  resolve();
  assert.equal(await firstUpdate, true);
  assert.equal(target.src, first);
});
