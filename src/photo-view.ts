import { backgroundCaption } from "./background.ts";
import type { Locale } from "./config";

const labels = {
  en: { view: "View photo", back: "Back to page" },
  de: { view: "Foto ansehen", back: "Zurück zur Seite" },
};

export function createPhotoView(
  button: HTMLButtonElement,
  caption: HTMLElement,
  regions: NodeListOf<HTMLElement>,
  initialLocale: Locale,
) {
  const page = button.ownerDocument;
  const view = page.defaultView!;
  const html = page.documentElement;
  const highContrast = view.matchMedia("(prefers-contrast: more), (forced-colors: active)");
  let selection: unknown;
  let locale = initialLocale;
  let active = false;
  let scrollY = 0;
  let revision = 0;

  function renderCaption() {
    if (selection === undefined) return;
    const { text, lang } = backgroundCaption(selection, locale);
    const action = active ? labels[locale].back : labels[locale].view;
    caption.textContent = text || action;
    caption.lang = lang;
    if (text) {
      button.setAttribute("aria-pressed", String(active));
      button.title = action;
    } else {
      // Without a caption the label already tells visitors what clicking will do.
      button.removeAttribute("aria-pressed");
      button.removeAttribute("title");
    }
    button.hidden = false;
  }

  function setActive(next: boolean) {
    if (next === active) return;
    const change = ++revision;
    active = next;
    if (active) {
      scrollY = view.scrollY;
      button.focus({ preventScroll: true });
      regions.forEach((region) => { region.inert = true; });
    }
    html.toggleAttribute("data-photo-view", active);
    renderCaption();

    if (!active) {
      if (view.scrollY !== scrollY) view.scrollTo({ top: scrollY, behavior: "instant" });
      const restoreInteraction = () => {
        if (change === revision) regions.forEach((region) => { region.inert = false; });
      };
      // Keep controls out of the tab order until the return fade completes.
      const fades = Array.from(regions).flatMap((region) => region.getAnimations());
      if (fades.length) void Promise.allSettled(fades.map((fade) => fade.finished)).then(restoreInteraction);
      else restoreInteraction();
    }
  }

  button.addEventListener("click", () => {
    if (!button.hidden && !highContrast.matches) setActive(!active);
  });
  page.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && active) {
      event.preventDefault();
      setActive(false);
      button.focus({ preventScroll: true });
    }
  });
  highContrast.addEventListener("change", () => {
    if (!highContrast.matches || !active) return;
    setActive(false);
    page.querySelector<HTMLElement>(".lang-toggle [aria-pressed='true']")?.focus({ preventScroll: true });
  });

  return {
    update(value: unknown) { selection = value; renderCaption(); },
    setLocale(value: Locale) { locale = value; renderCaption(); },
  };
}
