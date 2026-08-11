import { DEFAULT_LOCALE, localePath, type SupportedLocale } from "./i18n";

const UUID_PATTERN = /[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/i;

export function slugify(value: string, fallback = "signal"): string {
  const slug = value
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 76)
    .replace(/-+$/g, "");
  return slug || fallback;
}

export function signalPath(
  title: string,
  claimId: string,
  locale: SupportedLocale = DEFAULT_LOCALE,
): string {
  return localePath(`/signals/${slugify(title)}--${claimId}`, locale);
}

export function topicPath(
  title: string,
  topicId: string,
  locale: SupportedLocale = DEFAULT_LOCALE,
): string {
  return localePath(`/topics/${slugify(title, "topic")}--${topicId}`, locale);
}

export function editionPath(
  editionId: string,
  locale: SupportedLocale = DEFAULT_LOCALE,
): string {
  return localePath(`/editions/${editionId}`, locale);
}

export function extractUuid(value: string): string | null {
  return value.match(UUID_PATTERN)?.[0] ?? null;
}

export function excerpt(value: string, length = 158): string {
  const compact = value.replace(/\s+/g, " ").trim();
  return compact.length <= length ? compact : `${compact.slice(0, length - 1).trimEnd()}…`;
}
