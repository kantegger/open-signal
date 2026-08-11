import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ClaimRecord } from "../../../components/claim-record";
import { SiteShell } from "../../../components/site-shell";
import { ApiError } from "../../../lib/api";
import { languageAlternates } from "../../../lib/i18n";
import { getRequestLocale } from "../../../lib/request-locale";
import { fetchClaimServer } from "../../../lib/server-api";
import { excerpt, signalPath } from "../../../lib/urls";

export const revalidate = 86_400;

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const locale = await getRequestLocale();
  const { id } = await params;
  try {
    const page = await fetchClaimServer(id, locale);
    const canonicalStatement =
      page.claim.source_public_statement || page.claim.public_statement || page.observation;
    const baseCanonical = signalPath(canonicalStatement, id);
    return {
      title: excerpt(page.claim.public_statement || page.observation, 68),
      description: excerpt(page.observation),
      alternates: {
        canonical: signalPath(canonicalStatement, id, locale),
        languages: languageAlternates(baseCanonical),
      },
      robots: { index: false, follow: true },
    };
  } catch {
    return { title: locale === "zh-Hant" ? "公開主張" : "Public Claim", robots: { index: false } };
  }
}

export default async function ClaimPage({ params }: { params: Promise<{ id: string }> }) {
  const locale = await getRequestLocale();
  const { id } = await params;
  let page;
  try {
    page = await fetchClaimServer(id, locale);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <SiteShell active="explore">
      <ClaimRecord locale={locale} page={page} />
    </SiteShell>
  );
}
