import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ClaimRecord } from "../../../components/claim-record";
import { SiteShell } from "../../../components/site-shell";
import { ApiError } from "../../../lib/api";
import { fetchClaimServer } from "../../../lib/server-api";

export const revalidate = 86_400;

export const metadata: Metadata = {
  title: "Public Claim · Open Signal",
  description: "Evidence, uncertainty, lineage, and public version history for an Open Signal Claim.",
};

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
    <SiteShell active="claim">
      <ClaimRecord page={page} />
    </SiteShell>
  );
}
