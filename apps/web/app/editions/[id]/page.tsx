import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cache } from "react";
import { FrontPage } from "../../../components/front-page";
import { JsonLd } from "../../../components/json-ld";
import { ApiError } from "../../../lib/api";
import { languageAlternates } from "../../../lib/i18n";
import { getRequestLocale } from "../../../lib/request-locale";
import {
  fetchEditionFrontPageServer,
  fetchEditionRecordServer,
} from "../../../lib/server-api";
import { absoluteUrl } from "../../../lib/site";
import { editionPath, extractUuid, signalPath } from "../../../lib/urls";

export const revalidate = 86_400;

type Props = { params: Promise<{ id: string }> };
const getEdition = cache(async (editionId: string, locale: string) => {
  const [page, record] = await Promise.all([
    fetchEditionFrontPageServer(editionId, locale),
    fetchEditionRecordServer(editionId).catch(() => null),
  ]);
  return { page, record };
});

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const locale = await getRequestLocale();
  const traditional = locale === "zh-Hant";
  const { id } = await params;
  const editionId = extractUuid(id);
  if (!editionId) return { title: traditional ? "找不到期次" : "Edition not found", robots: { index: false } };
  try {
    const { page } = await getEdition(editionId, locale);
    const title = `${traditional ? "Open Signal 期次" : "Open Signal edition"} · ${page.snapshot.edition_date}`;
    const claimCount = new Set(page.slots.flatMap((slot) => slot.items.flatMap((item) => item.claim_ids))).size;
    const description = traditional
      ? `${claimCount} 筆已驗證公共訊號，分布於 ${page.sections.length} 個有效區段，並保存為不可變的 Open Signal 期次。`
      : `${claimCount} verified public signals across ${page.sections.length} active Sections, preserved as an immutable Open Signal edition.`;
    const canonical = editionPath(editionId, locale);
    return {
      title,
      description,
      alternates: { canonical, languages: languageAlternates(editionPath(editionId)) },
      openGraph: { type: "article", title, description, url: canonical, publishedTime: page.snapshot.published_at },
      twitter: { card: "summary_large_image", title, description },
    };
  } catch {
    return { title: traditional ? "找不到期次" : "Edition not found", robots: { index: false } };
  }
}

export default async function EditionPage({ params }: Props) {
  const locale = await getRequestLocale();
  const { id } = await params;
  const editionId = extractUuid(id);
  if (!editionId) notFound();

  let edition;
  try {
    edition = await getEdition(editionId, locale);
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
          name: `${locale === "zh-Hant" ? "Open Signal 期次" : "Open Signal edition"} · ${page.snapshot.edition_date}`,
          inLanguage: locale,
          url: absoluteUrl(editionPath(editionId, locale)),
          datePublished: page.snapshot.published_at,
          dateModified: page.snapshot.composed_at,
          isPartOf: { "@type": "WebSite", name: "Open Signal", url: absoluteUrl(locale === "zh-Hant" ? "/zh-Hant" : "/") },
          mainEntity: {
            "@type": "ItemList",
            numberOfItems: uniqueSignals.size,
            itemListElement: [...uniqueSignals.entries()].map(([claimId, headline], index) => ({
              "@type": "ListItem",
              position: index + 1,
              name: headline,
              url: absoluteUrl(signalPath(headline, claimId, locale)),
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
