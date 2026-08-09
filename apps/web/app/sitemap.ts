import type { MetadataRoute } from "next";
import { fetchSeoIndexServer } from "../lib/server-api";
import { siteUrl } from "../lib/site";
import { editionPath, signalPath, topicPath } from "../lib/urls";

export const revalidate = 900;

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const origin = siteUrl();
  const entries: MetadataRoute.Sitemap = [
    {
      url: origin,
      changeFrequency: "hourly",
      priority: 1,
    },
    {
      url: `${origin}/explore`,
      changeFrequency: "hourly",
      priority: 0.9,
    },
    {
      url: `${origin}/editions`,
      changeFrequency: "hourly",
      priority: 0.7,
    },
    {
      url: `${origin}/method`,
      changeFrequency: "monthly",
      priority: 0.55,
    },
  ];
  try {
    const index = await fetchSeoIndexServer();
    entries.push(
      ...index.topics.map((topic) => ({
        url: `${origin}${topicPath(topic.title, topic.id)}`,
        lastModified: topic.updated_at,
        changeFrequency: "hourly" as const,
        priority: 0.9,
      })),
      ...index.claims.map((claim) => ({
        url: `${origin}${signalPath(claim.title, claim.id)}`,
        lastModified: claim.updated_at,
        changeFrequency: "weekly" as const,
        priority: 0.75,
      })),
      ...index.editions.map((edition) => ({
        url: `${origin}${editionPath(edition.id)}`,
        lastModified: edition.updated_at,
        changeFrequency: "never" as const,
        priority: 0.45,
      })),
    );
  } catch {
    // A temporary API outage must not make the root sitemap invalid.
  }
  return entries;
}
