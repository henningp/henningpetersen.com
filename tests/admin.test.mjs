import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

test("admin page sorts sources, preserves typed labels, and sends authenticated mutations", async () => {
  const html = readFileSync(new URL("../services/admin/index.html", import.meta.url), "utf8");
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  const element = (tag) => ({
    tag, children: [], listeners: {}, attributes: {}, dataset: {}, textContent: "",
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    addEventListener(name, fn) { this.listeners[name] = fn; },
    setAttribute(name, value) { this.attributes[name] = value; },
  });
  const tbody = element("tbody"), status = element("p"), refresh = element("button");
  const viewer = element("dialog"), fullImage = element("img");
  viewer.showModal = () => { viewer.open = true; };
  viewer.close = () => { viewer.open = false; };
  const sort = element("button"); sort.dataset.sort = "key";
  const document = {
    createElement: element,
    querySelector(selector) { return { "#images": tbody, "#status": status, "#refresh": refresh, "#image-viewer": viewer, "#full-image": fullImage }[selector]; },
    querySelectorAll() { return [sort]; },
  };
  const images = [
    { key: "incoming/z.jpg", version: "v2", image: "https://s3.amazonaws.com/signed?token=test", size: 1, modified: "2026-01-01" },
    { key: "incoming/<img>.jpg", version: "v1", image: "/photos/a.jpg", size: 1, modified: "2026-01-01", label: { en: "A" } },
  ];
  const requests = [];
  const fetch = async (path, options) => {
    requests.push({ path, options });
    return { ok: true, json: async () => path === "/admin/images" ? { images } : { ok: true } };
  };
  vm.runInNewContext(script, { document, fetch, confirm: () => true });
  await new Promise(setImmediate);
  assert.equal(tbody.children[0].children[1].textContent, "incoming/<img>.jpg");
  const preview = tbody.children[0].children[0].children[0];
  assert.equal(preview.tag, "button");
  assert.equal(preview.attributes["aria-label"], "View incoming/<img>.jpg larger");
  preview.listeners.click();
  assert.equal(viewer.open, true);
  assert.equal(fullImage.src, "/photos/a.jpg");
  assert.equal(fullImage.alt, "A");
  viewer.listeners.click();
  assert.equal(viewer.open, false);
  const input = tbody.children[0].children[2].children[0];
  input.value = "Edited"; input.listeners.input();
  sort.listeners.click();
  assert.equal(tbody.children[1].children[2].children[0].value, "Edited");
  tbody.children[0].children[0].children[0].listeners.click();
  assert.equal(fullImage.src, "https://s3.amazonaws.com/signed?token=test");
  assert.equal(fullImage.alt, "incoming/z.jpg");
  viewer.listeners.click();
  assert.equal(requests.length, 1);
  tbody.children[1].children[7].children[0].listeners.click();
  await new Promise(setImmediate);
  const mutation = requests.find(({ path }) => path === "/admin/labels");
  assert.equal(mutation.options.method, "POST");
  assert.equal(mutation.options.headers["X-Admin-Request"], "1");
  assert.deepEqual(JSON.parse(mutation.options.body), {
    key: "incoming/<img>.jpg", version: "v1", labels: { en: "Edited", de: "" },
  });
});
