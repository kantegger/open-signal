import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ClaimRecord } from "../../../components/claim-record";
import { SiteShell } from "../../../components/site-shell";
import { ApiError, fetchClaim } from "../../../lib/api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Public Claim · Open Signal",
  description: "Evidence, uncertainty, lineage, and public version history for an Open Signal Claim.",
};

export default async function ClaimPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let page;
  try {
    page = await fetchClaim(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <SiteShell active="claim">
      <ClaimRecord page={page} />
    </SiteShell>
  );
}
