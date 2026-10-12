export const SITE = {
  name: "Henning Petersen",
  domain: "henningpetersen.com",
  email: "hp@henningpetersen.com",
  companyUrl: "https://daenen4.de",
  companyLabel: "daenen4.de",
} as const;

export type Locale = "en" | "de";

export const LOCALES: readonly Locale[] = ["en", "de"] as const;

export const STRINGS: Record<Locale, { title: string; message: string; ctaSite: string; ctaMail: string }> = {
  en: {
    title: "Henning Petersen",
    message:
      "This domain is currently used for email only. My work website is at daenen4.de.",
    ctaSite: "Go to daenen4.de",
    ctaMail: "Send an email",
  },
  de: {
    title: "Henning Petersen",
    message:
      "Diese Domain wird im Moment nur für E-Mail benutzt. Meine berufliche Website findet sich unter daenen4.de.",
    ctaSite: "Zu daenen4.de",
    ctaMail: "E-Mail schreiben",
  },
};
