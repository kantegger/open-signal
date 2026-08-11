import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cache } from "react";
import { ClaimRecord } from "../../../components/claim-record";
import { JsonLd } from "../../../components/json-ld";
import { SiteShell } from "../../../components/site-shell";
import { ApiError } from "../../../lib/api";
import { languageAlternates, localePath } from "../../../lib/i18n";
import { getRequestLocale } from "../../../lib/request-locale";
import { fetchClaimServer } from "../../../lib/server-api";
import { absoluteUrl } from "../../../lib/site";
import { excerpt, extractUuid, signalPath, topicPath } from "../../../lib/urls";

export const revalidate = 86_400;

type Props = { params: Promise<{ slug: string }> };
const getClaim = cache((claimId: string, locale: string) => fetchClaimServer(claimId, locale));

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const locale = await getRequestLocale();
  const notFoundTitle = locale === "zh-Hant" ? "找不到訊號" : "Signal not found";
  const { slug } = await params;
  const claimId = extractUuid(slug);
  if (!claimId) return { title: notFoundTitle, robots: { index: false } };
  try {
    const page = await getClaim(claimId, locale);
    const title = excerpt(page.claim.public_statement || page.observation, 68);
    const description = excerpt(page.observation || page.claim.public_statement);
    const canonicalStatement =
      page.claim.source_public_statement || page.claim.public_statement || page.observation;
    const baseCanonical = signalPath(canonicalStatement, claimId);
    const canonical = signalPath(canonicalStatement, claimId, locale);
    return {
      title,
      description,
      alternates: { canonical, languages: languageAlternates(baseCanonical) },
      openGraph: {
        type: "article",
        siteName: "Open Signal",
        title,
        description,
        url: canonical,
        publishedTime: page.claim.issued_at,
        modifiedTime: page.claim.materially_updated_at ?? page.claim.issued_at,
      },
      twitter: { card: "summary_large_image", title, description },
    };
  } catch {
    return { title: notFoundTitle, robots: { index: false } };
  }
}

export default async function SignalPage({ params }: Props) {
  const locale = await getRequestLocale();
  const { slug } = await params;
  const claimId = extractUuid(slug);
  if (!claimId) notFound();
  let page;
  try {
    page = await getClaim(claimId, locale);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
  const canonicalStatement =
    page.claim.source_public_statement || page.claim.public_statement || page.observation;
  const canonical = signalPath(canonicalStatement, claimId, locale);
  const breadcrumbs: Array<Record<string, unknown>> = [
    { "@type": "ListItem", position: 1, name: "Open Signal", item: absoluteUrl(localePath("/", locale)) },
  ];
  if (page.topic) {
    breadcrumbs.push({
      "@type": "ListItem",
      position: 2,
      name: page.topic.title,
      item: absoluteUrl(topicPath(page.topic.title, page.topic.id, locale)),
    });
  }
  breadcrumbs.push({
    "@type": "ListItem",
    position: breadcrumbs.length + 1,
    name: excerpt(page.claim.public_statement || page.observation, 80),
    item: absoluteUrl(canonical),
  });

  return (
    <>
      <JsonLd
        value={{
          "@context": "https://schema.org",
          "@type": "Article",
          inLanguage: page.locale?.published ?? locale,
          headline: page.claim.public_statement || page.observation,
          description: excerpt(page.observation),
          datePublished: page.claim.issued_at,
          dateModified: page.claim.materially_updated_at ?? page.claim.issued_at,
          mainEntityOfPage: absoluteUrl(canonical),
          author: { "@type": "Organization", name: "Open Signal" },
          publisher: { "@type": "Organization", name: "Open Signal" },
          about: page.topic?.title,
        }}
      />
      <JsonLd
        value={{
          "@context": "https://schema.org",
          "@type": "BreadcrumbList",
          itemListElement: breadcrumbs,
        }}
      />
      <SiteShell active="explore">
        <ClaimRecord locale={locale} page={page} />
      </SiteShell>
    </>
  );
}
