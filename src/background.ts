/** Accept only generated, same-origin image paths; never arbitrary URLs. */
export function backgroundPath(value: unknown): string | null {
  if (typeof value !== "object" || value === null || !("src" in value)) return null;
  return typeof value.src === "string" && /^\/photos\/[a-f0-9]{64}\.jpg$/.test(value.src)
    ? value.src
    : null;
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
      const src = backgroundPath(await response.json());
      if (!src) return false;
      if (src !== current) {
        // Keep the existing photo (or solid fallback) until the new photo loads.
        await preload(src);
        image.src = src;
        image.classList.add("is-loaded");
        current = src;
      }
      return true;
    } catch {
      // Missing initial selection, offline, invalid JSON, image failure: no broken UI.
      return false;
    } finally {
      pending = false;
    }
  };
}
