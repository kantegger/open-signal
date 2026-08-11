import type { MetadataRoute } from "next";
import { fetchSeoIndexServer } from "../lib/server-api";
import { localePath, SUPPORTED_LOCALES } from "../lib/i18n";
import { siteUrl } from "../lib/site";
import { editionPath, signalPath, topicPath } from "../lib/urls";

export const revalidate = 900;

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const origin = siteUrl();
  const entries: MetadataRoute.Sitemap = [
    ...localizedEntries(origin, "/", { changeFrequency: "hourly", priority: 1 }),
    ...localizedEntries(origin, "/explore", { changeFrequency: "hourly", priority: 0.9 }),
    ...localizedEntries(origin, "/editions", { changeFrequency: "hourly", priority: 0.7 }),
    ...localizedEntries(origin, "/method", { changeFrequency: "monthly", priority: 0.55 }),
  ];
  try {
    const index = await fetchSeoIndexServer();
    entries.push(
      ...index.topics.flatMap((topic) => localizedEntries(origin, topicPath(topic.title, topic.id), {
        lastModified: topic.updated_at,
        changeFrequency: "hourly",
        priority: 0.9,
      })),
      ...index.claims.flatMap((claim) => localizedEntries(origin, signalPath(claim.title, claim.id), {
        lastModified: claim.updated_at,
        changeFrequency: "weekly",
        priority: 0.75,
      })),
      ...index.editions.flatMap((edition) => localizedEntries(origin, editionPath(edition.id), {
        lastModified: edition.updated_at,
        changeFrequency: "never",
        priority: 0.45,
      })),
    );
  } catch {
    // A temporary API outage must not make the root sitemap invalid.
  }
  return entries;
}

function localizedEntries(
  origin: string,
  path: string,
  fields: Omit<MetadataRoute.Sitemap[number], "url" | "alternates">,
): MetadataRoute.Sitemap {
  const languages = Object.fromEntries(
    SUPPORTED_LOCALES.map((locale) => [locale, `${origin}${localePath(path, locale)}`]),
  );
  return SUPPORTED_LOCALES.map((locale) => ({
    ...fields,
    url: `${origin}${localePath(path, locale)}`,
    alternates: { languages },
  }));
}
