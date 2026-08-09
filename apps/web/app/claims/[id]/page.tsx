import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ClaimRecord } from "../../../components/claim-record";
import { SiteShell } from "../../../components/site-shell";
import { ApiError } from "../../../lib/api";
import { fetchClaimServer } from "../../../lib/server-api";
import { excerpt, signalPath } from "../../../lib/urls";

export const revalidate = 86_400;

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  try {
    const page = await fetchClaimServer(id);
    return {
      title: excerpt(page.claim.public_statement || page.observation, 68),
      description: excerpt(page.observation),
      alternates: {
        canonical: signalPath(page.claim.public_statement || page.observation, id),
      },
      robots: { index: false, follow: true },
    };
  } catch {
    return { title: "Public Claim", robots: { index: false } };
  }
}

export default async function ClaimPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let page;
  try {
    page = await fetchClaimServer(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <SiteShell active="explore">
      <ClaimRecord page={page} />
    </SiteShell>
  );
}
