import type { Locale } from "./config";

/** Accept only generated, same-origin image paths; never arbitrary URLs. */
export function backgroundPath(value: unknown): string | null {
  if (typeof value !== "object" || value === null || !("src" in value)) return null;
  return typeof value.src === "string" && /^\/photos\/[a-f0-9]{64}\.jpg$/.test(value.src)
    ? value.src
    : null;
}

function captionLabel(value: unknown): string {
  return typeof value === "string" && Array.from(value).length <= 120
    && !/[\p{Cc}\p{Cs}]/u.test(value) ? value.trim() : "";
}

/** Optional caption data must never prevent an otherwise valid image loading. */
export function backgroundCaption(value: unknown, locale: Locale): { text: string; lang: Locale } {
  const empty = { text: "", lang: locale };
  if (typeof value !== "object" || value === null) return empty;
  const label = "label" in value && typeof value.label === "object" && value.label !== null
    ? value.label as Partial<Record<Locale, unknown>> : {};
  const other = locale === "en" ? "de" : "en";
  const preferred = captionLabel(label[locale]);
  const place = preferred || captionLabel(label[other]);
  const year = "year" in value && typeof value.year === "number" && Number.isInteger(value.year)
    && value.year >= 1000 && value.year <= 9999 ? String(value.year) : "";
  return { text: [place, year].filter(Boolean).join(", "), lang: place && !preferred ? other : locale };
}

export function createBackgroundCaption(element: HTMLElement | null, initialLocale: Locale) {
  let selection: unknown = null;
  let locale = initialLocale;
  function render() {
    if (!element) return;
    const caption = backgroundCaption(selection, locale);
    element.textContent = caption.text;
    element.lang = caption.lang;
    element.hidden = !caption.text;
  }
  return {
    update(value: unknown) { selection = value; render(); },
    setLocale(value: Locale) { locale = value; render(); },
  };
}

function preloadPhoto(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const photo = new Image();
    const timeout = setTimeout(() => {
      photo.src = "";
      reject(new Error("Background image loading timed out"));
    }, 15000);
    photo.onload = () => {
      clearTimeout(timeout);
      resolve();
    };
    photo.onerror = () => {
      clearTimeout(timeout);
      reject(new Error("Background image could not be loaded"));
    };
    photo.src = src;
  });
}

export function createBackgroundUpdater(
  image: HTMLImageElement,
  fetcher: typeof fetch = fetch,
  preload: (src: string) => Promise<void> = preloadPhoto,
  caption?: ReturnType<typeof createBackgroundCaption>,
) {
  let current: string | null = null;
  let pending = false;

  return async function updateBackground(): Promise<boolean> {
    if (pending) return false;
    pending = true;
    try {
      const response = await fetcher("/background.json", {
        cache: "no-cache",
        credentials: "omit",
        signal: AbortSignal.timeout(10000),
      });
      if (!response.ok) return false;
      const selection: unknown = await response.json();
      const src = backgroundPath(selection);
      if (!src) return false;
      if (src !== current) {
        // Keep the existing photo (or solid fallback) until the new photo loads.
        await preload(src);
        image.src = src;
        image.classList.add("is-loaded");
        current = src;
      }
      // Commit caption only after the image succeeds; refresh even for the same URL.
      caption?.update(selection);
      return true;
    } catch {
      // Missing initial selection, offline, invalid JSON, image failure: no broken UI.
      return false;
    } finally {
      pending = false;
    }
  };
}
