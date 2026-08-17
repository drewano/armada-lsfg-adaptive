// Bilingual FR/EN helper. Steam UI language takes precedence, then browser
// locale. French by default.

const steamLanguage =
  (window as any)?.SteamClient?.Settings?.GetSteamLanguage ||
  (window as any)?.steamUILanguage ||
  "";

const locale: string =
  (typeof steamLanguage === "string" && steamLanguage) ||
  navigator.language ||
  "";

export const isFrench = /^fr/i.test(locale) || /french/i.test(locale);

export function t(fr: string, en: string): string {
  return isFrench ? fr : en;
}
