import assert from "node:assert/strict";
import test from "node:test";
import { backgroundPath, createBackgroundUpdater } from "../src/background.ts";

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
