import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";
import { getDefaultLocale, getLocale, isLocale, saveLocale } from "../src/locale.ts";
import { pickGreeting } from "../src/config.ts";

function memoryStorage(initial = null) {
  let value = initial;
  const writes = [];
  return {
    writes,
    getItem(key) { assert.equal(key, "locale"); return value; },
    setItem(key, next) { assert.equal(key, "locale"); writes.push(next); value = next; },
    removeItem(key) { assert.equal(key, "locale"); writes.push(null); value = null; },
  };
}

test("browser locale detection falls back to English", () => {
  for (const language of ["de", "de-DE", "DE-at"]) assert.equal(getDefaultLocale(language), "de");
  for (const language of ["en", "en-US", "fr-FR", ""]) assert.equal(getDefaultLocale(language), "en");
  for (const value of [null, "fr", "", 42]) assert.equal(isLocale(value), false);
});

test("reading the default or a valid override never writes storage", () => {
  for (const defaultLocale of ["en", "de"]) {
    for (const stored of [null, "invalid", "en", "de"]) {
      const storage = memoryStorage(stored);
      assert.equal(getLocale(defaultLocale, () => storage), isLocale(stored) ? stored : defaultLocale);
      assert.deepEqual(storage.writes, []);
    }
  }
});

test("only overrides are saved and choosing the default removes them", () => {
  for (const defaultLocale of ["en", "de"]) {
    const storage = memoryStorage();
    const override = defaultLocale === "en" ? "de" : "en";
    saveLocale(override, defaultLocale, () => storage);
    assert.equal(getLocale(defaultLocale, () => storage), override);
    saveLocale(defaultLocale, defaultLocale, () => storage);
    assert.equal(storage.getItem("locale"), null);
    assert.deepEqual(storage.writes, [override, null]);
  }
});

test("unavailable storage falls back safely, including a blocked storage getter", () => {
  const blocked = () => { throw new Error("Storage blocked"); };
  const broken = () => ({ getItem: blocked, setItem: blocked, removeItem: blocked });
  for (const storage of [blocked, broken]) {
    assert.equal(getLocale("de", storage), "de");
    assert.doesNotThrow(() => saveLocale("en", "de", storage));
    assert.doesNotThrow(() => saveLocale("de", "de", storage));
  }
});

test("initialization and greeting refresh never persist; switching works without storage", () => {
  const page = readFileSync(new URL("../src/pages/index.astro", import.meta.url), "utf8");
  // Exercise the page's actual locale wiring, without importing its unrelated background updater.
  const script = page.slice(page.indexOf("      (function () {", page.indexOf('import { pickGreeting')),
    page.indexOf("    </script>", page.indexOf('import { pickGreeting')));
  for (const blocked of [false, true]) {
    const storage = memoryStorage();
    const access = () => { if (blocked) throw new Error("Storage blocked"); return storage; };
    const attributes = new Map();
    const element = (locale) => ({
      getAttribute() { return locale; },
      setAttribute() {},
      addEventListener(event, listener) { this.click = listener; },
      textContent: "",
    });
    const greetings = [element("en"), element("de")];
    const buttons = [element("en"), element("de")];
    let refresh;
    const captionLocales = [];
    let hour = 8;
    vm.runInNewContext(ts.transpileModule(script, {
      compilerOptions: { target: ts.ScriptTarget.ESNext },
    }).outputText, {
      document: {
        documentElement: {
          getAttribute(name) { return attributes.get(name) ?? null; },
          setAttribute(name, value) { attributes.set(name, value); },
        },
        querySelectorAll(selector) {
          if (selector === ".greeting") return greetings;
          if (selector === "[data-choose-locale]") return buttons;
          return greetings;
        },
      },
      getLocale: () => getLocale("de", access),
      saveLocale: (locale) => saveLocale(locale, "de", access),
      isLocale,
      pickGreeting,
      backgroundCaption: { setLocale(locale) { captionLocales.push(locale); } },
      Date: class { getHours() { return hour; } },
      setInterval(callback, delay) { assert.equal(delay, 60000); refresh = callback; },
    });
    assert.equal(attributes.get("lang"), "de");
    assert.deepEqual(captionLocales, ["de"]);
    assert.equal(greetings[1].textContent, "Guten Morgen!");
    hour = 13;
    refresh();
    assert.equal(greetings[1].textContent, "Guten Tag!");
    assert.deepEqual(captionLocales, ["de"]);
    assert.deepEqual(storage.writes, []);
    buttons[0].click();
    assert.equal(attributes.get("lang"), "en");
    assert.deepEqual(captionLocales, ["de", "en"]);
    assert.equal(greetings[0].textContent, "Good afternoon!");
    hour = 19;
    refresh();
    assert.equal(greetings[0].textContent, "Good evening!");
    assert.deepEqual(storage.writes, blocked ? [] : ["en"]);
    buttons[1].click();
    assert.deepEqual(captionLocales, ["de", "en", "de"]);
    assert.equal(greetings[1].textContent, "Guten Abend!");
    assert.deepEqual(storage.writes, blocked ? [] : ["en", null]);
  }
});
