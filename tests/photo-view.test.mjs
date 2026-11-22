import assert from "node:assert/strict";
import test from "node:test";
import { setImmediate } from "node:timers/promises";
import { createPhotoView } from "../src/photo-view.ts";

function setup() {
  const html = new Map();
  const attributes = new Map();
  const contrast = Object.assign(new EventTarget(), { matches: false });
  const regions = [
    { inert: false, animations: [], getAnimations() { return this.animations; } },
    { inert: false, getAnimations() { return []; } },
  ];
  let focused;
  const localeButton = { focus() { focused = this; } };
  const page = Object.assign(new EventTarget(), {
    defaultView: { matchMedia: () => contrast, scrollY: 0 },
    documentElement: { toggleAttribute(key, enabled) { return enabled ? html.set(key, "") : html.delete(key); } },
    querySelector: () => localeButton,
  });
  const caption = { textContent: "", lang: "" };
  const button = Object.assign(new EventTarget(), {
    ownerDocument: page,
    hidden: true,
    setAttribute(key, value) { attributes.set(key, value); },
    removeAttribute(key) { attributes.delete(key); if (key === "title") this.title = ""; },
    focus() { focused = this; },
  });
  return {
    page, button, caption, contrast, localeButton, regions, attributes,
    active: () => html.has("data-photo-view"), focused: () => focused,
    click: () => button.dispatchEvent(new Event("click")),
    controller: createPhotoView(button, caption, regions, "en"),
  };
}

test("a loaded photo gets a localized toggle even without a caption", () => {
  const { controller, caption, button, attributes, click, active } = setup();
  controller.setLocale("de");
  click();
  assert.equal(button.hidden, true);
  assert.equal(active(), false);

  controller.update({});
  assert.equal(button.hidden, false);
  assert.equal(caption.textContent, "Foto ansehen");
  click();
  assert.equal(caption.textContent, "Zurück zur Seite");

  controller.update({ label: { en: "<b>Lake</b>", de: "See" } });
  assert.deepEqual(caption, { textContent: "See", lang: "de" });
  assert.equal(attributes.get("aria-pressed"), "true");
  controller.setLocale("en");
  assert.deepEqual(caption, { textContent: "<b>Lake</b>", lang: "en" });
  click();
  assert.equal(caption.textContent, "<b>Lake</b>");
  assert.equal(attributes.get("aria-pressed"), "false");
  controller.update({});
  assert.equal(caption.textContent, "View photo");
  assert.equal(attributes.has("aria-pressed"), false);
});

test("Escape exits and a completed earlier fade cannot unlock a later photo-only view", async () => {
  const { controller, regions, page, button, click, active, focused } = setup();
  controller.update({});
  click();
  assert.equal(active(), true);
  assert.equal(focused(), button);
  assert.ok(regions.every((region) => region.inert));

  const first = Promise.withResolvers();
  regions[0].animations = [{ finished: first.promise }];
  const escape = Object.assign(new Event("keydown", { cancelable: true }), { key: "Escape" });
  page.dispatchEvent(escape);
  assert.equal(escape.defaultPrevented, true);
  assert.equal(active(), false);
  assert.ok(regions.every((region) => region.inert));

  click();
  first.resolve();
  await setImmediate();
  assert.equal(active(), true);
  assert.ok(regions.every((region) => region.inert));

  const second = Promise.withResolvers();
  regions[0].animations = [{ finished: second.promise }];
  click();
  assert.equal(active(), false);
  assert.ok(regions.every((region) => region.inert));
  second.resolve();
  await setImmediate();
  assert.ok(regions.every((region) => !region.inert));
});

test("switching to high contrast restores the page and prevents activation", () => {
  const { controller, contrast, localeButton, click, active, focused, regions } = setup();
  controller.update({});
  click();
  assert.equal(active(), true);
  contrast.matches = true;
  contrast.dispatchEvent(new Event("change"));
  assert.equal(active(), false);
  assert.equal(focused(), localeButton);
  assert.ok(regions.every((region) => !region.inert));
  click();
  assert.equal(active(), false);
});
