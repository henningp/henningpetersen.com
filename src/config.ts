export const SITE = {
  name: "Henning Petersen",
  domain: "henningpetersen.com",
  email: "hp@henningpetersen.com",
  companyUrl: "https://daenen4.de",
  companyLabel: "daenen4.de",
} as const;

export type Locale = "en" | "de";

/**
 * A time-of-day greeting band: show `text` from `from` (inclusive) until the
 * next band starts (exclusive, wrapping past midnight). `from` is the local
 * wall-clock hour, 0–23, taken from the visitor's own device clock.
 */
export type GreetingBand = { from: number; text: string };

/**
 * Per-locale greeting bands, ordered by ascending `from`. The final band wraps
 * past midnight, so the pre-dawn hours fall to it.
 *
 * Both languages intentionally use three slots and have **no** "Good night" /
 * "Gute Nacht" entry — that reads oddly as a greeting to someone who is awake
 * — so the evening simply runs on until morning.
 *
 * English keeps the conventional morning / afternoon / evening split (morning
 * through noon). German differs deliberately: "Guten Morgen" is not said past
 * ~10 AM, so it gives way to "Guten Tag" (the all-purpose daytime hello),
 * which then carries the whole day until "Guten Abend" in the evening.
 */
export const GREETINGS: Record<Locale, GreetingBand[]> = {
  en: [
      { from: 5, text: "Good morning!" },
      { from: 12, text: "Good afternoon!" },
      { from: 18, text: "Good evening!" },
    ],
  de: [
      { from: 5, text: "Guten Morgen!" },
      { from: 10, text: "Guten Tag!" },
      { from: 18, text: "Guten Abend!" },
    ],
};

/** Pick the greeting for a locale from the local hour (0–23). */
export function pickGreeting(locale: Locale, hour: number): string {
  const bands = GREETINGS[locale];
    // The winning band is the last one whose `from` does not exceed `hour`; no
    // match means we wrapped past midnight, so fall back to the last band.
  let match = bands.length - 1;
  for (let i = 0; i < bands.length; i++) {
    if (bands[i].from <= hour) match = i;
    else break;
    }
  return bands[match].text;
}
