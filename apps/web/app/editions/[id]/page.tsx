import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cache } from "react";
import { FrontPage } from "../../../components/front-page";
import { JsonLd } from "../../../components/json-ld";
import { ApiError } from "../../../lib/api";
import {
  fetchEditionFrontPageServer,
  fetchEditionRecordServer,
} from "../../../lib/server-api";
import { absoluteUrl } from "../../../lib/site";
import { editionPath, extractUuid, signalPath } from "../../../lib/urls";

export const revalidate = 86_400;

type Props = { params: Promise<{ id: string }> };
const getEdition = cache(async (editionId: string) => {
  const [page, record] = await Promise.all([
    fetchEditionFrontPageServer(editionId),
    fetchEditionRecordServer(editionId).catch(() => null),
  ]);
  return { page, record };
});

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const editionId = extractUuid(id);
  if (!editionId) return { title: "Edition not found", robots: { index: false } };
  try {
    const { page } = await getEdition(editionId);
    const title = `Open Signal edition · ${page.snapshot.edition_date}`;
    const claimCount = new Set(page.slots.flatMap((slot) => slot.items.flatMap((item) => item.claim_ids))).size;
    const description = `${claimCount} verified public signals across ${page.sections.length} active Sections, preserved as an immutable Open Signal edition.`;
    return {
      title,
      description,
      alternates: { canonical: editionPath(editionId) },
      openGraph: { type: "article", title, description, url: editionPath(editionId), publishedTime: page.snapshot.published_at },
      twitter: { card: "summary_large_image", title, description },
    };
  } catch {
    return { title: "Edition not found", robots: { index: false } };
  }
}

export default async function EditionPage({ params }: Props) {
  const { id } = await params;
  const editionId = extractUuid(id);
  if (!editionId) notFound();

  let edition;
  try {
    edition = await getEdition(editionId);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
  const { page, record } = edition;

  const uniqueSignals = new Map<string, string>();
  for (const slot of page.slots) {
    for (const item of slot.items) {
      const claimId = item.trust.claim_id;
      if (claimId && !uniqueSignals.has(claimId)) uniqueSignals.set(claimId, item.headline);
    }
  }

  return (
    <>
      <JsonLd
        value={{
          "@context": "https://schema.org",
          "@type": "CollectionPage",
          name: `Open Signal edition · ${page.snapshot.edition_date}`,
          url: absoluteUrl(editionPath(editionId)),
          datePublished: page.snapshot.published_at,
          dateModified: page.snapshot.composed_at,
          isPartOf: { "@type": "WebSite", name: "Open Signal", url: absoluteUrl("/") },
          mainEntity: {
            "@type": "ItemList",
            numberOfItems: uniqueSignals.size,
            itemListElement: [...uniqueSignals.entries()].map(([claimId, headline], index) => ({
              "@type": "ListItem",
              position: index + 1,
              name: headline,
              url: absoluteUrl(signalPath(headline, claimId)),
            })),
          },
        }}
      />
      <FrontPage
        editionRecord={record ? {
          first_published_at: record.first_published_at,
          payload_hash: record.payload_hash,
          record_class: record.record_class,
          events: record.events,
        } : undefined}
        initialData={page}
        live={false}
      />
    </>
  );
}
